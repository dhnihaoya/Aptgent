from __future__ import annotations

from typing import Any


def coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def coerce_int_list(
    values: Any,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> list[int]:
    if not isinstance(values, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in values:
        value = coerce_int(item)
        if value is None:
            continue
        if min_value is not None and value < min_value:
            continue
        if max_value is not None and value > max_value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def coerce_float_list(values: Any, *, exact_len: int | None = None) -> list[float]:
    if not isinstance(values, list):
        return []
    result = [value for item in values if (value := coerce_float(item)) is not None]
    if exact_len is not None and len(result) != exact_len:
        return []
    return result
