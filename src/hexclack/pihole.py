"""Pi-hole v6 client (docs/design.md section 7; research R4, R5).

One session per host: `POST /api/auth {password}` returns `session.sid`, sent as `X-FTL-SID`
(https://docs.pi-hole.net/api/auth/). Sessions are kept and reused, because Pi-hole has a small
number of seats and a client that logs in on every call exhausts them. On a 401 the client logs
in again once and retries. The password comes from the Keychain, never from config.
"""

import json
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

TIMEOUT_S = 5


class PiholeError(Exception):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    body: dict[str, object]


# (method, url, json body or None, headers) -> Response. Injected so tests run without a network.
Transport = Callable[[str, str, dict[str, object] | None, dict[str, str]], Response]


def urllib_transport(method: str, url: str, body: dict[str, object] | None, headers: dict[str, str]) -> Response:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as reply:
            return Response(reply.status, json.loads(reply.read() or b"{}"))
    except urllib.error.HTTPError as err:
        try:
            parsed = json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            parsed = {}
        return Response(err.code, parsed)
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise PiholeError(f"{url}: {err}") from err


def keychain_password(host: str, service: str = "hexclack-pihole") -> str:
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", service, "-a", host, "-w"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise PiholeError(
            f"no Keychain password for {host}; add it with: security add-generic-password -s {service} -a {host} -w"
        )
    return result.stdout.strip()


class PiholeClient:
    def __init__(
        self,
        host: str,
        password: Callable[[], str] | None = None,
        transport: Transport = urllib_transport,
        scheme: str = "http",
    ) -> None:
        self.base = f"{scheme}://{host}/api"
        self.host = host
        self.password = password or (lambda: keychain_password(host))
        self.transport = transport
        self.sid: str | None = None
        self.logins = 0
        self._lock = threading.Lock()  # one login at a time, even if the widget and a key press race

    def _login(self) -> str:
        reply = self.transport("POST", f"{self.base}/auth", {"password": self.password()}, {})
        session = reply.body.get("session")
        sid = session.get("sid") if isinstance(session, dict) else None
        if reply.status != 200 or not isinstance(sid, str):
            raise PiholeError(f"{self.host}: login failed (HTTP {reply.status})")
        self.logins += 1
        return sid

    def _call(self, method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
        with self._lock:
            for attempt in range(2):
                if self.sid is None:
                    self.sid = self._login()
                reply = self.transport(method, f"{self.base}{path}", body, {"X-FTL-SID": self.sid})
                if reply.status == 401 and attempt == 0:
                    self.sid = None  # session expired or was revoked: log in once more
                    continue
                if reply.status >= 400:
                    raise PiholeError(f"{self.host}: {method} {path} returned HTTP {reply.status}")
                return reply.body
        raise PiholeError(f"{self.host}: still unauthorised after a fresh login")

    def status(self) -> dict[str, object]:
        """The raw blocking status: {"blocking": "enabled"|"disabled"|..., "timer": seconds or None}."""
        return self._call("GET", "/dns/blocking")

    def blocked_24h(self) -> int | None:
        """Queries blocked in the last 24 hours (rolling): the Elgato plugin's `ads_blocked_today` stat."""
        queries = self._call("GET", "/stats/summary").get("queries")
        blocked = queries.get("blocked") if isinstance(queries, dict) else None
        return blocked if isinstance(blocked, int) else None

    def blocking(self) -> str:
        """'enabled' or 'disabled' (or another state Pi-hole reports, e.g. 'failed')."""
        return str(self._call("GET", "/dns/blocking").get("blocking"))

    def timer(self) -> float | None:
        """Seconds until blocking turns back on, if a disable timer is running."""
        value = self._call("GET", "/dns/blocking").get("timer")
        return float(value) if isinstance(value, int | float) else None

    def disable(self, seconds: int) -> None:
        self._call("POST", "/dns/blocking", {"blocking": False, "timer": seconds})
