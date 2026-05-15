"""
config_manager.py
=================
Provides a simple, JSON-backed persistence layer for user preferences and
theme definitions.

Features
--------
- Loads configuration from ``config.json`` in the project root on first access.
- Creates the file with sensible defaults if it does not exist.
- Supports nested dot-notation key access (e.g. ``get("weather.city")``).
- Writes atomically (write to a temp file then rename) to prevent corruption
  on unexpected shutdown.
- Thread-safe via a ``threading.Lock``.

Typical usage
-------------
>>> cfg = ConfigManager()
>>> city = cfg.get("weather.city", default="Cairo")
>>> cfg.set("weather.city", "London")
>>> cfg.save()
"""

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default configuration schema
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict = {
    "app": {
        "theme": "dark",
        "language": "en",
        "window_width": 1200,
        "window_height": 750,
    },
    "monitor": {
        "poll_interval_seconds": 2.0,
    },
    "weather": {
        "api_key": "",          # Empty → mock mode
        "city": "Cairo",
        "poll_interval_seconds": 600,
    },
    "serial": {
        "port": "",
        "baud_rate": 115200,
    },
    "themes": {
        "active_theme": "default",
        "custom_themes": {},
    },
}


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """
    Singleton-friendly configuration manager backed by a JSON file.

    Parameters
    ----------
    config_path:
        Absolute or relative path to the JSON config file.
        Defaults to ``config.json`` in the current working directory.
    """

    def __init__(self, config_path: str | Path = "config.json") -> None:
        self._path = Path(config_path).resolve()
        self._data: dict = {}
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value using dot-notation.

        Parameters
        ----------
        key:
            Dot-separated path (e.g. ``"weather.city"``).
        default:
            Value to return if the key does not exist.

        Returns
        -------
        Any
            The stored value or *default*.
        """
        with self._lock:
            return self._nested_get(self._data, key.split("."), default)

    def set(self, key: str, value: Any) -> None:
        """
        Store a value using dot-notation.  Missing intermediate dicts are
        created automatically.

        Parameters
        ----------
        key:
            Dot-separated path (e.g. ``"weather.city"``).
        value:
            JSON-serialisable value to store.
        """
        with self._lock:
            self._nested_set(self._data, key.split("."), value)

    def save(self) -> bool:
        """
        Persist the current in-memory config to disk atomically.

        Returns
        -------
        bool
            ``True`` on success, ``False`` on I/O error.
        """
        with self._lock:
            try:
                self._atomic_write(self._data)
                logger.debug("Config saved to %s.", self._path)
                return True
            except OSError as exc:
                logger.error("Failed to save config: %s", exc)
                return False

    def reload(self) -> None:
        """Re-read the config file from disk, discarding in-memory changes."""
        with self._lock:
            self._load(locked=True)

    def all(self) -> dict:
        """Return a shallow copy of the entire config dictionary."""
        with self._lock:
            return dict(self._data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self, locked: bool = False) -> None:
        """Load (or create) the config file.  Pass ``locked=True`` when the
        caller already holds ``self._lock``."""
        def _do_load():
            if self._path.exists():
                try:
                    with self._path.open("r", encoding="utf-8") as fh:
                        on_disk = json.load(fh)
                    # Deep-merge: disk values override defaults so new default
                    # keys are added without wiping existing user settings.
                    self._data = self._deep_merge(_DEFAULT_CONFIG, on_disk)
                    logger.debug("Config loaded from %s.", self._path)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Config file unreadable (%s); using defaults.", exc)
                    self._data = dict(_DEFAULT_CONFIG)
            else:
                logger.info("Config file not found; creating with defaults.")
                self._data = dict(_DEFAULT_CONFIG)
                self._atomic_write(self._data)

        if locked:
            _do_load()
        else:
            with self._lock:
                _do_load()

    def _atomic_write(self, data: dict) -> None:
        """Write *data* to disk using a temp-file rename for atomicity."""
        dir_ = self._path.parent
        dir_.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=4, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except Exception:
            # Clean up the temp file if something went wrong
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _nested_get(data: dict, keys: list[str], default: Any) -> Any:
        """Traverse nested dicts using a list of keys."""
        node = data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @staticmethod
    def _nested_set(data: dict, keys: list[str], value: Any) -> None:
        """Create or update a value at the nested path defined by *keys*."""
        node = data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """
        Recursively merge *override* into *base*.

        Dict values are merged recursively; all other types are replaced
        by the override value.
        """
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigManager._deep_merge(result[k], v)
            else:
                result[k] = v
        return result
