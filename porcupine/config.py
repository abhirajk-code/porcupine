"""CLI flag parsing and config file management."""
import argparse
import configparser

DEFAULT_CONFIG_PATH = "/etc/porcupine/porcupine.conf"

_MONITOR_FLAGS = ("power", "cpu", "temp", "net")


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """
    Parse an INI-style config file.

    Returns an empty dict if the file does not exist or cannot be read,
    so callers fall back to hardcoded defaults without error.
    """
    cp = configparser.ConfigParser()
    if not cp.read(path):
        return {}

    result: dict = {}

    # [monitors]
    for flag in _MONITOR_FLAGS:
        if cp.has_option("monitors", flag):
            result[flag] = cp.getboolean("monitors", flag)

    # [hardware]
    if cp.has_option("hardware", "lcd_addr"):
        result["lcd_addr"] = int(cp.get("hardware", "lcd_addr"), 0)  # accepts 0x27
    for key in ("button_pin", "buzzer_pin"):
        if cp.has_option("hardware", key):
            result[key] = cp.getint("hardware", key)

    # [display]
    if cp.has_option("display", "refresh"):
        result["refresh"] = cp.getfloat("display", "refresh")

    # [alerts]
    for key in ("temp_warn", "cpu_warn", "mem_warn"):
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

    # Monitor flags: BooleanOptionalAction gives --power / --no-power.
    # default=None lets us distinguish "not given" from "explicitly set".
    for flag in _MONITOR_FLAGS:
        parser.add_argument(
            f"--{flag}",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=f"Enable or disable the {flag} monitor",
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
        "--button-pin", type=int,
        default=file_cfg.get("button_pin", 17),
        metavar="PIN",
    )
    parser.add_argument(
        "--buzzer-pin", type=int,
        default=file_cfg.get("buzzer_pin", 18),
        metavar="PIN",
    )
    parser.add_argument(
        "--refresh", type=float,
        default=file_cfg.get("refresh", 3.0),
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
        "--config",
        default=config_path,
        metavar="PATH",
        help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})",
    )

    args = parser.parse_args(argv)

    # Resolve monitor flags: None → config file value → True (all on by default).
    for flag in _MONITOR_FLAGS:
        if getattr(args, flag) is None:
            setattr(args, flag, file_cfg.get(flag, True))

    return args
