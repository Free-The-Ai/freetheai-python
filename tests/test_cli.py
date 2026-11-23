import orjson
import pytest

from freetheai._cli import (
    CliError,
    edit_claude_settings,
    edit_codex_config,
    edit_shell_profile,
    main,
    valid_key,
    valid_model_id,
)

CHOICE = {"key": "ftai_test", "model": "kimi-k3", "fast_model": "glm-5.3-flash"}


def test_claude_adds_freetheai_and_keeps_other_settings():
    settings = orjson.loads(edit_claude_settings('{"theme":"dark","env":{"KEEP":"1"}}', CHOICE))
    assert settings["theme"] == "dark"
    assert settings["env"]["KEEP"] == "1"
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://api.freetheai.org"
    assert settings["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "glm-5.3-flash"


def test_claude_remove_undoes_exactly_what_was_added():
    original = edit_claude_settings('{"theme":"dark","env":{"KEEP":"1"}}', None)
    assert edit_claude_settings(edit_claude_settings(original, CHOICE), None) == original
    assert orjson.loads(edit_claude_settings(edit_claude_settings("", CHOICE), None)) == {}


def test_claude_refuses_a_file_that_is_not_an_object():
    with pytest.raises(CliError):
        edit_claude_settings("[1]", CHOICE)
    with pytest.raises(CliError):
        edit_claude_settings("{nope", CHOICE)


def test_codex_sets_and_removes_the_provider():
    config = 'approval_policy = "on-request"\nmodel = "gpt-5"\n\n[profiles.fast]\nmodel = "o4-mini"\n\n[model_providers.freetheai]\nname = "old"\n'
    added = edit_codex_config(config, "kimi-k3")
    assert added.startswith('model = "kimi-k3"\nmodel_provider = "freetheai"\napproval_policy = "on-request"\n')
    assert '[profiles.fast]\nmodel = "o4-mini"' in added
    assert added.count("[model_providers.freetheai]") == 1
    assert 'name = "old"' not in added
    removed = edit_codex_config(added, None)
    assert "freetheai" not in removed
    assert "[profiles.fast]" in removed


def test_shell_profile_keeps_one_export():
    once = edit_shell_profile("alias ll=ls\nexport FREETHEAI_API_KEY=old\n", "ftai_new")
    assert once == "alias ll=ls\nexport FREETHEAI_API_KEY='ftai_new'\n"
    assert edit_shell_profile(once, None) == "alias ll=ls\n"


def test_inputs():
    assert valid_key("ftai_abc-DEF_1")
    assert not valid_key("sk-abc")
    assert valid_model_id("openai/gpt-5.1")
    assert not valid_model_id('x"; rm -rf')


def test_init_writes_claude_settings(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FTAI_KEY", "ftai_testkey")
    monkeypatch.setattr("freetheai._cli._key_info", lambda key: {})
    (tmp_path / "settings.json").write_text('{"theme":"dark"}\n', encoding="utf-8")
    assert main(["init", "claude-code", "--model", "kimi-k3"]) == 0
    settings = orjson.loads((tmp_path / "settings.json").read_bytes())
    assert settings["theme"] == "dark"
    assert settings["env"]["ANTHROPIC_MODEL"] == "kimi-k3"
    assert len(list(tmp_path.glob("settings.json.bak-*"))) == 1
    assert main(["init", "claude-code", "--remove"]) == 0
    assert orjson.loads((tmp_path / "settings.json").read_bytes()) == {"theme": "dark"}


def test_bad_key_is_refused(monkeypatch, capsys):
    monkeypatch.setenv("FTAI_KEY", "sk-nope")
    assert main(["whoami"]) == 1
    assert "not a FreeTheAI key" in capsys.readouterr().err
