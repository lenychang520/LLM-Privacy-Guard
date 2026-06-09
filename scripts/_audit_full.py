"""Full audit — scan git history for potentially sensitive strings.

⚠  WARNING  ⚠
This script scans ALL git commits for patterns that look like credentials.
Running it with --raw will print potentially real secrets to stdout.

Default mode (no --raw): only shows redacted summaries (type + commit + count).
Use --raw only in a secure environment where stdout is not logged/piped.

Usage:
    python scripts/_audit_full.py          # safe: redacted summary
    python scripts/_audit_full.py --raw    # ⚠ prints actual values
"""

import re
import sys
import subprocess

RAW_MODE = "--raw" in sys.argv

# ── Banner ──
print("=" * 64)
print("  🔍 LLM Privacy Guard — Git History Audit")
if RAW_MODE:
    print("  ⚠  RAW MODE: actual values will be printed!")
    print("  ⚠  Ensure stdout is NOT logged, piped, or shared.")
else:
    print("  ℹ  Safe mode: values are redacted (first 4 chars only).")
    print("  ℹ  Use --raw to see full values (⚠ caution!).")
print("=" * 64)

# ── Scan ──
try:
    commits = subprocess.check_output(
        ["git", "log", "--all", "--oneline"],
        text=True, encoding="utf-8", errors="replace",
    ).strip().split("\n")
except (subprocess.SubprocessError, FileNotFoundError):
    print("[ERROR] Not a git repository or git not available.")
    sys.exit(1)

if not commits or commits == [""]:
    print("No commits found.")
    sys.exit(0)

all_found: dict[tuple[str, str, str], str] = {}

patterns = [
    ("UUID",       r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I),
    ("IP",         r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', 0),
    ("API_KEY",    r'sk-[a-zA-Z0-9_-]{16,}', 0),
    ("GITHUB_TOKEN", r'gh[pousr]_[a-zA-Z0-9]{30,}', 0),
    ("AWS_KEY",    r'AKIA[A-Z0-9]{16}', 0),
    ("CREDIT_CARD", r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', 0),
    ("SSH_KEY",    r'ssh-(?:rsa|dss|ed25519|ecdsa)\s+[A-Za-z0-9+/=]{100,}', 0),
]

for line in commits:
    if not line.strip():
        continue
    commit_hash = line.split()[0]
    try:
        diff = subprocess.check_output(
            ["git", "show", commit_hash, "--patch"],
            text=True, encoding="utf-8", errors="replace",
            stderr=subprocess.DEVNULL,
        )
    except subprocess.SubprocessError:
        continue

    for ptype, pattern, flags in patterns:
        for m in re.finditer(pattern, diff, flags):
            val = m.group()
            key = (ptype, commit_hash, val)
            if key not in all_found:
                all_found[key] = commit_hash[:7]

# ── Redact helper ──
def _redact(val: str) -> str:
    """Show first 4 chars + type-appropriate hint."""
    if len(val) <= 6:
        return val[:3] + "..."
    if "@" in val:  # email
        parts = val.split("@")
        return parts[0][:3] + "...@" + parts[1]
    return val[:4] + "..." + val[-4:] if len(val) > 8 else val[:4] + "..."

# ── Group and print ──
by_type: dict[str, list[tuple[str, str]]] = {}
for (ptype, ch, val), short_hash in all_found.items():
    by_type.setdefault(ptype, []).append((short_hash, val))

for ptype in ["UUID", "IP", "API_KEY", "GITHUB_TOKEN", "AWS_KEY", "CREDIT_CARD", "SSH_KEY"]:
    if ptype not in by_type:
        continue
    entries = by_type[ptype]
    print(f"\n{'─' * 60}")
    print(f"  {ptype}  ({len(entries)} found)")
    print(f"{'─' * 60}")
    seen = set()
    for short_hash, val in sorted(entries, key=lambda x: x[1]):
        if val in seen:
            continue
        seen.add(val)
        display = val if RAW_MODE else _redact(val)
        print(f"  [{short_hash}]  {display}")

print(f"\n{'=' * 64}")
print(f"  Total: {sum(len(v) for v in by_type.values())} potential secrets found")
if not RAW_MODE:
    print("  Run with --raw to see full values (⚠ secure environment only!)")
print(f"{'=' * 64}")
