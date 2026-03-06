import asyncio
from playwright.async_api import async_playwright
import argparse
import os
from datetime import datetime
import pandas as pd

async def run_automation(script_path: str, url: str, outdir: str, headless: bool):
    async with async_playwright() as p:
        print(f"Launching browser (Headless={headless})...")
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        try:
            print(f"Step 1: Navigating to {url}")
            await page.goto(url, timeout=60000)

            print("Step 2: Accessing Support Queries section")
            await page.click('text="Support Queries"')
            await page.wait_for_load_state("networkidle")

            print(f"Step 3: Reading Gosu script from temp file")
            with open(script_path, "r", encoding="utf-8") as f:
                gosu_script = f.read()

            print("Step 4: Filling the Gosu Script area")
            await page.fill('textarea#gosuScript', gosu_script)

            print("Step 5: Executing script...")
            await page.click('button:has-text("Execute")')

            # Wait for execution to process
            print("Step 6: Waiting for results (approx. 10s)...")
            await page.wait_for_timeout(10000)

            print("Step 7: Identifying and extracting results")
            results_selectors = [
                '#resultsArea',
                '.results-container',
                '#results',
                'pre',
                'textarea'
            ]

            raw_results = None
            for selector in results_selectors:
                try:
                    element = page.locator(selector)
                    tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
                    
                    if tag_name == "textarea":
                        content = await element.input_value()
                    else:
                        content = await element.text_content()
                        
                    if content and content.strip():
                        raw_results = content
                        print(f"SUCCESS: Results captured from {selector} ({tag_name})")
                        break
                except Exception:
                    continue

            if not raw_results:
                print("WARNING: Specific results container not found, taking page text snapshot.")
                raw_results = await page.inner_text('body')

            # --- Parse and Process Results ---
            print("Step 8: Parsing results and generating Excel...")
            lines = [line.strip() for line in raw_results.splitlines() if line.strip()]
            data = []
            
            count_not_happen = 0
            count_not_created = 0
            
            for line in lines:
                if '|' in line:
                    parts = line.split('|', 1)
                    policy = parts[0].strip()
                    comment = parts[1].strip()
                else:
                    policy = line
                    comment = ""
                
                data.append({"policy": policy, "comment": comment})
                
                # Update counts
                if "FAB cancellation did not happen" in comment:
                    count_not_happen += 1
                elif "cancellation not created" in comment:
                    count_not_created += 1

            # Print counts for Streamlit to parse
            print(f"TOTAL_ROWS: {len(lines)}")
            print(f"COUNT_DID_NOT_HAPPEN: {count_not_happen}")
            print(f"COUNT_NOT_CREATED: {count_not_created}")

            # Create DataFrame and save to Excel
            df = pd.DataFrame(data)
            
            os.makedirs(outdir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Save Excel
            excel_filename = f"results_{timestamp}.xlsx"
            excel_path = os.path.join(outdir, excel_filename)
            df.to_excel(excel_path, index=False)
            
            # Also save TXT for legacy/backup
            txt_filename = f"results_{timestamp}.txt"
            txt_path = os.path.join(outdir, txt_filename)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(raw_results)

            print(f"DONE: Final output saved to {excel_path}")

        except Exception as e:
            print(f"ERROR: Automation failed: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate PolicyCenter Gosu script execution.")
    parser.add_argument("script_path", help="Path to the temporary Gosu script file")
    parser.add_argument("--url", default="https://policy-center-sample-server.onrender.com", help="Target URL")
    parser.add_argument("--outdir", default=os.getcwd(), help="Output directory")
    parser.add_argument("--headless", type=lambda x: (str(x).lower() == 'true'), default=True, help="Run browser in headless mode")
    
    args = parser.parse_args()
    
    asyncio.run(run_automation(args.script_path, args.url, args.outdir, args.headless))
