from __future__ import annotations

import json

import pytest

from pystudio.agents import AGENTS, choose, write_profile


def test_the_profile_is_a_claude_code_plugin_with_one_skill(tmp_path) -> None:
    plugin = write_profile(tmp_path)
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "pystudio"
    skill = (plugin / "skills" / "data-science" / "SKILL.md").read_text()
    assert skill.startswith("---\nname: data-science\ndescription: ")
    for needed in ("# %%", "list_variables", "PNG", "plt.show()"):
        assert needed in skill


def test_claude_is_started_with_the_bridge_the_prompt_and_the_profile(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("PYSTUDIO_AGENT_PROFILE", raising=False)
    argv = AGENTS["claude"].command(tmp_path / "bridge")
    assert argv[0] == "claude"
    config = json.loads(argv[argv.index("--mcp-config") + 1])
    assert config["mcpServers"]["pystudio"]["args"][-1] == str(tmp_path / "bridge")
    assert "pystudio:data-science" in argv[argv.index("--append-system-prompt") + 1]
    assert argv[argv.index("--plugin-dir") + 1] == str(tmp_path / "plugin")


def test_the_profile_can_be_turned_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PYSTUDIO_AGENT_PROFILE", "off")
    assert "--plugin-dir" not in AGENTS["claude"].command(tmp_path / "bridge")
    assert not (tmp_path / "plugin").exists()


def test_claude_is_kept_from_api_keys_so_it_uses_its_own_login() -> None:
    assert "ANTHROPIC_API_KEY" in AGENTS["claude"].without_env


def test_an_unknown_agent_is_an_error() -> None:
    with pytest.raises(ValueError, match="known: claude"):
        choose("hal")
