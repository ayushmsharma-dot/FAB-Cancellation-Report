# RNCL Minimal Dashboard – FINAL EXACT-FORMAT BUILD

"""
Run:
  pip install -r requirements.txt
  streamlit run app.py

What’s included:
• Minimal UI: only “Report Date” on sidebar; no live preview.
• One clean flow: Upload 4 RNCL files -> Process -> Download outputs.
• .docx accepted for gosu templates (uses python-docx if installed; else safe fallback).
• Template text normalization (HTML entities, smart quotes, arrows).
• Gosu output preserves template formatting for:
    - var pols = { … }  (indentation, multi-line, trailing comma style; braces/spacing unchanged)
    - var eventDate = "MM/DD/YYYY".toDate().trimToMidnight()  (only the literal changes)
• Gosu download as .txt (not .gosu)
"""
import streamlit as st
import pandas as pd
import datetime
import re
import csv
import io
import html
import unicodedata
from zoneinfo import ZoneInfo
import zipfile
import io as _io
import sys
import subprocess
import tempfile
import os


# ---------- Optional engines (Excel) ----------
try:
    import openpyxl  # noqa: F401
    import xlsxwriter  # noqa: F401
except ImportError:
    pass

# ---------- Optional python-docx for .docx parsing ----------
HAS_DOCX = False
try:
    from docx import Document  # optional
    HAS_DOCX = True
except Exception:
    HAS_DOCX = False


# ---------- .docx extraction ----------
def extract_text_from_docx(file_bytes: bytes) -> str:
    """
    Return plain text from a .docx file. If python-docx is available, use it.
    Otherwise, fall back to reading /word/document.xml and extracting text
    paragraph-by-paragraph so line breaks are preserved.
    """
    if HAS_DOCX:
        try:
            doc = Document(_io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            pass  # fall back

    # Fallback: unzip and parse paragraphs
    try:
        with zipfile.ZipFile(_io.BytesIO(file_bytes)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")

        paras = re.findall(r"<w:p[^>]*>.*?</w:p>", xml, flags=re.DOTALL)
        lines = []
        for p in paras:
            runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, flags=re.DOTALL)
            txt = "".join(runs)
            txt = (txt.replace("&amp;", "&")
                      .replace("&lt;", "<")
                      .replace("&gt;", ">")
                      .replace("&quot;", '"')
                      .replace("&apos;", "'"))
            lines.append(txt)
        return "\n".join(lines).strip()
    except Exception:
        return ""


# ---------- Template text normalizer ----------
def normalize_template_text(s: str) -> str:
    r"""
    Normalize text coming from .docx or pasted HTML:
    - HTML entities (&gt; &lt; &quot; etc.) -> real chars
    - “smart quotes” -> straight quotes
    - stray backslashes before arrows (\->) -> ->
    - &nbsp; -> space
    - NFC normalization (safer regex)
    """
    # 1) HTML decode (&gt; -> >, &quot; -> ", etc.)
    s = html.unescape(s)

    # 2) Smart quotes to straight quotes
    s = (s.replace("“", '"').replace("”", '"')
           .replace("‘", "'").replace("’", "'"))

    # 3) Fix \-> or \ -&gt; to ->
    s = re.sub(r'\\\s*-\s*>', '->', s)

    # 4) Non‑breaking space -> regular space
    s = s.replace("\u00A0", " ")

    # 5) Unicode normalize for stable matching
    s = unicodedata.normalize("NFC", s)
    return s


# ---------- Helpers & defaults (minimal UI) ----------
def get_ist_yesterday() -> datetime.date:
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime.datetime.now(ist)
    return (now - datetime.timedelta(days=1)).date()


# Trailer patterns (per-file bottom)
THREE_TOKEN_TRAILER = re.compile(r"^9{9}\s+0+\s+0+$")   # e.g., "999999999 0000000 0000447"
LONG_EOF_COUNTER   = re.compile(r"^900000[0-9]{10,}$")  # e.g., "90000063100000000000"
CONTROL_SUB        = re.compile(r"[\x1A]")
TRAILER_PATTERNS   = [THREE_TOKEN_TRAILER, LONG_EOF_COUNTER]

# Baked-in defaults
ENFORCE_DATE = True
ENFORCE_COUNTS = True
REMOVE_PER_FILE_TRAILERS = True
NOISE_TOKENS = ["error", "reject"]   # lower-case compare
MIN_LEN = 3
DROP_DECOR = True
EXTRACT_MODE = "Substring"           # Column | Regex | Substring
COL_INDEX = 0
REGEX_PATTERN = r"([A-Z0-9]+)"
REGEX_GROUP = 1
SUB_START = 4
SUB_LENGTH = 9
UPPERCASE = False
STRIP_QUOTES = True
TREAT_AS_SINGLE_COL = True

DEFAULT_GOSU_TEMPLATE = r"""uses gw.api.database.Relop

var pols = {
  "PLACEHOLDER"
}
var eventDate = "MM/DD/YYYY".toDate().trimToMidnight()
var sb = new StringBuilder()
pols.each(\elt -> {
  try{


    var policy = Policy.finder.findPolicyByPolicyNumber(elt)
    if (policy == null) {
      sb.append(elt + "|invalid policy number for GWPC").append("\n")
    } else {
      var prds = gw.api.database.Query.make(PolicyPeriod).compare(PolicyPeriod#PolicyNumber,gw.api.database.Relop.Equals, elt)
      var jb = prds.join(PolicyPeriod#Job).compare(Job#Subtype, gw.api.database.Relop.Equals.Equals, typekey.Job.TC_CANCELLATION)
      jb.compare(Job#CloseDate, Relop.NotEquals, null)
      var qry = prds.withDistinct(true).select()

      if(qry.Count==0){
        sb.append(elt + "|cancellation not created").append("\n")
      }else{
        var ppOrdr = qry.toSet().orderByDescending(\dt->dt.Job.CloseDate).thenByDescending(\dt->dt.EditEffectiveDate)
        var periodCheck =  ppOrdr?.firstWhere(\chk -> chk.Job.CloseDate.trimToMidnight()>= eventDate)
        if(periodCheck==null){
          sb.append(elt + "|FAB cancellation did not happen on or after "+eventDate).append("\n")
        }else{
          sb.append(elt + "|FAB cancellation ~ "+periodCheck.Job.JobNumber).append("\n")
        }
      }
    }
  }catch (e:Exception){
    sb.append(elt + "|Error ~ "+e.Message).append("\n")
  }
})
print(sb)
"""


def validate_files(uploaded_files, target_date: datetime.date) -> tuple[bool, str]:
    """Returns (is_valid, error_msg) with baked-in rules."""
    if ENFORCE_COUNTS and len(uploaded_files) != 4:
        return False, f"Expected exactly 4 files, got {len(uploaded_files)}."

    apps, fpps = 0, 0
    target_date_str = target_date.strftime("%Y%m%d")
    pat = re.compile(r"^RNCL_(\d{8})_(APPS|FPPS)_([A-Z]{2})$")

    for f in uploaded_files:
        name_no_ext = f.name.rsplit(".", 1)[0]
        m = pat.match(name_no_ext)
        if not m:
            return False, f"Filename '{f.name}' must be RNCL_<YYYYMMDD>_<APPS|FPPS>_<STATE>."
        fdate, feed, _ = m.groups()
        if ENFORCE_DATE and fdate != target_date_str:
            return False, f"Filename '{f.name}' date {fdate} != selected date {target_date_str}."
        if feed == "APPS": apps += 1
        elif feed == "FPPS": fpps += 1

    if ENFORCE_COUNTS and (apps != 2 or fpps != 2):
        return False, f"Need 2 APPS + 2 FPPS; got {apps} APPS, {fpps} FPPS."
    return True, ""


def strip_per_file_trailers(lines: list[str]) -> tuple[list[str], int]:
    """Drops trailing garbage/trailer rows at end of a single file."""
    def is_trailer_like(line: str) -> bool:
        ln = CONTROL_SUB.sub("", line)
        ln = ln.rstrip("\r")
        stripped = ln.strip()
        if any(p.fullmatch(stripped) for p in TRAILER_PATTERNS):
            return True
        if not stripped:
            return True
        no_alpha = not re.search(r"[A-Za-z]", ln)
        digits_spaces = re.fullmatch(r"[0-9\s]+", ln or "") is not None
        few_tokens = len(ln.split()) < 2
        return (digits_spaces and len(stripped) >= 8) or (no_alpha and few_tokens)

    i, removed = len(lines) - 1, 0
    while i >= 0 and is_trailer_like(lines[i]):
        removed += 1
        i -= 1
    kept = [CONTROL_SUB.sub("", l) for l in lines[: i + 1]]
    return kept, removed


def process_pipeline(files, selected_date: datetime.date):
    """Minimal pipeline using baked-in defaults; returns (policies, recon, final_one_line_txt)."""
    decor_pattern = re.compile(r"^[-=]{3,}$")
    total_in = 0
    kept = 0
    r_token = r_len = r_decor = 0
    r_trailer = 0
    per_file_counts = {}
    per_file_trailers = {}

    all_lines = []

    for f in files:
        # Read lines for any file type; Excel -> CSV lines
        if f.name.lower().endswith((".xlsx", ".xls")):
            try:
                df = pd.read_excel(f)
                lines = df.to_csv(index=False, header=False).splitlines()
            except Exception:
                lines = []
        else:
            raw = f.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")
            lines = text.splitlines()
        per_file_counts[f.name] = len(lines)
        total_in += len(lines)

        if REMOVE_PER_FILE_TRAILERS:
            lines, dropped = strip_per_file_trailers(lines)
            per_file_trailers[f.name] = dropped
            r_trailer += dropped

        for ln in lines:
            s = ln.rstrip("\r\n")
            if any(tok in s.lower() for tok in NOISE_TOKENS):
                r_token += 1
                continue
            t = s.strip()
            if len(t) < MIN_LEN:
                r_len += 1
                continue
            if DROP_DECOR and decor_pattern.match(t):
                r_decor += 1
                continue
            all_lines.append(t)
            kept += 1

        f.seek(0)

    # Build rows for DataFrame
    if TREAT_AS_SINGLE_COL:
        rows = [[line] for line in all_lines]
    else:
        split_pat = re.compile(r"[,\|]")
        rows = [[p.strip() for p in split_pat.split(line)] for line in all_lines]

    df = pd.DataFrame(rows).fillna("")

    # Extraction -> policies list
    policies = []
    if len(df) > 0 and len(df.columns) > 0:
        if EXTRACT_MODE == "Column":
            raw_p = df.iloc[:, COL_INDEX].astype(str) if COL_INDEX < len(df.columns) else pd.Series([""] * len(df))
        elif EXTRACT_MODE == "Substring":
            base = df.iloc[:, COL_INDEX].astype(str) if COL_INDEX < len(df.columns) else pd.Series([""] * len(df))
            tmp = []
            for v in base:
                out = ""
                if len(v) >= SUB_START:
                    out = v[SUB_START - 1 : SUB_START - 1 + SUB_LENGTH]
                tmp.append(out.strip())  # TRIM
            raw_p = pd.Series(tmp)
        else:  # Regex
            first = df.iloc[:, 0].astype(str)
            rp = re.compile(REGEX_PATTERN)
            tmp = []
            for v in first:
                m = rp.search(v)
                tmp.append((m.group(REGEX_GROUP) if m else "").strip())
            raw_p = pd.Series(tmp)

        for v in raw_p:
            vv = v.strip()
            if STRIP_QUOTES and len(vv) >= 2 and vv[0] == vv[-1] and vv[0] in ("'", '"'):
                vv = vv[1:-1].strip()
            if UPPERCASE:
                vv = vv.upper()
            if vv:
                policies.append(vv)

    # Deduplicate preserving order
    seen = set()
    uniq = []
    for p in policies:
        if p not in seen:
            seen.add(p)
            uniq.append(p)

    # Final one-line
    final_one_line_txt = ",".join(f'"{p}"' for p in uniq)

    recon = {
        "inputs_total_lines": total_in,
        "kept_lines": kept,
        "removed": {
            "by_trailer_per_file": r_trailer,
            "token": r_token,
            "length": r_len,
            "decor": r_decor,
        },
        "per_file_line_counts": per_file_counts,
        "per_file_trailers_removed": per_file_trailers,
        "unique_policies": len(uniq),
        "selected_date": selected_date.isoformat(),
        "timezone": "Asia/Kolkata",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    return uniq, recon, final_one_line_txt


# ---------- Gosu replacer (preserve template formatting; change ONLY policies + date literal) ----------
def inject_into_gosu(src: str, list_payload_one_line: str, mmddyyyy: str) -> str:
    """
    Replace in the template:
      1) var pols = { ... }  -> inject using the template’s original formatting
         (multi-line or single-line, same indentation, same trailing comma style).
      2) var eventDate = "..." -> replace only the literal with MM/DD/YYYY; keep .toDate().trimToMidnight().
    Preserves the template’s original line ending (LF or CRLF) and inserts a newline
    between '}' and 'var eventDate' only when they are glued together.
    """
    # Preserve original EOLs
    line_ending = "\r\n" if "\r\n" in src else "\n"

    # Parse items from the prepared one-line list: "A","B","C" -> ["A","B","C"]
    items = re.findall(r'"([^"]+)"', list_payload_one_line)

    # ----- 1) var pols = { ... } -----
    pols_pattern = re.compile(r'(var\s+pols\s*=\s*\{)(.*?)(\})', re.DOTALL | re.IGNORECASE)

    def _format_pols_like_template(original_content: str, values: list[str]) -> str:
        if "\n" in original_content:
            # MULTILINE STYLE (respect indent & trailing comma style)
            m = re.search(r'\n([ \t]*)"', original_content)  # indentation before first item
            indent = m.group(1) if m else "  "
            had_trailing_comma = bool(re.search(r',\s*\Z', original_content.strip(), re.S))

            if not values:
                # keep braces on their own lines if template used multiline
                return line_ending

            lines = []
            for i, v in enumerate(values):
                is_last = (i == len(values) - 1)
                comma = "," if (had_trailing_comma or not is_last) else ""
                lines.append(f'{indent}"{v}"{comma}')
            return line_ending + line_ending.join(lines) + line_ending
        else:
            # SINGLE‑LINE STYLE – respect comma spacing
            m = re.search(r'",(\s*)"', original_content)
            inter = m.group(1) if m else ""
            leading = " " if original_content.startswith(" ") else ""
            return leading + '"' + ('",' + inter + '"').join(values) + '"'

    def _pols_repl(m):
        before, body, after = m.group(1), m.group(2), m.group(3)
        formatted = _format_pols_like_template(body, items)
        return f"{before}{formatted}{after}"

    if pols_pattern.search(src):
        src = pols_pattern.sub(_pols_repl, src, count=1)

    # ----- 2) var eventDate = "MM/DD/YYYY".toDate().trimToMidnight() -----
    # Replace only the literal, keep exact trailing chain and spacing.
    # Pattern with explicit method chain to preserve everything after the quotes:
    ev_strict = re.compile(
        r'(^[ \t]*var[ \t]+eventDate[ \t]*=[ \t]*[\"“])'     # group 1: 'var eventDate = "'
        r'([^\"”]*)'                                        # group 2: the date literal (to replace)
        r'([\"”][ \t]*\.toDate\(\)\.trimToMidnight\(\))',   # group 3: '".toDate().trimToMidnight()'
        re.IGNORECASE | re.MULTILINE
    )
    if ev_strict.search(src):
        src = ev_strict.sub(rf'\g<1>{mmddyyyy}\g<3>', src, count=1)
    else:
        # Fallback: just replace the literal between quotes after 'var eventDate ='
        ev_fallback = re.compile(r'(var\s+eventdate\s*=\s*[\"“])([^\"”]*)([\"”])', re.IGNORECASE | re.MULTILINE)
        if ev_fallback.search(src):
            src = ev_fallback.sub(rf'\g<1>{mmddyyyy}\g<3>', src, count=1)

    # ----- 3) Ensure a newline between '}' and 'var eventDate' ONLY if glued -----
    brace_then_event = re.compile(r'(\})\s*(var[ \t]+eventDate\b)', re.IGNORECASE)
    if brace_then_event.search(src):
        src = brace_then_event.sub(rf'\g<1>{line_ending}\g<2>', src, count=1)

    # Normalize any LF we introduced to the original EOL style
    if line_ending == "\r\n":
        src = src.replace("\n", "\r\n").replace("\r\r\n", "\r\n")

    # Final defensive unescape (if any stray entities slipped in)
    src = html.unescape(src)
    return src


# ---------- App ----------
def main():
    st.set_page_config(page_title="RNCL — Minimal Dashboard", layout="wide")
    st.title("RNCL — Minimal Dashboard")

    # Sidebar (ONLY date)
    with st.sidebar:
        st.header("Report Date")
        report_date = st.date_input("Selected Date", value=get_ist_yesterday())

    # Content: Upload & Process (single section)
    st.subheader("Upload 4 RNCL files")
    uploaded_files = st.file_uploader(
        "Upload files (No extension, .txt, .csv, .xlsx, .xls)",
        accept_multiple_files=True
    )

    # Process button
    btn = st.button("Process & Prepare Downloads", type="primary", use_container_width=True, disabled=not uploaded_files)

    if btn:
        ok, err = validate_files(uploaded_files, report_date)
        if not ok:
            st.error(err)
        else:
            with st.spinner("Processing..."):
                policies, recon, final_one_line_txt = process_pipeline(uploaded_files, report_date)

            # Save to session for Gosu step
            st.session_state["final_one_line_txt"] = final_one_line_txt
            st.session_state["report_date"] = report_date

            st.success(
                f"Processed {len(uploaded_files)} files → {recon['inputs_total_lines']} lines; "
                f"kept {recon['kept_lines']}; unique policies = {recon['unique_policies']}."
            )

            # Downloads (Excel A1 one-liner, final TXT one-liner, CSV)
            if policies:
                # Excel (A1 only)
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
                    ws_name = "Result"
                    pd.DataFrame([]).to_excel(writer, index=False, header=False, sheet_name=ws_name)
                    ws = writer.sheets[ws_name]
                    ws.write(0, 0, final_one_line_txt)  # A1
                excel_data = excel_buffer.getvalue()

                # TXT (one-liner)
                txt_data = final_one_line_txt

                # CSV (quoted B values, no header)
                csv_buf = io.StringIO()
                pd.DataFrame(policies).to_csv(csv_buf, index=False, header=False, quoting=csv.QUOTE_ALL)
                csv_data = csv_buf.getvalue()

                date_str = report_date.strftime("%Y-%m-%d")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.download_button(
                        "Download Excel (.xlsx)",
                        data=excel_data,
                        file_name=f"policies_{date_str}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                with c2:
                    st.download_button(
                        "Download TXT (one-line)",
                        data=txt_data,
                        file_name=f"policies_{date_str}.txt",
                        mime="text/plain"
                    )
                with c3:
                    st.download_button(
                        "Download CSV (quoted, no header)",
                        data=csv_data,
                        file_name=f"policies_{date_str}.csv",
                        mime="text/csv"
                    )

            with st.expander("Recon (JSON)"):
                st.json(recon)

    st.markdown("---")

    # Gosu Script Builder (minimal)
    st.subheader("Gosu Script Builder")
    final_payload = st.session_state.get("final_one_line_txt", "")
    selected_dt = st.session_state.get("report_date", None)

    if not final_payload or not selected_dt:
        st.info("Run processing first; the builder uses the final one-line list and selected date.")
    else:
        gosu_file = st.file_uploader(
            "Upload gosu template (.gosu/.gsp/.txt/.docx)",
            type=["gosu", "gsp", "txt", "docx"],
            key="gosu_template"
        )

        template_text = DEFAULT_GOSU_TEMPLATE
        if gosu_file is not None:
            try:
                file_bytes = gosu_file.read()
                if gosu_file.name.lower().endswith(".docx"):
                    template_text = extract_text_from_docx(file_bytes)
                else:
                    try:
                        template_text = file_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        template_text = file_bytes.decode("latin-1", errors="replace")
            except Exception as e:
                st.error(f"Error reading template: {e}")

        # Normalize template text regardless of source (fixes ->, quotes, entities)
        template_text = normalize_template_text(template_text)

        template_text = st.text_area(
            "Or paste gosu script here:",
            value=template_text,
            height=260,
            help='We will replace only: var pols = { … } (items) and var eventDate = "MM/DD/YYYY".toDate().trimToMidnight() (literal only).'
        )

        # Normalize again in case user pasted encoded text
        template_text = normalize_template_text(template_text)

        # Build new script (preserving template formatting; date = MM/DD/YYYY)
        if st.button("Generate Gosu (.txt)", type="primary", use_container_width=True, disabled=len(template_text.strip()) == 0):
            date_mmddyyyy = selected_dt.strftime("%m/%d/%Y")
            new_gosu = inject_into_gosu(template_text, final_payload, date_mmddyyyy)
            st.session_state["generated_gosu"] = new_gosu
            st.session_state["gosu_out_name"] = f"fab_gosuScript_{selected_dt.strftime('%Y-%m-%d')}.txt"

        # --- Display Results and Automation (if generated) ---
        if "generated_gosu" in st.session_state:
            new_gosu = st.session_state["generated_gosu"]
            out_name = st.session_state["gosu_out_name"]

            st.success(f"Gosu script generated: {out_name}")
            st.download_button(
                label="Download gosu (.txt)",
                data=new_gosu.encode("utf-8"),
                file_name=out_name,
                mime="text/plain"
            )
            # --- Automation Trigger ---
            st.write("---")
            st.subheader("🤖 PolicyCenter Automation")
            
            if st.button("🚀 Execute and Get Output", type="primary", use_container_width=True):
                with st.status("Running PolicyCenter Automation...", expanded=True) as status:
                    # 1. Write the script to a temp file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode='w', encoding='utf-8') as tf:
                        tf.write(new_gosu)
                        temp_script_path = tf.name

                    try:
                        # 2. Run the Playwright script
                        st.write("Launching browser and navigating to PolicyCenter...")
                        cmd = [
                            sys.executable, 
                            "automation_pc.py", 
                            temp_script_path, 
                            "--url", "https://policy-center-sample-server.onrender.com",
                            "--outdir", os.getcwd(),
                            "--headless", "False"
                        ]
                        
                        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                        
                        # Stream the output and capture stats
                        count_not_happen = 0
                        count_not_created = 0
                        total_found = 0
                        
                        for line in process.stdout:
                            clean_line = line.strip()
                            st.write(f"`{clean_line}`")
                            
                            # Parse stats from stdout
                            if "COUNT_DID_NOT_HAPPEN:" in clean_line:
                                try:
                                    count_not_happen = int(clean_line.split(":")[-1].strip())
                                except ValueError: pass
                            elif "COUNT_NOT_CREATED:" in clean_line:
                                try:
                                    count_not_created = int(clean_line.split(":")[-1].strip())
                                except ValueError: pass
                            elif "TOTAL_ROWS:" in clean_line:
                                try:
                                    total_found = int(clean_line.split(":")[-1].strip())
                                except ValueError: pass
                        
                        process.wait()

                        if process.returncode == 0:
                            status.update(label="✅ Automation Completed successfully!", state="complete", expanded=False)
                            
                            # Display statistics
                            st.write("### 📊 Execution Summary")
                            m1, m2, m3 = st.columns(3)
                            m1.metric("Did Not Happen", count_not_happen)
                            m2.metric("Not Created", count_not_created)
                            
                            successful_count = total_found - (count_not_happen + count_not_created)
                            m3.metric("Total Captured", successful_count)
                            
                            st.success(f"Results have been saved as an Excel file (.xlsx) in your project directory: `{os.getcwd()}`")
                        else:
                            status.update(label="❌ Automation Failed", state="error", expanded=True)
                            st.error("There was an error during the automation process. Check the logs above.")
                    except Exception as e:
                        st.error(f"Error launching automation: {e}")
                    finally:
                        # Cleanup temp file
                        if os.path.exists(temp_script_path):
                            os.remove(temp_script_path)


if __name__ == "__main__":
    main()