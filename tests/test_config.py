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

def test_load_config_reads_monitor_every(tmp_path):
    path = write_conf(tmp_path, """
        [monitors]
        power_every = 2
        cpu_every   = 0
        temp_every  = 3
        net_every   = 1
    """)
    cfg = load_config(path)
    assert cfg["power_every"] == 2
    assert cfg["cpu_every"]   == 0
    assert cfg["temp_every"]  == 3
    assert cfg["net_every"]   == 1


def test_load_config_partial_monitors_section(tmp_path):
    path = write_conf(tmp_path, """
        [monitors]
        cpu_every = 0
    """)
    cfg = load_config(path)
    assert cfg["cpu_every"] == 0
    assert "power_every" not in cfg
    assert "temp_every" not in cfg


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
        boot_every  = 10
        power_every = 5
        cpu_every   = 5
        temp_every  = 1
        net_every   = 10
        gpio_every  = 2
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
    assert cfg["boot_every"]  == 10
    assert cfg["power_every"] == 5
    assert cfg["gpio_every"]  == 2
    assert cfg["lcd_addr"]    == 0x27
    assert cfg["refresh"]     == pytest.approx(3.0)
    assert cfg["temp_warn"]   == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# parse_args — hardcoded defaults (no config file, no CLI flags)
# ---------------------------------------------------------------------------

def test_parse_args_defaults_all_monitors_enabled(tmp_path):
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert args.boot_every  == 10
    assert args.power_every == 5
    assert args.cpu_every   == 5
    assert args.temp_every  == 1
    assert args.net_every   == 10
    assert args.gpio_every  == 2


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
    args = parse_args(["--cpu-every", "0", "--temp-every", "0", "--net-every", "0"],
                      config_path=str(tmp_path / "none.conf"))
    assert args.power_every == 5   # unchanged default
    assert args.cpu_every   == 0
    assert args.temp_every  == 0
    assert args.net_every   == 0


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
        power_every = 0
        cpu_every   = 1
        temp_every  = 0
        net_every   = 2
    """)
    args = parse_args([], config_path=path)
    assert args.power_every == 0
    assert args.cpu_every   == 1
    assert args.temp_every  == 0
    assert args.net_every   == 2


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
        power_every = 0
    """)
    # Config says power_every=0, CLI says --power-every 1 → CLI wins
    args = parse_args(["--power-every", "1"], config_path=path)
    assert args.power_every == 1


def test_cli_overrides_config_file_numeric(tmp_path):
    path = write_conf(tmp_path, """
        [display]
        refresh = 10
    """)
    args = parse_args(["--refresh", "3"], config_path=path)
    assert args.refresh == pytest.approx(3.0)


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


# ---------------------------------------------------------------------------
# parse_args — validation rejects out-of-range values
# ---------------------------------------------------------------------------

def test_validate_refresh_below_minimum_rejected(tmp_path):
    with pytest.raises(SystemExit):
        parse_args(["--refresh", "2"], config_path=str(tmp_path / "none.conf"))


def test_validate_refresh_above_maximum_rejected(tmp_path):
    with pytest.raises(SystemExit):
        parse_args(["--refresh", "301"], config_path=str(tmp_path / "none.conf"))


def test_validate_refresh_boundary_values_accepted(tmp_path):
    cfg = str(tmp_path / "none.conf")
    assert parse_args(["--refresh", "3"],   config_path=cfg).refresh == pytest.approx(3.0)
    assert parse_args(["--refresh", "300"], config_path=cfg).refresh == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# load_config — [fan] section
# ---------------------------------------------------------------------------

def test_load_config_reads_fan_section(tmp_path):
    path = write_conf(tmp_path, """
        [fan]
        fan_enabled  = true
        fan_pin      = 19
        fan_type     = 4pin
        fan_min_duty = 20
    """)
    cfg = load_config(path)
    assert cfg["fan_enabled"]  is True
    assert cfg["fan_pin"]      == 19
    assert cfg["fan_type"]     == "4pin"
    assert cfg["fan_min_duty"] == 20


def test_load_config_fan_disabled(tmp_path):
    path = write_conf(tmp_path, """
        [fan]
        fan_enabled = false
    """)
    cfg = load_config(path)
    assert cfg["fan_enabled"] is False


def test_load_config_missing_fan_section_returns_no_fan_keys(tmp_path):
    path = write_conf(tmp_path, """
        [monitors]
        cpu_every = 5
    """)
    cfg = load_config(path)
    assert "fan_enabled" not in cfg
    assert "fan_pin"     not in cfg


# ---------------------------------------------------------------------------
# parse_args — fan flags
# ---------------------------------------------------------------------------

def test_parse_args_fan_defaults(tmp_path):
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert args.fan_enabled  is False
    assert args.fan_pin      == 19
    assert args.fan_type     == "3pin"
    assert args.fan_min_duty == 30


def test_parse_args_fan_enabled_flag(tmp_path):
    cfg = str(tmp_path / "none.conf")
    args = parse_args(["--fan-enabled"], config_path=cfg)
    assert args.fan_enabled is True


def test_parse_args_fan_cli_flags(tmp_path):
    cfg = str(tmp_path / "none.conf")
    args = parse_args(
        ["--fan-enabled", "--fan-pin", "13", "--fan-type", "4pin", "--fan-min-duty", "20"],
        config_path=cfg,
    )
    assert args.fan_enabled  is True
    assert args.fan_pin      == 13
    assert args.fan_type     == "4pin"
    assert args.fan_min_duty == 20


def test_parse_args_fan_config_file(tmp_path):
    path = write_conf(tmp_path, """
        [fan]
        fan_enabled  = true
        fan_pin      = 19
        fan_type     = 3pin
        fan_min_duty = 30
    """)
    args = parse_args([], config_path=path)
    assert args.fan_enabled is True
    assert args.fan_type    == "3pin"


def test_parse_args_fan_cli_overrides_config(tmp_path):
    path = write_conf(tmp_path, """
        [fan]
        fan_enabled = false
        fan_type    = 3pin
    """)
    args = parse_args(["--fan-enabled", "--fan-type", "4pin"], config_path=path)
    assert args.fan_enabled is True
    assert args.fan_type    == "4pin"


def test_parse_args_fan_freq_default_is_none(tmp_path):
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert args.fan_freq is None


def test_parse_args_fan_freq_cli(tmp_path):
    args = parse_args(["--fan-freq", "10000"], config_path=str(tmp_path / "none.conf"))
    assert args.fan_freq == 10000


def test_load_config_reads_fan_freq(tmp_path):
    path = write_conf(tmp_path, """
        [fan]
        fan_freq = 10000
    """)
    assert load_config(path)["fan_freq"] == 10000


def test_validate_fan_freq_out_of_range(tmp_path):
    cfg = str(tmp_path / "none.conf")
    with pytest.raises(SystemExit):
        parse_args(["--fan-freq", "50"], config_path=cfg)


def test_validate_fan_invalid_min_duty_rejected(tmp_path):
    cfg = str(tmp_path / "none.conf")
    with pytest.raises(SystemExit):
        parse_args(["--fan-min-duty", "101"], config_path=cfg)


def test_validate_fan_pin_out_of_range_when_enabled(tmp_path):
    cfg = str(tmp_path / "none.conf")
    with pytest.raises(SystemExit):
        parse_args(["--fan-enabled", "--fan-pin", "99"], config_path=cfg)


# ---------------------------------------------------------------------------
# load_config — alerts section (bat_warn, disk_warn, conn_host, alert_log)
# ---------------------------------------------------------------------------

def test_load_config_reads_bat_warn(tmp_path):
    path = write_conf(tmp_path, """
        [alerts]
        bat_warn = 20
    """)
    assert load_config(path)["bat_warn"] == pytest.approx(20.0)


def test_load_config_reads_disk_warn(tmp_path):
    path = write_conf(tmp_path, """
        [alerts]
        disk_warn = 90
    """)
    assert load_config(path)["disk_warn"] == pytest.approx(90.0)


def test_load_config_reads_alert_log(tmp_path):
    path = write_conf(tmp_path, """
        [alerts]
        alert_log = /var/log/porcupine/alerts.log
    """)
    assert load_config(path)["alert_log"] == "/var/log/porcupine/alerts.log"


def test_load_config_reads_conn_host(tmp_path):
    path = write_conf(tmp_path, """
        [network]
        conn_host = 1.1.1.1
    """)
    assert load_config(path)["conn_host"] == "1.1.1.1"


def test_load_config_reads_ina219_addr(tmp_path):
    path = write_conf(tmp_path, """
        [hardware]
        ina219_addr = 0x40
    """)
    assert load_config(path)["ina219_addr"] == 0x40


def test_load_config_reads_only_alert(tmp_path):
    path = write_conf(tmp_path, """
        [display]
        only_alert = true
    """)
    assert load_config(path)["only_alert"] is True


# ---------------------------------------------------------------------------
# parse_args — alert/network/display flags
# ---------------------------------------------------------------------------

def test_parse_args_bat_warn_default(tmp_path):
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert args.bat_warn == pytest.approx(40.0)


def test_parse_args_disk_warn_default(tmp_path):
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert args.disk_warn == pytest.approx(85.0)


def test_parse_args_conn_host_default(tmp_path):
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert args.conn_host == "8.8.8.8"


def test_parse_args_disk_warn_cli(tmp_path):
    args = parse_args(["--disk-warn", "90"], config_path=str(tmp_path / "none.conf"))
    assert args.disk_warn == pytest.approx(90.0)


def test_parse_args_conn_host_cli(tmp_path):
    args = parse_args(["--conn-host", "1.1.1.1"], config_path=str(tmp_path / "none.conf"))
    assert args.conn_host == "1.1.1.1"


def test_validate_disk_warn_out_of_range(tmp_path):
    cfg = str(tmp_path / "none.conf")
    with pytest.raises(SystemExit):
        parse_args(["--disk-warn", "101"], config_path=cfg)

