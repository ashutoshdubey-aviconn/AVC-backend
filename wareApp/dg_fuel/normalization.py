"""Shared value and timestamp normalization for DG-fuel providers."""

import re
from datetime import datetime
from typing import Any, Optional


def as_float(value: Any) -> Optional[float]:
    """Return a numeric provider value as float, or None when unavailable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def epoch_milliseconds(value: Any) -> Optional[int]:
    """Normalize epoch seconds, epoch milliseconds, or ISO timestamps to ms."""
    if value is None or isinstance(value, bool):
        return None

    try:
        numeric_value = int(float(str(value).strip()))
    except (TypeError, ValueError):
        numeric_value = None

    if numeric_value is not None:
        return numeric_value if numeric_value >= 1_000_000_000_000 else numeric_value * 1000

    try:
        normalized_value = str(value).strip().replace("Z", "+00:00")
        normalized_value = re.sub(
            r"([+-]\d{2})(\d{2})$",
            r"\1:\2",
            normalized_value,
        )
        parsed = datetime.fromisoformat(normalized_value)
    except (TypeError, ValueError):
        return None

    return int(parsed.timestamp() * 1000)