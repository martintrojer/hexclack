"""What the screen saver warns about (user request): server, sensor and the air quality.

Pure rules over the latest readings the widgets saw. The clock draws the result as a stripe of
labelled segments; an empty list means a plain clock.
"""

from dataclasses import dataclass
from enum import IntEnum

from hexclack.widgets.health import Summary
from hexclack.widgets.sensors import Reading


class Severity(IntEnum):
    WARN = 1  # orange: worth a look (Poor air, a stale reading)
    BAD = 2  # red: something is down (unhealthy service, unreachable host, Unhealthy air)


@dataclass(frozen=True)
class Alert:
    label: str
    severity: Severity


def health_alert(name: str, summary: Summary | None) -> Alert | None:
    if summary is None:
        return None
    if summary.error:
        return Alert(f"{name} down", Severity.BAD)
    if summary.unhealthy:
        return Alert(f"{name} {summary.healthy}/{summary.total}", Severity.BAD)
    if summary.stale:
        return Alert(f"{name} stale", Severity.WARN)
    return None


def sensors_alerts(name: str, reading: Reading | None) -> list[Alert]:
    if reading is None:
        return []
    if reading.error:
        return [Alert(f"{name} down", Severity.BAD)]
    if reading.stale:
        return [Alert(f"{name} stale", Severity.WARN)]
    if reading.aq == "Unhealthy":
        return [Alert("air unhealthy", Severity.BAD)]
    if reading.aq == "Poor":
        return [Alert("air poor", Severity.WARN)]
    return []


def collect(healths: dict[str, Summary], sensors: dict[str, Reading]) -> list[Alert]:
    """All current alerts, worst first, then by label (stable across redraws)."""
    found = [a for name, s in healths.items() if (a := health_alert(name, s)) is not None]
    for name, r in sensors.items():
        found += sensors_alerts(name, r)
    return sorted(found, key=lambda a: (-a.severity, a.label))
