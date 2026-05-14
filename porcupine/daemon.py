"""Main event loop — wires monitors to interfaces."""
import argparse
import configparser
import logging
import math
import queue
import signal
import subprocess
import threading
import time

from .interfaces.button import Button
from .interfaces.buzzer import AlertChecker, Buzzer
from .interfaces.lcd import LCD
from .monitors import boot, cpu_mem, gpio_pins, network, power, temperature


# ---------------------------------------------------------------------------
# Custom LCD characters (CGRAM slots 0-3) for the GPIO pin screen
#
# Each bitmap is 8 rows × 5 cols.  Bit 4 is the leftmost pixel.
#   slot 0: Output High — up-arrow, forked shaft  (pin driving high)
#   slot 1: Output Low  — down-arrow, forked shaft (pin driving low)
#   slot 2: Input High  — up-arrow, solid shaft   (pin reading high)
#   slot 3: Input Low   — down-arrow, solid shaft  (pin reading low)
#
# Pixel legend (5-wide):  ..#..=0b00100  .###.=0b01110  #.#.#=0b10101  .#.#.=0b01010
# ---------------------------------------------------------------------------

_CGRAM: list[list[int]] = [
    [0b00100, 0b01110, 0b10101, 0b01010, 0b01010, 0b00100, 0b00000, 0b00000],  # slot 0: out_h
    [0b00000, 0b00000, 0b00100, 0b01010, 0b01010, 0b10101, 0b01110, 0b00100],  # slot 1: out_l
    [0b00100, 0b01110, 0b10101, 0b00100, 0b00100, 0b00100, 0b00000, 0b00000],  # slot 2: in_h
    [0b00000, 0b00000, 0b00100, 0b00100, 0b00100, 0b10101, 0b01110, 0b00100],  # slot 3: in_l
]

# Map gpio_pins state strings → display character
_GPIO_CHARS: dict[str | None, str] = {
    "3v3":   "+",
    "5v":    "^",
    "gnd":   "_",
    "out_h": chr(0),
    "out_l": chr(1),
    "in_h":  chr(2),
    "in_l":  chr(3),
    None:    " ",
}


# ---------------------------------------------------------------------------
# Screen formatters — each returns (line1, line2) for the LCD
# ---------------------------------------------------------------------------

def _fmt_boot(data: dict) -> tuple[str, str]:
    uptime = int(data.get("uptime_s", 0))
    return "Boot", f"#{data.get('boot_count', 0)} {uptime // 3600}h{uptime % 3600 // 60:02d}m"


def _fmt_power(data: dict) -> tuple[str, str]:
    source = data.get("power_source", "Unknown")
    pct = data.get("battery_pct", float("nan"))
    bat_warn = data.get("bat_warn", 40.0)
    if not math.isnan(pct):
        warn = source == "Battery" and pct < bat_warn
        suffix = f" {pct:.0f}%" + (" WARN" if warn else "")
    else:
        suffix = ""
    return "Power", f"{source}{suffix}"


def _fmt_cpu(data: dict) -> tuple[str, str]:
    cpu  = data.get("cpu_avg_pct", 0)
    mem  = data.get("mem_pct", 0)
    cpu_s = "WARN" if cpu >= data.get("cpu_warn", 90.0) else f"{cpu:.0f}%"
    mem_s = "WARN" if mem >= data.get("mem_warn", 90.0) else f"{mem:.0f}%"
    return " CPU   Mem", f"{cpu_s:>4}  {mem_s:>4}"


def _fmt_temp(data: dict) -> tuple[str, str]:
    temp = data.get("cpu_temp_c", float("nan"))
    warn = data.get("temp_warn", 80.0)
    if not math.isnan(temp):
        temp_str = f"{temp:.0f}C" if temp >= 100 else f"{temp:.1f}C"
        suffix = " WARN" if temp >= warn else ""
    else:
        temp_str = "---"
        suffix = ""
    return ("Temperature", f"{temp_str}{suffix}")


def _fmt_net(data: dict) -> tuple[str, str]:
    return (
        f"Net {data.get('interface', '???')[:5]}",
        f"R:{_bps_str(data.get('rx_bps', 0))} T:{_bps_str(data.get('tx_bps', 0))}",
    )


def _fmt_gpio(data: dict) -> list[tuple[str, str]]:
    pins = data.get("gpio_pins", [])
    chars = [_GPIO_CHARS.get(s, " ") for s in pins]
    chars += [" "] * (40 - len(chars))

    def _row(indices: range, first_pin: int, last_pin: int) -> str:
        return f"{first_pin:02d}[{''.join(chars[i] for i in indices)}]{last_pin:02d}"

    return [
        (_row(range( 0, 20, 2),  1, 19), _row(range( 1, 20, 2),  2, 20)),  # pins  1–20
        (_row(range(20, 40, 2), 21, 39), _row(range(21, 40, 2), 22, 40)),  # pins 21–40
    ]


_KB = 1024
_MB = 1024 * 1024


def _bps_str(bps: float) -> str:
    if bps >= _MB:
        mb = bps / _MB
        return f"{mb:.0f}M" if mb >= 100 else f"{mb:.1f}M"
    if bps >= _KB:
        kb = bps / _KB
        return f"{kb:.0f}K" if kb >= 100 else f"{kb:.1f}K"
    return f"{int(bps)}B"


# ---------------------------------------------------------------------------
# Alert → monitor flag mapping and per-alert beep patterns
# ---------------------------------------------------------------------------

_ALERT_TO_FLAG: dict[str, str] = {
    "temp": "temp",
    "cpu":  "cpu",
    "mem":  "cpu",
    "bat":  "power",
}

_ALERT_BEEP: dict[str, dict] = {
    "temp": {"count": 3, "duration_ms": 200, "gap_ms": 100},
    "cpu":  {"count": 2, "duration_ms": 200, "gap_ms": 100},
    "mem":  {"count": 2, "duration_ms": 200, "gap_ms": 100},
    "bat":  {"count": 1, "duration_ms": 600, "gap_ms":   0},
}

# Monitors that can ever have an alert — derived from _ALERT_TO_FLAG values.
# Used by _apply_escalation to skip boot/net/gpio (which have no alert conditions).
_ALERTABLE_FLAGS: frozenset[str] = frozenset(_ALERT_TO_FLAG.values())


# ---------------------------------------------------------------------------
# Monitor registry  (flag name, module, formatter)
# ---------------------------------------------------------------------------

_MONITOR_DEFS = [
    ("boot",  boot,        _fmt_boot),
    ("power", power,       _fmt_power),
    ("cpu",   cpu_mem,     _fmt_cpu),
    ("temp",  temperature, _fmt_temp),
    ("net",   network,     _fmt_net),
    ("gpio",  gpio_pins,   _fmt_gpio),
]


def _read_all(
    args: argparse.Namespace,
    r_cycle: int = 0,
    effective_every: "dict | None" = None,
) -> dict:
    """Call read() on every enabled monitor whose cycle is due and merge results.

    At r_cycle=0 all enabled monitors are read regardless of their every value.
    """
    merged: dict = {}
    for flag, module, _ in _MONITOR_DEFS:
        base_every = getattr(args, f"{flag}_every", 0)
        if base_every <= 0:
            continue
        every = (effective_every or {}).get(flag, base_every)
        if r_cycle % every != 0:
            continue
        try:
            merged.update(module.read())
        except Exception:
            logging.warning("monitor %r read failed", flag, exc_info=True)
    return merged


def _apply_escalation(
    args: argparse.Namespace,
    active_alerts: set[str],
    effective_every: dict,
) -> None:
    """Escalate to every=1 for monitors with active alerts; restore when clear."""
    for flag in _ALERTABLE_FLAGS:
        base_every = getattr(args, f"{flag}_every", 0)
        if base_every <= 0:
            continue
        flag_has_alert = any(_ALERT_TO_FLAG.get(ak) == flag for ak in active_alerts)
        effective_every[flag] = 1 if flag_has_alert else base_every


def _build_screens(args: argparse.Namespace, data: dict, d_cycle: int = 0) -> list[tuple[str, str]]:
    """Build the ordered LCD screen list from the latest monitor snapshot."""
    screens, _ = _build_screens_tagged(args, data, d_cycle=d_cycle)
    return screens


def _with_alert_indicator(
    screens: list[tuple[str, str]], active: bool
) -> list[tuple[str, str]]:
    """Place '!' at column 15 (last char) on every screen's first line when any alert is active."""
    if not active:
        return screens
    return [(f"{line1[:15]:<15}!", line2) for line1, line2 in screens]


def _build_screens_tagged(
    args: argparse.Namespace, data: dict, d_cycle: int = 0
) -> tuple[list[tuple[str, str]], list[str]]:
    """Like _build_screens but also returns a parallel list of monitor flag names.

    The flag name identifies which monitor owns each screen so the alert checker
    can fire only when that monitor's screen is currently displayed.
    d_cycle=0 always includes all enabled monitors (used at startup and in tests).
    """
    data = {**data,
            "temp_warn": getattr(args, "temp_warn", 80.0),
            "cpu_warn":  getattr(args, "cpu_warn",  90.0),
            "mem_warn":  getattr(args, "mem_warn",  90.0),
            "bat_warn":  getattr(args, "bat_warn",  40.0)}
    screens: list[tuple[str, str]] = []
    tags: list[str] = []
    for flag, _, formatter in _MONITOR_DEFS:
        every = getattr(args, f"{flag}_every", 0)
        if every <= 0:
            continue
        if d_cycle % every != 0:
            continue
        result = formatter(data)
        if isinstance(result, list):
            screens.extend(result)
            tags.extend([flag] * len(result))
        else:
            screens.append(result)
            tags.append(flag)
    if not screens:
        return [("No monitors", "enabled")], [""]
    return screens, tags


def _filter_alert_screens(
    screens: list[tuple[str, str]], tags: list[str], active_alerts: set[str]
) -> tuple[list[tuple[str, str]], list[str]]:
    """Return (screens, tags) restricted to monitors with active alerts.

    Falls back to the full list if no match is found (should not happen in practice).
    """
    alert_flags = {_ALERT_TO_FLAG[k] for k in active_alerts if k in _ALERT_TO_FLAG}
    pairs = [(s, t) for s, t in zip(screens, tags) if t in alert_flags]
    if not pairs:
        return screens, tags
    return [s for s, _ in pairs], [t for _, t in pairs]


# ---------------------------------------------------------------------------
# Button controller
# ---------------------------------------------------------------------------

class _ButtonController:
    """
    Button press sequences:
      1. Short press (LCD on)         — start 5-second window; if no follow-up,
                                        turn off LCD backlight (monitoring continues)
      2. Short press (LCD off)        — turn LCD back on
      3. Short + short press (< 5 s)  — 20-second reboot countdown
      4. Short + long press  (< 5 s)  — 20-second shutdown countdown

    During a countdown, a short press cancels it.
    Data collection always continues regardless of LCD state.
    """

    _WINDOW_S    = 5.0
    _COUNTDOWN_S = 20

    def __init__(self, button: Button, lcd: LCD, on_long_idle=None):
        self._lcd    = lcd
        self._lcd_on = True
        # idle | after_first | after_second_start | counting
        self._state  = "idle"
        self._window_timer: threading.Timer | None = None
        self._cancel = threading.Event()
        self._on_long_idle = on_long_idle

        button.on_press_start(self._on_press_down)
        button.on_short_press(self._on_short)
        button.on_long_press(self._on_long)

    @property
    def monitoring(self) -> bool:
        return True  # data collection never stops; only the LCD turns off

    def _on_press_down(self) -> None:
        # Cancel the window as soon as a second press begins so the full
        # long-press duration (2 s) doesn't eat into the follow-up window.
        if self._state == "after_first":
            self._cancel_window()
            self._state = "after_second_start"

    def _on_short(self) -> None:
        if self._state == "idle":
            if not self._lcd_on:
                self._lcd_on = True
                self._lcd.resume()
            else:
                self._state = "after_first"
                self._window_timer = threading.Timer(self._WINDOW_S, self._window_expired)
                self._window_timer.start()
        elif self._state == "after_second_start":
            self._begin_countdown("reboot")
        elif self._state == "counting":
            self._cancel.set()

    def _on_long(self) -> None:
        if self._state == "after_second_start":
            self._begin_countdown("shutdown")
        elif self._state == "idle" and self._on_long_idle:
            self._on_long_idle()

    def set_lcd_on(self, state: bool) -> None:
        """Sync LCD on/off from external code (e.g. only_alert logic) without disturbing FSM state."""
        if state == self._lcd_on:
            return
        self._lcd_on = state
        if state:
            self._lcd.resume()
        else:
            self._lcd.pause()

    def _window_expired(self) -> None:
        self._lcd_on = False
        self._lcd.pause()
        self._state = "idle"

    def _cancel_window(self) -> None:
        if self._window_timer is not None:
            self._window_timer.cancel()
            self._window_timer = None

    def _begin_countdown(self, action: str) -> None:
        self._state = "counting"
        if not self._lcd_on:
            self._lcd_on = True
            self._lcd.resume()
        self._cancel.clear()
        line1 = "Rebooting..." if action == "reboot" else "Shutdown"
        self._lcd.enter_menu(line1, f"{self._COUNTDOWN_S}s  Press:cancel")
        threading.Thread(
            target=self._countdown_loop, args=(action, line1), daemon=True
        ).start()

    def _countdown_loop(self, action: str, line1: str) -> None:
        for remaining in range(self._COUNTDOWN_S - 1, -1, -1):
            if self._cancel.wait(timeout=1.0):
                self._lcd.update_menu("Cancelled", "")
                time.sleep(1.5)
                self._lcd.exit_menu()
                self._state = "idle"
                return
            self._lcd.update_menu(line1, f"{remaining}s  Press:cancel")
        if action == "reboot":
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    enabled = [f for f, _, _ in _MONITOR_DEFS if getattr(args, f"{f}_every", 0) > 0]
    if not enabled:
        logging.warning("No monitors enabled — exiting. Re-enable with: sudo porcupine enable <monitor>")
        return

    def _on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)

    boot.init()
    power.init(addr=args.ina219_addr)

    lcd    = LCD(i2c_addr=args.lcd_addr, cols=16, rows=2)
    lcd.load_custom_chars(_CGRAM)
    button = Button(pin=args.button_pin, long_press_ms=2000)
    buzzer = Buzzer(pin=args.buzzer_pin)
    alert  = AlertChecker(
        temp_warn=args.temp_warn,
        cpu_warn=args.cpu_warn,
        mem_warn=args.mem_warn,
        bat_warn=args.bat_warn,
        temp_enabled=args.temp_every > 0,
        cpu_enabled=args.cpu_every > 0,
        bat_enabled=args.power_every > 0,
    )

    # Persistent worker thread — GPIO callbacks just enqueue; no thread-spawn
    # overhead per beep (which caused the ~80 ms press-start beep to be missed).
    _beep_q: queue.Queue = queue.Queue()

    def _beep_worker() -> None:
        while True:
            item = _beep_q.get()
            if item is None:
                break
            buzzer.beep(**item)

    _beep_thread = threading.Thread(target=_beep_worker, daemon=True)
    _beep_thread.start()

    def _beep_async(count: int, duration_ms: int, gap_ms: int = 0) -> None:
        _beep_q.put({"count": count, "duration_ms": duration_ms, "gap_ms": gap_ms})

    def _beep_alerts(alert_keys: set[str]) -> None:
        for alert_key in sorted(alert_keys):
            beep_kwargs = _ALERT_BEEP.get(alert_key)
            if beep_kwargs:
                _beep_async(**beep_kwargs)

    # Two-counter escalation state
    r_cycle = 0
    d_cycle = 0           # increments each time the LCD completes a full rotation
    _lcd_wrapped = threading.Event()
    effective_every: dict = {
        flag: getattr(args, f"{flag}_every", 0)
        for flag, _, _ in _MONITOR_DEFS
    }
    active_alerts: set[str] = set()
    _current_tags: list[str] = []
    _state_lock = threading.Lock()

    def _on_screen_advance(index: int) -> None:
        # Called by the LCD thread each time a new screen is rendered.
        # Signal a full-rotation wrap so the main loop can increment d_cycle.
        # Beep only when the screen just shown belongs to a monitor with an active alert.
        if index == 0:
            _lcd_wrapped.set()
        with _state_lock:
            alerts_snapshot = set(active_alerts)
            tags_snapshot = list(_current_tags)
        if not alerts_snapshot or index >= len(tags_snapshot):
            return
        screen_flag = tags_snapshot[index]
        for alert_key in sorted(alerts_snapshot):
            if _ALERT_TO_FLAG.get(alert_key) == screen_flag:
                beep_kwargs = _ALERT_BEEP.get(alert_key)
                if beep_kwargs:
                    _beep_async(**beep_kwargs)

    lcd.on_screen_advance(_on_screen_advance)

    _only_alert = getattr(args, "only_alert", False)
    _alert_lcd_on = False

    last_data: dict = _read_all(args, r_cycle=0, effective_every=effective_every)
    initial_alerts = alert.check(last_data)
    _apply_escalation(args, initial_alerts, effective_every)
    _beep_alerts(initial_alerts)
    screens, tags = _build_screens_tagged(args, last_data, d_cycle=0)
    if _only_alert and initial_alerts:
        screens, tags = _filter_alert_screens(screens, tags, initial_alerts)
        _alert_lcd_on = True
    with _state_lock:
        active_alerts = initial_alerts
        _current_tags = tags
    lcd.start(_with_alert_indicator(screens, bool(initial_alerts)), refresh_s=args.refresh)

    def _toggle_only_alert() -> None:
        cp = configparser.ConfigParser()
        cp.read(args.config)
        current = cp.getboolean("display", "only_alert", fallback=False)
        if not cp.has_section("display"):
            cp.add_section("display")
        cp.set("display", "only_alert", "false" if current else "true")
        with open(args.config, "w") as f:
            cp.write(f)
        label = "OFF" if current else "ON"
        lcd.enter_menu("Only Alert", label)
        time.sleep(1.5)
        subprocess.run(["systemctl", "restart", "porcupine"], check=False)

    controller = _ButtonController(button, lcd, on_long_idle=_toggle_only_alert)
    if _only_alert and not initial_alerts:
        controller.set_lcd_on(False)

    # Short beep on every press-down — immediate feedback that the press registered.
    button.on_press_start(lambda: _beep_async(count=1, duration_ms=150))
    # Long beep when held past the threshold — cues the user to release for long press.
    button.on_held(lambda: _beep_async(count=1, duration_ms=400))

    button.start()
    _beep_async(count=1, duration_ms=150)

    try:
        while True:
            time.sleep(args.refresh)
            r_cycle += 1

            wrapped = _lcd_wrapped.is_set()
            if wrapped:
                _lcd_wrapped.clear()
                d_cycle += 1

            data = _read_all(args, r_cycle=r_cycle, effective_every=effective_every)
            if not data and not wrapped:
                continue
            if data:
                last_data = {**last_data, **data}

            new_alerts = alert.check(last_data)
            _apply_escalation(args, new_alerts, effective_every)

            screens, tags = _build_screens_tagged(args, last_data, d_cycle=d_cycle)
            if _only_alert and new_alerts:
                display_screens, display_tags = _filter_alert_screens(screens, tags, new_alerts)
            else:
                display_screens, display_tags = screens, tags

            with _state_lock:
                prev_alerts = set(active_alerts)
                active_alerts = new_alerts
                _current_tags = display_tags

            _beep_alerts(new_alerts - prev_alerts)

            if _only_alert:
                if new_alerts:
                    lcd.update_screens(_with_alert_indicator(display_screens, True))
                    if not _alert_lcd_on:
                        controller.set_lcd_on(True)
                        _alert_lcd_on = True
                elif _alert_lcd_on:
                    controller.set_lcd_on(False)
                    _alert_lcd_on = False
            elif controller.monitoring:
                lcd.update_screens(_with_alert_indicator(display_screens, bool(new_alerts)))
    except KeyboardInterrupt:
        pass
    finally:
        buzzer.beep(count=1, duration_ms=150)
        _beep_q.put(None)  # signal worker to exit
        button.stop()
        lcd.stop()
        buzzer.cleanup()
