"""CLI flag parsing and config file management."""
import argparse


DEFAULT_CONFIG_PATH = "/etc/porcupine/porcupine.conf"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="porcupine",
        description="Raspberry Pi system monitor",
    )
    parser.add_argument("--power", action="store_true", help="Monitor boot count and uptime")
    parser.add_argument("--cpu", action="store_true", help="Monitor CPU and memory usage")
    parser.add_argument("--temp", action="store_true", help="Monitor CPU temperature")
    parser.add_argument("--net", action="store_true", help="Monitor network usage")

    parser.add_argument("--lcd-addr", type=lambda x: int(x, 0), default=0x27, metavar="ADDR")
    parser.add_argument("--button-pin", type=int, default=17, metavar="PIN")
    parser.add_argument("--buzzer-pin", type=int, default=18, metavar="PIN")
    parser.add_argument("--refresh", type=float, default=3.0, metavar="SECS")

    parser.add_argument("--temp-warn", type=float, default=80.0, metavar="C")
    parser.add_argument("--cpu-warn", type=float, default=90.0, metavar="PCT")
    parser.add_argument("--mem-warn", type=float, default=90.0, metavar="PCT")

    args = parser.parse_args(argv)

    # If no monitor flags given, enable all.
    if not any([args.power, args.cpu, args.temp, args.net]):
        args.power = args.cpu = args.temp = args.net = True

    return args
