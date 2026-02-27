from typing import Any

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


JSONDict = dict[str, Any]
