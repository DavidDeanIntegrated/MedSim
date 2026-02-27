import json
from pathlib import Path
from typing import Any


class SessionRepository:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        return self.session_dir / f"{session_id}.json"

    def save(self, session_id: str, data: dict[str, Any]) -> None:
        path = self._session_path(session_id)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._session_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Session {session_id} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, session_id: str) -> None:
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
