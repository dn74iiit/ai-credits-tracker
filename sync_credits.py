import os
import sys
import json
import sqlite3
import datetime
import urllib.request
import urllib.error
import subprocess

# Force utf-8 output on Windows standard streams if supported
if sys.platform.startswith('win'):
    try:
        import ctypes
        # Set console output code page to UTF-8 (65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

def load_env(path=".env"):
    """Parse local .env file without external dependencies."""
    env = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        val = v.strip().strip("'\"")
                        # Strip accidental leading colon (e.g. key=:value)
                        if val.startswith(":"):
                            val = val[1:].strip().strip("'\"")
                        env[k.strip()] = val
    return env

def get_cursor_usage():
    """Fetch usage stats from Cursor backend using local database session token."""
    print("[INFO] Checking Cursor usage...")
    try:
        # Resolve Cursor database path
        db_path = os.path.expandvars(r'%APPDATA%\Cursor\User\globalStorage\state.vscdb')
        if not os.path.exists(db_path):
            print("[WARN] Cursor SQLite database not found locally.")
            return None
        
        # Connect to SQLite
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'")
        row = c.fetchone()
        conn.close()
        
        if not row or not row[0]:
            print("[WARN] Cursor accessToken not found in SQLite database. Please log in to Cursor.")
            return None
            
        token = row[0]
        
        # Call Cursor DashboardService RPC API
        url = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
        req = urllib.request.Request(url, method="POST", headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Connect-Protocol-Version': '1',
            'User-Agent': 'Mozilla/5.0'
        }, data=b'{}')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            plan_usage = data.get("planUsage", {})
            used = plan_usage.get("totalSpend", 0)
            pct = plan_usage.get("totalPercentUsed", 0.0)
            
            # Compute limit dynamically
            if pct > 0:
                limit = int(round(used / (pct / 100.0)))
            else:
                limit = 500 # Default fallback
            
            # Parse reset date from billingCycleEnd
            reset_ts = data.get("billingCycleEnd")
            reset_date = ""
            if reset_ts:
                try:
                    dt = datetime.datetime.fromtimestamp(int(reset_ts) / 1000)
                    reset_date = dt.strftime('%Y-%m-%d')
                except Exception:
                    pass
            
            print(f"[SUCCESS] Cursor: {used}/{limit} requests used (resets {reset_date}).")
            return {"used": int(used), "limit": int(limit), "resetDate": reset_date}
            
    except Exception as e:
        print(f"[ERROR] Failed to retrieve Cursor usage: {e}")
        return None

def get_openai_usage(api_key):
    """Fetch OpenAI/Codex usage stats using the billing APIs."""
    print("[INFO] Checking OpenAI/Codex usage...")
    if not api_key or api_key == "your_openai_key_here":
        print("[WARN] OpenAI API key not configured in .env.")
        return None
        
    try:
        # Determine current month start/end dates for API query
        today = datetime.date.today()
        start_date = today.replace(day=1).isoformat()
        end_date = today.isoformat()
        
        # 1. Fetch remaining credit and limits
        sub_url = "https://api.openai.com/v1/dashboard/billing/subscription"
        req_sub = urllib.request.Request(sub_url, headers={
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'Mozilla/5.0'
        })
        
        limit_usd = 0.0
        try:
            with urllib.request.urlopen(req_sub, timeout=10) as response:
                sub_data = json.loads(response.read().decode('utf-8'))
                limit_usd = float(sub_data.get("hard_limit_usd", 0.0))
        except urllib.error.HTTPError as he:
            if he.code == 403:
                print("[WARN] OpenAI billing API returned 403 (Forbidden).")
                print("       Project-restricted API keys (sk-proj-...) do not have permission to read billing/limits.")
                print("       To automate this, use an Admin/User API key or update Codex manually in the JSON file.")
                return None
            raise he
            
        # 2. Fetch usage for the current month
        usage_url = f"https://api.openai.com/v1/dashboard/billing/usage?start_date={start_date}&end_date={end_date}"
        req_usage = urllib.request.Request(usage_url, headers={
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'Mozilla/5.0'
        })
        
        used_usd = 0.0
        with urllib.request.urlopen(req_usage, timeout=10) as response:
            usage_data = json.loads(response.read().decode('utf-8'))
            used_usd = float(usage_data.get("total_usage", 0.0)) / 100.0 # OpenAI returns usage in cents
            
        print(f"[SUCCESS] OpenAI: ${used_usd:.2f}/${limit_usd:.2f} used.")
        return {
            "used": round(used_usd, 2),
            "limit": round(limit_usd, 2)
        }
    except Exception as e:
        print(f"[ERROR] Failed to retrieve OpenAI usage: {e}")
        return None

def get_devin_usage(api_key):
    """Fetch Devin consumption/usage metrics using the Devin organization scope API."""
    print("[INFO] Checking Devin usage...")
    if not api_key or api_key == "your_devin_key_here":
        print("[WARN] Devin API key not configured in .env.")
        return None
        
    try:
        # 1. First, fetch org_id dynamically via /v3/self
        self_url = "https://api.devin.ai/v3/self"
        req_self = urllib.request.Request(self_url, headers={
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'Mozilla/5.0'
        })
        
        with urllib.request.urlopen(req_self, timeout=10) as response:
            self_data = json.loads(response.read().decode('utf-8'))
            org_id = self_data.get("org_id")
            
        if not org_id:
            print("[WARN] Devin: Could not determine organization ID from /v3/self.")
            return None
            
        # 2. Query daily consumption using the organization-specific endpoint
        url = f"https://api.devin.ai/v3/organizations/{org_id}/consumption/daily"
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'Mozilla/5.0'
        })
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            total_acus = float(data.get("total_acus", 0.0))
            
            print(f"[SUCCESS] Devin: {total_acus:.2f} ACUs used.")
            # Note: We return only the 'used' ACUs, limit is preserved in the json file
            return {"used": round(total_acus, 2)}
            
    except Exception as e:
        print(f"[ERROR] Failed to retrieve Devin usage: {e}")
        return None

def get_gemini_usage(api_key):
    """Placeholder check for Google AI Studio / Gemini."""
    print("[INFO] Checking Google Gemini API usage...")
    if not api_key or api_key == "your_gemini_key_here":
        print("[WARN] Gemini API key not configured in .env.")
        return None
    # Google AI Studio API key doesn't expose a credit-balance dashboard endpoint,
    # it is free-tier rate-limited. We return a placeholder to verify connectivity.
    print("[SUCCESS] Google Gemini API key is configured. Free tier active (rate limits apply).")
    return {"used": 0, "limit": 0} # 0 indicates unlimited / rate-only

def update_json_file(cursor_stats, openai_stats, devin_stats, gemini_stats):
    """Write updated usage stats into the local JSON data file."""
    file_path = "ai-tracker-sources.json"
    if not os.path.exists(file_path):
        print(f"[ERROR] Error: {file_path} not found.")
        return False
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["lastUpdated"] = datetime.datetime.utcnow().isoformat() + "Z"
        
        for source in data.get("sources", []):
            name_lower = source["name"].lower()
            
            # Match Cursor
            if "cursor" in name_lower and cursor_stats:
                source["used"] = cursor_stats["used"]
                source["limit"] = cursor_stats["limit"]
                if "resetDate" in cursor_stats and cursor_stats["resetDate"]:
                    source["resetDate"] = cursor_stats["resetDate"]
                
            # Match Codex (OpenAI)
            elif ("codex" in name_lower or "openai" in name_lower) and openai_stats:
                source["used"] = openai_stats["used"]
                source["limit"] = openai_stats["limit"]
                
            # Match Devin
            elif "devin" in name_lower and devin_stats:
                source["used"] = devin_stats["used"]
                # Only update limit if provided, otherwise keep existing
                if "limit" in devin_stats:
                    source["limit"] = devin_stats["limit"]
                
            # Match Antigravity Gemini
            elif "gemini" in name_lower and gemini_stats:
                source["used"] = gemini_stats["used"]
                source["limit"] = gemini_stats["limit"]
                
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        print(f"[INFO] Updated {file_path} successfully.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to write updates to JSON file: {e}")
        return False

def push_to_github():
    """Automatically commit and push changes to GitHub Pages."""
    print("[INFO] Syncing with GitHub...")
    try:
        # Check if it is a git repo
        git_check = subprocess.run(["git", "status"], capture_output=True, text=True)
        if git_check.returncode != 0:
            print("[WARN] Current folder is not initialized as a git repository. Skipping push.")
            return False
            
        # Stage the updated JSON
        subprocess.run(["git", "add", "ai-tracker-sources.json"], check=True)
        
        # Commit changes
        commit_msg = f"auto-sync: update AI credit metrics [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        
        # Push to remote
        push_res = subprocess.run(["git", "push"], capture_output=True, text=True)
        if push_res.returncode == 0:
            print("[SUCCESS] GitHub Pages sync complete. Dashboard is updating!")
            return True
        else:
            print(f"[ERROR] Git push failed: {push_res.stderr.strip()}")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Git sync failed: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Error running Git commands: {e}")
        return False

def main():
    # Parse arguments
    dry_run = "--dry-run" in sys.argv
    skip_git = "--skip-git" in sys.argv or dry_run
    
    # Load keys
    env = load_env()
    
    # Fetch usage for each app
    cursor_stats = get_cursor_usage()
    openai_stats = get_openai_usage(env.get("OPENAI_API_KEY"))
    devin_stats = get_devin_usage(env.get("DEVIN_API_KEY"))
    gemini_stats = get_gemini_usage(env.get("GEMINI_API_KEY"))
    
    # Update local database file
    if not dry_run:
        update_ok = update_json_file(cursor_stats, openai_stats, devin_stats, gemini_stats)
        if update_ok and not skip_git:
            push_to_github()
    else:
        print("\n[INFO] DRY-RUN: Updates were fetched but not written or pushed.")
        print(f"Cursor: {cursor_stats}")
        print(f"OpenAI: {openai_stats}")
        print(f"Devin: {devin_stats}")
        print(f"Gemini: {gemini_stats}")

if __name__ == "__main__":
    main()
