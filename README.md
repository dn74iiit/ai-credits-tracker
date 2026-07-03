# ⚡ My AI Credits Tracker

A simple, beautiful website that tracks how many free credits/plans I have left on all the AI coding tools on my laptop!

👉 **[View My Live Dashboard Here!](https://dn74iiit.github.io/ai-credits-tracker/)** *(Note: Replace `ai-credits-tracker` with your repository name if you change it)*

---

## 🚀 How it works

1. **The Website**: A clean, dark-themed dashboard (HTML, CSS, JS) that loads details from `ai-tracker-sources.json`.
2. **The Sync Script**: A local Python script (`sync_credits.py`) that runs in the background on my laptop. It:
   * Extracts my **Cursor** tokens locally and gets my usage details.
   * Connects to the **Devin** API using my service key to get my ACUs.
   * Auto-commits the updated numbers and pushes them to GitHub.

---

## 🛠️ How to set it up on your laptop

1. **Create your `.env` file** in the project folder and paste your keys:
   ```env
   OPENAI_API_KEY=your_openai_key_here
   GEMINI_API_KEY=your_gemini_key_here
   DEVIN_API_KEY=your_devin_key_here
   ```
2. **Run a test check** (won't push to GitHub):
   ```bash
   python sync_credits.py --dry-run
   ```
3. **Run a full sync**:
   ```bash
   python sync_credits.py
   ```

---

## ⏰ Keep it updating automatically

To keep it updating every 10 minutes without thinking:
1. Open **Task Scheduler** on Windows.
2. Create a basic task named `AI Credits Sync`.
3. Set the trigger to **Daily** and configure it to **repeat every 10 minutes**.
4. Set Action to **Start a Program**:
   * **Program/script**: `pythonw.exe` *(runs in the background without popping up a terminal window)*
   * **Arguments**: `sync_credits.py`
   * **Start in**: `c:\Users\dhanu\OneDrive\Documentos\AI plans tracker site`
