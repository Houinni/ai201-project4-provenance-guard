import json
from pathlib import Path

LOG_FILE = Path(__file__).parent / "audit_log.jsonl"


def append_entry(entry):
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_recent_entries(limit=50):
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries[-limit:]
