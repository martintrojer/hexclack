"""The device-owner queue. A full queue must never drop a health Tick, or a wedge goes undetected."""

from pathlib import Path

from PIL import Image

from hexclack import device
from hexclack.device import Draw, Owner, Tick
from hexclack.watchdog import Watchdog
from tests.fakes import Clock, FakeDevice


def make_owner(tmp_path: Path) -> Owner:
    clock = Clock()
    wd = Watchdog(FakeDevice(), clock, lambda _c: None, lambda _m: None, tmp_path / "state.json")
    return Owner(device.StreamDeckIO(), wd, clock)  # not started: we inspect the queue directly


def test_overflow_drops_oldest_draw_not_tick(tmp_path: Path) -> None:
    owner = make_owner(tmp_path)
    img = Image.new("RGB", (80, 80))
    owner.submit(Tick())
    for i in range(device.QUEUE_SIZE - 1):
        owner.submit(Draw(i, img))
    owner.submit(Draw(999, img))  # queue full: the oldest Draw (key 0) goes
    queued = list(owner.commands.queue)
    assert len(queued) == device.QUEUE_SIZE
    assert isinstance(queued[0], Tick)
    keys = [c.key for c in queued if isinstance(c, Draw)]
    assert 0 not in keys and keys[-1] == 999


def test_draws_refused_after_a_hang(tmp_path: Path) -> None:
    owner = make_owner(tmp_path)
    owner.watchdog.accepting_draws = False
    owner.submit(Draw(0, Image.new("RGB", (80, 80))))
    assert owner.commands.empty()


def test_urgent_jumps_the_queue(tmp_path: Path) -> None:
    from hexclack.device import Suspend

    owner = make_owner(tmp_path)
    for i in range(5):
        owner.submit(Draw(i, Image.new("RGB", (80, 80))))
    owner.urgent(Suspend())
    assert isinstance(owner.commands.get_nowait(), Suspend)
