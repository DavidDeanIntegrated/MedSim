import json
from pathlib import Path
from typing import Any


class MedicationLibrary:
    def __init__(self, contracts_dir: Path) -> None:
        self.contracts_dir = contracts_dir

    def load_hypertensive_emergency_library(self) -> dict[str, Any]:
        path = self.contracts_dir / "medication_library.hypertensive_emergency.json"
        return json.loads(path.read_text(encoding="utf-8"))
