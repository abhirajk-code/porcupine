"""Main event loop — wires monitors to interfaces."""
import argparse
import configparser
import logging
import math
import os
import signal
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from .interfaces.button import Button
from .interfaces.button_controller import ButtonController
from .interfaces.buzzer import Buzzer
from .interfaces.lcd import LCD
from .monitors import boot, connectivity, cpu_mem, disk, gpio_pins, network, power, temperature, wifi


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

# Map gpio_pins state strings → display character
_GPIO_CHARS: dict[str | None, str] = {
    "3v3":   "^",
    "5v":    "+",
    "gnd":   "-",
    "out_h": chr(0),
    "out_l": chr(1),
    "in_h":  chr(2),
    "in_l":  chr(3),
    None:    " ",
}

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


def _gb_fmt(gb: float) -> str:
    """Format gigabytes compactly — one decimal below 100 GB, integer above."""
    return f"{gb:.0f}" if gb >= 100 else f"{gb:.1f}"


def _is_valid(value: object) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


# ---------------------------------------------------------------------------
# Monitor objects — own reading, formatting, breach detection, and beep pattern
# ---------------------------------------------------------------------------

class _Monitor(ABC):
    """Per-feature monitor with a uniform interface for the orchestrator."""
    flag: str

    def __init__(self, every: int = 0) -> None:
        self.every = every
        self._escalated: bool = False

    @property
    def effective_every(self) -> int:
        """Read cadence: 1 when a breach is active, configured every otherwise."""
        return 1 if self._escalated else self.every

    @abstractmethod
    def read(self) -> dict: ...

    @abstractmethod
    def format_screens(self, data: dict) -> list[tuple[str, str]]: ...

    def has_breach(self, data: dict) -> bool:
        return False

    def beep_pattern(self) -> dict | None:
        return None


class _BootMonitor(_Monitor):
    flag = "boot"

    def __init__(self, every: int = 0) -> None:
        super().__init__(every)

    def read(self) -> dict:
        return boot.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        uptime = int(data.get("uptime_s", 0))
        return [("Boot", f"#{data.get('boot_count', 0)} {uptime // 3600}h{uptime % 3600 // 60:02d}m")]


class _PowerMonitor(_Monitor):
    flag = "power"

    def __init__(self, bat_warn: float = 40.0, every: int = 0) -> None:
        super().__init__(every)
        self._bat_warn = bat_warn

    def read(self) -> dict:
        return power.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        source = data.get("power_source", "Unknown")
        pct    = data.get("battery_pct", float("nan"))
        if not math.isnan(pct):
            warn   = source == "Battery" and pct < self._bat_warn
            suffix = f" {pct:.0f}%" + (" WARN" if warn else "")
        else:
            suffix = ""
        return [("Power", f"{source}{suffix}")]

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

    def __init__(self, cpu_warn: float = 90.0, mem_warn: float = 90.0, every: int = 0) -> None:
        super().__init__(every)
        self._cpu_warn = cpu_warn
        self._mem_warn = mem_warn

    def read(self) -> dict:
        return cpu_mem.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        cpu   = data.get("cpu_avg_pct", 0)
        mem   = data.get("mem_pct", 0)
        cpu_s = "WARN" if cpu >= self._cpu_warn else f"{cpu:.0f}%"
        mem_s = "WARN" if mem >= self._mem_warn else f"{mem:.0f}%"
        return [(" CPU   Mem", f"{cpu_s:>4}  {mem_s:>4}")]

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

    def __init__(self, temp_warn: float = 80.0, every: int = 0) -> None:
        super().__init__(every)
        self._temp_warn = temp_warn

    def read(self) -> dict:
        return temperature.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        temp      = data.get("cpu_temp_c", float("nan"))
        throttled = data.get("throttled")
        if not math.isnan(temp):
            temp_str = f"{temp:.0f}C" if temp >= 100 else f"{temp:.1f}C"
            parts    = []
            if temp >= self._temp_warn:
                parts.append("WARN")
            if throttled:
                parts.append("THRT")
            suffix = (" " + "+".join(parts)) if parts else ""
        else:
            temp_str = "---"
            suffix   = " THRT" if throttled else ""
        return [("Temperature", f"{temp_str}{suffix}")]

    def has_breach(self, data: dict) -> bool:
        temp      = data.get("cpu_temp_c")
        throttled = data.get("throttled")
        return (
            (_is_valid(temp) and temp >= self._temp_warn)
            or throttled is True
        )

    def beep_pattern(self) -> dict:
        return {"count": 3, "duration_ms": 200, "gap_ms": 100}


class _NetMonitor(_Monitor):
    flag = "net"

    def __init__(self, every: int = 0) -> None:
        super().__init__(every)

    def read(self) -> dict:
        return network.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        return [(
            f"Net {data.get('interface', '???')[:5]}",
            f"R:{_bps_str(data.get('rx_bps', 0))} T:{_bps_str(data.get('tx_bps', 0))}",
        )]


class _GpioMonitor(_Monitor):
    flag = "gpio"

    def __init__(self, page: int, every: int = 0) -> None:
        super().__init__(every)
        self._page = page  # 1 = pins 1-20, 2 = pins 21-40

    def read(self) -> dict:
        return gpio_pins.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        pins  = data.get("gpio_pins", [])
        chars = [_GPIO_CHARS.get(s, " ") for s in pins]
        chars += [" "] * (40 - len(chars))

        def _row(indices: range, first_pin: int, last_pin: int) -> str:
            return f"{first_pin:02d}[{''.join(chars[i] for i in indices)}]{last_pin:02d}"

        if self._page == 1:
            return [(_row(range( 0, 20, 2),  1, 19), _row(range( 1, 20, 2),  2, 20))]
        else:
            return [(_row(range(20, 40, 2), 21, 39), _row(range(21, 40, 2), 22, 40))]


class _DiskMonitor(_Monitor):
    flag = "disk"

    def __init__(self, disk_warn: float = 85.0, every: int = 0) -> None:
        super().__init__(every)
        self._disk_warn = disk_warn

    def read(self) -> dict:
        return disk.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        pct   = data.get("disk_pct",      float("nan"))
        used  = data.get("disk_used_gb",  float("nan"))
        total = data.get("disk_total_gb", float("nan"))
        if not math.isnan(pct):
            pct_s  = "WARN" if pct >= self._disk_warn else f"{pct:.0f}%"
            size_s = f"{_gb_fmt(used)}/{_gb_fmt(total)}GB"
        else:
            pct_s  = "---"
            size_s = ""
        return [("Disk /", f"{pct_s} {size_s}".rstrip())]

    def has_breach(self, data: dict) -> bool:
        pct = data.get("disk_pct")
        return _is_valid(pct) and pct >= self._disk_warn

    def beep_pattern(self) -> dict:
        return {"count": 2, "duration_ms": 400, "gap_ms": 200}


class _WifiMonitor(_Monitor):
    flag = "wifi"

    def __init__(self, every: int = 0) -> None:
        super().__init__(every)

    def read(self) -> dict:
        return wifi.read()

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        connected = data.get("wifi_connected")
        ip        = data.get("wifi_ip")
        signal    = data.get("wifi_signal_dbm", float("nan"))

        sig_str = f" {signal:.0f}dBm" if not math.isnan(signal) else ""
        header  = f"WiFi{sig_str}"

        if connected is True:
            line2 = ip or "No IP"
        elif connected is False:
            line2 = "Disconnected"
        else:
            line2 = "---"

        return [(header, line2)]

    def has_breach(self, data: dict) -> bool:
        # Only breach when WiFi hardware is present but not connected
        return data.get("wifi_connected") is False and data.get("wifi_iface") is not None

    def beep_pattern(self) -> dict:
        return {"count": 2, "duration_ms": 400, "gap_ms": 200}


class _ConnectivityMonitor(_Monitor):
    flag = "conn"

    def __init__(self, host: str = "8.8.8.8", every: int = 0) -> None:
        super().__init__(every)
        self._host = host

    def read(self) -> dict:
        return connectivity.read(host=self._host)

    def format_screens(self, data: dict) -> list[tuple[str, str]]:
        reachable  = data.get("reachable")
        latency_ms = data.get("latency_ms", float("nan"))
        if reachable is True:
            line2 = f"OK {latency_ms:.1f}ms"
        elif reachable is False:
            line2 = "UNREACHABLE"
        else:
            line2 = "---"
        return [("Internet", line2)]

    def has_breach(self, data: dict) -> bool:
        return data.get("reachable") is False

    def beep_pattern(self) -> dict:
        return {"count": 3, "duration_ms": 300, "gap_ms": 150}


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
        if self._only_alert and new_breached:
            display_screens, display_tags = _filter_alert_screens(screens, tags, new_breached)
        else:
            display_screens, display_tags = screens, tags

        self._log_transitions(self._breached, new_breached, patterns)

        with self._lock:
            self._breached      = new_breached
            self._tags          = display_tags
            self._beep_patterns = patterns

        if self._only_alert:
            if new_breached:
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
    r_cycle = 0
    d_cycle = 0
    try:
        while True:
            time.sleep(args.refresh)
            r_cycle += 1

            wrapped = notifier.consume_wrap()
            if wrapped:
                d_cycle += 1

            data = _read_all(monitors, r_cycle=r_cycle)
            if not data and not wrapped:
                continue
            if data:
                last_data.update(data)

            breached = {m.flag for m in monitors if m.has_breach(last_data)}
            _apply_escalation(monitors, breached)
            notifier.update(monitors, last_data, breached, d_cycle, wrapped=wrapped)

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
