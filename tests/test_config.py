"""Config loading and CLI argument parsing tests."""
import textwrap
from pathlib import Path

import pytest

from porcupine.config import load_config, parse_args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_conf(tmp_path: Path, content: str) -> str:
    p = tmp_path / "porcupine.conf"
    p.write_text(textwrap.dedent(content))
    return str(p)


# ---------------------------------------------------------------------------
# load_config — missing / unreadable file
# ---------------------------------------------------------------------------

def test_load_config_missing_file_returns_empty(tmp_path):
    result = load_config(str(tmp_path / "nonexistent.conf"))
    assert result == {}


def test_load_config_empty_file_returns_empty(tmp_path):
    p = tmp_path / "empty.conf"
    p.write_text("")
    assert load_config(str(p)) == {}


# ---------------------------------------------------------------------------
# load_config — monitors section
# ---------------------------------------------------------------------------

def test_load_config_reads_monitor_flags(tmp_path):
    path = write_conf(tmp_path, """
        [monitors]
        power = true
        cpu   = false
        temp  = true
        net   = false
    """)
    cfg = load_config(path)
    assert cfg["power"] is True
    assert cfg["cpu"] is False
    assert cfg["temp"] is True
    assert cfg["net"] is False


def test_load_config_partial_monitors_section(tmp_path):
    path = write_conf(tmp_path, """
        [monitors]
        cpu = false
    """)
    cfg = load_config(path)
    assert cfg["cpu"] is False
    assert "power" not in cfg
    assert "temp" not in cfg


# ---------------------------------------------------------------------------
# load_config — hardware section
# ---------------------------------------------------------------------------

def test_load_config_reads_lcd_addr_as_hex(tmp_path):
    path = write_conf(tmp_path, """
        [hardware]
        lcd_addr = 0x3f
    """)
    cfg = load_config(path)
    assert cfg["lcd_addr"] == 0x3F


def test_load_config_reads_lcd_addr_as_decimal(tmp_path):
    path = write_conf(tmp_path, """
        [hardware]
        lcd_addr = 39
    """)
    cfg = load_config(path)
    assert cfg["lcd_addr"] == 39


def test_load_config_reads_gpio_pins(tmp_path):
    path = write_conf(tmp_path, """
        [hardware]
        button_pin = 22
        buzzer_pin = 23
    """)
    cfg = load_config(path)
    assert cfg["button_pin"] == 22
    assert cfg["buzzer_pin"] == 23


# ---------------------------------------------------------------------------
# load_config — display and alerts sections
# ---------------------------------------------------------------------------

def test_load_config_reads_refresh(tmp_path):
    path = write_conf(tmp_path, """
        [display]
        refresh = 5.0
    """)
    cfg = load_config(path)
    assert cfg["refresh"] == pytest.approx(5.0)


def test_load_config_reads_alert_thresholds(tmp_path):
    path = write_conf(tmp_path, """
        [alerts]
        temp_warn = 75.0
        cpu_warn  = 85.0
        mem_warn  = 88.5
    """)
    cfg = load_config(path)
    assert cfg["temp_warn"] == pytest.approx(75.0)
    assert cfg["cpu_warn"]  == pytest.approx(85.0)
    assert cfg["mem_warn"]  == pytest.approx(88.5)


def test_load_config_full_file(tmp_path):
    path = write_conf(tmp_path, """
        [monitors]
        power = true
        cpu   = true
        temp  = true
        net   = true
        [hardware]
        lcd_addr   = 0x27
        button_pin = 17
        buzzer_pin = 18
        [display]
        refresh = 3
        [alerts]
        temp_warn = 80
        cpu_warn  = 90
        mem_warn  = 90
    """)
    cfg = load_config(path)
    assert cfg["lcd_addr"] == 0x27
    assert cfg["refresh"]  == pytest.approx(3.0)
    assert cfg["temp_warn"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# parse_args — hardcoded defaults (no config file, no CLI flags)
# ---------------------------------------------------------------------------

def test_parse_args_defaults_all_monitors_enabled(tmp_path):
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert args.boot  is True
    assert args.power is True
    assert args.cpu   is True
    assert args.temp  is True
    assert args.net   is True


def test_parse_args_defaults_numeric_values(tmp_path):
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert args.lcd_addr   == 0x27
    assert args.button_pin == 4
    assert args.buzzer_pin == 18
    assert args.refresh    == pytest.approx(5.0)
    assert args.temp_warn  == pytest.approx(80.0)
    assert args.cpu_warn   == pytest.approx(90.0)
    assert args.mem_warn   == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# parse_args — CLI flags override hardcoded defaults
# ---------------------------------------------------------------------------

def test_parse_args_cli_monitor_flags(tmp_path):
    args = parse_args(["--power", "--no-cpu", "--no-temp", "--no-net"],
                      config_path=str(tmp_path / "none.conf"))
    assert args.power is True
    assert args.cpu   is False
    assert args.temp  is False
    assert args.net   is False


def test_parse_args_cli_numeric_overrides(tmp_path):
    args = parse_args(
        ["--lcd-addr", "0x3f", "--button-pin", "22", "--refresh", "5"],
        config_path=str(tmp_path / "none.conf"),
    )
    assert args.lcd_addr   == 0x3F
    assert args.button_pin == 22
    assert args.refresh    == pytest.approx(5.0)


def test_parse_args_cli_alert_overrides(tmp_path):
    args = parse_args(
        ["--temp-warn", "70", "--cpu-warn", "85", "--mem-warn", "75"],
        config_path=str(tmp_path / "none.conf"),
    )
    assert args.temp_warn == pytest.approx(70.0)
    assert args.cpu_warn  == pytest.approx(85.0)
    assert args.mem_warn  == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# parse_args — config file values used when CLI flag absent
# ---------------------------------------------------------------------------

def test_parse_args_config_file_sets_monitor_flags(tmp_path):
    path = write_conf(tmp_path, """
        [monitors]
        power = false
        cpu   = true
        temp  = false
        net   = true
    """)
    args = parse_args([], config_path=path)
    assert args.power is False
    assert args.cpu   is True
    assert args.temp  is False
    assert args.net   is True


def test_parse_args_config_file_sets_numeric_values(tmp_path):
    path = write_conf(tmp_path, """
        [hardware]
        lcd_addr   = 0x3f
        button_pin = 22
        buzzer_pin = 23
        [display]
        refresh = 10
        [alerts]
        temp_warn = 75
    """)
    args = parse_args([], config_path=path)
    assert args.lcd_addr   == 0x3F
    assert args.button_pin == 22
    assert args.refresh    == pytest.approx(10.0)
    assert args.temp_warn  == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# parse_args — CLI overrides config file (three-level precedence)
# ---------------------------------------------------------------------------

def test_cli_overrides_config_file_monitor_flag(tmp_path):
    path = write_conf(tmp_path, """
        [monitors]
        power = false
    """)
    # Config says power=false, CLI says --power → CLI wins
    args = parse_args(["--power"], config_path=path)
    assert args.power is True


def test_cli_overrides_config_file_numeric(tmp_path):
    path = write_conf(tmp_path, """
        [display]
        refresh = 10
    """)
    args = parse_args(["--refresh", "2"], config_path=path)
    assert args.refresh == pytest.approx(2.0)


def test_config_file_overrides_hardcoded_default(tmp_path):
    path = write_conf(tmp_path, """
        [alerts]
        temp_warn = 70
    """)
    # No CLI flag → config file value wins over hardcoded 80.0
    args = parse_args([], config_path=path)
    assert args.temp_warn == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# parse_args — --config flag selects custom path
# ---------------------------------------------------------------------------

def test_parse_args_config_flag_selects_file(tmp_path):
    path = write_conf(tmp_path, """
        [display]
        refresh = 7
    """)
    args = parse_args(["--config", path])
    assert args.refresh == pytest.approx(7.0)


def test_parse_args_config_flag_missing_file_uses_defaults(tmp_path):
    missing = str(tmp_path / "ghost.conf")
    args = parse_args(["--config", missing])
    assert args.refresh == pytest.approx(5.0)  # hardcoded default
