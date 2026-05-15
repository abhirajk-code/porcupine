"""Unit tests for ButtonController (interfaces/button_controller.py)."""
from unittest.mock import MagicMock, patch


from porcupine.interfaces.button_controller import ButtonController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_controller():
    """Return (controller, button_mock, lcd_mock) with callbacks wired."""
    button = MagicMock()
    lcd    = MagicMock()

    # Capture the callbacks registered via button.on_*
    cbs: dict = {}
    def _on_press_start(cb): cbs["press_start"] = cb
    def _on_short_press(cb): cbs["short"]       = cb
    def _on_long_press(cb):  cbs["long"]        = cb

    button.on_press_start.side_effect = _on_press_start
    button.on_short_press.side_effect = _on_short_press
    button.on_long_press.side_effect  = _on_long_press

    ctrl = ButtonController(button, lcd)
    return ctrl, cbs, lcd


def _short(cbs):
    """Simulate a short press (press-down then short-release)."""
    if "press_start" in cbs:
        cbs["press_start"]()
    cbs["short"]()


def _long(cbs):
    """Simulate a long press (press-down then long-release)."""
    if "press_start" in cbs:
        cbs["press_start"]()
    cbs["long"]()


# ---------------------------------------------------------------------------
# monitoring property
# ---------------------------------------------------------------------------

def test_monitoring_always_true():
    ctrl, cbs, lcd = _make_controller()
    assert ctrl.monitoring is True
    _short(cbs)  # press once
    assert ctrl.monitoring is True


# ---------------------------------------------------------------------------
# Short press with LCD on — starts 5-second window, doesn't touch LCD yet
# ---------------------------------------------------------------------------

def test_short_press_does_not_immediately_pause_lcd():
    ctrl, cbs, lcd = _make_controller()
    with patch.object(ctrl, "_window_timer") as _:
        _short(cbs)
    lcd.pause.assert_not_called()
    lcd.resume.assert_not_called()


def test_short_press_starts_window_timer():
    ctrl, cbs, lcd = _make_controller()
    with patch("porcupine.interfaces.button_controller.threading.Timer") as MockTimer:
        mock_timer = MagicMock()
        MockTimer.return_value = mock_timer
        _short(cbs)
    MockTimer.assert_called_once_with(5.0, ctrl._window_expired)
    mock_timer.start.assert_called_once()


def test_window_expired_pauses_lcd_and_returns_to_idle():
    ctrl, cbs, lcd = _make_controller()
    ctrl._window_expired()
    lcd.pause.assert_called_once()
    assert ctrl._state == "idle"
    assert ctrl._lcd_on is False


# ---------------------------------------------------------------------------
# Short press with LCD off — turns LCD back on
# ---------------------------------------------------------------------------

def test_short_press_when_lcd_off_resumes_lcd():
    ctrl, cbs, lcd = _make_controller()
    ctrl._lcd_on = False
    ctrl._state  = "idle"
    _short(cbs)
    lcd.resume.assert_called_once()
    assert ctrl._lcd_on is True


def test_short_press_when_lcd_off_does_not_start_window():
    ctrl, cbs, lcd = _make_controller()
    ctrl._lcd_on = False
    ctrl._state  = "idle"
    with patch("porcupine.interfaces.button_controller.threading.Timer") as MockTimer:
        _short(cbs)
    MockTimer.assert_not_called()


# ---------------------------------------------------------------------------
# Short + short → reboot countdown
# ---------------------------------------------------------------------------

def test_short_short_starts_reboot_countdown():
    ctrl, cbs, lcd = _make_controller()
    with patch("porcupine.interfaces.button_controller.threading.Timer") as MockTimer:
        MockTimer.return_value = MagicMock()
        _short(cbs)           # first press — opens window
    with patch("porcupine.interfaces.button_controller.threading.Thread") as MockThread:
        MockThread.return_value = MagicMock()
        _short(cbs)           # second short — reboot
    lcd.enter_menu.assert_called_once()
    assert "Reboot" in lcd.enter_menu.call_args[0][0]


# ---------------------------------------------------------------------------
# Short + long → shutdown countdown
# ---------------------------------------------------------------------------

def test_short_long_starts_shutdown_countdown():
    ctrl, cbs, lcd = _make_controller()
    with patch("porcupine.interfaces.button_controller.threading.Timer") as MockTimer:
        MockTimer.return_value = MagicMock()
        _short(cbs)           # first press — opens window
    with patch("porcupine.interfaces.button_controller.threading.Thread") as MockThread:
        MockThread.return_value = MagicMock()
        _long(cbs)            # long press — shutdown
    lcd.enter_menu.assert_called_once()
    assert "Shutdown" in lcd.enter_menu.call_args[0][0]


# ---------------------------------------------------------------------------
# Countdown resumes LCD if it was off
# ---------------------------------------------------------------------------

def test_countdown_resumes_lcd_when_off():
    ctrl, cbs, lcd = _make_controller()
    ctrl._lcd_on = False
    ctrl._state  = "after_second_start"
    with patch("porcupine.interfaces.button_controller.threading.Thread") as MockThread:
        MockThread.return_value = MagicMock()
        _short(cbs)           # second short → reboot while LCD is off
    lcd.resume.assert_called_once()
    assert ctrl._lcd_on is True


# ---------------------------------------------------------------------------
# Countdown cancel via short press
# ---------------------------------------------------------------------------

def test_short_press_during_countdown_cancels():
    ctrl, cbs, lcd = _make_controller()
    ctrl._state = "counting"
    ctrl._cancel.clear()
    _short(cbs)
    assert ctrl._cancel.is_set()


# ---------------------------------------------------------------------------
# Window cancelled by second press-down (press_start callback)
# ---------------------------------------------------------------------------

def test_second_press_down_cancels_window_timer():
    ctrl, cbs, lcd = _make_controller()
    mock_timer = MagicMock()
    ctrl._window_timer = mock_timer
    ctrl._state = "after_first"
    cbs["press_start"]()   # second press begins
    mock_timer.cancel.assert_called_once()
    assert ctrl._state == "after_second_start"


# ---------------------------------------------------------------------------
# set_lcd_on — external sync (used by only_alert logic)
# ---------------------------------------------------------------------------

def test_set_lcd_on_true_resumes_when_off():
    ctrl, cbs, lcd = _make_controller()
    ctrl._lcd_on = False
    ctrl.set_lcd_on(True)
    lcd.resume.assert_called_once()
    assert ctrl._lcd_on is True


def test_set_lcd_on_false_pauses_when_on():
    ctrl, cbs, lcd = _make_controller()
    ctrl._lcd_on = True
    ctrl.set_lcd_on(False)
    lcd.pause.assert_called_once()
    assert ctrl._lcd_on is False


def test_set_lcd_on_no_op_when_already_matches():
    ctrl, cbs, lcd = _make_controller()
    ctrl._lcd_on = True
    ctrl.set_lcd_on(True)   # already on — no LCD call
    lcd.resume.assert_not_called()
    lcd.pause.assert_not_called()

    ctrl._lcd_on = False
    ctrl.set_lcd_on(False)  # already off — no LCD call
    lcd.resume.assert_not_called()
    lcd.pause.assert_not_called()


def test_set_lcd_on_does_not_change_fsm_state():
    ctrl, cbs, lcd = _make_controller()
    ctrl._state = "after_first"
    ctrl._lcd_on = False
    ctrl.set_lcd_on(True)
    assert ctrl._state == "after_first"   # FSM untouched
