"""Main event loop — wires monitors to interfaces."""
import argparse
import math
import subprocess
import time
from typing import Callable

from .interfaces.button import Button, MenuFSM
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
# Menu controller
# ---------------------------------------------------------------------------

class _MenuController:
    _TOGGLE_FLAGS = frozenset(("power", "cpu", "temp", "net"))
    _ITEMS: list[tuple[str, str]] = [
        ("Toggle POWER", "power"),
        ("Toggle CPU  ", "cpu"),
        ("Toggle TEMP ", "temp"),
        ("Toggle NET  ", "net"),
        ("Restart Pi  ", "restart"),
        ("Shutdown Pi ", "shutdown"),
    ]

    def __init__(
        self,
        lcd: LCD,
        args: argparse.Namespace,
        get_screens,       # callable → list[tuple[str,str]]
    ):
        self._lcd = lcd
        self._args = args
        self._get_screens = get_screens
        self._reset_fn = lambda: None   # wired after MenuFSM is created
        self._index = 0

    def enter(self) -> None:
        self._index = 0
        self._render()

    def next_item(self) -> None:
        self._index = (self._index + 1) % len(self._ITEMS)
        self._render()

    def confirm(self) -> None:
        _, action = self._ITEMS[self._index]
        if action in self._TOGGLE_FLAGS:
            setattr(self._args, action, not getattr(self._args, action))
            self._lcd.update_screens(self._get_screens())
            self._render()
        elif action == "restart":
            self._reset_fn()
            subprocess.run(["sudo", "reboot"], check=False)
        elif action == "shutdown":
            self._reset_fn()
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=False)

    def _render(self) -> None:
        label, action = self._ITEMS[self._index]
        if action in self._TOGGLE_FLAGS:
            state = "ON " if getattr(self._args, action) else "OFF"
            self._lcd.update_menu(f">{label}", f" Now:{state}")
        else:
            self._lcd.update_menu(f">{label}", " Hold:confirm")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
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

    def _beep_async(count: int, duration_ms: int, gap_ms: int = 0) -> None:
        import threading as _t
        _t.Thread(
            target=lambda: buzzer.beep(count=count, duration_ms=duration_ms, gap_ms=gap_ms),
            daemon=True,
        ).start()

    def _short_beep_then(fn: Callable) -> Callable:
        """Wrap a callback so a single short beep fires before it."""
        def _wrapper():
            _beep_async(count=1, duration_ms=80)
            fn()
        return _wrapper

    def get_screens() -> list[tuple[str, str]]:
        return _build_screens(args, _read_all(args))

    menu = _MenuController(lcd, args, get_screens)
    fsm  = MenuFSM(
        button=button,
        next_screen_cb=_short_beep_then(lcd.next_screen),
        enter_menu_cb=menu.enter,
        menu_next_cb=_short_beep_then(menu.next_item),
        menu_confirm_cb=menu.confirm,
    )
    menu._reset_fn = fsm.reset

    # Two quick beeps when the long-press threshold is crossed — tells the
    # user the button has been held long enough and they can release.
    button.on_held(lambda: _beep_async(count=2, duration_ms=100, gap_ms=60))

    lcd.start(get_screens(), refresh_s=args.refresh)
    button.start()

    try:
        while True:
            data = _read_all(args)
            if not fsm.in_menu:
                lcd.update_screens(_build_screens(args, data))
            alert.check(data)
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        pass
    finally:
        button.stop()
        lcd.stop()
        buzzer.cleanup()
