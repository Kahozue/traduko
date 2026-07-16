"""API token: generated on first start, stored under config/api-token.

Delete the file and restart to rotate the token. Single token in v1.
"""
from __future__ import annotations

import secrets
from pathlib import Path

TOKEN_FILE = "config/api-token"


def load_or_create_token(root: Path) -> str:
    path = root / TOKEN_FILE
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    return token
