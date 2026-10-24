"""Configuration: config.yaml + .env + credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml


def load_dotenv(path: Path) -> None:
    """Minimal .env loader; never overrides variables already set in the environment."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ.setdefault(key, val)


class Config:
    def __init__(self, data: dict, root: Path):
        self.data = data
        self.root = root

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        cfg_path = Path(path) if path else Path(os.environ.get("P2A_CONFIG", "config.yaml"))
        if not cfg_path.is_file():
            raise FileNotFoundError(f"config file not found: {cfg_path.resolve()}")
        root = cfg_path.resolve().parent
        load_dotenv(root / ".env")
        data = yaml.safe_load(cfg_path.read_text()) or {}
        return cls(data, root)

    def get(self, dotted: str, default=None):
        cur = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def section(self, name: str) -> dict:
        return dict(self.data.get(name) or {})

    @property
    def data_dir(self) -> Path:
        d = self.root / self.get("paths.data_dir", ".p2a")
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def prompts_dir(self) -> Path:
        return self.root / self.get("paths.prompts_dir", "prompts")

    def prompt(self, name: str) -> str:
        return (self.prompts_dir / f"{name}.md").read_text()


def brain_credentials() -> tuple[str, str] | None:
    email, password = os.environ.get("BRAIN_EMAIL"), os.environ.get("BRAIN_PASSWORD")
    if email and password:
        return email, password
    cred_file = Path.home() / ".brain_credentials"
    if cred_file.is_file():
        try:
            data = json.loads(cred_file.read_text())
            if isinstance(data, list) and len(data) == 2:
                return data[0], data[1]
            if isinstance(data, dict) and data.get("email") and data.get("password"):
                return data["email"], data["password"]
        except (json.JSONDecodeError, OSError):
            return None
    return None


def openrouter_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY")
