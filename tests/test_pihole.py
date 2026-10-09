"""Pi-hole session logic. A re-auth that fails silently stops status updates, and a login per call
exhausts Pi-hole's session seats; neither shows an error on the deck."""

import pytest

from hexclack.pihole import PiholeClient, PiholeError, Response


class FakePihole:
    def __init__(self) -> None:
        self.valid_sids: set[str] = set()
        self.issued = 0
        self.calls: list[tuple[str, str]] = []
        self.password = "correct horse"

    def __call__(self, method: str, url: str, body: dict[str, object] | None, headers: dict[str, str]) -> Response:
        path = url.split("/api", 1)[1]
        self.calls.append((method, path))
        if path == "/auth":
            if body != {"password": self.password}:
                return Response(401, {"error": {"key": "unauthorized"}})
            self.issued += 1
            sid = f"sid{self.issued}"
            self.valid_sids.add(sid)
            return Response(200, {"session": {"valid": True, "sid": sid}})
        if headers.get("X-FTL-SID") not in self.valid_sids:
            return Response(401, {"error": {"key": "unauthorized"}})
        if method == "GET":
            return Response(200, {"blocking": "enabled", "timer": None})
        return Response(200, {"blocking": "disabled", "timer": body.get("timer") if body else None})

    def expire_all(self) -> None:
        self.valid_sids.clear()


def client(fake: FakePihole) -> PiholeClient:
    return PiholeClient("server:8000", password=lambda: "correct horse", transport=fake)


def test_one_login_reused_across_calls() -> None:
    fake = FakePihole()
    c = client(fake)
    for _ in range(20):
        assert c.blocking() == "enabled"
    c.disable(3600)
    assert fake.issued == 1  # a login per poll would exhaust the seat limit


def test_reauth_once_on_401_then_succeeds() -> None:
    fake = FakePihole()
    c = client(fake)
    c.blocking()
    fake.expire_all()  # Pi-hole restarted or the session timed out
    assert c.blocking() == "enabled"
    assert fake.issued == 2
    assert fake.calls[-3:] == [("GET", "/dns/blocking"), ("POST", "/auth"), ("GET", "/dns/blocking")]


def test_disable_sends_the_timer() -> None:
    fake = FakePihole()
    client(fake).disable(3600)
    assert fake.calls[-1] == ("POST", "/dns/blocking")


def test_wrong_password_raises_instead_of_looping() -> None:
    fake = FakePihole()
    fake.password = "something else"
    with pytest.raises(PiholeError, match="login failed"):
        client(fake).blocking()
    assert fake.calls.count(("POST", "/auth")) == 1


def test_persistent_401_after_relogin_raises() -> None:
    fake = FakePihole()
    c = client(fake)
    c.blocking()
    real = fake.__call__

    def always_401_on_api(method: str, url: str, body: dict[str, object] | None, headers: dict[str, str]) -> Response:
        if url.endswith("/auth"):
            return real(method, url, body, headers)
        return Response(401, {})

    c.transport = always_401_on_api
    with pytest.raises(PiholeError, match="401"):
        c.blocking()
