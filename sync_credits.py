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
    """Fetch Devin consumption/usage metrics. Prio 1: Local IDE chat quota. Prio 2: Web API ACUs."""
    print("[INFO] Checking Devin usage...")
    
    # 1. Try to read local Devin IDE state cache
    try:
        db_path = os.path.expandvars(r'%APPDATA%\devin\User\globalStorage\state.vscdb')
        if os.path.exists(db_path):
            import sqlite3
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT value FROM ItemTable WHERE key LIKE 'windsurf.reactSettings.cachedPlanInfoData:%'")
            row = c.fetchone()
            conn.close()
            
            if row:
                info = json.loads(row[0])
                weekly_rem = info.get("weeklyRemainingPercent", 100)
                weekly_used = int(round(100 - weekly_rem))
                weekly_reset_unix = info.get("weeklyResetAtUnix")
                
                daily_rem = info.get("dailyRemainingPercent", 100)
                daily_used = int(round(100 - daily_rem))
                daily_reset_unix = info.get("dailyResetAtUnix")
                
                weekly_reset_date = ""
                if weekly_reset_unix:
                    try:
                        dt = datetime.datetime.fromtimestamp(weekly_reset_unix, datetime.timezone.utc)
                        weekly_reset_date = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                    except Exception:
                        pass
                        
                daily_reset_date = ""
                if daily_reset_unix:
                    try:
                        dt = datetime.datetime.fromtimestamp(daily_reset_unix, datetime.timezone.utc)
                        daily_reset_date = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                    except Exception:
                        pass
                        
                print(f"[SUCCESS] Devin (Local IDE): Daily {daily_used}%, Weekly {weekly_used}%.")
                return {
                    "is_local": True,
                    "daily": {"used": daily_used, "limit": 100, "resetDate": daily_reset_date},
                    "weekly": {"used": weekly_used, "limit": 100, "resetDate": weekly_reset_date}
                }
    except Exception as e:
        print(f"[WARN] Failed to read local Devin IDE cache: {e}")

    # 2. Fallback: Query Web API
    if not api_key or api_key == "your_devin_key_here":
        print("[WARN] Devin API key not configured in .env. Skipping Web API check.")
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
            
            # Calculate next Monday (standard Devin weekly credit reset)
            today = datetime.date.today()
            days_to_monday = (0 - today.weekday()) % 7
            if days_to_monday == 0:
                days_to_monday = 7
            next_monday = today + datetime.timedelta(days=days_to_monday)
            reset_date = next_monday.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            print(f"[SUCCESS] Devin (Web API): {total_acus:.2f} ACUs used (resets {reset_date}).")
            return {
                "is_local": False,
                "weekly": {"used": round(total_acus, 2), "resetDate": reset_date}
            }
            
    except Exception as e:
        print(f"[ERROR] Failed to retrieve Devin Web API usage: {e}")
        return None

def get_antigravity_usage():
    """Fetch usage stats from Antigravity IDE local cache."""
    print("[INFO] Checking Antigravity IDE usage...")
    try:
        config_path = os.path.expandvars(r'%APPDATA%\antigravity-usage\config.json')
        if not os.path.exists(config_path):
            print("[WARN] Antigravity IDE configuration not found.")
            return None
            
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            email = config.get("activeAccount")
            
        if not email:
            print("[WARN] Active account not found in Antigravity config.")
            return None
            
        cache_path = os.path.expandvars(f'%APPDATA%\\antigravity-usage\\accounts\\{email}\\cache.json')
        if not os.path.exists(cache_path):
            print("[WARN] Antigravity cache file not found.")
            return None
            
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
            
        models = cache.get("data", {}).get("models", [])
        
        gemini_stats = None
        claude_stats = None
        
        # Find first gemini model and first claude model
        for m in models:
            model_id = m.get("modelId", "").lower()
            rem_pct = m.get("remainingPercentage", 1.0)
            reset_time_str = m.get("resetTime", "")
            
            # Format reset date
            reset_date = ""
            if reset_time_str:
                try:
                    dt = datetime.datetime.strptime(reset_time_str.split(".")[0].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                    reset_date = dt.strftime('%Y-%m-%d')
                except Exception:
                    pass
            
            used_pct = int(round((1.0 - rem_pct) * 100))
            
            if "gemini" in model_id and not gemini_stats:
                gemini_stats = {"used": used_pct, "limit": 100, "resetDate": reset_date}
            elif "claude" in model_id and not claude_stats:
                claude_stats = {"used": used_pct, "limit": 100, "resetDate": reset_date}
                
        if gemini_stats:
            print(f"[SUCCESS] Antigravity Gemini: {gemini_stats.get('used')}% used (resets {gemini_stats.get('resetDate')}).")
        if claude_stats:
            print(f"[SUCCESS] Antigravity Claude: {claude_stats.get('used')}% used (resets {claude_stats.get('resetDate')}).")
            
        return {
            "gemini": gemini_stats,
            "claude": claude_stats
        }
    except Exception as e:
        print(f"[ERROR] Failed to retrieve Antigravity usage: {e}")
        return None

def update_json_file(cursor_stats, openai_stats, devin_stats, antigravity_stats):
    """Write updated usage stats into the local JSON data file."""
    file_path = "ai-tracker-sources.json"
    if not os.path.exists(file_path):
        print(f"[ERROR] Error: {file_path} not found.")
        return False
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["lastUpdated"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        
        for source in data.get("sources", []):
            name_lower = source["name"].lower()
            
            # Match Cursor
            if "cursor" in name_lower and cursor_stats:
                for q in source.get("quotas", []):
                    if q.get("period") == "monthly":
                        q["used"] = cursor_stats["used"]
                        q["limit"] = cursor_stats["limit"]
                        q["resetDate"] = cursor_stats["resetDate"]
                
            # Match Codex (OpenAI)
            elif ("codex" in name_lower or "openai" in name_lower) and openai_stats:
                for q in source.get("quotas", []):
                    if q.get("period") == "monthly":
                        q["used"] = openai_stats["used"]
                        q["limit"] = openai_stats["limit"]
                
            # Match Devin
            elif "devin" in name_lower and devin_stats:
                if devin_stats.get("is_local"):
                    for q in source.get("quotas", []):
                        if q.get("period") == "daily" and "daily" in devin_stats:
                            q["used"] = devin_stats["daily"]["used"]
                            q["limit"] = devin_stats["daily"]["limit"]
                            q["resetDate"] = devin_stats["daily"]["resetDate"]
                        elif q.get("period") == "weekly" and "weekly" in devin_stats:
                            q["used"] = devin_stats["weekly"]["used"]
                            q["limit"] = devin_stats["weekly"]["limit"]
                            q["resetDate"] = devin_stats["weekly"]["resetDate"]
                else:
                    # Web API: update weekly only
                    for q in source.get("quotas", []):
                        if q.get("period") == "weekly" and "weekly" in devin_stats:
                            q["used"] = devin_stats["weekly"]["used"]
                            q["resetDate"] = devin_stats["weekly"]["resetDate"]
                
            # Match Antigravity Gemini
            elif "gemini" in name_lower and antigravity_stats and antigravity_stats.get("gemini"):
                for q in source.get("quotas", []):
                    if q.get("period") == "weekly":
                        q["used"] = antigravity_stats["gemini"]["used"]
                        q["limit"] = antigravity_stats["gemini"]["limit"]
                        if antigravity_stats["gemini"].get("resetDate"):
                            q["resetDate"] = antigravity_stats["gemini"]["resetDate"]
                    
            # Match Antigravity Claude
            elif "claude" in name_lower and antigravity_stats and antigravity_stats.get("claude"):
                for q in source.get("quotas", []):
                    if q.get("period") == "weekly":
                        q["used"] = antigravity_stats["claude"]["used"]
                        q["limit"] = antigravity_stats["claude"]["limit"]
                        if antigravity_stats["claude"].get("resetDate"):
                            q["resetDate"] = antigravity_stats["claude"]["resetDate"]
                
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
    antigravity_stats = get_antigravity_usage()
    
    # Update local database file
    if not dry_run:
        update_ok = update_json_file(cursor_stats, openai_stats, devin_stats, antigravity_stats)
        if update_ok and not skip_git:
            push_to_github()
    else:
        print("\n[INFO] DRY-RUN: Updates were fetched but not written or pushed.")
        print(f"Cursor: {cursor_stats}")
        print(f"OpenAI: {openai_stats}")
        print(f"Devin: {devin_stats}")
        print(f"Antigravity: {antigravity_stats}")

if __name__ == "__main__":
    main()
