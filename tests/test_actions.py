"""Toggle state and duplicate presses. A toggle that advances after a failed action shows the
wrong label for every later press; a double-fired press runs an action twice. Neither raises."""

import threading
from pathlib import Path

from hexclack import config
from hexclack.actions import ActionError, Runner
from hexclack.config import Action
from hexclack.pihole import PiholeClient

ROOT = Path(__file__).parent.parent
CFG = config.load(ROOT / "tests/data/layout.toml")
# A blind toggle (no status source): Elgato Multi Action Switch behaviour, still supported in config.
BLIND = config.parse(
    {
        "pages": ["utils"],
        "screens": {
            "utils": {
                "kind": "page",
                "keys": {
                    "1,1": {
                        "toggle": {
                            "states": [
                                {"label": "A", "http": {"method": "PUT", "url": "http://x/?v=1"}},
                                {"label": "B", "http": {"method": "PUT", "url": "http://x/?v=0"}},
                            ]
                        }
                    }
                },
            }
        },
    }
)
DIRAC = BLIND.screens["utils"].keys["1,1"]


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.ran: list[Action] = []
        self.fail = fail
        self.done = threading.Event()
        self.results: list[bool] = []
        self.gate = threading.Event()
        self.gate.set()

    def execute(self, action: Action) -> None:
        self.gate.wait(5)
        self.ran.append(action)
        if self.fail:
            raise ActionError("boom")

    def on_done(self, _screen: str, _key: int, ok: bool) -> None:
        self.results.append(ok)
        self.done.set()


def no_pihole(host: str) -> PiholeClient:
    raise AssertionError(f"unexpected Pi-hole call for {host}")


def press(runner: Runner, rec: Recorder) -> None:
    rec.done.clear()
    assert runner.submit("utils", 4, DIRAC, None)
    assert rec.done.wait(5)


def url(action: Action) -> str:
    return str(action.fields["url"])


def test_toggle_runs_shown_state_then_advances_and_wraps() -> None:
    rec = Recorder()
    runner = Runner(pihole=no_pihole, on_done=rec.on_done, execute=rec.execute)
    for _ in range(3):
        press(runner, rec)
    assert [url(a)[-1] for a in rec.ran] == ["1", "0", "1"]
    assert runner.toggle_state("utils", 4, DIRAC) == 1


def test_failed_toggle_action_does_not_advance() -> None:
    rec = Recorder(fail=True)
    runner = Runner(pihole=no_pihole, on_done=rec.on_done, execute=rec.execute)
    press(runner, rec)
    press(runner, rec)
    assert [url(a)[-1] for a in rec.ran] == ["1", "1"]  # retried the same state
    assert rec.results == [False, False]
    assert runner.toggle_state("utils", 4, DIRAC) == 0


def test_second_press_while_running_is_dropped() -> None:
    rec = Recorder()
    rec.gate.clear()  # hold the first action in flight
    runner = Runner(pihole=no_pihole, on_done=rec.on_done, execute=rec.execute)
    key = CFG.screens["now"].keys["1,0"]
    assert runner.submit("now", 1, key, key.action)
    assert not runner.submit("now", 1, key, key.action)  # dropped
    rec.gate.set()
    assert rec.done.wait(5)
    rec.done.clear()
    assert runner.submit("now", 1, key, key.action)  # free again
    assert rec.done.wait(5)
    assert len(rec.ran) == 2


# -- status-backed toggle (the real Dirac key) -----------------------------------------------------

STATUS_DIRAC = CFG.screens["utils"].keys["0,1"]


def test_status_toggle_press_sends_the_opposite_of_the_polled_state() -> None:
    # User report: the blind toggle drifted from Dirac. Now a press is relative to Dirac's real state.
    rec = Recorder()
    runner = Runner(pihole=no_pihole, on_done=rec.on_done, execute=rec.execute)
    for polled, expected in ((0, "1"), (1, "0"), (0, "1")):
        runner.set_known("utils", 4, polled)
        rec.done.clear()
        assert runner.submit("utils", 4, STATUS_DIRAC, None)
        assert rec.done.wait(5)
        assert url(rec.ran[-1])[-1] == expected
    assert runner.toggle_state("utils", 4, STATUS_DIRAC) == 0  # the press does not move it; the re-poll does


def test_status_toggle_unknown_state_ignores_the_press() -> None:
    rec = Recorder()
    runner = Runner(pihole=no_pihole, on_done=rec.on_done, execute=rec.execute)
    runner.set_known("utils", 4, None)  # Dirac unreachable
    assert not runner.submit("utils", 4, STATUS_DIRAC, None)
    assert rec.ran == []
