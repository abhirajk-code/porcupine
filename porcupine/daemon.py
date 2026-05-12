"""Main event loop — wires monitors to interfaces."""
import argparse
import math
import queue
import signal
import subprocess
import threading
import time

from .interfaces.button import Button
from .interfaces.buzzer import AlertChecker, Buzzer
from .interfaces.lcd import LCD
from .monitors import cpu_mem, network, power, temperature


# ---------------------------------------------------------------------------
# Screen formatters — each returns (line1, line2) for the LCD
# ---------------------------------------------------------------------------

def _fmt_power(data: dict) -> tuple[str, str]:
    uptime = data.get("uptime_s", 0)
    h, rem = divmod(int(uptime), 3600)
    m = rem // 60
    return ("Power", f"Boot:{data.get('boot_count', 0)} {h}h{m:02d}m")


def _fmt_cpu(data: dict) -> tuple[str, str]:
    return (
        "CPU      Mem",
        f"{data.get('cpu_avg_pct', 0):.0f}%      {data.get('mem_pct', 0):.0f}%",
    )


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
    iface = data.get("interface", "???")[:5]
    rx = _bps_str(data.get("rx_bps", 0))
    tx = _bps_str(data.get("tx_bps", 0))
    return (f"Net {iface}", f"RX:{rx} TX:{tx}")


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
    ("power", power,       _fmt_power),
    ("cpu",   cpu_mem,     _fmt_cpu),
    ("temp",  temperature, _fmt_temp),
    ("net",   network,     _fmt_net),
]


def _read_all(args: argparse.Namespace) -> dict:
    """Call read() on every enabled monitor and merge results."""
    merged: dict = {}
    for flag, module, _ in _MONITOR_DEFS:
        if getattr(args, flag, False):
            try:
                merged.update(module.read())
            except Exception:
                pass
    return merged


def _build_screens(args: argparse.Namespace, data: dict) -> list[tuple[str, str]]:
    """Build the ordered LCD screen list from the latest monitor snapshot."""
    screens = [
        formatter(data)
        for flag, _, formatter in _MONITOR_DEFS
        if getattr(args, flag, False)
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
        self._state      = "idle"   # idle | after_first | counting
        self._window_timer: threading.Timer | None = None
        self._cancel     = threading.Event()

        button.on_short_press(self._on_short)
        button.on_long_press(self._on_long)

    @property
    def monitoring(self) -> bool:
        return self._monitoring

    def _on_short(self) -> None:
        if self._state == "idle":
            self._toggle()
            self._state = "after_first"
            self._window_timer = threading.Timer(self._WINDOW_S, self._window_expired)
            self._window_timer.start()
        elif self._state == "after_first":
            self._cancel_window()
            self._begin_countdown("reboot")

    def _on_long(self) -> None:
        if self._state == "after_first":
            self._cancel_window()
            self._begin_countdown("shutdown")
        elif self._state == "counting":
            self._cancel.set()

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
        label = "Rebooting" if action == "reboot" else "Shutdown"
        self._lcd.enter_menu(f"{label} in {self._COUNTDOWN_S}s", "Long: cancel")
        threading.Thread(
            target=self._countdown_loop, args=(action, label), daemon=True
        ).start()

    def _countdown_loop(self, action: str, label: str) -> None:
        for remaining in range(self._COUNTDOWN_S - 1, -1, -1):
            if self._cancel.wait(timeout=1.0):
                self._lcd.update_menu("Cancelled", "")
                time.sleep(1.5)
                self._lcd.exit_menu()
                self._state = "idle"
                return
            self._lcd.update_menu(f"{label} in {remaining}s", "Long: cancel")
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

    power.init()

    lcd    = LCD(i2c_addr=args.lcd_addr)
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

    lcd.start(_build_screens(args, _read_all(args)), refresh_s=args.refresh)

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
                lcd.update_screens(_build_screens(args, data))
            alert.check(data)
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        pass
    finally:
        buzzer.beep(count=1, duration_ms=150)
        _beep_q.put(None)  # signal worker to exit
        button.stop()
        lcd.stop()
        buzzer.cleanup()
