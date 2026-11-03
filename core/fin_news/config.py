"""Configuration management for Fin-News."""
import copy
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Tuple


def home() -> Path:
    """Return the Fin-News home directory."""
    env_home = os.environ.get("FIN_NEWS_HOME")
    if env_home:
        return Path(env_home).resolve()
    return (Path.home() / ".fin-news").resolve()


def _get_defaults_dir() -> Path:
    # fin-news/core/fin_news/config.py -> parent.parent.parent is fin-news/
    return Path(__file__).resolve().parent.parent.parent / "defaults"


def _deep_merge(base: Any, override: Any) -> Any:
    """Merge dicts key-by-key; lists and scalars replace."""
    if isinstance(base, dict) and isinstance(override, dict):
        result = copy.deepcopy(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = _deep_merge(result[k], v)
            else:
                result[k] = copy.deepcopy(v)
        return result
    return copy.deepcopy(override)


def load(name: str) -> dict:
    """Load configuration by name, merging default and user config."""
    defaults_file = _get_defaults_dir() / f"{name}.json"
    user_file = home() / "config" / f"{name}.json"

    base_data = {}
    if defaults_file.exists():
        with open(defaults_file, "r", encoding="utf-8") as f:
            base_data = json.load(f)

    user_data = {}
    if user_file.exists():
        with open(user_file, "r", encoding="utf-8") as f:
            user_data = json.load(f)

    return _deep_merge(base_data, user_data)


def _get_nested(data: dict, parts: list[str]) -> Any:
    curr = data
    for part in parts:
        if isinstance(curr, dict) and part in curr:
            curr = curr[part]
        else:
            return None
    return curr


def set_value(name: str, dotted_key: str, value: Any) -> Tuple[Any, Any]:
    """Set a configuration value in user config, append to CHANGELOG.md, and return (old, new)."""
    current_merged = load(name)
    parts = dotted_key.split(".")
    old_value = _get_nested(current_merged, parts)

    user_file = home() / "config" / f"{name}.json"
    user_file.parent.mkdir(parents=True, exist_ok=True)

    user_data = {}
    if user_file.exists():
        try:
            with open(user_file, "r", encoding="utf-8") as f:
                user_data = json.load(f)
        except Exception:
            user_data = {}

    curr = user_data
    for part in parts[:-1]:
        if part not in curr or not isinstance(curr[part], dict):
            curr[part] = {}
        curr = curr[part]
    curr[parts[-1]] = value

    with open(user_file, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)

    # Append to CHANGELOG.md
    changelog_file = home() / "config" / "CHANGELOG.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"- [{timestamp}] {name}.json: {dotted_key} | {old_value} → {value}\n"
    with open(changelog_file, "a", encoding="utf-8") as f:
        f.write(log_entry)

    return old_value, value


def unset(name: str, dotted_key: str) -> None:
    """Remove a dotted key from user config to restore default."""
    user_file = home() / "config" / f"{name}.json"
    if not user_file.exists():
        return

    try:
        with open(user_file, "r", encoding="utf-8") as f:
            user_data = json.load(f)
    except Exception:
        return

    parts = dotted_key.split(".")
    curr = user_data
    stack = []
    for part in parts[:-1]:
        if isinstance(curr, dict) and part in curr:
            stack.append((curr, part))
            curr = curr[part]
        else:
            return

    if isinstance(curr, dict) and parts[-1] in curr:
        del curr[parts[-1]]

    with open(user_file, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)
