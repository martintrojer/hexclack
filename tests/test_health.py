"""The server health key. Wrong here means a down service shows as green, or a stale page as fresh."""

import json
from datetime import UTC, datetime, timedelta

from hexclack.widgets import Event
from hexclack.widgets import health as h

NOW = datetime(2026, 10, 5, 14, 24, 30, tzinfo=UTC)


def doc(age_s: float = 20, **statuses: str) -> dict[str, object]:
    services = {k: {"label": k.title(), "section": "applications", "status": v} for k, v in statuses.items()}
    return {
        "checked_at": (NOW - timedelta(seconds=age_s)).isoformat().replace("+00:00", "Z"),
        "data": {"status": "healthy"},
        "services": services,
    }


def test_all_healthy_counts_data_and_services() -> None:
    s = h.summarize(doc(immich="healthy", grafana="healthy"), NOW)
    assert (s.healthy, s.total, s.unhealthy, s.stale) == (3, 3, (), False)
    assert h.age_text(s.age_s) == "20s"


def test_unhealthy_is_counted_and_named() -> None:
    s = h.summarize(doc(immich="unhealthy", grafana="healthy"), NOW)
    assert (s.healthy, s.total, s.unhealthy) == (2, 3, ("Immich",))


def test_not_installed_is_not_counted() -> None:
    s = h.summarize(doc(immich="healthy", papra="not-installed"), NOW)
    assert (s.healthy, s.total) == (2, 2)


def test_stale_after_three_minutes_like_servers_page() -> None:
    assert not h.summarize(doc(age_s=179, a="healthy"), NOW).stale
    assert h.summarize(doc(age_s=181, a="healthy"), NOW).stale


def test_unreachable_or_malformed_is_an_error_not_green() -> None:
    def down(_url: str) -> bytes:
        raise OSError("refused")

    for fetch in (down, lambda _u: b"<html>", lambda _u: b'{"no": "services"}'):
        summary = h.poll("utils", "0,1", "http://server/health.json", fetch=fetch).data["summary"]
        assert isinstance(summary, h.Summary) and summary.error


def test_poll_parses_the_real_shape() -> None:
    body = json.dumps(doc(immich="healthy")).encode()
    summary = h.poll("utils", "0,1", "http://server/health.json", fetch=lambda _u: body).data["summary"]
    assert isinstance(summary, h.Summary) and summary.total == 2 and summary.error is None


def test_widget_redraws_on_status_or_shown_age_change_only() -> None:
    w = h.HealthWidget("utils", "0,1", "server")
    ev = h.event_name("utils", "0,1")

    def at(age: float, **st: str) -> Event:
        return Event(ev, {"summary": h.summarize(doc(age_s=age, **st), NOW)})

    assert w.render(at(20, a="healthy")) is not None
    assert w.render(at(25, a="healthy")) is not None  # "20s" -> "25s": the shown age changed
    assert w.render(at(70, a="healthy")) is not None  # "1m"
    assert w.render(at(80, a="healthy")) is None  # still "1m"
    assert w.render(at(80, a="unhealthy")) is not None
