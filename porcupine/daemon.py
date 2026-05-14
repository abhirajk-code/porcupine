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
from .interfaces.buzzer import Buzzer
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


def _is_valid(value: object) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


# ---------------------------------------------------------------------------
# Monitor objects — own reading, formatting, breach detection, and beep pattern
# ---------------------------------------------------------------------------

class _Monitor:
    """Per-feature monitor with a uniform interface for the orchestrator."""
    flag: str
    every: int = 0  # set by _make_monitors; 0 = disabled

    def read(self) -> dict:
        raise NotImplementedError

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        raise NotImplementedError

    def has_breach(self, data: dict) -> bool:
        return False

    def beep_pattern(self) -> dict | None:
        return None


class _BootMonitor(_Monitor):
    flag = "boot"

    def read(self) -> dict:
        return boot.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        return [_fmt_boot(data)]


class _PowerMonitor(_Monitor):
    flag = "power"

    def __init__(self, bat_warn: float = 40.0):
        self._bat_warn = bat_warn

    def read(self) -> dict:
        return power.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        return [_fmt_power({**data, "bat_warn": self._bat_warn})]

    def has_breach(self, data: dict) -> bool:
        pct = data.get("battery_pct")
        return (
            _is_valid(pct)
            and data.get("power_source") == "Battery"
            and pct < self._bat_warn
        )

    def beep_pattern(self) -> dict:
        return {"count": 1, "duration_ms": 600, "gap_ms": 0}


class _CpuMemMonitor(_Monitor):
    flag = "cpu"

    def __init__(self, cpu_warn: float = 90.0, mem_warn: float = 90.0):
        self._cpu_warn = cpu_warn
        self._mem_warn = mem_warn

    def read(self) -> dict:
        return cpu_mem.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        return [_fmt_cpu({**data, "cpu_warn": self._cpu_warn, "mem_warn": self._mem_warn})]

    def has_breach(self, data: dict) -> bool:
        cpu = data.get("cpu_avg_pct")
        mem = data.get("mem_pct")
        return (
            (_is_valid(cpu) and cpu >= self._cpu_warn)
            or (_is_valid(mem) and mem >= self._mem_warn)
        )

    def beep_pattern(self) -> dict:
        return {"count": 2, "duration_ms": 200, "gap_ms": 100}


class _TempMonitor(_Monitor):
    flag = "temp"

    def __init__(self, temp_warn: float = 80.0):
        self._temp_warn = temp_warn

    def read(self) -> dict:
        return temperature.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        return [_fmt_temp({**data, "temp_warn": self._temp_warn})]

    def has_breach(self, data: dict) -> bool:
        temp = data.get("cpu_temp_c")
        return _is_valid(temp) and temp >= self._temp_warn

    def beep_pattern(self) -> dict:
        return {"count": 3, "duration_ms": 200, "gap_ms": 100}


class _NetMonitor(_Monitor):
    flag = "net"

    def read(self) -> dict:
        return network.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        return [_fmt_net(data)]


class _GpioMonitor(_Monitor):
    flag = "gpio"

    def read(self) -> dict:
        return gpio_pins.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        return _fmt_gpio(data)


def _make_monitors(args: argparse.Namespace) -> list[_Monitor]:
    """Create and return enabled Monitor instances, in display order."""
    candidates: list[_Monitor] = [
        _BootMonitor(),
        _PowerMonitor(bat_warn=args.bat_warn),
        _CpuMemMonitor(cpu_warn=args.cpu_warn, mem_warn=args.mem_warn),
        _TempMonitor(temp_warn=args.temp_warn),
        _NetMonitor(),
        _GpioMonitor(),
    ]
    monitors = []
    for m in candidates:
        m.every = getattr(args, f"{m.flag}_every", 0)
        if m.every > 0:
            monitors.append(m)
    return monitors


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _read_all(
    monitors: list[_Monitor],
    r_cycle: int = 0,
    effective_every: "dict | None" = None,
) -> dict:
    """Call read() on every monitor whose cycle is due and merge results.

    At r_cycle=0 all monitors are read regardless of their every value.
    """
    merged: dict = {}
    for m in monitors:
        every = (effective_every or {}).get(m.flag, m.every)
        if r_cycle % every != 0:
            continue
        try:
            merged.update(m.read())
        except Exception:
            logging.warning("monitor %r read failed", m.flag, exc_info=True)
    return merged


def _apply_escalation(
    monitors: list[_Monitor],
    breached: set[str],
    effective_every: dict,
) -> None:
    """Escalate to every=1 for alertable monitors with active breaches; restore when clear."""
    for m in monitors:
        if m.beep_pattern() is None:
            continue
        effective_every[m.flag] = 1 if m.flag in breached else m.every


def _build_screens(
    monitors: list[_Monitor], data: dict, d_cycle: int = 0
) -> list[tuple[str, str]]:
    """Build the ordered LCD screen list from the latest monitor snapshot."""
    screens, _ = _build_screens_tagged(monitors, data, d_cycle=d_cycle)
    return screens


def _with_alert_indicator(
    screens: list[tuple[str, str]], active: bool
) -> list[tuple[str, str]]:
    """Place '!' at column 15 (last char) on every screen's first line when any alert is active."""
    if not active:
        return screens
    return [(f"{line1[:15]:<15}!", line2) for line1, line2 in screens]


def _build_screens_tagged(
    monitors: list[_Monitor], data: dict, d_cycle: int = 0
) -> tuple[list[tuple[str, str]], list[str]]:
    """Like _build_screens but also returns a parallel list of monitor flag names.

    d_cycle=0 always includes all enabled monitors (used at startup and in tests).
    """
    screens: list[tuple[str, str]] = []
    tags: list[str] = []
    for m in monitors:
        if d_cycle % m.every != 0:
            continue
        result = m.format_screens(data)
        screens.extend(result)
        tags.extend([m.flag] * len(result))
    if not screens:
        return [("No monitors", "enabled")], [""]
    return screens, tags


def _filter_alert_screens(
    screens: list[tuple[str, str]], tags: list[str], breached: set[str]
) -> tuple[list[tuple[str, str]], list[str]]:
    """Return (screens, tags) restricted to monitors with active breaches.

    Falls back to the full list if no match is found (should not happen in practice).
    """
    pairs = [(s, t) for s, t in zip(screens, tags) if t in breached]
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
# Notifier — owns display + buzzer decisions
# ---------------------------------------------------------------------------

class _Notifier:
    """
    Decides what to show on the LCD and when to beep, based on monitor breaches
    and the only_alert / LCD-on state.  The orchestrator calls update() each
    cycle; the LCD thread calls on_screen_advance() asynchronously.
    """

    def __init__(
        self,
        lcd: LCD,
        beep_async,
        controller: _ButtonController,
        only_alert: bool,
    ):
        self._lcd          = lcd
        self._beep_async   = beep_async
        self._controller   = controller
        self._only_alert   = only_alert
        self._alert_lcd_on = False
        self._lcd_wrapped  = threading.Event()
        self._lock         = threading.Lock()
        # State shared with the LCD thread via on_screen_advance
        self._breached: set[str]               = set()
        self._tags: list[str]                  = []
        self._beep_patterns: dict[str, dict | None] = {}

    def consume_wrap(self) -> bool:
        """Return True (and reset) if the LCD completed a full rotation since last call."""
        if self._lcd_wrapped.is_set():
            self._lcd_wrapped.clear()
            return True
        return False

    def on_screen_advance(self, index: int) -> None:
        """Called by the LCD thread each time a new screen is rendered."""
        if index == 0:
            self._lcd_wrapped.set()
        with self._lock:
            breached = set(self._breached)
            tags     = list(self._tags)
            patterns = dict(self._beep_patterns)
        if not breached or index >= len(tags):
            return
        flag = tags[index]
        if flag in breached:
            pattern = patterns.get(flag)
            if pattern:
                self._beep_async(**pattern)

    def start(
        self,
        monitors: list[_Monitor],
        data: dict,
        breached: set[str],
        refresh_s: float,
    ) -> None:
        """Build initial screens, start LCD cycling, and beep any initial breaches."""
        screens, tags = _build_screens_tagged(monitors, data, d_cycle=0)
        patterns = {m.flag: m.beep_pattern() for m in monitors if m.flag in breached}
        if self._only_alert and breached:
            display_screens, display_tags = _filter_alert_screens(screens, tags, breached)
        else:
            display_screens, display_tags = screens, tags
        with self._lock:
            self._breached      = breached
            self._tags          = display_tags
            self._beep_patterns = patterns
        self._lcd.start(
            _with_alert_indicator(display_screens, bool(breached)), refresh_s=refresh_s
        )
        if self._only_alert and not breached:
            self._controller.set_lcd_on(False)
        for flag in sorted(breached):
            pattern = patterns.get(flag)
            if pattern:
                self._beep_async(**pattern)

    def update(
        self,
        monitors: list[_Monitor],
        data: dict,
        new_breached: set[str],
        d_cycle: int,
    ) -> None:
        """Refresh screens and beep any monitors that newly crossed their threshold."""
        screens, tags = _build_screens_tagged(monitors, data, d_cycle=d_cycle)
        patterns = {m.flag: m.beep_pattern() for m in monitors if m.flag in new_breached}
        if self._only_alert and new_breached:
            display_screens, display_tags = _filter_alert_screens(screens, tags, new_breached)
        else:
            display_screens, display_tags = screens, tags

        # Beep for monitors that just crossed threshold (before updating self._breached)
        for flag in sorted(new_breached - self._breached):
            pattern = patterns.get(flag)
            if pattern:
                self._beep_async(**pattern)

        with self._lock:
            self._breached      = new_breached
            self._tags          = display_tags
            self._beep_patterns = patterns

        if self._only_alert:
            if new_breached:
                self._lcd.update_screens(_with_alert_indicator(display_screens, True))
                if not self._alert_lcd_on:
                    self._controller.set_lcd_on(True)
                    self._alert_lcd_on = True
            elif self._alert_lcd_on:
                self._controller.set_lcd_on(False)
                self._alert_lcd_on = False
        else:
            self._lcd.update_screens(
                _with_alert_indicator(display_screens, bool(new_breached))
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    monitors = _make_monitors(args)
    if not monitors:
        logging.warning(
            "No monitors enabled — exiting. Re-enable with: sudo porcupine enable <monitor>"
        )
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

    _beep_q: queue.Queue = queue.Queue()

    def _beep_worker() -> None:
        while True:
            item = _beep_q.get()
            if item is None:
                break
            buzzer.beep(**item)

    threading.Thread(target=_beep_worker, daemon=True).start()

    def _beep_async(**kwargs) -> None:
        _beep_q.put(kwargs)

    effective_every: dict = {m.flag: m.every for m in monitors}

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
    button.on_press_start(lambda: _beep_async(count=1, duration_ms=150, gap_ms=0))
    button.on_held(lambda: _beep_async(count=1, duration_ms=400, gap_ms=0))

    notifier = _Notifier(
        lcd, _beep_async, controller,
        only_alert=getattr(args, "only_alert", False),
    )
    lcd.on_screen_advance(notifier.on_screen_advance)

    last_data = _read_all(monitors, r_cycle=0, effective_every=effective_every)
    initial_breached = {m.flag for m in monitors if m.has_breach(last_data)}
    _apply_escalation(monitors, initial_breached, effective_every)
    notifier.start(monitors, last_data, initial_breached, refresh_s=args.refresh)

    button.start()
    _beep_async(count=1, duration_ms=150, gap_ms=0)

    r_cycle = 0
    d_cycle = 0

    try:
        while True:
            time.sleep(args.refresh)
            r_cycle += 1

            wrapped = notifier.consume_wrap()
            if wrapped:
                d_cycle += 1

            data = _read_all(monitors, r_cycle=r_cycle, effective_every=effective_every)
            if not data and not wrapped:
                continue
            if data:
                last_data = {**last_data, **data}

            breached = {m.flag for m in monitors if m.has_breach(last_data)}
            _apply_escalation(monitors, breached, effective_every)
            notifier.update(monitors, last_data, breached, d_cycle)

    except KeyboardInterrupt:
        pass
    finally:
        buzzer.beep(count=1, duration_ms=150)
        _beep_q.put(None)
        button.stop()
        lcd.stop()
        buzzer.cleanup()
