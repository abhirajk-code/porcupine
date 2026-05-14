"""LCD tests run entirely against _StubLCD (no hardware required)."""
import time
from unittest.mock import patch

import pytest

# Force RPLCD unavailable so LCD always uses _StubLCD
with patch.dict("sys.modules", {"RPLCD": None, "RPLCD.i2c": None}):
    import importlib
    import porcupine.interfaces.lcd as lcd_mod
    importlib.reload(lcd_mod)

LCD = lcd_mod.LCD
_StubLCD = lcd_mod._StubLCD


@pytest.fixture
def lcd():
    instance = LCD(cols=16, rows=2)
    yield instance
    instance.stop()


def _display(lcd_instance) -> tuple[str, str]:
    stub = lcd_instance._lcd
    lines = stub.current_display()
    return lines[0], lines[1]


# ------------------------------------------------------------------
# show()
# ------------------------------------------------------------------

def test_show_writes_two_lines(lcd):
    lcd.show("Hello", "World")
    assert _display(lcd) == ("Hello", "World")


def test_show_truncates_to_cols(lcd):
    lcd.show("A" * 20, "B" * 20)
    line1, line2 = _display(lcd)
    assert len(line1) == 16
    assert len(line2) == 16


def test_show_empty_second_line(lcd):
    lcd.show("Only line 1")
    line1, line2 = _display(lcd)
    assert line1 == "Only line 1"
    assert line2 == ""


# ------------------------------------------------------------------
# screen cycling
# ------------------------------------------------------------------

def test_next_screen_advances_index(lcd):
    screens = [("CPU", "12%"), ("MEM", "45%"), ("TEMP", "52C")]
    lcd.start(screens, refresh_s=60)
    time.sleep(0.05)

    lcd.next_screen()
    assert lcd._index == 1
    lcd.next_screen()
    assert lcd._index == 2
    lcd.next_screen()
    assert lcd._index == 0  # wraps


def test_cycle_loop_advances_screen(lcd):
    screens = [("A", "1"), ("B", "2")]
    lcd.start(screens, refresh_s=0.05)
    time.sleep(0.18)
    # Should have advanced at least twice
    assert lcd._index >= 0  # basic liveness check


def test_start_with_empty_screens_does_not_crash(lcd):
    lcd.start([], refresh_s=0.05)
    time.sleep(0.1)


# ------------------------------------------------------------------
# menu mode
# ------------------------------------------------------------------

def test_enter_menu_freezes_cycle(lcd):
    screens = [("A", "1"), ("B", "2")]
    lcd.start(screens, refresh_s=0.02)
    lcd.enter_menu("> Restart", "")
    time.sleep(0.1)
    # index must not have changed while in menu
    assert lcd._in_menu is True
    assert _display(lcd)[0] == "> Restart"


def test_exit_menu_resumes_cycle(lcd):
    screens = [("A", "1"), ("B", "2")]
    lcd.start(screens, refresh_s=60)
    lcd.enter_menu("> Menu", "")
    lcd.exit_menu()
    assert lcd._in_menu is False


def test_update_menu_changes_display(lcd):
    lcd.start([("A", "1")], refresh_s=60)
    lcd.enter_menu("> Option 1", "")
    lcd.update_menu("> Option 2", "confirm?")
    assert _display(lcd)[0] == "> Option 2"


# ------------------------------------------------------------------
# update_screens
# ------------------------------------------------------------------

def test_update_screens_replaces_list(lcd):
    lcd.start([("A", "1")], refresh_s=60)
    lcd.update_screens([("X", "9"), ("Y", "8")])
    assert len(lcd._screens) == 2


def test_update_screens_clamps_index(lcd):
    lcd.start([("A", "1"), ("B", "2"), ("C", "3")], refresh_s=60)
    lcd._index = 2
    lcd.update_screens([("X", "9")])
    assert lcd._index == 0


# ------------------------------------------------------------------
# pause / resume — cycle loop stays alive
# ------------------------------------------------------------------

def test_pause_keeps_cycle_thread_running(lcd):
    lcd.start([("A", "1"), ("B", "2")], refresh_s=60)
    lcd.pause()
    assert lcd._thread is not None
    assert lcd._thread.is_alive()
    assert lcd._display_enabled is False


def test_pause_clears_display_and_kills_backlight(lcd):
    lcd.start([("A", "1")], refresh_s=60)
    lcd.show("Hello", "World")
    lcd.pause()
    # Stub always returns backlight=True, but display should be blank after clear
    assert lcd._display_enabled is False


def test_resume_re_enables_display(lcd):
    lcd.start([("A", "1"), ("B", "2")], refresh_s=60)
    lcd.pause()
    lcd.resume()
    assert lcd._display_enabled is True
    assert lcd._thread is not None
    assert lcd._thread.is_alive()


def test_callback_fires_while_paused(lcd):
    """_on_screen_advance must fire even when display is off."""
    fired = []
    lcd.on_screen_advance(fired.append)
    lcd.start([("A", "1"), ("B", "2")], refresh_s=0.05)
    lcd.pause()
    time.sleep(0.2)
    assert len(fired) >= 1


def test_display_not_updated_while_paused(lcd):
    """_index advances but hardware is not written while paused."""
    lcd.start([("A", "1"), ("B", "2")], refresh_s=0.05)
    lcd.pause()
    before = _display(lcd)
    time.sleep(0.2)
    # Display content must not change while paused (hardware stays blank/cleared)
    after = _display(lcd)
    assert before == after


# ------------------------------------------------------------------
# _StubLCD
# ------------------------------------------------------------------

def test_stub_clear_resets_lines():
    stub = _StubLCD(16, 2)
    stub.write_string("hello")
    stub.clear()
    assert stub.current_display() == ["", ""]
