"""Main event loop — wires monitors to interfaces."""
import argparse
import configparser
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .interfaces.button import Button
from .interfaces.button_controller import ButtonController
from .interfaces.buzzer import Buzzer
from .interfaces.lcd import LCD
from .monitors import boot, connectivity, cpu_mem, power, wifi  # noqa: F401 (tests patch via daemon.X.read/init)
from .monitors.base import _Monitor
from .monitors.boot_monitor import _BootMonitor
from .monitors.connectivity_monitor import _ConnectivityMonitor
from .monitors.cpu_mem_monitor import _CpuMemMonitor
from .monitors.disk_monitor import _DiskMonitor
from .monitors.gpio_monitor import _GpioMonitor
from .monitors.network_monitor import _NetMonitor, _bps_str  # noqa: F401 (tests access daemon._bps_str)
from .monitors.power_monitor import _PowerMonitor
from .monitors.temperature_monitor import _TempMonitor
from .monitors.wifi_monitor import _WifiMonitor


# ---------------------------------------------------------------------------
# Custom LCD characters (CGRAM slots 0-5) for the GPIO pin screen, lock, and alert indicator
#
# Each bitmap is 8 rows × 5 cols.  Bit 4 is the leftmost pixel.
#   slot 0: Output High — open diamond head (top), Y-fork shaft (pin driving high)
#   slot 1: Output Low  — Y-fork shaft, open diamond head (bottom) (pin driving low)
#   slot 2: Input High  — open diamond head (top), solid shaft    (pin reading high)
#   slot 3: Input Low   — solid shaft, open diamond head (bottom) (pin reading low)
#   slot 4: Lock        — padlock icon shown at col 15 when screen is frozen
#   slot 5: Warning     — triangle with embedded ! shown at col 15 on any active alert
#
# Pixel legend (5-wide):  ..#..=0b00100  .#.#.=0b01010  #...#=0b10001  #.#.#=0b10101
# ---------------------------------------------------------------------------

_CGRAM: list[list[int]] = [
    [0b00100, 0b01010, 0b10001, 0b00000, 0b00100, 0b01010, 0b01010, 0b00100],  # slot 0: out_h
    [0b00100, 0b01010, 0b01010, 0b00100, 0b00000, 0b10001, 0b01010, 0b00100],  # slot 1: out_l
    [0b00100, 0b01010, 0b10001, 0b00000, 0b00100, 0b00100, 0b00100, 0b00100],  # slot 2: in_h
    [0b00100, 0b00100, 0b00100, 0b00100, 0b00000, 0b10001, 0b01010, 0b00100],  # slot 3: in_l
    [0b01110, 0b10001, 0b10001, 0b11111, 0b11011, 0b11011, 0b11111, 0b00000],  # slot 4: lock
    [0b00000, 0b01110, 0b11011, 0b11011, 0b11111, 0b11011, 0b01110, 0b00000],  # slot 5: warn
]


def _make_monitors(args: argparse.Namespace) -> list[_Monitor]:
    """Create and return enabled Monitor instances, in display order."""
    def _e(flag: str) -> int:
        return getattr(args, f"{flag}_every", 0)

    candidates: list[_Monitor] = [
        _BootMonitor(every=_e("boot")),
        _PowerMonitor(bat_warn=args.bat_warn, every=_e("power")),
        _CpuMemMonitor(cpu_warn=args.cpu_warn, mem_warn=args.mem_warn, every=_e("cpu")),
        _TempMonitor(temp_warn=args.temp_warn, every=_e("temp")),
        _NetMonitor(every=_e("net")),
        _GpioMonitor(page=1, every=_e("gpio")),
        _GpioMonitor(page=2, every=_e("gpio")),
        _DiskMonitor(disk_warn=args.disk_warn, every=_e("disk")),
        _ConnectivityMonitor(host=args.conn_host, every=_e("conn")),
        _WifiMonitor(every=_e("wifi")),
    ]
    return [m for m in candidates if m.every > 0]


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _read_all(monitors: list[_Monitor], r_cycle: int = 0) -> dict:
    """Call read() on every monitor whose cycle is due and merge results.

    At r_cycle=0 all monitors are read regardless of their every value.
    """
    merged: dict = {}
    for m in monitors:
        if r_cycle % m.effective_every != 0:
            continue
        try:
            merged.update(m.read())
        except Exception:
            logging.warning("monitor %r read failed", m.flag, exc_info=True)
    return merged


def _apply_escalation(monitors: list[_Monitor], breached: set[str]) -> None:
    """Escalate to every=1 for alertable monitors with active breaches; restore when clear."""
    for m in monitors:
        if m.beep_pattern() is None:
            continue
        m._escalated = m.flag in breached


def _build_screens(
    monitors: list[_Monitor], data: dict, d_cycle: int = 0
) -> list[tuple[str, str]]:
    """Build the ordered LCD screen list from the latest monitor snapshot."""
    screens, _ = _build_screens_tagged(monitors, data, d_cycle=d_cycle)
    return screens


def _with_alert_indicator(
    screens: list[tuple[str, str]], active: bool
) -> list[tuple[str, str]]:
    """Place warning triangle (CGRAM slot 5) at column 15 on every screen's first line when any alert is active."""
    if not active:
        return screens
    return [(f"{line1[:15]:<15}{chr(5)}", line2) for line1, line2 in screens]


def _build_screens_tagged(
    monitors: list[_Monitor], data: dict, d_cycle: int = 0,
    breached: set[str] | None = None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Like _build_screens but also returns a parallel list of monitor flag names.

    d_cycle=0 always includes all enabled monitors (used at startup and in tests).
    Breached monitors are always included regardless of their d_cycle cadence.
    """
    screens: list[tuple[str, str]] = []
    tags: list[str] = []
    for m in monitors:
        if d_cycle % m.effective_every != 0 and m.flag not in (breached or set()):
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
        buzzer: Buzzer,
        controller: ButtonController,
        only_alert: bool,
        alert_log: str | None = None,
    ) -> None:
        self._lcd: LCD                  = lcd
        self._buzzer: Buzzer            = buzzer
        self._controller: ButtonController = controller
        self._only_alert: bool          = only_alert
        self._alert_log: str | None     = alert_log
        self._alert_lcd_on: bool        = False
        self._lcd_wrapped: threading.Event = threading.Event()
        self._lock: threading.Lock      = threading.Lock()
        # State shared with the LCD thread via on_screen_advance
        self._breached: set[str]               = set()
        self._tags: list[str]                  = []
        self._beep_patterns: dict[str, dict | None] = {}

    def _log(self, flag: str, event: str) -> None:
        if not self._alert_log:
            return
        try:
            path = Path(self._alert_log)
            path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with path.open("a") as f:
                f.write(f"{ts} {event:<6} {flag}\n")
        except Exception:
            logging.warning("failed to write alert log", exc_info=True)

    def _log_transitions(
        self,
        old_breached: set[str],
        new_breached: set[str],
        patterns: dict[str, dict | None],
    ) -> None:
        """Beep and log monitors that newly breached; log those that cleared."""
        for flag in sorted(new_breached - old_breached):
            self._log(flag, "BREACH")
            pattern = patterns.get(flag)
            if pattern:
                self._buzzer.beep_async(**pattern)
        for flag in sorted(old_breached - new_breached):
            self._log(flag, "CLEAR")

    def consume_wrap(self) -> bool:
        """Return True (and reset) if the LCD completed a full rotation since last call."""
        if self._lcd_wrapped.is_set():
            self._lcd_wrapped.clear()
            return True
        return False

    def on_screen_advance(self, index: int) -> None:
        """Called by the LCD thread each time a new screen is rendered."""
        if index == 0 and not self._lcd.frozen:
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
                self._buzzer.beep_async(**pattern)

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
        self._log_transitions(set(), breached, patterns)

    def update(
        self,
        monitors: list[_Monitor],
        data: dict,
        new_breached: set[str],
        d_cycle: int,
        *,
        wrapped: bool = False,
    ) -> None:
        """Refresh screens and beep any monitors that newly crossed their threshold."""
        screens, tags = _build_screens_tagged(monitors, data, d_cycle=d_cycle, breached=new_breached)
        patterns = {m.flag: m.beep_pattern() for m in monitors if m.flag in new_breached}
        alert_mode_active = self._only_alert and bool(new_breached)
        if alert_mode_active:
            display_screens, display_tags = _filter_alert_screens(screens, tags, new_breached)
        else:
            display_screens, display_tags = screens, tags

        self._log_transitions(self._breached, new_breached, patterns)

        with self._lock:
            self._breached      = new_breached
            self._tags          = display_tags
            self._beep_patterns = patterns

        if self._only_alert:
            if alert_mode_active:
                self._lcd.update_screens(
                    _with_alert_indicator(display_screens, True),
                    reset_position=wrapped,
                )
                if not self._alert_lcd_on:
                    self._controller.set_lcd_on(True)
                    self._alert_lcd_on = True
            elif self._alert_lcd_on:
                self._controller.set_lcd_on(False)
                self._alert_lcd_on = False
        else:
            self._lcd.update_screens(
                _with_alert_indicator(display_screens, bool(new_breached)),
                reset_position=wrapped,
            )
        # A single-screen rotation fires on_screen_advance(0) every tick, so
        # an extra wrap event can land in the gap between consume_wrap() and
        # this update_screens call.  Clearing it here prevents the next
        # d_cycle from being entered prematurely (which would skip gpio_p2).
        if wrapped:
            self._lcd_wrapped.clear()


# ---------------------------------------------------------------------------
# Startup WiFi splash
# ---------------------------------------------------------------------------

def _wifi_startup(lcd: LCD) -> None:
    """Show the WiFi screen before the main loop starts.

    If no WiFi hardware is detected, shows the screen once and returns.
    Otherwise polls every 5 s for up to 60 s waiting for an IP address.
    Once connected, displays the screen for 20 s then hands off to the
    regular monitoring cycle. If 60 s elapses without a connection the
    startup block exits and regular monitoring begins regardless.
    """
    m = _WifiMonitor()
    data = wifi.read()

    if data.get("wifi_iface") is None:
        header, line2 = m.format_screens(data)[0]
        lcd.show(header, line2)
        return

    t_start = time.monotonic()
    t_max   = t_start + 60

    while True:
        header, line2 = m.format_screens(data)[0]
        lcd.show(header, line2)

        if data.get("wifi_connected"):
            time.sleep(20)
            break

        if time.monotonic() >= t_max:
            break

        time.sleep(5)
        data = wifi.read()


# ---------------------------------------------------------------------------
# Fan controller helpers
# ---------------------------------------------------------------------------

_FAN_PID_FILE = Path("/run/porcupine-fan.pid")


def _fan_running() -> bool:
    """Return True if a fan controller process is alive (PID file + signal check)."""
    try:
        pid = int(_FAN_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, OSError):
        return False


def _ensure_fan(args: argparse.Namespace) -> None:
    """Spawn porcupine-fan if it is not already running."""
    if _fan_running():
        return
    fan_bin = Path(sys.executable).parent / "porcupine-fan"
    cmd = [
        str(fan_bin),
        "--fan-pin",  str(args.fan_pin),
        "--fan-type", args.fan_type,
        "--fan-on",   str(args.temp_warn),
        "--min-duty", str(args.fan_min_duty),
    ]
    if args.fan_freq is not None:
        cmd += ["--fan-freq", str(args.fan_freq)]
    subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Entry-point helpers
# ---------------------------------------------------------------------------

def _on_sigterm(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def _toggle_only_alert(args: argparse.Namespace, lcd: LCD) -> None:
    """Toggle the only_alert config flag and restart the service to apply it."""
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


def _run_loop(
    monitors: list[_Monitor],
    notifier: _Notifier,
    args: argparse.Namespace,
    last_data: dict,
) -> None:
    """Main polling loop — read monitors, update display, manage alerts."""
    read_cycle    = 0
    display_cycle = 0
    try:
        while True:
            time.sleep(args.refresh)
            read_cycle += 1

            wrapped = notifier.consume_wrap()
            if wrapped:
                display_cycle += 1

            data = _read_all(monitors, r_cycle=read_cycle)
            if not data and not wrapped:
                continue
            if data:
                last_data.update(data)

            breached = {m.flag for m in monitors if m.has_breach(last_data)}
            _apply_escalation(monitors, breached)
            notifier.update(monitors, last_data, breached, display_cycle, wrapped=wrapped)

            if args.fan_enabled and last_data.get("cpu_temp_c", 0.0) >= args.temp_warn:
                _ensure_fan(args)
    except KeyboardInterrupt:
        pass


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

    signal.signal(signal.SIGTERM, _on_sigterm)

    boot.init()
    power.init(addr=args.ina219_addr)

    lcd    = LCD(i2c_addr=args.lcd_addr, cols=16, rows=2)
    lcd.load_custom_chars(_CGRAM)
    button = Button(pin=args.button_pin, long_press_ms=2000)
    buzzer = Buzzer(pin=args.buzzer_pin)

    _wifi_startup(lcd)

    controller = ButtonController(button, lcd, on_long_idle=lambda: _toggle_only_alert(args, lcd))
    button.on_press_start(lambda: buzzer.beep_async(count=1, duration_ms=150, gap_ms=0))
    button.on_held(lambda: buzzer.beep_async(count=1, duration_ms=400, gap_ms=0))

    notifier = _Notifier(
        lcd, buzzer, controller,
        only_alert=getattr(args, "only_alert", False),
        alert_log=getattr(args, "alert_log", None),
    )
    lcd.on_screen_advance(notifier.on_screen_advance)

    last_data = _read_all(monitors, r_cycle=0)
    initial_breached = {m.flag for m in monitors if m.has_breach(last_data)}
    _apply_escalation(monitors, initial_breached)
    notifier.start(monitors, last_data, initial_breached, refresh_s=args.refresh)

    button.start()
    buzzer.beep_async(count=1, duration_ms=150, gap_ms=0)

    try:
        _run_loop(monitors, notifier, args, last_data)
    finally:
        buzzer.beep(count=1, duration_ms=150)
        button.stop()
        lcd.stop()
        buzzer.cleanup()
