from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    environment: str
    admin_password: str
    session_secret: str
    data_dir: Path
    repo_root: Path
    run_timeout_seconds: int

    @property
    def database_path(self) -> Path:
        return self.data_dir / "wxread.sqlite3"

    @property
    def secrets_path(self) -> Path:
        return self.data_dir / "secrets.json"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        values = dict(os.environ)
        if env:
            values.update({key: str(value) for key, value in env.items()})

        environment = values.get("WXREAD_CONSOLE_ENV", "development")
        admin_password = values.get("WXREAD_ADMIN_PASSWORD", "")
        session_secret = values.get("WXREAD_SESSION_SECRET", "")
        if environment == "production" and not admin_password:
            raise RuntimeError("WXREAD_ADMIN_PASSWORD is required in production")
        if environment == "production" and not session_secret:
            raise RuntimeError("WXREAD_SESSION_SECRET is required in production")

        repo_root = Path(__file__).resolve().parents[1]
        data_dir = Path(values.get("WXREAD_DATA_DIR", repo_root / "data"))
        return cls(
            environment=environment,
            admin_password=admin_password,
            session_secret=session_secret or "development-only-secret",
            data_dir=data_dir,
            repo_root=repo_root,
            run_timeout_seconds=int(values.get("WXREAD_RUN_TIMEOUT_SECONDS", "14400")),
        )
