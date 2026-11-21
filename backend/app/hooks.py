"""Safe calls from Person 3's modules into Person 1's shared modules.

P3 code (events, cane_drop, activity, ...) uses these helpers instead of
importing `audio`, `state`, `serial_reader` and `config` directly. While P1's
functions don't exist yet, calls are logged once and skipped, so P3's modules
run and can be tested on their own. Once P1's code lands, calls go straight
through with no changes needed here.

Both styles from docs/contracts.md section 7 are supported: module-level
functions (`audio.say`) and a module-level instance named after the module
(`audio.audio.say`, like `camera.camera` in camera.py).
"""
from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("echoguide.hooks")

BACKEND_DIR = Path(__file__).resolve().parent.parent
SETTINGS_PATH = BACKEND_DIR / "settings.json"

_warned: set[str] = set()
_raw_settings: Optional[dict] = None


def _resolve(module: str, func: str) -> Optional[Callable[..., Any]]:
    try:
        mod = importlib.import_module(f".{module}", __package__)
    except Exception as exc:  # stub or broken module: treat as missing
        _warn_once(f"{module}.{func}", f"cannot import app.{module}: {exc}")
        return None
    for owner in (mod, getattr(mod, module, None)):
        target = getattr(owner, func, None) if owner is not None else None
        if callable(target):
            return target
    _warn_once(f"{module}.{func}", f"app.{module} has no {func}() yet")
    return None


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning("hook skipped: %s", message)


def call(module: str, func: str, *args: Any, **kwargs: Any) -> Any:
    """Call app.<module>.<func>(...) if it exists; return None otherwise or on error."""
    target = _resolve(module, func)
    if target is None:
        return None
    try:
        return target(*args, **kwargs)
    except Exception:
        log.exception("hook %s.%s failed", module, func)
        return None


# Shared APIs from docs/contracts.md section 7 -------------------------------

def say(text: str) -> None:
    log.info("say: %s", text)
    call("audio", "say", text)


def chime(kind: str) -> None:
    call("audio", "chime", kind)


def send_cmd(cmd: dict) -> None:
    log.info("arduino cmd: %s", cmd)
    call("serial_reader", "send", cmd)


def update_state(**fields: Any) -> None:
    call("state", "update", **fields)


def setting(key: str, default: Any = None) -> Any:
    """Read a setting from P1's config if it has it, else straight from settings.json."""
    try:
        cfg = importlib.import_module(".config", __package__)
        settings = getattr(cfg, "settings", None)
        if isinstance(settings, dict) and key in settings:
            return settings[key]
        if settings is not None and hasattr(settings, key):
            return getattr(settings, key)
    except Exception:
        pass
    return _load_raw_settings().get(key, default)


def _load_raw_settings() -> dict:
    global _raw_settings
    if _raw_settings is None:
        try:
            _raw_settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _raw_settings = {}
    return _raw_settings
