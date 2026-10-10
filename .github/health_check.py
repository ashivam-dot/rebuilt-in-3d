"""Open (or update) an alert issue when the studio is silent or its last run failed."""
import json
import subprocess
import sys
from datetime import datetime, timezone

health = json.load(open(sys.argv[1]))
age = (datetime.now(timezone.utc) - datetime.fromisoformat(health["at"])).total_seconds() / 3600
problem = None
if age > 4:
    problem = f"No studio run recorded for {age:.1f} hours (last at {health['at']})."
elif not health.get("ok"):
    problem = f"Last run failed: {health.get('error')}"
print(problem or f"healthy: last run {age:.1f} h ago")
if problem:
    found = subprocess.run(["gh", "issue", "list", "--state", "open", "--label", "alert", "--search", "Studio is silent",
                            "--json", "number", "--jq", ".[0].number"], capture_output=True, text=True).stdout.strip()
    if found:
        subprocess.run(["gh", "issue", "comment", found, "--body", problem], check=True)
    else:
        subprocess.run(["gh", "issue", "create", "--label", "alert", "--title", "Studio is silent", "--body", problem],
                       check=True)

try:  # the other channels' watch must never hide this studio's own alert
    import fleet_check

    fleet_check.main()
except Exception as exc:
    print(f"fleet check: {type(exc).__name__}: {exc}")
