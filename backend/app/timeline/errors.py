from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TimelineImportError(ValueError):
    message: str
    line_number: int | None = None
    code: str = "import_error"

    def __str__(self) -> str:
        if self.line_number is None:
            return self.message
        return f"line {self.line_number}: {self.message}"
