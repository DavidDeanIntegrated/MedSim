import json
from pathlib import Path
from typing import Any


class CaseLoader:
    def __init__(self, case_dir: Path) -> None:
        self.case_dir = case_dir

    def load_case(self, case_id: str) -> dict[str, Any]:
        path = self.case_dir / f"{case_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Case file not found: {case_id}")
        return json.loads(path.read_text(encoding="utf-8"))
