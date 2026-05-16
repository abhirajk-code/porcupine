#!/usr/bin/env python3
"""
Hardware test helper — called by install/test.sh.

Exit codes:
  0  — test passed / action detected correctly
  1  — test failed or wrong action detected
  2  — hardware not available (driver missing); test should be skipped

Usage:
  python3 install/test_hardware.py lcd
  python3 install/test_hardware.py buzzer
  python3 install/test_hardware.py button-short
  python3 install/test_hardware.py button-long
  python3 install/test_hardware.py monitor-boot
  python3 install/test_hardware.py monitor-power
  python3 install/test_hardware.py monitor-cpu
  python3 install/test_hardware.py monitor-temp
  python3 install/test_hardware.py monitor-net
"""
import configparser
import math
import sys
import time

CONFIG_PATH = "/etc/porcupine/porcupine.conf"
LONG_PRESS_S = 2.0
BUTTON_TIMEOUT_S = 30


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_cfg() -> dict:
    cp = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    cp.read(CONFIG_PATH)

    def _get(section, key, default):
        try:
            return cp.get(section, key)
        except Exception:
            return default

    return {
        "lcd_addr":    int(_get("hardware", "lcd_addr",    "0x27"), 0),
        "button_pin":  int(_get("hardware", "button_pin",  "4")),
        "buzzer_pin":  int(_get("hardware", "buzzer_pin",  "18")),
        "ina219_addr": int(_get("hardware", "ina219_addr", "0x41"), 0),
    }


# ---------------------------------------------------------------------------
# LCD
# ---------------------------------------------------------------------------

def cmd_lcd(cfg: dict) -> None:
    from porcupine.interfaces.lcd import LCD, _HAS_RPLCD
    if not _HAS_RPLCD:
        print("Hardware not available: RPLCD not installed.", file=sys.stderr)
        sys.exit(2)

    addr = cfg["lcd_addr"]
    print(f"  Connecting to LCD at I2C address 0x{addr:02x}...")
    lcd = LCD(i2c_addr=addr)

    print("  Displaying: 'Porcupine v0.1' / 'LCD Test OK?'")
    lcd.show("Porcupine v0.1", "LCD Test OK?")
    time.sleep(3)

    print("  Displaying: 'Line 1 of 2' / 'Line 2 of 2'")
    lcd.show("Line 1 of 2", "Line 2 of 2")
    time.sleep(3)

    lcd.stop()
    print("  LCD off.")


# ---------------------------------------------------------------------------
# Buzzer
# ---------------------------------------------------------------------------

def cmd_buzzer(cfg: dict) -> None:
    from porcupine.interfaces.buzzer import Buzzer, _HAS_GPIO
    if not _HAS_GPIO:
        print("Hardware not available: lgpio/RPi.GPIO not installed.", file=sys.stderr)
        sys.exit(2)

    bz = Buzzer(pin=cfg["buzzer_pin"])

    print("  Pattern 1/4 — 3 short beeps  (temperature alert)")
    bz.beep(count=3, duration_ms=200, gap_ms=100)
    time.sleep(1.0)

    print("  Pattern 2/4 — 2 short beeps  (CPU alert)")
    bz.beep(count=2, duration_ms=200, gap_ms=100)
    time.sleep(1.0)

    print("  Pattern 3/4 — 2 short beeps  (memory alert)")
    bz.beep(count=2, duration_ms=200, gap_ms=100)
    time.sleep(1.0)

    print("  Pattern 4/4 — 1 long beep    (battery low alert)")
    bz.beep(count=1, duration_ms=600, gap_ms=0)


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------

def cmd_button(cfg: dict, expected: str) -> None:
    # Prefer lgpio (Pi 5+); fall back to RPi.GPIO (Pi 1–4).
    try:
        import lgpio
        _chip = lgpio.gpiochip_open(0)
        _use_lgpio = True
    except (ImportError, Exception):
        _use_lgpio = False
        try:
            import RPi.GPIO as GPIO
        except (ImportError, RuntimeError):
            print("Hardware not available: lgpio/RPi.GPIO not installed.",
                  file=sys.stderr)
            sys.exit(2)

    from porcupine.interfaces.buzzer import Buzzer
    bz = Buzzer(pin=cfg["buzzer_pin"])

    pin = cfg["button_pin"]

    if _use_lgpio:
        lgpio.gpio_claim_input(_chip, pin, lgpio.SET_PULL_UP)
        read_pin = lambda: lgpio.gpio_read(_chip, pin)
        cleanup = lambda: (lgpio.gpiochip_close(_chip), bz.cleanup())
    else:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        read_pin = lambda: GPIO.input(pin)
        cleanup = lambda: (GPIO.cleanup(), bz.cleanup())

    try:
        if expected == "short":
            print(f"  Waiting for a SHORT press on GPIO {pin}  "
                  f"(press and release in under {LONG_PRESS_S:.0f} s)...")
        else:
            print(f"  Waiting for a LONG press on GPIO {pin}  "
                  f"(hold for {LONG_PRESS_S:.0f}+ seconds, then release)...")
        print(f"  Timeout: {BUTTON_TIMEOUT_S} s", flush=True)

        deadline = time.monotonic() + BUTTON_TIMEOUT_S

        # Wait for press (active low with internal pull-up)
        while read_pin() == 1:
            if time.monotonic() > deadline:
                print("  TIMEOUT — no press detected within "
                      f"{BUTTON_TIMEOUT_S} s.", file=sys.stderr)
                sys.exit(1)
            time.sleep(0.01)

        press_time = time.monotonic()
        print("  Button pressed — waiting for release...", flush=True)
        bz.beep(count=1, duration_ms=150)  # short beep: press registered

        long_beeped = False
        # Wait for release; play long beep when held past the threshold
        while read_pin() == 0:
            if not long_beeped and time.monotonic() - press_time >= LONG_PRESS_S:
                bz.beep(count=1, duration_ms=400)  # long beep: release now
                long_beeped = True
            time.sleep(0.005)

        duration = time.monotonic() - press_time
        detected = "long" if duration >= LONG_PRESS_S else "short"
        print(f"  Detected: {detected.upper()} press  ({duration:.2f} s)")

        if detected == expected:
            print(f"  ✓ Correct — expected {expected.upper()}, got {detected.upper()}.")
        else:
            print(f"  ✗ Wrong type — expected {expected.upper()}, "
                  f"got {detected.upper()}.", file=sys.stderr)
            sys.exit(1)

    finally:
        cleanup()


# ---------------------------------------------------------------------------
# Monitors
# ---------------------------------------------------------------------------

def cmd_monitor_boot() -> None:
    from porcupine.monitors import boot
    boot.init(path="/var/lib/porcupine/bootcount")
    data = boot.read()
    h, rem = divmod(int(data["uptime_s"]), 3600)
    m = rem // 60
    print(f"  Boot count : {data['boot_count']}")
    print(f"  Uptime     : {h}h {m:02d}m")


def cmd_monitor_power(cfg: dict) -> None:
    from porcupine.monitors.power import _HAS_SMBUS
    if not _HAS_SMBUS:
        print("Hardware not available: smbus/smbus2 not installed.", file=sys.stderr)
        sys.exit(2)
    from porcupine.monitors import power
    power.init(addr=cfg["ina219_addr"])
    data = power.read()
    print(f"  Source      : {data['power_source']}")
    pct = data["battery_pct"]
    print(f"  Battery     : {pct:.1f}%" if pct == pct else "  Battery     : N/A")


def cmd_monitor_cpu() -> None:
    from porcupine.monitors import cpu_mem
    # Two reads 0.5 s apart so cpu_percent has an interval to measure against
    cpu_mem.read()
    time.sleep(0.5)
    data = cpu_mem.read()
    cores = "  ".join(f"{p:.0f}%" for p in data["cpu_pct"])
    print(f"  CPU average : {data['cpu_avg_pct']:.1f}%")
    print(f"  Per core    : {cores}")
    print(f"  Memory      : {data['mem_used_mb']} MB / {data['mem_total_mb']} MB"
          f"  ({data['mem_pct']:.1f}%)")


def cmd_monitor_temp() -> None:
    from porcupine.monitors import temperature
    data = temperature.read()
    temp = data["cpu_temp_c"]
    temp_str = f"{temp:.1f} °C" if not math.isnan(temp) else "N/A (not on Pi)"
    flags = data["throttle_flags"]
    throttled = data["throttled"]
    if throttled is True:
        status = "THROTTLED"
    elif throttled is False:
        status = "OK"
    else:
        status = "N/A (vcgencmd unavailable)"
    print(f"  CPU temperature : {temp_str}")
    print(f"  Throttle status : {status}")
    if flags >= 0:
        print(f"  Throttle flags  : 0x{flags:x}")


def cmd_monitor_net() -> None:
    from porcupine.monitors import network
    # First read establishes baseline; second read computes rate.
    network.read()
    print("  Sampling network for 1 second...")
    time.sleep(1)
    data = network.read()

    def _fmt(bps: float) -> str:
        if bps >= 1024 ** 2:
            return f"{bps / 1024**2:.2f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.2f} KB/s"
        return f"{bps:.0f} B/s"

    print(f"  Interface : {data['interface']}")
    print(f"  RX rate   : {_fmt(data['rx_bps'])}")
    print(f"  TX rate   : {_fmt(data['tx_bps'])}")
    print(f"  RX total  : {data['rx_total_mb']:.1f} MB")
    print(f"  TX total  : {data['tx_total_mb']:.1f} MB")


def cmd_monitor_gpio() -> None:
    from porcupine.monitors import gpio_pins
    data = gpio_pins.read()
    pins = data["gpio_pins"]
    exported = [(i + 1, s) for i, s in enumerate(pins) if s not in ("3v3", "5v", "gnd", None)]
    print(f"  Exported GPIO pins : {len(exported)}")
    for phys, state in exported[:8]:
        print(f"    Pin {phys:2d}: {state}")
    if not exported:
        print("  (no GPIO pins currently exported via sysfs)")


def cmd_monitor_disk() -> None:
    from porcupine.monitors import disk
    data = disk.read()
    print(f"  Disk usage  : {data['disk_pct']:.1f}%")
    print(f"  Used / Total: {data['disk_used_gb']:.1f} GB / {data['disk_total_gb']:.1f} GB")


def cmd_monitor_conn() -> None:
    from porcupine.monitors import connectivity
    data = connectivity.read()
    host = data["conn_host"]
    if data["reachable"]:
        print(f"  Host        : {host}")
        print(f"  Reachable   : yes  ({data['latency_ms']:.1f} ms)")
    else:
        print(f"  Host        : {host}")
        print("  Reachable   : NO")


def cmd_monitor_wifi() -> None:
    import math
    from porcupine.monitors import wifi
    data = wifi.read()
    iface = data["wifi_iface"]
    if iface is None:
        print("  No WiFi hardware detected.")
        return
    print(f"  Interface   : {iface}")
    print(f"  Connected   : {'yes' if data['wifi_connected'] else 'no'}")
    if data["wifi_ip"]:
        print(f"  IP address  : {data['wifi_ip']}")
    sig = data["wifi_signal_dbm"]
    if not math.isnan(sig):
        print(f"  Signal      : {sig:.0f} dBm")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_COMMANDS = {
    "lcd":           lambda cfg: cmd_lcd(cfg),
    "buzzer":        lambda cfg: cmd_buzzer(cfg),
    "button-short":  lambda cfg: cmd_button(cfg, "short"),
    "button-long":   lambda cfg: cmd_button(cfg, "long"),
    "monitor-boot":  lambda cfg: cmd_monitor_boot(),
    "monitor-power": lambda cfg: cmd_monitor_power(cfg),
    "monitor-cpu":   lambda cfg: cmd_monitor_cpu(),
    "monitor-temp":  lambda cfg: cmd_monitor_temp(),
    "monitor-net":   lambda cfg: cmd_monitor_net(),
    "monitor-gpio":  lambda cfg: cmd_monitor_gpio(),
    "monitor-disk":  lambda cfg: cmd_monitor_disk(),
    "monitor-conn":  lambda cfg: cmd_monitor_conn(),
    "monitor-wifi":  lambda cfg: cmd_monitor_wifi(),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        cmds = " | ".join(_COMMANDS)
        print(f"Usage: {sys.argv[0]} <{cmds}>", file=sys.stderr)
        sys.exit(1)
    cfg = _load_cfg()
    _COMMANDS[sys.argv[1]](cfg)
