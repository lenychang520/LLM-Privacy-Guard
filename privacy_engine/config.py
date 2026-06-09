# -*- coding: utf-8 -*-
"""Config loader — reads user-defined rules and parameters from config.yaml"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Default config ──

DEFAULT_CONFIG = {
    "preprocess": {
        "strip_zw_chars": True,    # Remove zero-width chars (\\u200b, \\u200c, etc.)
        "url_decode": True,        # URL decode (%3A → :)
        "html_unescape": True,     # HTML entity decode (&#64; → @)
    },
    "entropy": {
        "enabled": True,          # Enable entropy detection
        "threshold": 5.0,          # Entropy threshold
        "min_length": 12,          # Min detection length (lowered to 12 for short tokens)
        "mode": "auto",            # "auto" (auto-replace) or "review" (mark only)
    },
    "rules": {
        # Built-in rule toggles — all enabled by default
        "ipv4": True,
        "ipv4_hex": True,
        "ipv6": True,
        "ipv6_hyphen": True,
        "uuid": True,
        "uuid_hex": True,
        "email": True,
        "phone_cn": True,
        "phone_cn_sep": True,
        "phone_intl": True,
        "id_card_cn": True,
        "id_card_cn_sep": True,
        "ssn_us": True,
        "api_key_prefix": True,
        "aws_access_key": True,
        "ssh_private_key": True,
        "ssh_public_key": True,
        "sha_hash": True,
        "github_token": True,
        "jwt": True,
        "jwt_multiline": True,
        "db_connection_string": True,
        "db_cli": True,
        "credit_card": True,
        "credential_value": True,
        "url_query_credential": True,
        "credential_inline": True,
    },
    "custom_rules": [
        # Users can add custom regex rules here
        # - name: "my_domain"
        #   pattern: "my-company\\.com"
        #   placeholder: "[MY_DOMAIN]"
    ],
    "placeholders": {
        # Override default placeholders
        # ipv4: "[HIDDEN_IP]"
    },
    "whitelist": {
        "ips": [],      # Extra IP whitelist entries
        "domains": [],  # Extra domain whitelist entries
        "strings": [],  # Exact-match whitelist strings
    },
}


def find_config_file() -> Path | None:
    """Find config.yaml.

    Search order:
    1. Current working directory (⚠ highest priority — be aware)
    2. Plugin parent directory (llm_filter/)
    3. ~/.llm-privacy-guard/
    """
    candidates = [
        Path.cwd() / "config.yaml",
        Path(__file__).resolve().parent.parent / "config.yaml",
        Path.home() / ".llm-privacy-guard" / "config.yaml",
    ]

    for p in candidates:
        if p.exists():
            if p == candidates[0]:
                logger.info(
                    "[LLM Privacy Guard] 📁 Loading config from CWD: %s — "
                    "this takes priority over plugin and home directories",
                    p,
                )
            return p
    return None


def load_config() -> dict:
    """Load config, merging defaults with user config."""
    import yaml

    config = dict(DEFAULT_CONFIG)

    # Deep-copy nested dicts to avoid reference pollution
    for key in ("preprocess", "entropy", "rules", "placeholders", "whitelist"):
        if key in config and isinstance(config[key], dict):
            config[key] = dict(config[key])

    config_path = find_config_file()
    if config_path is None:
        logger.info("config.yaml not found, using defaults")
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load config.yaml: {e}, using defaults")
        return config

    # Deep merge (two levels only — preprocess, entropy, rules, placeholders, whitelist)
    for section in ("preprocess", "entropy", "rules", "placeholders", "whitelist"):
        if section in user_config:
            if isinstance(config.get(section), dict) and isinstance(user_config[section], dict):
                config[section].update(user_config[section])
            else:
                config[section] = user_config[section]

    # Custom rules: direct append
    if "custom_rules" in user_config and isinstance(user_config["custom_rules"], list):
        config["custom_rules"] = user_config["custom_rules"]

    return config
