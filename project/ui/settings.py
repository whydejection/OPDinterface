from __future__ import annotations

import json
import os
from typing import Any


def _settings_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".seismic_data_suite.json")


def load_settings() -> dict[str, Any]:
    path = _settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data: dict[str, Any]) -> None:
    path = _settings_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, path)
        except Exception:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

