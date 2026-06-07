# -*- coding: utf-8 -*-
"""Core engine functional tests + adversarial regression tests"""

import sys
sys.path.insert(0, ".")

from privacy_engine import filter_text, scan_text, add_rule

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}  {detail}")


# ══════════════════════════════════════════════════════
# Positive functional tests
# ══════════════════════════════════════════════════════

print("=" * 60)
print("PART 1: Positive Functional Tests")
print("=" * 60)

# 1 — IPv4
result = filter_text("ssh root@203.0.113.1 ufw status")
check("IPv4 public", "[IP]" in result and "203.0.113.1" not in result, result)

# 2 — UUID with hyphens
result = filter_text("UUID: 4e0a1c0d-3342-4d5b-8785-6618aff9b102")
check("UUID with hyphens", "[UUID]" in result and "4e0a1c0d" not in result, result)

# 3 — API Key
result = filter_text("Authorization: Bearer sk-abc123def45678901234567890")
check("API Key", "[API_KEY]" in result and "sk-abc123" not in result, result)

# 4 — Private IPs now filtered
result = filter_text("ping 127.0.0.1 && ping 192.168.1.1 && ping 10.0.0.1")
check("Private IP filter", all(x not in result for x in ["127.0.0.1", "192.168.1.1", "10.0.0.1"]), result)

# 5 — Protocol address 0.0.0.0 still preserved
result = filter_text("bind 0.0.0.0:8080")
check("0.0.0.0 whitelist", "0.0.0.0" in result, result)

# 6 — scan
matches = scan_text("IP: 203.0.113.1, UUID: abcd1234-5678-abcd-1234-5678abcdef01, key=sk-test12345678901234567890")
check("scan detection", len(matches) >= 3, f"got {len(matches)}")

# 7 — add_rule
add_rule("test_project", r"PROJ-\d{6}", "[PROJECT]")
result = filter_text("deploy PROJ-123456 to server")
check("custom rule", "[PROJECT]" in result, result)

# 8 — Email
result = filter_text("contact admin@company.com")
check("email", "[EMAIL]" in result, result)

# 9 — China mainland phone
result = filter_text("phone: 13812345678")
check("phone CN", "[PHONE]" in result, result)

# 10 — China mainland ID card
result = filter_text("ID: 110101199001011234")
check("ID card CN", "[ID_CARD]" in result, result)

# 11 — All rules loadable by default
from privacy_engine import PrivacyDetector
d = PrivacyDetector()
check(f"rules loaded ({len(d._rules)})", len(d._rules) >= 18, f"got {len(d._rules)}")

# ══════════════════════════════════════════════════════
# Adversarial regression tests (should be fixed)
# ══════════════════════════════════════════════════════

print()
print("=" * 60)
print("PART 2: Adversarial Regression Tests (should be fixed)")
print("=" * 60)

# Unicode normalization — fullwidth phone number
result = filter_text("电话: １３９１２３４５６７８")
check("fullwidth digits → phone", "[PHONE]" in result, result)

# Unicode normalization — fullwidth credit card (Luhn fail → filter skips, scan still detects)
result = filter_text("卡号 ４３９２ ５７９９ １２３４ ５６７８")
check("fullwidth digits → card", "[CARD]" not in result, "NFKC works but Luhn fails — should not replace")
# Confirm scan can still detect (low confidence)
m = scan_text("卡号 ４３９２ ５７９９ １２３４ ５６７８")
check("fullwidth digits → card scan detects", any(x["type"] == "credit_card" and x["confidence"] == "low" for x in m), f"matched: {[x['type'] for x in m]}")

# AWS Key case-insensitive
result = filter_text("register akiaqt4v25abcd6efghj test")
check("AWS Key lowercase", "[AWS_KEY]" in result, result)

# GitHub fine-grained PAT
result = filter_text("token is github_pat_11A22B33C44D55E66F77G88H99I00J11K22L33")
check("GitHub PAT new prefix", "[GITHUB_TOKEN]" in result, result)

# SSH PRIVATE KEY generic format
result = filter_text("-----BEGIN PRIVATE KEY-----\nMIIEvg...\n-----END PRIVATE KEY-----")
check("SSH PKCS#8 generic", "[SSH_KEY]" in result, result)

# UUID 32 hex without hyphens
result = filter_text("trace id: 550e8400e29b41d4a716446655440000")
check("UUID no hyphens", "[UUID]" in result, result)

# DB connection dialect driver
result = filter_text("connect postgresql+psycopg2://admin:pass@db.example.com:5432/prod")
check("DB connection dialect driver", "[DB_URL]" in result, result)

# DB CLI format
result = filter_text("psql -h pg-server.internal -U readonly -d prod -p 5432")
check("DB CLI command line", "[DB_CMD]" in result, result)

# Credit card Luhn fail → filter skips, scan still detects at low confidence
result = filter_text("card 4392 5799 1234 5678")
check("credit card Luhn — no replace", "[CARD]" not in result, "Luhn fail — should not replace")
m = scan_text("card 4392 5799 1234 5678")
check("credit card Luhn — scan detects", any(x["type"] == "credit_card" for x in m), f"matched: {[x['type'] for x in m]}")

# IPv6 hyphen format
result = filter_text("connect FE80-0000-0000-0000-0202-B3FF-FE1E-8329 failed")
check("IPv6 hyphen format", "[IP]" in result, result)

# IPv6 brackets + compressed — no leftover debris
result = filter_text("endpoint [2001:db8::1] port 443 timeout")
check("IPv6 brackets no debris", "[IP]" in result and "1]" not in result, result)

# IPv6 mixed IPv4
result = filter_text("address ::ffff:192.0.2.1 format")
check("IPv6 mixed IPv4", "[IP]" in result and "0.2.1" not in result, result)

# Hex IPv4
result = filter_text("address 0xC0A80101 maps to")
check("IPv4 hex", "[IP]" in result, result)

# JWT multiline format
result = filter_text("token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\n.\neyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ\n.\nsignature")
check("JWT multiline", "[JWT]" in result, result)

# Phone with parentheses
result = filter_text("phone (138) 1234-5678")
check("phone with parentheses", "[PHONE]" in result, result)

# ID card with hyphens
result = filter_text("ID 110101-19900101-1234 verify")
check("ID card with hyphens", "[ID_CARD]" in result, result)

# ══════════════════════════════════════════════════════
# Known limitations (expected leaks)
# ══════════════════════════════════════════════════════

print()
print("=" * 60)
print("PART 3: Known Limitations (expected leaks)")
print("=" * 60)

# "[.]" bypass
result = filter_text("address 192[.]168[.]1[.]150 check")
check("[.] bypass → expected leak", "192[.]168[.]1[.]150" in result, result)

# "at" as @ bypass
result = filter_text("email zhangjie at company")
check("at as @ bypass → expected leak", "zhangjie at company" in result, result)

# IP with spaces
result = filter_text("address 192. 168. 1. 1 check")
check("IP spaces → expected leak", "192. 168. 1. 1" in result, result)

# ══════════════════════════════════════════════════════

print()
print("=" * 60)
print(f"RESULT: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 60)
