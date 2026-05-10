"""Button and MenuFSM tests — no GPIO hardware required."""
import time

import pytest

from porcupine.interfaces.button import Button, MenuFSM, _StubGPIO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_button(long_press_ms: int = 200) -> Button:
    """Return a started Button backed by _StubGPIO."""
    btn = Button(pin=17, long_press_ms=long_press_ms, debounce_ms=0)
    btn.start()
    return btn


def short_press(btn: Button, duration_s: float = 0.05) -> None:
    btn._stub.simulate_press()
    time.sleep(duration_s)
    btn._stub.simulate_release()


def long_press(btn: Button, long_press_ms: int = 200, extra_ms: int = 50) -> None:
    btn._stub.simulate_press()
    time.sleep((long_press_ms + extra_ms) / 1000)
    btn._stub.simulate_release()


# ---------------------------------------------------------------------------
# Button — press detection
# ---------------------------------------------------------------------------

def test_short_press_fires_short_callback():
    btn = make_button()
    fired = []
    btn.on_short_press(lambda: fired.append("short"))
    short_press(btn)
    assert fired == ["short"]
    btn.stop()


def test_long_press_fires_long_callback():
    btn = make_button(long_press_ms=100)
    fired = []
    btn.on_long_press(lambda: fired.append("long"))
    long_press(btn, long_press_ms=100)
    assert fired == ["long"]
    btn.stop()


def test_short_press_does_not_fire_long_callback():
    btn = make_button(long_press_ms=200)
    fired = []
    btn.on_long_press(lambda: fired.append("long"))
    short_press(btn)
    assert fired == []
    btn.stop()


def test_long_press_does_not_fire_short_callback():
    btn = make_button(long_press_ms=100)
    fired = []
    btn.on_short_press(lambda: fired.append("short"))
    long_press(btn, long_press_ms=100)
    assert fired == []
    btn.stop()


def test_multiple_short_presses_fire_each_time():
    btn = make_button()
    fired = []
    btn.on_short_press(lambda: fired.append(1))
    short_press(btn)
    short_press(btn)
    short_press(btn)
    assert len(fired) == 3
    btn.stop()


def test_release_without_press_is_ignored():
    btn = make_button()
    fired = []
    btn.on_short_press(lambda: fired.append(1))
    btn._stub.simulate_release()  # release with no preceding press
    assert fired == []
    btn.stop()


def test_stop_prevents_callbacks_after_stop():
    btn = make_button()
    fired = []
    btn.on_short_press(lambda: fired.append(1))
    btn.stop()
    short_press(btn)
    assert fired == []


# ---------------------------------------------------------------------------
# _StubGPIO
# ---------------------------------------------------------------------------

def test_stub_initial_state_released():
    stub = _StubGPIO(pin=17)
    assert stub.read() == 1


def test_stub_press_sets_state_to_zero():
    stub = _StubGPIO(pin=17)
    stub.simulate_press()
    assert stub.read() == 0


def test_stub_release_restores_state():
    stub = _StubGPIO(pin=17)
    stub.simulate_press()
    stub.simulate_release()
    assert stub.read() == 1


def test_stub_edge_callback_called_on_press_and_release():
    stub = _StubGPIO(pin=17)
    calls = []
    stub.on_edge(lambda ch: calls.append(ch))
    stub.simulate_press()
    stub.simulate_release()
    assert calls == [17, 17]


# ---------------------------------------------------------------------------
# MenuFSM — state transitions
# ---------------------------------------------------------------------------

@pytest.fixture
def fsm_setup():
    btn = make_button(long_press_ms=100)
    log = []
    fsm = MenuFSM(
        button=btn,
        next_screen_cb=lambda: log.append("next"),
        enter_menu_cb=lambda: log.append("enter_menu"),
        menu_next_cb=lambda: log.append("menu_next"),
        menu_confirm_cb=lambda: log.append("confirm"),
    )
    yield btn, fsm, log
    btn.stop()


def test_fsm_starts_in_normal(fsm_setup):
    _, fsm, _ = fsm_setup
    assert not fsm.in_menu


def test_fsm_short_in_normal_calls_next_screen(fsm_setup):
    btn, fsm, log = fsm_setup
    short_press(btn)
    assert log == ["next"]
    assert not fsm.in_menu


def test_fsm_long_in_normal_enters_menu(fsm_setup):
    btn, fsm, log = fsm_setup
    long_press(btn, long_press_ms=100)
    assert log == ["enter_menu"]
    assert fsm.in_menu


def test_fsm_short_in_menu_calls_menu_next(fsm_setup):
    btn, fsm, log = fsm_setup
    long_press(btn, long_press_ms=100)   # enter menu
    log.clear()
    short_press(btn)
    assert log == ["menu_next"]
    assert fsm.in_menu


def test_fsm_long_in_menu_confirms_and_returns_to_normal(fsm_setup):
    btn, fsm, log = fsm_setup
    long_press(btn, long_press_ms=100)   # enter menu
    log.clear()
    long_press(btn, long_press_ms=100)   # confirm
    assert log == ["confirm"]
    assert not fsm.in_menu


def test_fsm_full_cycle(fsm_setup):
    btn, fsm, log = fsm_setup
    short_press(btn)                    # next screen
    long_press(btn, long_press_ms=100)  # enter menu
    short_press(btn)                    # menu next
    short_press(btn)                    # menu next
    long_press(btn, long_press_ms=100)  # confirm → back to normal
    short_press(btn)                    # next screen again
    assert log == ["next", "enter_menu", "menu_next", "menu_next", "confirm", "next"]
    assert not fsm.in_menu


def test_fsm_reset_forces_normal(fsm_setup):
    btn, fsm, log = fsm_setup
    long_press(btn, long_press_ms=100)  # enter menu
    assert fsm.in_menu
    fsm.reset()
    assert not fsm.in_menu
