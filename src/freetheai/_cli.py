"""The ``freetheai`` command.

    freetheai init                      pick a tool and set it up
    freetheai init claude-code --model kimi-k3
    freetheai init codex --remove
    freetheai whoami                    the key's balance and spend

The key comes from --key, FTAI_KEY, or a hidden prompt. It is checked with the
API before any file changes, every file is backed up first, and only
FreeTheAI's own settings are written or removed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import orjson

from ._version import __version__

API_ROOT = "https://api.freetheai.org"
API_BASE = f"{API_ROOT}/v1"
DEFAULT_MODEL = "glm-5.3"
DEFAULT_FAST_MODEL = "glm-5.3-flash"

CLAUDE_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
)

_MODEL_ID = re.compile(r"^[A-Za-z0-9._/:-]+$")
_KEY_SHAPE = re.compile(r"^ftai_[A-Za-z0-9_-]+$")
_TABLE_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
_TOP_KEY = re.compile(r"^\s*(model|model_provider)\s*=")


class CliError(Exception):
    """A refusal the user should read as is."""


def valid_model_id(model: str) -> bool:
    return bool(_MODEL_ID.match(model))


def valid_key(key: str) -> bool:
    return bool(_KEY_SHAPE.match(key))


def edit_claude_settings(text: str, choice: dict[str, str] | None) -> str:
    """Adds (choice given) or removes (None) the FreeTheAI env keys in a
    Claude Code settings.json text. Raises on a file that is not a JSON object."""
    settings: dict[str, Any] = {}
    if text.strip():
        try:
            parsed = orjson.loads(text)
        except orjson.JSONDecodeError as error:
            raise CliError("settings.json is not valid JSON; fix or move it, then run again") from error
        if not isinstance(parsed, dict):
            raise CliError("settings.json is not a JSON object")
        settings = parsed
    current = settings.get("env")
    env: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    values = None
    if choice is not None:
        values = {
            "ANTHROPIC_BASE_URL": API_ROOT,
            "ANTHROPIC_AUTH_TOKEN": choice["key"],
            "ANTHROPIC_MODEL": choice["model"],
            "ANTHROPIC_DEFAULT_OPUS_MODEL": choice["model"],
            "ANTHROPIC_DEFAULT_SONNET_MODEL": choice["model"],
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": choice["fast_model"],
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
    for name in CLAUDE_KEYS:
        if values is not None:
            env[name] = values[name]
        else:
            env.pop(name, None)
    next_settings = {key: value for key, value in settings.items() if key != "env"}
    if env:
        next_settings["env"] = env
    return orjson.dumps(next_settings, option=orjson.OPT_INDENT_2).decode() + "\n"


def edit_codex_config(text: str, model: str | None) -> str:
    """Makes FreeTheAI Codex's model provider (model given) or takes it out
    (None) in a config.toml text. Only the top-level model and model_provider
    keys and the [model_providers.freetheai] table change."""
    out: list[str] = []
    table: str | None = None
    ours = False
    for line in text.replace("\r\n", "\n").split("\n"):
        header = _TABLE_HEADER.match(line)
        if header:
            table = header.group(1)
            ours = table == "model_providers.freetheai"
            if ours:
                continue
        if ours:
            continue
        if table is None:
            key = _TOP_KEY.match(line)
            if key and model is not None:
                continue
            if key and model is None and key.group(1) == "model_provider" and "freetheai" in line:
                continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    if model is not None:
        out = [f'model = "{model}"', 'model_provider = "freetheai"', *out]
        out += [
            "",
            "[model_providers.freetheai]",
            'name = "FreeTheAI"',
            f'base_url = "{API_BASE}"',
            'env_key = "FREETHEAI_API_KEY"',
            'wire_api = "responses"',
        ]
    return "\n".join(out) + "\n"


def edit_shell_profile(text: str, key: str | None) -> str:
    """Sets (key given) or removes the FREETHEAI_API_KEY export in a shell profile."""
    lines = [
        line for line in text.replace("\r\n", "\n").split("\n") if not line.startswith("export FREETHEAI_API_KEY=")
    ]
    while lines and lines[-1] == "":
        lines.pop()
    if key is not None:
        lines.append(f"export FREETHEAI_API_KEY='{key}'")
    return "\n".join(lines) + "\n" if lines else ""


def _read_key(options: argparse.Namespace) -> str:
    key = options.key or os.environ.get("FTAI_KEY", "")
    if not key:
        if not sys.stdin.isatty():
            raise CliError("no terminal to ask for the key: pass --key or set FTAI_KEY")
        key = getpass.getpass("FreeTheAI API key (from freetheai.org/dashboard/api-keys): ").strip()
    if not valid_key(key):
        raise CliError("that is not a FreeTheAI key (they start with ftai_)")
    return key


def _key_info(key: str) -> dict[str, Any]:
    try:
        response = httpx.get(f"{API_BASE}/key", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    except httpx.HTTPError as error:
        raise CliError("could not reach FreeTheAI. Check your connection and try again.") from error
    if response.status_code in (401, 403):
        raise CliError("FreeTheAI did not accept that key. Make a new one at freetheai.org/dashboard/api-keys")
    if response.status_code != 200:
        raise CliError(f"FreeTheAI answered {response.status_code}. Try again in a minute.")
    data = orjson.loads(response.content).get("data")
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _backup(path: Path) -> None:
    if not path.exists():
        return
    copy = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d%H%M%S')}-{os.getpid()}")
    shutil.copyfile(path, copy)
    print(f"Saved a copy of {path} to {copy}")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".freetheai.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    if os.name != "nt":
        tmp.chmod(0o600)
    os.replace(tmp, path)


def _pick_tool(options: argparse.Namespace) -> str:
    if options.tool:
        return options.tool
    if not sys.stdin.isatty():
        raise CliError("name the tool: freetheai init claude-code or freetheai init codex")
    answer = input("Set up which tool? 1) Claude Code  2) Codex CLI [1]: ").strip().lower()
    return "codex" if answer == "2" or answer.startswith("codex") else "claude-code"


def _init_claude(options: argparse.Namespace) -> None:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    path = (Path(base) if base else Path.home() / ".claude") / "settings.json"
    if options.remove:
        if not path.exists():
            print("Nothing to remove.")
            return
        _backup(path)
        _write_text(path, edit_claude_settings(_read_text(path), None))
        print("FreeTheAI settings removed from Claude Code.")
        return
    key = _read_key(options)
    _key_info(key)
    print("Key checked.")
    text = edit_claude_settings(
        _read_text(path), {"key": key, "model": options.model, "fast_model": options.fast_model}
    )
    _backup(path)
    _write_text(path, text)
    print(f"\nClaude Code now uses FreeTheAI with {options.model} (background tasks: {options.fast_model}).")
    print("Start it with: claude")
    print("Paid models bill your wallet: freetheai.org/dashboard/wallet")


def _shell_profile() -> Path:
    shell = os.environ.get("SHELL", "")
    if shell.endswith("zsh"):
        return Path.home() / ".zshrc"
    if shell.endswith("bash"):
        return Path.home() / ".bashrc"
    return Path.home() / ".profile"


def _save_key_variable(key: str | None) -> str:
    if os.name == "nt":
        script = (
            "[Environment]::SetEnvironmentVariable('FREETHEAI_API_KEY', $null, 'User')"
            if key is None
            else "[Environment]::SetEnvironmentVariable('FREETHEAI_API_KEY', $env:FTAI_SAVE_KEY, 'User')"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            env={**os.environ, "FTAI_SAVE_KEY": key or ""},
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise CliError("could not save FREETHEAI_API_KEY as a user variable")
        return "the user variable FREETHEAI_API_KEY"
    profile = _shell_profile()
    _write_text(profile, edit_shell_profile(_read_text(profile), key))
    return f"FREETHEAI_API_KEY in {profile}"


def _init_codex(options: argparse.Namespace) -> None:
    base = os.environ.get("CODEX_HOME")
    path = (Path(base) if base else Path.home() / ".codex") / "config.toml"
    if options.remove:
        if path.exists():
            _backup(path)
            _write_text(path, edit_codex_config(_read_text(path), None))
        _save_key_variable(None)
        print("FreeTheAI removed from Codex. Pick another model provider in config.toml before running codex.")
        return
    key = _read_key(options)
    _key_info(key)
    print("Key checked.")
    _backup(path)
    _write_text(path, edit_codex_config(_read_text(path), options.model))
    saved = _save_key_variable(key)
    print(f"\nCodex now uses FreeTheAI with {options.model}.")
    print(f"Your key is saved as {saved}. Open a new terminal, then run codex.")
    print("Paid models bill your wallet: freetheai.org/dashboard/wallet")


def _whoami(options: argparse.Namespace) -> None:
    info = _key_info(_read_key(options))
    limit = f" of ${info['limit']}" if info.get("limit") else ""
    print(f"{'Key':<12}{info.get('label') or info.get('key_prefix') or '-'}")
    print(f"{'Balance':<12}${info.get('balance', 0)}")
    print(f"{'Spendable':<12}${info.get('spendable', 0)}")
    print(f"{'Key spent':<12}${info.get('usage', 0)}{limit}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freetheai", description="Set up coding tools to use FreeTheAI.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    init = commands.add_parser("init", help="set up Claude Code or Codex CLI")
    init.add_argument("tool", nargs="?", choices=["claude-code", "codex"])
    init.add_argument("--model", default=DEFAULT_MODEL)
    init.add_argument("--fast-model", default=DEFAULT_FAST_MODEL)
    init.add_argument("--key")
    init.add_argument("--remove", action="store_true")
    who = commands.add_parser("whoami", help="the key's balance and spend")
    who.add_argument("--key")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    options = parser.parse_args(argv)
    try:
        if options.command == "init":
            if not valid_model_id(options.model) or not valid_model_id(options.fast_model):
                raise CliError("model IDs may hold letters, digits, and . _ / : - only")
            if _pick_tool(options) == "codex":
                _init_codex(options)
            else:
                _init_claude(options)
        elif options.command == "whoami":
            _whoami(options)
        else:
            parser.print_help()
    except CliError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
