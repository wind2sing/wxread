from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


class SecretStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, values: Mapping[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(dict(values), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        if os.name == "posix":
            os.chmod(self.path, 0o600)
