"""Readable ranges for MQTT log lines ("2026-10-19 09:00→18:00 (10 h)")."""

from datetime import datetime, timedelta

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
MAX_RANGES = 6


def _hour(value):
    return value.strftime("%Y-%m-%d %H:%M")


def hour_span(first_hour, last_hour):
    """``first_hour`` .. ``last_hour`` inclusive, both hour starts."""
    hours = int((last_hour - first_hour) / HOUR) + 1
    if first_hour.date() == last_hour.date():
        end = last_hour.strftime("%H:%M")
    else:
        end = _hour(last_hour)
    if hours == 1:
        return f"{_hour(first_hour)} (1 h)"
    return f"{_hour(first_hour)}→{end} ({hours} h)"


def missing_hours(missing_from, missing_to):
    """Gap ``[missing_from, missing_to)`` as hours, e.g. ``09:00→18:00 (10 h)``."""
    if missing_to <= missing_from:
        return hour_span(missing_from, missing_from)
    return hour_span(missing_from, missing_to - HOUR)


def _runs(values, step):
    values = sorted(set(values))
    runs = []
    for value in values:
        if runs and value - runs[-1][1] == step:
            runs[-1][1] = value
        else:
            runs.append([value, value])
    return runs


def hour_ranges(hours):
    """Consecutive hours merged: ``2026-10-01 00:00→23:00 (24 h), 2026-10-02 05:00 (1 h)``."""
    if not hours:
        return "-"
    runs = _runs(hours, HOUR)
    text = ", ".join(hour_span(start, end) for start, end in runs[:MAX_RANGES])
    if len(runs) > MAX_RANGES:
        text += f", +{len(runs) - MAX_RANGES} more ranges"
    return text


def day_ranges(days):
    """Consecutive dates merged: ``2026-09-30→2026-10-19 (20 d)``."""
    if not days:
        return "-"
    days = [day.date() if isinstance(day, datetime) else day for day in days]
    runs = _runs(days, DAY)
    parts = []
    for start, end in runs[:MAX_RANGES]:
        count = (end - start).days + 1
        parts.append(f"{start}" if count == 1 else f"{start}→{end} ({count} d)")
    text = ", ".join(parts)
    if len(runs) > MAX_RANGES:
        text += f", +{len(runs) - MAX_RANGES} more ranges"
    return text

