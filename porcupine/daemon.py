"""Main event loop — wires monitors to interfaces."""
import argparse
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
#   slot 0: Output High — solid up-arrow + base bar  (pin driving high)
#   slot 1: Output Low  — small up-arrow + base bar  (pin driving low)
#   slot 2: Input High  — top bar + solid down-arrow (pin reading high)
#   slot 3: Input Low   — top bar + small down-arrow (pin reading low)
# ---------------------------------------------------------------------------

_CGRAM: list[list[int]] = [
    [0b00100, 0b01110, 0b11111, 0b00100, 0b00100, 0b00100, 0b11111, 0b00000],
    [0b00000, 0b00100, 0b01110, 0b00100, 0b00100, 0b00100, 0b11111, 0b00000],
    [0b11111, 0b00100, 0b00100, 0b00100, 0b11111, 0b01110, 0b00100, 0b00000],
    [0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110, 0b00100, 0b00000],
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
    suffix = f" {pct:.0f}%" if not math.isnan(pct) else ""
    return "Power", f"{source}{suffix}"


def _fmt_cpu(data: dict) -> tuple[str, str]:
    return "CPU      Mem", f"{data.get('cpu_avg_pct', 0):.0f}%      {data.get('mem_pct', 0):.0f}%"


def _fmt_temp(data: dict) -> tuple[str, str]:
    temp = data.get("cpu_temp_c", float("nan"))
    throttled = data.get("throttled")
    if throttled is True:
        status = "THROTTLED"
    elif throttled is False:
        status = "OK"
    else:
        status = "N/A"
    temp_str = f"{temp:.1f}C" if not (isinstance(temp, float) and math.isnan(temp)) else "---"
    return ("Temperature", f"{temp_str} {status}")


def _fmt_net(data: dict) -> tuple[str, str]:
    return (
        f"Net {data.get('interface', '???')[:5]}",
        f"RX:{_bps_str(data.get('rx_bps', 0))} TX:{_bps_str(data.get('tx_bps', 0))}",
    )


def _fmt_gpio(data: dict) -> tuple[str, str]:
    pins = data.get("gpio_pins", [])
    chars = [_GPIO_CHARS.get(s, " ") for s in pins]
    # Pad to 40 in case the monitor returned fewer entries
    chars += [" "] * (40 - len(chars))
    # Physical header: odd pins (1,3,...,39) on row 1; even pins (2,4,...,40) on row 2
    row1 = "".join(chars[i] for i in range(0, 40, 2))
    row2 = "".join(chars[i] for i in range(1, 40, 2))
    return row1, row2


def _bps_str(bps: float) -> str:
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f}M"
    if bps >= 1024:
        return f"{bps / 1024:.1f}K"
    return f"{int(bps)}B"


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


def _read_all(args: argparse.Namespace) -> dict:
    """Call read() on every enabled monitor and merge results."""
    merged: dict = {}
    for flag, module, _ in _MONITOR_DEFS:
        if getattr(args, flag, False):
            try:
                merged.update(module.read())
            except Exception:
                logging.warning("monitor %r read failed", flag, exc_info=True)
    return merged


def _build_screens(args: argparse.Namespace, data: dict, cycle: int = 0) -> list[tuple[str, str]]:
    """Build the ordered LCD screen list from the latest monitor snapshot.

    A monitor with {flag}_every=N only appears on cycles where cycle % N == 0.
    """
    screens = [
        formatter(data)
        for flag, _, formatter in _MONITOR_DEFS
        if getattr(args, flag, False)
        and cycle % max(1, getattr(args, f"{flag}_every", 1)) == 0
    ]
    return screens or [("No monitors", "enabled")]


# ---------------------------------------------------------------------------
# Button controller
# ---------------------------------------------------------------------------

class _ButtonController:
    """
    Three button-press sequences:
      1. Short press                  — toggle monitoring (backlight + screen cycling)
      2. Short + short press (< 3 s)  — 20-second reboot countdown
      3. Short + long press  (< 3 s)  — 20-second shutdown countdown

    During a countdown, a long press cancels it.
    """

    _WINDOW_S    = 3.0
    _COUNTDOWN_S = 20

    def __init__(self, button: Button, lcd: LCD):
        self._lcd        = lcd
        self._monitoring = True
        # idle | after_first | after_second_start | counting
        self._state      = "idle"
        self._window_timer: threading.Timer | None = None
        self._cancel     = threading.Event()

        button.on_press_start(self._on_press_down)
        button.on_short_press(self._on_short)
        button.on_long_press(self._on_long)

    @property
    def monitoring(self) -> bool:
        return self._monitoring

    def _on_press_down(self) -> None:
        # Cancel the 3-second window as soon as a second press begins so the
        # full long-press duration (2 s) doesn't eat into the window.
        if self._state == "after_first":
            self._cancel_window()
            self._state = "after_second_start"

    def _on_short(self) -> None:
        if self._state == "idle":
            self._toggle()
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

    def _window_expired(self) -> None:
        self._state = "idle"

    def _cancel_window(self) -> None:
        if self._window_timer is not None:
            self._window_timer.cancel()
            self._window_timer = None

    def _toggle(self) -> None:
        self._monitoring = not self._monitoring
        if self._monitoring:
            self._lcd.resume()
        else:
            self._lcd.pause()

    def _begin_countdown(self, action: str) -> None:
        self._state = "counting"
        if not self._monitoring:
            self._monitoring = True
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
    def _on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)

    boot.init()
    power.init(addr=args.ina219_addr)

    lcd    = LCD(i2c_addr=args.lcd_addr, cols=20, rows=2)
    lcd.load_custom_chars(_CGRAM)
    button = Button(pin=args.button_pin, long_press_ms=2000)
    buzzer = Buzzer(pin=args.buzzer_pin)
    alert  = AlertChecker(
        buzzer,
        temp_warn=args.temp_warn,
        cpu_warn=args.cpu_warn,
        mem_warn=args.mem_warn,
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

    cycle = 0
    lcd.start(_build_screens(args, _read_all(args), cycle), refresh_s=args.refresh)

    controller = _ButtonController(button, lcd)

    # Short beep on every press-down — immediate feedback that the press registered.
    button.on_press_start(lambda: _beep_async(count=1, duration_ms=150))
    # Long beep when held past the threshold — cues the user to release for long press.
    button.on_held(lambda: _beep_async(count=1, duration_ms=400))

    button.start()
    _beep_async(count=1, duration_ms=150)

    try:
        while True:
            data = _read_all(args)
            if controller.monitoring:
                lcd.update_screens(_build_screens(args, data, cycle))
            alert.check(data)
            cycle += 1
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        pass
    finally:
        buzzer.beep(count=1, duration_ms=150)
        _beep_q.put(None)  # signal worker to exit
        button.stop()
        lcd.stop()
        buzzer.cleanup()
