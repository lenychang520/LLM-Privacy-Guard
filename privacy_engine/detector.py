# -*- coding: utf-8 -*-
"""Privacy detector — combines regex detection + entropy detection, provides filter/scan API"""

import re
import time
import logging
import unicodedata
import html
import urllib.parse
from dataclasses import dataclass, field
from collections import OrderedDict
from threading import Thread

from .patterns import BUILTIN_RULES, Rule as PatternRule
from .entropy import find_high_entropy, EntropyMatch
from .whitelist import (
    is_whitelisted_ip,
    is_whitelisted_domain,
    is_whitelisted_hostname,
)
from .config import load_config

logger = logging.getLogger(__name__)

# ── Security guards ──

# Maximum text length for regex scanning (100 KB).
# Text exceeding this is truncated to prevent resource exhaustion (DoS).
MAX_TEXT_LENGTH = 100_000

# IPv6 addresses are at most ~39 characters. Scanning very long text
# with the complex IPv6 regex risks ReDoS (catastrophic backtracking).
_IPV6_MAX_TEXT = 5_000

# Burst rate canary: log a warning if filter/scan is called more than
# this many times within a one-second window. Not a hard block — just
# an early-warning signal for potential abuse.
_MAX_CALLS_PER_SECOND = 500

# Regex patterns that are very likely to cause catastrophic backtracking
# (nested quantifiers: (X+)+, (X*)*, (X{n,m})+, etc.)
_REDOS_DANGER = re.compile(r"\([^()]*(?:[+*]|\{\d+,?\d*\})[^()]*\)[+*]")


@dataclass
class Match:
    """A detection match"""

    type: str           # Rule name, e.g. "ipv4", "entropy"
    value: str          # Original value
    start: int          # Start position
    end: int            # End position
    placeholder: str    # Replacement placeholder
    entropy: float = 0.0    # Only populated for entropy matches
    priority: int = 0       # Rule priority
    confidence: str = "high"  # "high" | "low" (card Luhn failure)


def _luhn_check(card_number: str) -> bool:
    """Luhn algorithm — validate credit card number."""
    digits = [int(ch) for ch in card_number if ch.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _normalize(text: str) -> str:
    """Unicode NFKC normalization (defensive inline)."""
    return unicodedata.normalize("NFKC", text)


# Zero-width character set (\u200b zero-width space, \u200c zero-width non-joiner, etc.)
_ZERO_WIDTH_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060\u2061"
    r"\u2062\u2063\u2064\u2066\u2067\u2068\u2069\ufe00-\ufe0f]"
)


def _preprocess(text: str, config: dict) -> str:
    """Preprocess pipeline: clean text before regex matching.

    Order: 1) NFKC normalization → 2) zero-width stripping → 3) URL decode → 4) HTML decode
    """
    pp = config.get("preprocess", {})
    # NFKC normalization (always applied)
    text = _normalize(text)
    # Zero-width character removal
    if pp.get("strip_zw_chars", True):
        text = _ZERO_WIDTH_CHARS.sub("", text)
    # URL decode
    if pp.get("url_decode", True):
        text = _safe_url_decode(text)
    # HTML entity decode
    if pp.get("html_unescape", True):
        text = _safe_html_unescape(text)
    return text


def _safe_url_decode(text: str) -> str:
    """Safe URL decode — falls back to original on failure."""
    try:
        # Limit decode iterations to prevent infinite loops
        for _ in range(3):
            decoded = urllib.parse.unquote(text, errors="strict")
            if decoded == text:
                break
            text = decoded
    except Exception:
        pass
    return text


def _safe_html_unescape(text: str) -> str:
    """Safe HTML decode — falls back to original on failure."""
    try:
        return html.unescape(text)
    except Exception:
        return text


def _validate_regex_safety(pattern: str, name: str) -> None:
    """Validate that a regex pattern does not contain dangerous constructs
    likely to cause catastrophic backtracking (ReDoS).

    Raises ValueError for patterns with nested quantifiers like (X+)+.
    Also runs a quick smoke test with a crafted input and a 1-second timeout.
    """
    # Heuristic: nested quantified groups
    if _REDOS_DANGER.search(pattern):
        raise ValueError(
            f"Rule '{name}': pattern contains nested quantifiers like (X+)+ "
            f"which may cause catastrophic backtracking (ReDoS). "
            f"Restructure the pattern to avoid nested quantifiers."
        )

    # Smoke test: compile + run against a benign long input with 1s timeout
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Rule '{name}': invalid regex: {e}") from e

    test_input = "a" * 256 + " " + "x" * 256
    timeout_exc = None

    def _run():
        nonlocal timeout_exc
        try:
            list(compiled.finditer(test_input))
        except Exception as e:
            timeout_exc = e

    t = Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=1.0)
    if t.is_alive():
        raise ValueError(
            f"Rule '{name}': regex timed out (>1s) on benign input — "
            f"likely vulnerable to catastrophic backtracking. "
            f"Simplify the pattern or add more specific anchors."
        )
    if timeout_exc is not None:
        raise ValueError(
            f"Rule '{name}': regex crashed on smoke test: {timeout_exc}"
        )


class PrivacyDetector:
    """Privacy detector — singleton, internally manages all rules."""

    def __init__(self, config: dict | None = None):
        self._config = config or load_config()

        # Compile built-in rules (OrderedDict preserves priority order)
        self._rules: OrderedDict[str, re.Pattern] = OrderedDict()
        self._placeholders: dict[str, str] = {}
        self._priorities: dict[str, int] = {}

        # Whitelist
        self._whitelist_ips: set[str] = set()
        self._whitelist_domains: set[str] = set()
        self._whitelist_strings: set[str] = set()

        self._custom_rules: list[dict] = []
        self._custom_compiled: list[tuple[str, re.Pattern, str, int]] = []

        # Rate canary (burst detection, not a hard block)
        self._call_count: int = 0
        self._call_window_start: float = time.time()

        self._load_rules()

    # ── Internal methods ──

    def _load_rules(self):
        """Load all rules from config."""
        rules_config = self._config.get("rules", {})
        placeholders_config = self._config.get("placeholders", {})

        # Built-in rules (loaded in BUILTIN_RULES order, preserving priority)
        for rule in BUILTIN_RULES:
            if rules_config.get(rule.name, True):
                self._rules[rule.name] = re.compile(rule.pattern)
                self._placeholders[rule.name] = placeholders_config.get(
                    rule.name, rule.placeholder
                )
                self._priorities[rule.name] = rule.priority

        # Whitelist
        wl = self._config.get("whitelist", {})
        self._whitelist_ips = set(wl.get("ips", []))
        self._whitelist_domains = set(wl.get("domains", []))
        self._whitelist_strings = set(wl.get("strings", []))

        # Custom rules
        for cr in self._config.get("custom_rules", []):
            name = cr.get("name", "")
            pattern = cr.get("pattern", "")
            placeholder = cr.get("placeholder", "[REDACTED]")
            priority = cr.get("priority", 50)
            if name and pattern:
                self._custom_compiled.append(
                    (name, re.compile(pattern), placeholder, priority)
                )
            else:
                logger.warning("Skipping invalid custom rule — missing name or pattern")

    def _check_rate(self, caller: str) -> None:
        """Rate canary: log warning if burst exceeds threshold.

        Not a hard block — just an early-warning signal so operators
        can investigate abnormal call patterns.
        """
        now = time.time()
        elapsed = now - self._call_window_start
        if elapsed >= 1.0:
            # Reset window
            self._call_window_start = now
            self._call_count = 1
            return
        self._call_count += 1
        if self._call_count == _MAX_CALLS_PER_SECOND:
            logger.warning(
                "[LLM Privacy Guard] ⚠ Rate canary triggered: "
                f"{self._call_count} {caller}() calls in {elapsed:.1f}s — "
                "possible abuse, check call patterns"
            )

    def _is_whitelisted(self, rule_name: str, value: str) -> bool:
        """Check if a matched value is in the whitelist."""
        # Exact-match whitelist
        if value in self._whitelist_strings:
            return True
        # IP whitelist: built-in protocol addresses + user config
        if rule_name in ("ipv4", "ipv6", "ipv4_hex", "ipv6_hyphen"):
            if is_whitelisted_ip(value):
                return True
            if value in self._whitelist_ips:
                return True
        # Domain whitelist: built-in + user config
        if rule_name == "email":
            domain_part = value.rsplit("@", 1)[-1] if "@" in value else ""
            if is_whitelisted_domain(domain_part):
                return True
            if domain_part in self._whitelist_domains:
                return True
        # Hostname whitelist (for CLI contexts)
        if is_whitelisted_hostname(value):
            return True
        return False

    # ── Regex match extraction ──

    def _find_regex_matches(
        self,
        text: str,
        rules: list[str] | None = None,
        placeholder: str | None = None,
    ) -> list[Match]:
        """Scan text and return all regex-based Match objects."""
        matches: list[Match] = []

        # Built-in rules (in load order)
        for name, pat in self._rules.items():
            if rules is not None and name not in rules:
                continue

            # ReDoS guard: skip complex IPv6 regex on long text.
            # IPv6 addresses are at most ~39 chars; no legitimate match
            # exists in text longer than _IPV6_MAX_TEXT.
            if name in ("ipv6", "ipv6_hyphen") and len(text) > _IPV6_MAX_TEXT:
                logger.debug(
                    "[LLM Privacy Guard] ⚡ Skipping %s regex — "
                    "text too long (%d chars) for safe scanning",
                    name, len(text),
                )
                continue

            priority = self._priorities.get(name, 0)
            for m in pat.finditer(text):
                value = m.group(0)
                if self._is_whitelisted(name, value):
                    continue
                # Credit card: Luhn failure → keep match but lower confidence
                confidence = "high"
                if name == "credit_card":
                    if not _luhn_check(value):
                        confidence = "low"
                matches.append(
                    Match(
                        type=name,
                        value=value,
                        start=m.start(),
                        end=m.end(),
                        placeholder=placeholder or self._placeholders.get(
                            name, "[REDACTED]"
                        ),
                        priority=priority,
                        confidence=confidence,
                    )
                )

        # Custom rules
        for name, pat, ph, priority in self._custom_compiled:
            if rules is not None and name not in rules:
                continue
            for m in pat.finditer(text):
                value = m.group(0)
                if self._is_whitelisted(name, value):
                    continue
                matches.append(
                    Match(
                        type=name,
                        value=value,
                        start=m.start(),
                        end=m.end(),
                        placeholder=placeholder or ph,
                        priority=priority,
                        confidence="high",
                    )
                )

        return matches

    # ── Overlap deduplication ──

    def _deduplicate_matches(self, matches: list[Match]) -> list[Match]:
        """Deduplicate overlapping matches by priority and length.

        Rules:
        1. Sort by priority (lower = more important)
        2. On overlap: keep higher priority; same priority → keep longer
        3. If one fully contains another → always keep the larger (avoid info leak)
        """
        if not matches:
            return []

        # Sort by start ascending, then priority ascending (lower = first), then length descending
        sorted_matches = sorted(
            matches,
            key=lambda m: (m.start, m.priority, -(m.end - m.start)),
        )

        deduped: list[Match] = []
        for m in sorted_matches:
            if not deduped:
                deduped.append(m)
                continue

            last = deduped[-1]
            # Non-overlapping
            if m.start >= last.end:
                deduped.append(m)
                continue

            # Overlapping — compare priority
            if m.priority < last.priority:
                # Higher priority (lower number) replaces
                deduped[-1] = m
            elif m.priority == last.priority:
                # Same priority → keep longer
                if (m.end - m.start) > (last.end - last.start):
                    deduped[-1] = m
            # else: lower priority → discard

        return deduped

    # ── Public API ──

    def add_rule(self, name: str, pattern: str, placeholder: str = "[REDACTED]", priority: int = 50):
        """Register a new custom rule at runtime.

        Validates the regex for ReDoS (catastrophic backtracking) before
        accepting. Raises ValueError if the pattern is dangerous.
        """
        _validate_regex_safety(pattern, name)
        self._custom_compiled.append(
            (name, re.compile(pattern), placeholder, priority)
        )

    def filter(
        self,
        text: str,
        rules: list[str] | None = None,
        placeholder: str | None = None,
    ) -> str:
        """Filter text: replace all detected sensitive info with placeholders."""
        if not text:
            return text

        self._check_rate("filter")

        # Truncate excessively long text to prevent resource exhaustion
        if len(text) > MAX_TEXT_LENGTH:
            logger.warning(
                "[LLM Privacy Guard] ⚠ Input text too long "
                f"({len(text)} chars), truncating to {MAX_TEXT_LENGTH} "
                "to prevent resource exhaustion"
            )
            text = text[:MAX_TEXT_LENGTH]

        # Preprocess pipeline (NFKC + zero-width + URL decode + HTML decode)
        original = text
        text = _preprocess(text, self._config)

        # 1. Regex matches
        regex_matches = self._find_regex_matches(text, rules=rules, placeholder=placeholder)

        # 2. Entropy matches
        entropy_matches: list[Match] = []
        entropy_config = self._config.get("entropy", {})
        ent_enabled = entropy_config.get("enabled", True)
        ent_threshold = entropy_config.get("threshold", 5.0)
        ent_min_len = entropy_config.get("min_length", 12)
        ent_mode = entropy_config.get("mode", "auto")

        if ent_enabled and ent_mode == "auto":
            ent_matches = find_high_entropy(
                text,
                threshold=ent_threshold,
                min_length=ent_min_len,
            )
            covered_regions: list[tuple[int, int]] = [
                (m.start, m.end) for m in regex_matches
            ]
            for em in ent_matches:
                overlap = False
                for start, end in covered_regions:
                    if not (em.end <= start or em.start >= end):
                        overlap = True
                        break
                if not overlap:
                    entropy_matches.append(
                        Match(
                            type="entropy",
                            value=em.value,
                            start=em.start,
                            end=em.end,
                            placeholder="[HIGH_ENTROPY]",
                            entropy=em.entropy,
                            priority=100,
                            confidence="high",
                        )
                    )

        # 3. Merge & deduplicate
        all_matches = regex_matches + entropy_matches
        deduped = self._deduplicate_matches(all_matches)

        # 4. Replace right-to-left (avoid index drift), skip low-confidence matches
        result = text
        for m in sorted(deduped, key=lambda x: x.start, reverse=True):
            if m.confidence == "low":
                continue
            result = result[: m.start] + m.placeholder + result[m.end :]

        return result

    def scan(self, text: str) -> list[dict]:
        """Scan text, returning all detected sensitive info (without modifying).

        Returns:
            List of matches, each containing type, value, start, end, placeholder
        """
        if not text:
            return []

        self._check_rate("scan")

        # Truncate excessively long text to prevent resource exhaustion
        if len(text) > MAX_TEXT_LENGTH:
            logger.warning(
                "[LLM Privacy Guard] ⚠ Input text too long "
                f"({len(text)} chars), truncating to {MAX_TEXT_LENGTH} "
                "to prevent resource exhaustion"
            )
            text = text[:MAX_TEXT_LENGTH]

        # Preprocess pipeline (NFKC + zero-width + URL decode + HTML decode)
        text = _preprocess(text, self._config)

        # Regex matches
        regex_matches = self._find_regex_matches(text)

        # Entropy matches
        entropy_matches: list[Match] = []
        entropy_config = self._config.get("entropy", {})
        ent_enabled = entropy_config.get("enabled", True)
        ent_threshold = entropy_config.get("threshold", 5.0)
        ent_min_len = entropy_config.get("min_length", 12)

        if ent_enabled:
            ent_matches = find_high_entropy(
                text,
                threshold=ent_threshold,
                min_length=ent_min_len,
            )
            covered_regions: list[tuple[int, int]] = [
                (m.start, m.end) for m in regex_matches
            ]
            for em in ent_matches:
                overlap = False
                for start, end in covered_regions:
                    if not (em.end <= start or em.start >= end):
                        overlap = True
                        break
                if not overlap:
                    entropy_matches.append(
                        Match(
                            type="entropy",
                            value=em.value,
                            start=em.start,
                            end=em.end,
                            placeholder="[HIGH_ENTROPY]",
                            entropy=em.entropy,
                            priority=100,
                            confidence="high",
                        )
                    )

        all_matches = regex_matches + entropy_matches
        deduped = self._deduplicate_matches(all_matches)

        return [
            {
                "type": m.type,
                "value": m.value,
                "start": m.start,
                "end": m.end,
                "placeholder": m.placeholder,
                "entropy": m.entropy,
                "confidence": m.confidence,
            }
            for m in deduped
        ]
