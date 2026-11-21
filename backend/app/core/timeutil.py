"""Simulation clock helpers – time is expressed as minutes since midnight."""


def hhmm_to_min(value: str) -> float:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def min_to_hhmm(value: float | None) -> str | None:
    if value is None:
        return None
    value = int(round(value))
    day = value // 1440
    text = f"{(value // 60) % 24:02d}:{value % 60:02d}"
    return text + (f" +{day}d" if day > 0 else "")
