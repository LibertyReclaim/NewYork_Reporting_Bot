from __future__ import annotations

from collections.abc import Callable
from typing import Any

from states import newyork

Runner = Callable[..., dict[str, str]]

STATE_RUNNERS: dict[str, Runner] = {
    "NY": newyork.run,
}


def get_runner(state_code: str) -> Runner | None:
    return STATE_RUNNERS.get((state_code or "").strip().upper())
