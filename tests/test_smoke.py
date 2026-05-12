"""
Smoke tests — verify the package is importable, the CLI works, and the
main data path (parse_args → _read_all → _build_screens) is coherent.
All tests run without Pi hardware.
"""
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Package imports
# ---------------------------------------------------------------------------

def test_top_level_package_has_version():
    import porcupine
    assert hasattr(porcupine, "__version__")
    assert porcupine.__version__


def test_all_monitor_modules_importable():
    from porcupine.monitors import boot, power, cpu_mem, temperature, network
    for mod in (boot, power, cpu_mem, temperature, network):
        assert callable(mod.read)


def test_all_interface_classes_importable():
    from porcupine.interfaces.lcd import LCD
    from porcupine.interfaces.button import Button
    from porcupine.interfaces.buzzer import Buzzer, AlertChecker
    for cls in (LCD, Button, Buzzer, AlertChecker):
        assert callable(cls)


def test_config_module_importable():
    from porcupine.config import load_config, parse_args
    assert callable(load_config)
    assert callable(parse_args)


def test_daemon_module_importable():
    import porcupine.daemon as daemon
    assert callable(daemon.run)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def test_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "porcupine", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "porcupine" in result.stdout.lower()


def test_help_lists_monitor_flags():
    result = subprocess.run(
        [sys.executable, "-m", "porcupine", "--help"],
        capture_output=True, text=True,
    )
    for flag in ("--boot", "--power", "--cpu", "--temp", "--net"):
        assert flag in result.stdout


def test_help_lists_config_flag():
    result = subprocess.run(
        [sys.executable, "-m", "porcupine", "--help"],
        capture_output=True, text=True,
    )
    assert "--config" in result.stdout


# ---------------------------------------------------------------------------
# parse_args end-to-end
# ---------------------------------------------------------------------------

def test_parse_args_defaults_without_config(tmp_path):
    from porcupine.config import parse_args
    args = parse_args([], config_path=str(tmp_path / "none.conf"))
    assert all(getattr(args, f) for f in ("boot", "power", "cpu", "temp", "net"))
    assert args.lcd_addr   == 0x27
    assert args.button_pin == 4
    assert args.buzzer_pin == 18
    assert args.refresh    == pytest.approx(3.0)


def test_parse_args_no_power_flag(tmp_path):
    from porcupine.config import parse_args
    args = parse_args(["--no-power"], config_path=str(tmp_path / "none.conf"))
    assert args.power is False
    assert args.cpu   is True


# ---------------------------------------------------------------------------
# Config file round-trip with sample file
# ---------------------------------------------------------------------------

def test_sample_config_parses_without_error():
    from porcupine.config import load_config
    example = Path(__file__).parent.parent / "install" / "porcupine.conf.example"
    cfg = load_config(str(example))
    assert cfg.get("boot") is True
    assert cfg.get("lcd_addr") == 0x27
    assert cfg.get("refresh") == pytest.approx(3.0)
    assert cfg.get("temp_warn") == pytest.approx(80.0)


def test_sample_config_inline_comments_stripped():
    """Inline # comments in the example file must not bleed into values."""
    from porcupine.config import load_config
    example = Path(__file__).parent.parent / "install" / "porcupine.conf.example"
    cfg = load_config(str(example))
    # If inline comment stripping failed, getfloat would have raised ValueError
    assert isinstance(cfg.get("temp_warn"), float)
    assert isinstance(cfg.get("cpu_warn"),  float)
    assert isinstance(cfg.get("mem_warn"),  float)


# ---------------------------------------------------------------------------
# Data path: _read_all → _build_screens
# ---------------------------------------------------------------------------

def test_build_screens_end_to_end(tmp_path):
    from porcupine.config import parse_args
    import porcupine.daemon as daemon

    args = parse_args(
        ["--no-power", "--no-temp", "--no-net", "--no-gpio"],
        config_path=str(tmp_path / "none.conf"),
    )
    data = {
        "boot_count": 3, "uptime_s": 3720.0,
        "cpu_avg_pct": 25.0, "mem_pct": 48.0,
        "cpu_pct": [], "mem_used_mb": 500, "mem_total_mb": 1024,
    }
    screens = daemon._build_screens(args, data)
    assert len(screens) == 2
    assert screens[0][0] == "Boot"
    assert screens[1][0] == "CPU      Mem"


def test_read_all_disabled_monitors_returns_empty(tmp_path):
    from porcupine.config import parse_args
    import porcupine.daemon as daemon

    args = parse_args(
        ["--no-boot", "--no-power", "--no-cpu", "--no-temp", "--no-net", "--no-gpio"],
        config_path=str(tmp_path / "none.conf"),
    )
    data = daemon._read_all(args)
    assert data == {}


# ---------------------------------------------------------------------------
# Interface stubs work without hardware
# ---------------------------------------------------------------------------

def test_lcd_show_and_clear():
    from porcupine.interfaces.lcd import LCD
    lcd = LCD()
    lcd.show("Line 1", "Line 2")
    lcd.clear()


def test_buzzer_beep_without_hardware():
    from porcupine.interfaces.buzzer import Buzzer
    bz = Buzzer(pin=18)
    with patch("porcupine.interfaces.buzzer.time.sleep"):
        bz.beep(count=1, duration_ms=50)


def test_button_start_stop_without_hardware():
    from porcupine.interfaces.button import Button
    btn = Button(pin=17)
    btn.start()
    btn.stop()


def test_alert_checker_empty_data():
    from porcupine.interfaces.buzzer import AlertChecker, Buzzer
    checker = AlertChecker(Buzzer(pin=18))
    checker.check({})   # must not raise


# ---------------------------------------------------------------------------
# Install artefact checks
# ---------------------------------------------------------------------------

def test_service_file_contains_placeholder():
    svc = Path(__file__).parent.parent / "install" / "porcupine.service"
    assert "@@PORCUPINE_BIN@@" in svc.read_text(), \
        "setup.sh substitutes @@PORCUPINE_BIN@@ — placeholder must exist in template"


def test_service_file_references_config():
    svc = Path(__file__).parent.parent / "install" / "porcupine.service"
    assert "/etc/porcupine/porcupine.conf" in svc.read_text()


def test_setup_script_is_executable():
    setup = Path(__file__).parent.parent / "install" / "setup.sh"
    assert setup.exists()
    assert setup.stat().st_mode & 0o111, "setup.sh must be executable"


def test_setup_script_orchestrates_three_steps():
    setup = Path(__file__).parent.parent / "install" / "setup.sh"
    text = setup.read_text()
    assert "1_install.sh" in text
    assert "2_test.sh" in text
    assert "3_enable.sh" in text


def test_step1_uses_venv():
    step1 = Path(__file__).parent.parent / "install" / "1_install.sh"
    text = step1.read_text()
    assert "VENV_DIR" in text
    assert "venv" in text
    assert "/opt/porcupine/venv" in text


def test_step1_has_prompt_functions():
    step1 = Path(__file__).parent.parent / "install" / "1_install.sh"
    text = step1.read_text()
    for fn in ("prompt()", "prompt_bool()", "configure_interactive()",
               "configure_noninteractive()", "write_config()"):
        assert fn in text, f"1_install.sh must define {fn}"


def test_step1_writes_all_config_keys():
    step1 = Path(__file__).parent.parent / "install" / "1_install.sh"
    text = step1.read_text()
    for key in ("lcd_addr", "button_pin", "buzzer_pin", "ina219_addr", "refresh",
                "temp_warn", "cpu_warn", "mem_warn",
                "boot", "power", "cpu", "temp", "net"):
        assert key in text, f"1_install.sh must write config key: {key}"


def test_step2_tests_all_interfaces():
    step2 = Path(__file__).parent.parent / "install" / "2_test.sh"
    text = step2.read_text()
    for subcmd in ("lcd", "buzzer", "button-short", "button-long",
                   "monitor-boot", "monitor-power", "monitor-cpu", "monitor-temp", "monitor-net"):
        assert subcmd in text, f"2_test.sh must invoke test_hardware.py {subcmd}"


def test_step3_enables_service():
    step3 = Path(__file__).parent.parent / "install" / "3_enable.sh"
    text = step3.read_text()
    assert "systemctl enable" in text
    assert "systemctl is-active" in text


def test_test_hardware_py_has_all_commands():
    hw = Path(__file__).parent.parent / "install" / "test_hardware.py"
    text = hw.read_text()
    for cmd in ("lcd", "buzzer", "button-short", "button-long",
                "monitor-boot", "monitor-power", "monitor-cpu", "monitor-temp", "monitor-net"):
        assert f'"{cmd}"' in text, f"test_hardware.py must handle command: {cmd}"


def test_all_install_scripts_executable():
    install = Path(__file__).parent.parent / "install"
    for name in ("setup.sh", "1_install.sh", "2_test.sh", "3_enable.sh", "check.sh"):
        f = install / name
        assert f.exists(), f"{name} must exist"
        assert f.stat().st_mode & 0o111, f"{name} must be executable"


def test_check_script_exists():
    check = Path(__file__).parent.parent / "install" / "check.sh"
    assert check.exists()
