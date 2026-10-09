"""Screen saver alerts. A missed alert means a down service hides behind a calm clock."""

from hexclack import alerts, render
from hexclack.alerts import Severity
from hexclack.widgets.health import Summary
from hexclack.widgets.sensors import Reading

OK_HEALTH = Summary(30, 30, (), 20)
OK_ROOM = Reading(21.4, 34, "Good", 40)


def labels(found: list[alerts.Alert]) -> list[tuple[str, Severity]]:
    return [(a.label, a.severity) for a in found]


def test_all_fine_means_no_alerts() -> None:
    assert alerts.collect({"server": OK_HEALTH}, {"sensor": OK_ROOM}) == []
    assert alerts.collect({}, {}) == []  # nothing polled yet: no alert, not a false alarm


def test_each_problem_maps_to_its_alert() -> None:
    cases = [
        ({"server": Summary(28, 30, ("Immich", "Forgejo"), 20)}, {}, [("server 28/30", Severity.BAD)]),
        ({"server": Summary(0, 0, (), None, error="URLError")}, {}, [("server down", Severity.BAD)]),
        ({"server": Summary(30, 30, (), 900)}, {}, [("server stale", Severity.WARN)]),
        ({}, {"sensor": Reading(None, None, "Unknown", None, error="URLError")}, [("sensor down", Severity.BAD)]),
        ({}, {"sensor": Reading(21.4, 34, "Good", 1200)}, [("sensor stale", Severity.WARN)]),
        ({}, {"sensor": Reading(21.4, 34, "Unhealthy", 40)}, [("air unhealthy", Severity.BAD)]),
        ({}, {"sensor": Reading(21.4, 34, "Poor", 40)}, [("air poor", Severity.WARN)]),
        ({}, {"sensor": Reading(21.4, 34, "Moderate", 40)}, []),
    ]
    for healths, sensors, expected in cases:
        assert labels(alerts.collect(healths, sensors)) == expected


def test_worst_first() -> None:
    found = alerts.collect({"server": Summary(30, 30, (), 900)}, {"sensor": Reading(21.4, 34, "Unhealthy", 40)})
    assert labels(found) == [("air unhealthy", Severity.BAD), ("server stale", Severity.WARN)]


def test_no_alerts_leaves_the_clock_exactly_as_before() -> None:
    plain = render.clock_keys("13:47", colour="#f38ba8")
    empty = render.clock_keys("13:47", colour="#f38ba8", alerts=[])
    assert all(plain[i].tobytes() == empty[i].tobytes() for i in plain)


def test_an_alert_draws_a_red_stripe_on_the_bottom_keys() -> None:
    keys = render.clock_keys("13:47", colour="#f38ba8", alerts=[("air unhealthy", int(Severity.BAD))])
    red = render.ALERT_COLOURS[int(Severity.BAD)]
    bottom = {c for i in (3, 4, 5) for _n, c in (keys[i].getcolors(maxcolors=6400) or [])}
    top = {c for i in (0, 1, 2) for _n, c in (keys[i].getcolors(maxcolors=6400) or [])}
    assert red in bottom and red not in top
