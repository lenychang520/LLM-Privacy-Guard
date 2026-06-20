# -*- coding: utf-8 -*-
"""Tests for auto-configuration helpers."""

from pathlib import Path


def test_setup_codex_rewrites_base_url_and_persists_upstream(monkeypatch, tmp_path):
    codex_home = tmp_path / ".codex"
    config_home = tmp_path / ".config" / "llm-privacy-guard"
    codex_home.mkdir(parents=True)
    config_home.mkdir(parents=True)

    codex_config = codex_home / "config.toml"
    codex_config.write_text(
        '\n'.join(
            [
                'model_provider = "aigocode"',
                'model = "gpt-5.4"',
                '',
                '[model_providers.aigocode]',
                'name = "aigocode"',
                'base_url = "https://api.aigocode.com"',
                'wire_api = "responses"',
            ]
        ),
        encoding="utf-8",
    )

    import setup_tools

    # Isolate from real user config
    manifest_path = config_home / "tool-manifest.json"
    monkeypatch.setattr(setup_tools, "_CODEX_CONFIG_PATH", str(codex_config))
    monkeypatch.setattr(setup_tools, "_manifest_path", lambda: str(manifest_path))
    monkeypatch.setattr(setup_tools, "_manifest_dir", lambda: str(config_home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    messages = setup_tools.setup_codex(port=19999, dry_run=False)

    updated = codex_config.read_text(encoding="utf-8")
    assert 'base_url = "http://127.0.0.1:19999"' in updated
    assert any("[aigocode] -> http://127.0.0.1:19999" in msg for msg in messages)

    user_config = (config_home / "config.yaml").read_text(encoding="utf-8")
    assert "proxy:" in user_config
    assert "upstream_map:" in user_config
    assert "gpt-5-4: https://api.aigocode.com" in user_config
    assert "gpt-5-4-mini: https://api.aigocode.com" in user_config
    assert "gpt-5-5: https://api.aigocode.com" in user_config
