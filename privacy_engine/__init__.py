# -*- coding: utf-8 -*-
"""LLM Privacy Guard — Core Engine

Usage:
    from privacy_engine import filter_text, scan_text, add_rule

    safe = filter_text("ssh root@192.168.1.1")
    # → "ssh root@[IP]"

    matches = scan_text("key=sk-abc123")
    # → [Match(type="API_KEY", value="sk-abc123", ...)]

    add_rule("my_company", r"company-\\d{6}", "[COMPANY_ID]")
"""

from .detector import PrivacyDetector

# Singleton
_detector: PrivacyDetector | None = None


def _get_detector() -> PrivacyDetector:
    global _detector
    if _detector is None:
        _detector = PrivacyDetector()
    return _detector


def filter_text(
    text: str,
    rules: list[str] | None = None,
    placeholder: str | None = None,
) -> str:
    """Filter text, replacing sensitive info with type placeholders.

    Args:
        text: Raw text
        rules: List of rule names to enable. None means all enabled.
        placeholder: Custom global placeholder. None means use each rule's default.

    Returns:
        Redacted text
    """
    return _get_detector().filter(text, rules=rules, placeholder=placeholder)


def scan_text(text: str) -> list[dict]:
    """Scan text, returning all detected sensitive info (without modifying).

    Returns:
        List of matches, each containing type, value, start, end, placeholder
    """
    return _get_detector().scan(text)


def add_rule(name: str, pattern: str, placeholder: str = "[REDACTED]"):
    """Register a custom rule at runtime.

    Args:
        name: Rule name (unique identifier)
        pattern: Regex pattern string
        placeholder: Replacement placeholder text
    """
    _get_detector().add_rule(name, pattern, placeholder)


def reload_config():
    """Reload config.yaml and reset the detector."""
    global _detector
    _detector = PrivacyDetector()


# Version
__version__ = "1.0.0"
__all__ = ["filter_text", "scan_text", "add_rule", "reload_config"]
