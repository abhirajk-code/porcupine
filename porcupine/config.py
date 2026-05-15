"""CLI flag parsing and config file management."""
import argparse
import configparser

DEFAULT_CONFIG_PATH = "/etc/porcupine/porcupine.conf"

_MONITOR_FLAGS = ("boot", "power", "cpu", "temp", "net", "gpio")

_MONITOR_DEFAULTS = {
    "boot":  10,
    "power":  5,
    "cpu":    5,
    "temp":   1,
    "net":   10,
    "gpio":   2,
}


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """
    Parse an INI-style config file.

    Returns an empty dict if the file does not exist or cannot be read,
    so callers fall back to hardcoded defaults without error.
    """
    cp = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    if not cp.read(path):
        return {}

    result: dict = {}

    # [monitors]  — only {flag}_every keys; 0 = disabled, N = every Nth cycle
    for flag in _MONITOR_FLAGS:
        every_key = f"{flag}_every"
        if cp.has_option("monitors", every_key):
            result[every_key] = cp.getint("monitors", every_key)

    # [hardware]
    if cp.has_option("hardware", "lcd_addr"):
        result["lcd_addr"] = int(cp.get("hardware", "lcd_addr"), 0)  # accepts 0x27
    for key in ("button_pin", "buzzer_pin"):
        if cp.has_option("hardware", key):
            result[key] = cp.getint("hardware", key)
    if cp.has_option("hardware", "ina219_addr"):
        result["ina219_addr"] = int(cp.get("hardware", "ina219_addr"), 0)

    # [display]
    if cp.has_option("display", "refresh"):
        result["refresh"] = cp.getfloat("display", "refresh")
    if cp.has_option("display", "only_alert"):
        result["only_alert"] = cp.getboolean("display", "only_alert")

    # [alerts]
    for key in ("temp_warn", "cpu_warn", "mem_warn", "bat_warn"):
        if cp.has_option("alerts", key):
            result[key] = cp.getfloat("alerts", key)

    return result


def parse_args(argv=None, config_path: str = DEFAULT_CONFIG_PATH) -> argparse.Namespace:
    """
    Parse CLI arguments with three-level precedence:
      CLI flag  >  config file  >  hardcoded default
    """
    # Pre-parse to pick up a custom --config path before loading the file.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=config_path)
    known, _ = pre.parse_known_args(argv)
    file_cfg = load_config(known.config)

    parser = argparse.ArgumentParser(
        prog="porcupine",
        description="Raspberry Pi system monitor",
    )

    # Monitor frequency: 0 = disabled, 1 = every cycle, N = every Nth cycle.
    for flag in _MONITOR_FLAGS:
        parser.add_argument(
            f"--{flag}-every",
            type=int,
            default=file_cfg.get(f"{flag}_every", _MONITOR_DEFAULTS[flag]),
            metavar="N",
            help=f"Show {flag} screen every Nth cycle; 0 disables (default {_MONITOR_DEFAULTS[flag]})",
        )

    # Numeric flags: config file values become the parser defaults so CLI
    # overrides them transparently.
    parser.add_argument(
        "--lcd-addr", type=lambda x: int(x, 0),
        default=file_cfg.get("lcd_addr", 0x27),
        metavar="ADDR",
        help="I2C address of the LCD (hex ok, e.g. 0x27)",
    )
    parser.add_argument(
        "--ina219-addr", type=lambda x: int(x, 0),
        default=file_cfg.get("ina219_addr", 0x41),
        metavar="ADDR",
        help="I2C address of the INA219 power monitor (hex ok, e.g. 0x41)",
    )
    parser.add_argument(
        "--button-pin", type=int,
        default=file_cfg.get("button_pin", 4),
        metavar="PIN",
    )
    parser.add_argument(
        "--buzzer-pin", type=int,
        default=file_cfg.get("buzzer_pin", 18),
        metavar="PIN",
    )
    parser.add_argument(
        "--refresh", type=float,
        default=file_cfg.get("refresh", 5.0),
        metavar="SECS",
        help="Screen refresh interval in seconds",
    )
    parser.add_argument(
        "--temp-warn", type=float,
        default=file_cfg.get("temp_warn", 80.0),
        metavar="C",
    )
    parser.add_argument(
        "--cpu-warn", type=float,
        default=file_cfg.get("cpu_warn", 90.0),
        metavar="PCT",
    )
    parser.add_argument(
        "--mem-warn", type=float,
        default=file_cfg.get("mem_warn", 90.0),
        metavar="PCT",
    )
    parser.add_argument(
        "--bat-warn", type=float,
        default=file_cfg.get("bat_warn", 40.0),
        metavar="PCT",
        help="Battery percentage below which to warn (default 40)",
    )
    parser.add_argument(
        "--only-alert", action="store_true",
        default=file_cfg.get("only_alert", False),
        help="LCD stays off until a threshold is breached; shows only the breached monitor(s)",
    )
    parser.add_argument(
        "--config",
        default=config_path,
        metavar="PATH",
        help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})",
    )

    args = parser.parse_args(argv)
    _validate(parser, args)
    return args


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    errors = []

    # GPIO pins 0–27 are valid BCM pins on all Pi models.
    for pin_attr in ("button_pin", "buzzer_pin"):
        pin = getattr(args, pin_attr)
        if not (0 <= pin <= 27):
            errors.append(f"--{pin_attr.replace('_', '-')} {pin} is out of range (0–27)")

    # I2C addresses are 7-bit (0x08–0x77; 0x00–0x07 are reserved).
    for addr_attr, label in (("lcd_addr", "--lcd-addr"), ("ina219_addr", "--ina219-addr")):
        addr = getattr(args, addr_attr)
        if not (0x08 <= addr <= 0x77):
            errors.append(f"{label} 0x{addr:02x} is not a valid 7-bit I2C address (0x08–0x77)")

    # Percentage thresholds must be 0–100.
    for pct_attr in ("cpu_warn", "mem_warn", "bat_warn"):
        val = getattr(args, pct_attr)
        if not (0.0 <= val <= 100.0):
            errors.append(f"--{pct_attr.replace('_', '-')} {val} must be between 0 and 100")

    # Temperature threshold sanity check.
    if not (0.0 <= args.temp_warn <= 120.0):
        errors.append(f"--temp-warn {args.temp_warn} must be between 0 and 120 °C")

    # Refresh interval must be positive.
    if args.refresh <= 0:
        errors.append(f"--refresh {args.refresh} must be a positive number")

    if errors:
        parser.error("\n  ".join(errors))
