"""Application errors, admission values and tariff policy."""

import json
from dataclasses import dataclass
from ..contracts.api import CommandResult, ErrorDetail


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class BusinessFault(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.detail = ErrorDetail(code=code, message=message, retryable=retryable)
        super().__init__(message)


@dataclass(frozen=True)
class Admission:
    result: CommandResult
    replayed: bool


def tariff_bani(entered_at: int, at: int, hourly_rate_bani: int) -> int:
    if at < entered_at:
        raise BusinessFault("DATA_UNAVAILABLE", "Ceasul gazdei este anterior intrării confirmate.")
    hours = max(1, (at - entered_at + 3_600_000 - 1) // 3_600_000)
    amount = hours * hourly_rate_bani
    if amount > 9007199254740991:
        raise BusinessFault("DATA_UNAVAILABLE", "Tariful calculat depășește domeniul monetar al contractului.")
    return amount
