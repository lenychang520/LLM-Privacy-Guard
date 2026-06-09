# -*- coding: utf-8 -*-
"""LLM Privacy Guard — QwenPaw plugin entry point

Intercepts all messages sent to the LLM and redacts them before sending.
Registers commands and monkey-patches query_handler in register().
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

_plugin_dir = os.path.dirname(os.path.abspath(__file__))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from privacy_engine import filter_text, scan_text, __version__ as engine_version

logger = logging.getLogger(__name__)

# ── Compatibility version check ──

_MIN_QWENPAW_VERSION = (1, 1)

_COMPAT_WARN_TEMPLATE = (
    "[LLM Privacy Guard] ⚠ Version compatibility warning: QwenPaw {actual} "
    "is below the recommended minimum {min_ver}. "
    "The plugin may not work correctly; sensitive data may leak."
)


def _check_qwenpaw_version():
    """Check QwenPaw version compatibility."""
    try:
        from qwenpaw import __version__ as qv
        parts = qv.split(".")
        actual = tuple(int(p) for p in parts[:2])
        if actual < _MIN_QWENPAW_VERSION:
            return (
                False,
                _COMPAT_WARN_TEMPLATE.format(
                    actual=qv, min_ver=".".join(str(x) for x in _MIN_QWENPAW_VERSION)
                ),
            )
        return (True, None)
    except Exception:
        logger.debug("Cannot detect QwenPaw version, skipping compatibility check")
        return (True, None)


# ── Persistence ──

_STATS_FILE = os.path.join(_plugin_dir, ".privacy_stats.json")
_MAX_RECENT_MATCHES = 10
_MAX_RECENT_SESSIONS = 20
_SAVE_COOLDOWN = 15  # seconds between auto-saves

_last_auto_save = 0.0
_cumulative_stats = {
    "messages_processed": 0,
    "messages_filtered": 0,
    "total_replacements": 0,
    "by_type": {},
}


def _load_stats():
    """Load persisted cumulative stats and session history."""
    global _cumulative_stats
    try:
        if os.path.exists(_STATS_FILE):
            with open(_STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "cumulative" in data and isinstance(data["cumulative"], dict):
                _cumulative_stats = data["cumulative"]
            logger.debug(
                "[LLM Privacy Guard] 📂 Loaded cumulative stats: "
                f"{_cumulative_stats['messages_processed']} messages processed, "
                f"{_cumulative_stats['total_replacements']} replacements"
            )
    except Exception:
        logger.debug("[LLM Privacy Guard] 📂 No previous stats found or load failed")


def _save_stats(session_end: str | None = None):
    """Persist cumulative stats + archive current session.

    Never stores raw values — only aggregated counts and type names.
    """
    global _last_auto_save
    _last_auto_save = time.time()

    try:
        # Load existing data to merge
        data = {}
        if os.path.exists(_STATS_FILE):
            with open(_STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

        # Merge cumulative
        data["cumulative"] = dict(_cumulative_stats)

        # Archive current session
        sessions = data.get("recent_sessions", [])
        if not isinstance(sessions, list):
            sessions = []
        session_entry = {
            "start": _report_stats.get("session_start", "unknown"),
            "end": session_end or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "messages_processed": _report_stats["messages_processed"],
            "messages_filtered": _report_stats["messages_filtered"],
            "total_replacements": _report_stats["total_replacements"],
            "by_type": dict(_report_stats["by_type"]),
        }
        sessions.append(session_entry)
        # Keep only recent sessions
        if len(sessions) > _MAX_RECENT_SESSIONS:
            sessions = sessions[-_MAX_RECENT_SESSIONS:]
        data["recent_sessions"] = sessions

        with open(_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.debug("[LLM Privacy Guard] ⚠ Failed to persist stats", exc_info=True)


def _auto_save():
    """Save stats if cooldown has passed (called after each stat update)."""
    global _last_auto_save
    now = time.time()
    if now - _last_auto_save >= _SAVE_COOLDOWN:
        _save_stats()


# ── Session-level masking report ──

_report_stats = {
    "session_start": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "messages_processed": 0,
    "messages_filtered": 0,
    "total_replacements": 0,
    "by_type": {},           # {"ipv4": 5, "email": 2, ...}
    "recent_matches": [],    # [{type, placeholder, time}, ...] — never stores raw values
}


def _reset_report():
    """Reset the masking report stats, archiving current session first."""
    global _report_stats
    # Archive current session to cumulative + persistence
    _merge_to_cumulative()
    _save_stats(session_end=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    _report_stats = {
        "session_start": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "messages_processed": 0,
        "messages_filtered": 0,
        "total_replacements": 0,
        "by_type": {},
        "recent_matches": [],
    }


def _merge_to_cumulative():
    """Merge current session stats into cumulative totals."""
    _cumulative_stats["messages_processed"] += _report_stats["messages_processed"]
    _cumulative_stats["messages_filtered"] += _report_stats["messages_filtered"]
    _cumulative_stats["total_replacements"] += _report_stats["total_replacements"]
    for mtype, count in _report_stats["by_type"].items():
        _cumulative_stats["by_type"][mtype] = (
            _cumulative_stats["by_type"].get(mtype, 0) + count
        )


# ── Message filtering ──

def _filter_message_content(msgs: list) -> tuple[list, int]:
    """Iterate message list, redact str or list[dict] content fields.

    Returns:
        (msgs, filtered_count): redacted message list and replacement count
    """
    total_replacements = 0
    _report_stats["messages_processed"] += 1
    for msg in msgs:
        content = getattr(msg, "content", None)
        if content is None:
            continue
        if isinstance(content, str):
            original = content
            msg.content = filter_text(content)
            if original != msg.content:
                total_replacements += 1
                _collect_report(original)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        original = text
                        block["text"] = filter_text(text)
                        if original != block["text"]:
                            total_replacements += 1
                            _collect_report(original)
    return msgs, total_replacements


def _collect_report(text: str):
    """Scan a message that triggered filtering and record match stats.

    IMPORTANT: Only stores redacted metadata (type, placeholder, timestamp).
    NEVER stores or logs the original sensitive value.
    """
    matches = scan_text(text)
    _report_stats["total_replacements"] += len(matches)
    for m in matches:
        mtype = m["type"]
        _report_stats["by_type"][mtype] = _report_stats["by_type"].get(mtype, 0) + 1
    _report_stats["messages_filtered"] += 1

    # Append to recent_matches (redacted only, FIFO, max 10)
    if matches:
        now_str = datetime.now().strftime("%H:%M:%S")
        for m in matches[:3]:  # At most 3 match types per message in recents
            _report_stats["recent_matches"].append({
                "type": m["type"],
                "placeholder": m["placeholder"],
                "time": now_str,
            })
        # Trim to max
        if len(_report_stats["recent_matches"]) > _MAX_RECENT_MATCHES:
            _report_stats["recent_matches"] = _report_stats["recent_matches"][
                -_MAX_RECENT_MATCHES:
            ]

    _auto_save()


def _feed_scan_to_report(matches: list[dict]):
    """Feed /privacy scan results into session report stats.

    Scan is user-initiated, so we count it as one 'processed' message
    plus any matched types. Does NOT store raw values.
    """
    _report_stats["messages_processed"] += 1
    if matches:
        _report_stats["messages_filtered"] += 1
        _report_stats["total_replacements"] += len(matches)
        now_str = datetime.now().strftime("%H:%M:%S")
        for m in matches[:3]:
            mtype = m["type"]
            _report_stats["by_type"][mtype] = _report_stats["by_type"].get(mtype, 0) + 1
            _report_stats["recent_matches"].append({
                "type": m["type"],
                "placeholder": m["placeholder"],
                "time": now_str,
                "source": "scan",
            })
        # Trim
        if len(_report_stats["recent_matches"]) > _MAX_RECENT_MATCHES:
            _report_stats["recent_matches"] = _report_stats["recent_matches"][
                -_MAX_RECENT_MATCHES:
            ]
    _auto_save()


def _inject_privacy_warning(msgs: list):
    """Prepend a privacy-failure warning marker to the first message."""
    warning = (
        "⚠ [LLM Privacy Guard] Redaction filter failed — "
        "the following message may contain unprocessed sensitive information. "
        "Please check the logs."
    )
    if msgs:
        first = msgs[0]
        content = getattr(first, "content", None)
        if isinstance(content, str):
            first.content = warning + "\n\n" + content
        elif isinstance(content, list) and content:
            content.insert(0, {"type": "text", "text": warning})


# ── Monkey-patch ──

def _patch_query_handler():
    """Replace AgentRunner.query_handler, injecting redaction logic."""
    try:
        from qwenpaw.app.runner.runner import AgentRunner
    except ImportError:
        logger.error(
            "[LLM Privacy Guard] Cannot import AgentRunner — "
            "plugin may be incompatible with the current QwenPaw version."
        )
        return

    original = AgentRunner.query_handler

    async def patched(self, msgs, request=None, **kwargs):
        try:
            _filter_message_content(msgs)
        except Exception:
            logger.error(
                "[LLM Privacy Guard] 🔴 Redaction pre-filter failed! "
                "Message will be sent raw — sensitive data may leak!"
            )
            _inject_privacy_warning(msgs)
        async for result in original(self, msgs, request, **kwargs):
            yield result

    AgentRunner.query_handler = patched
    logger.info("[LLM Privacy Guard] ✅ Activated — interceptor in place")


# ── Commands ──

def _cmd_privacy_report(api, args):
    """Command: /privacy report — show masking report for current session"""
    processed = _report_stats["messages_processed"]
    filtered = _report_stats["messages_filtered"]
    total = _report_stats["total_replacements"]
    by_type = _report_stats["by_type"]
    recent = _report_stats["recent_matches"]
    session_start = _report_stats.get("session_start", "unknown")

    # Merge to cumulative before computing totals so report is always up to date
    _merge_to_cumulative()

    cum_processed = _cumulative_stats["messages_processed"]
    cum_filtered = _cumulative_stats["messages_filtered"]
    cum_total = _cumulative_stats["total_replacements"]
    cum_by_type = _cumulative_stats["by_type"]

    if processed == 0 and cum_processed == 0:
        return "📊 No messages processed yet."

    lines = [
        f"📊 LLM Privacy Guard — Masking Report",
        f"   Session started: {session_start}",
        "─" * 48,
    ]

    # Current session
    if processed > 0:
        lines.append("📌 Current Session")
        lines.append(f"   📨 Messages processed : {processed}")
        lines.append(
            f"   🛡️  Messages filtered  : {filtered} "
            + ("(clean)" if filtered == 0 else "")
        )
        lines.append(f"   🔢 Total replacements : {total}")
        if by_type:
            for mtype, count in sorted(by_type.items(), key=lambda x: -x[1]):
                lines.append(f"      [{mtype}]: {count}")
    else:
        lines.append("📌 Current Session — no messages processed yet")

    # Cumulative (all-time)
    if cum_processed > 0:
        lines.append("")
        lines.append("📚 All-Time Cumulative")
        lines.append(f"   📨 Messages processed : {cum_processed}")
        lines.append(f"   🛡️  Messages filtered  : {cum_filtered}")
        lines.append(f"   🔢 Total replacements : {cum_total}")
        if cum_by_type:
            for mtype, count in sorted(cum_by_type.items(), key=lambda x: -x[1])[:10]:
                lines.append(f"      [{mtype}]: {count}")
            if len(cum_by_type) > 10:
                lines.append(f"      ... and {len(cum_by_type) - 10} more types")

    # Recent matches
    if recent:
        lines.append("")
        lines.append(f"🕐 Recent matches (last {min(len(recent), 5)}):")
        for entry in recent[-5:]:
            tag = "🔍" if entry.get("source") == "scan" else "🛡️"
            lines.append(
                f"   [{entry['time']}] {tag} {entry['placeholder']} ({entry['type']})"
            )

    lines.append("─" * 48)
    lines.append("💡 Use /privacy export to save this report as JSON")
    return "\n".join(lines)


def _cmd_privacy_export(api, args):
    """Command: /privacy export [path] — export aggregated report as JSON.

    Exports only aggregated statistics — NEVER includes raw sensitive values.
    """
    # Merge current session before export
    _merge_to_cumulative()

    # Determine output path
    if args:
        export_path = args[0]
    else:
        export_path = os.path.join(
            _plugin_dir,
            f"privacy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )

    export_data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine_version": engine_version,
        "current_session": {
            "start": _report_stats.get("session_start", "unknown"),
            "messages_processed": _report_stats["messages_processed"],
            "messages_filtered": _report_stats["messages_filtered"],
            "total_replacements": _report_stats["total_replacements"],
            "by_type": dict(_report_stats["by_type"]),
        },
        "cumulative": dict(_cumulative_stats),
    }

    try:
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"❌ Failed to export: {e}"

    # Also update persistence
    _save_stats()

    return (
        f"📤 Report exported to: {export_path}\n"
        f"   Size: {os.path.getsize(export_path)} bytes\n"
        f"   Contains: current session + all-time cumulative stats\n"
        f"   ⚠ No raw sensitive values included — safe to share"
    )


def _cmd_privacy_reset(api, args):
    """Command: /privacy reset — reset current session stats (archiving first)"""
    session_processed = _report_stats["messages_processed"]
    _reset_report()
    return (
        f"🔄 Session stats reset.\n"
        f"   Previous session ({session_processed} messages) archived to cumulative.\n"
        f"   All-time totals preserved. Use /privacy report to view."
    )


def _cmd_privacy_test(api, args):
    """Command: /privacy test — verify the plugin is working"""
    from privacy_engine import PrivacyDetector
    import yaml

    try:
        detector = PrivacyDetector()
        rules_count = len(detector._rules) + len(detector._custom_compiled)
        rule_names = list(detector._rules.keys())
        ent_cfg = detector._config.get("entropy", {})

        test_input = "ssh root@203.0.113.1 key=sk-abc123def456 ID: ab12cd34-5678-90ab-cdef-1234567890ab"
        safe = detector.filter(test_input)
        matches = detector.scan(test_input)

        lines = [
            f"🔒 LLM Privacy Guard v{engine_version} — Status Report",
            "─" * 40,
            f"✅ Interceptor active, {rules_count} rules loaded",
            f"📋 Built-in rules ({len(rule_names)}): {', '.join(rule_names)}",
            f"🧠 Entropy detection: {'Enabled' if ent_cfg.get('enabled') else 'Disabled'} "
            f"(mode={ent_cfg.get('mode')}, threshold={ent_cfg.get('threshold')}, "
            f"min_length={ent_cfg.get('min_length')})",
            "",
            "🧪 Self-test input:",
            f"   Raw   : {test_input}",
            f"   Filtered: {safe}",
            f"   Matched {len(matches)}: "
            + ", ".join(f"{m['type']}" for m in matches),
            "─" * 40,
            "✅ All good" if len(matches) >= 3 else "⚠ Match count below expected — check config",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Detection failed: {e}"


def _cmd_privacy_scan(api, args):
    """Command: /privacy scan — scan input text for sensitive info.

    Results are also fed into session report stats (aggregated only).
    """
    text = " ".join(args) if args else ""
    if not text:
        return "Usage: /privacy scan <text> — scan text for sensitive information"

    matches = scan_text(text)

    # Feed results into report stats (aggregated, no raw values stored)
    _feed_scan_to_report(matches)

    if not matches:
        return "✅ No sensitive information detected. (Scanned, stats updated)"

    lines = [f"🔍 Detected {len(matches)} sensitive matches:"]
    for m in matches:
        conf_tag = " ⚠Suspicious format" if m.get("confidence") == "low" else ""
        ent_tag = f" (entropy={m['entropy']:.2f})" if m.get("entropy") else ""
        lines.append(
            f"  [{m['type']}]{conf_tag}{ent_tag}: "
            f"{m['value'][:60]} → {m['placeholder']}"
        )
    lines.append("")
    lines.append("📊 Scan results logged to session report. Use /privacy report to view totals.")
    return "\n".join(lines)


# ── Plugin entry ──

class PrivacyGuardPlugin:
    def register(self, api):
        # Version check
        ok, warning = _check_qwenpaw_version()
        if not ok:
            logger.warning(warning)

        # Load persisted cumulative stats
        _load_stats()

        # Register commands
        api.register_command("privacy", _cmd_privacy_test, subcommand="test")
        api.register_command("privacy", _cmd_privacy_scan, subcommand="scan")
        api.register_command("privacy", _cmd_privacy_report, subcommand="report")
        api.register_command("privacy", _cmd_privacy_export, subcommand="export")
        api.register_command("privacy", _cmd_privacy_reset, subcommand="reset")

        # Activate interceptor
        _patch_query_handler()


plugin = PrivacyGuardPlugin()
