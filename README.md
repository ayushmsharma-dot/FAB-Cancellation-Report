# RNCL & PolicyCenter Automation Dashboard

This project is a Streamlit-based dashboard designed for processing RNCL files and automating the execution of generated Gosu scripts on a PolicyCenter server.
https://policy-center-sample-server.onrender.com
## 🚀 Quick Start Guide

If you are setting this up for the first time or on a new machine, follow these steps:

### 1. Prerequisites
- **Python 3.11+** installed.
- Internet connection for installing dependencies.

### 2. Initial Setup
1. **Open your terminal** and navigate to the project directory:
   ```bash
   cd "path/to/project/pipeline_AO/pipeline_AO/"
   ```

2. **Create and Activate a Virtual Environment**:
   ```bash
   # Create the environment
   py -m venv venv

   # Activate it (Windows)
   venv\Scripts\activate

   # Activate it (macOS/Linux)
   source venv/bin/activate
   ```

3. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright Browsers** (Critical for Automation):
   ```bash
   playwright install chromium
   ```

### 3. Running the Application
# cd to phase_1 folder
Start the Streamlit dashboard:
```bash
streamlit run app.py
```
The app will typically open at `http://localhost:8501`.

---

## 🛠 Features & Workflow

### 1. RNCL Data Processing
- **Date Selection:** Set the Report Date in the sidebar.
- **File Upload:** Upload the required RNCL files (APPS and FPPS).
- **Standardization:** The app automatically cleans and standardizes the data into Excel, CSV, and TXT formats.

### 2. Gosu Script Builder
- **Template Integration:** Upload or paste a Gosu template.
- **Injection:** The app injects the processed policy list and selected date into the template.
- **Download:** Save the final `.txt` script locally.

### 3. PolicyCenter Automation (New)
- **Direct Execution:** Click the **🚀 Execute and Get Output** button.
- **Headed Browser:** A browser window will launch automatically, navigate to the PolicyCenter server, execute your script, and capture the results.
- **Automatic Retrieval:** Results are saved directly to your project folder with a timestamp (e.g., `results_20260302_123456.txt`).

---

## 📁 Project Structure
- `app.py`: Main Streamlit application and processing logic.
- `automation_pc.py`: Playwright script for PolicyCenter interaction.
- `requirements.txt`: List of required Python libraries.
- `README.md`: This setup and usage guide.

## ⚠️ Troubleshooting
- **Automation doesn't start:** Ensure you ran `playwright install chromium`. 
- **Variable state lost:** If the automation button disappears, ensure you've clicked "Generate Gosu (.txt)" first.





## Mock Server Link: https://policy-center-sample-server.onrender.com
