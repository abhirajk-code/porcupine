"""GPIO pin monitor tests — no hardware required."""
import pytest
import porcupine.monitors.gpio_pins as gpio_pins


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _debugfs_content(pins: list[tuple[int, str, int]], base: int = 0) -> str:
    """Build a minimal /sys/kernel/debug/gpio file.  pins = [(bcm, dir, value)]."""
    end = base + 53
    lines = [f"gpiochip0: GPIOs {base}-{end}, parent: platform/gpio, pinctrl-bcm2835:"]
    for bcm, direction, value in pins:
        level = "hi" if value else "lo"
        lines.append(
            f" gpio-{base + bcm:<4} (GPIO{bcm:<16}|{'':20}) {direction}  {level}"
        )
    return "\n".join(lines) + "\n"


@pytest.fixture
def fake_debugfs(tmp_path, monkeypatch):
    """Patch _DEBUG_GPIO to a temp file; caller writes content into it."""
    p = tmp_path / "gpio"
    p.write_text("")
    monkeypatch.setattr(gpio_pins, "_DEBUG_GPIO", p)
    return p


@pytest.fixture
def fake_sysfs(tmp_path, monkeypatch):
    """Patch _SYSFS_ROOT for sysfs fallback tests."""
    monkeypatch.setattr(gpio_pins, "_SYSFS_ROOT", tmp_path)
    return tmp_path


def _make_sysfs_gpio(sysfs_root, bcm: int, direction: str, value: int):
    d = sysfs_root / f"gpio{bcm}"
    d.mkdir()
    (d / "direction").write_text(direction)
    (d / "value").write_text(str(value))


# ---------------------------------------------------------------------------
# Fixed pin states (power/gnd — no GPIO read needed)
# ---------------------------------------------------------------------------

def test_read_returns_40_entries():
    assert len(gpio_pins.read()["gpio_pins"]) == 40


def test_fixed_power_and_gnd_pins():
    pins = gpio_pins.read()["gpio_pins"]
    assert pins[0]  == "3v3"   # physical pin 1
    assert pins[1]  == "5v"    # physical pin 2
    assert pins[3]  == "5v"    # physical pin 4
    assert pins[5]  == "gnd"   # physical pin 6
    assert pins[16] == "3v3"   # physical pin 17
    assert pins[38] == "gnd"   # physical pin 39


def test_unexported_gpio_returns_none():
    # BCM 4 (physical pin 7, index 6) — not in debugfs or sysfs by default
    assert gpio_pins.read()["gpio_pins"][6] is None


# ---------------------------------------------------------------------------
# debugfs reads (primary path)
# ---------------------------------------------------------------------------

def test_gpio_output_high(fake_debugfs):
    fake_debugfs.write_text(_debugfs_content([(4, "out", 1)]))
    assert gpio_pins.read()["gpio_pins"][6] == "out_h"   # pin 7 → index 6 → BCM 4


def test_gpio_output_low(fake_debugfs):
    fake_debugfs.write_text(_debugfs_content([(4, "out", 0)]))
    assert gpio_pins.read()["gpio_pins"][6] == "out_l"


def test_gpio_input_high(fake_debugfs):
    fake_debugfs.write_text(_debugfs_content([(17, "in", 1)]))
    assert gpio_pins.read()["gpio_pins"][10] == "in_h"   # pin 11 → index 10 → BCM 17


def test_gpio_input_low(fake_debugfs):
    fake_debugfs.write_text(_debugfs_content([(17, "in", 0)]))
    assert gpio_pins.read()["gpio_pins"][10] == "in_l"


def test_multiple_gpio_pins(fake_debugfs):
    fake_debugfs.write_text(_debugfs_content([(4, "out", 1), (17, "in", 0)]))
    pins = gpio_pins.read()["gpio_pins"]
    assert pins[6]  == "out_h"
    assert pins[10] == "in_l"


def test_debugfs_pi5_chip_offset(fake_debugfs):
    # Pi 5: main GPIO chip starts at a large base offset (e.g. 571)
    fake_debugfs.write_text(_debugfs_content([(4, "out", 1), (17, "in", 0)], base=571))
    pins = gpio_pins.read()["gpio_pins"]
    assert pins[6]  == "out_h"
    assert pins[10] == "in_l"


def test_debugfs_small_chip_ignored(fake_debugfs):
    # A small chip (< 28 pins) should not be treated as the header GPIO chip
    content = (
        "gpiochip0: GPIOs 0-7, parent: i2c/1-0020, mcp23008:\n"
        " gpio-4   (GPIO4               |                    ) out  hi\n"
        "gpiochip1: GPIOs 100-153, parent: platform/gpio, pinctrl-bcm2835:\n"
    )
    fake_debugfs.write_text(content)
    # BCM 4 on the small chip (index 4 from base 0) should NOT appear —
    # only the large chip (base=100) is considered; gpio-104 → BCM 4 is absent
    assert gpio_pins.read()["gpio_pins"][6] is None


def test_debugfs_label_captured(fake_debugfs):
    content = _debugfs_content([])
    # Insert a line with a real label (e.g. sysfs-exported pin)
    content += " gpio-4   (GPIO4               |sysfs               ) in  hi IRQ\n"
    fake_debugfs.write_text(content)
    pins = gpio_pins.read()["gpio_pins"]
    assert pins[6] == "in_h"


# ---------------------------------------------------------------------------
# sysfs fallback (when debugfs is unreadable)
# ---------------------------------------------------------------------------

def test_sysfs_fallback_when_debugfs_empty(fake_debugfs, fake_sysfs):
    # debugfs file exists but is empty → falls back to sysfs
    fake_debugfs.write_text("")
    _make_sysfs_gpio(fake_sysfs, bcm=4, direction="out", value=1)
    assert gpio_pins.read()["gpio_pins"][6] == "out_h"


def test_sysfs_fallback_when_debugfs_missing(tmp_path, monkeypatch, fake_sysfs):
    # Point _DEBUG_GPIO at a path that does not exist → OSError → sysfs
    monkeypatch.setattr(gpio_pins, "_DEBUG_GPIO", tmp_path / "nonexistent")
    _make_sysfs_gpio(fake_sysfs, bcm=17, direction="in", value=0)
    assert gpio_pins.read()["gpio_pins"][10] == "in_l"


# ---------------------------------------------------------------------------
# _GpioMonitor.format_screens (via daemon)
# ---------------------------------------------------------------------------

def test_fmt_gpio_row_lengths():
    from porcupine.daemon import _GpioMonitor
    data = {"gpio_pins": gpio_pins.read()["gpio_pins"]}
    for page in (1, 2):
        (r1, r2), = _GpioMonitor(page=page).format_screens(data)
        assert len(r1) == 16
        assert len(r2) == 16


def test_fmt_gpio_fixed_pin_chars():
    from porcupine.daemon import _GpioMonitor
    data = {"gpio_pins": gpio_pins.read()["gpio_pins"]}
    (r1_p1, r2_p1), = _GpioMonitor(page=1).format_screens(data)
    assert r1_p1[3] == "+"   # pin 0 → 3v3
    assert r2_p1[3] == "^"   # pin 1 → 5v
    assert r2_p1[5] == "_"   # pin 5 → gnd


def test_fmt_gpio_gpio_chars(fake_debugfs):
    from porcupine.daemon import _GpioMonitor
    fake_debugfs.write_text(_debugfs_content([(4, "out", 1)]))
    data = {"gpio_pins": gpio_pins.read()["gpio_pins"]}
    (r1_p1, _), = _GpioMonitor(page=1).format_screens(data)
    assert r1_p1[6] == chr(0)   # BCM 4, out_h → custom char slot 0


def test_fmt_gpio_unconfigured_is_space():
    from porcupine.daemon import _GpioMonitor
    data = {"gpio_pins": [None] * 40}
    (r1_p1, r2_p1), = _GpioMonitor(page=1).format_screens(data)
    (r1_p2, r2_p2), = _GpioMonitor(page=2).format_screens(data)
    for row in (r1_p1, r2_p1, r1_p2, r2_p2):
        assert row[3:13] == " " * 10


def test_fmt_gpio_short_list_padded():
    from porcupine.daemon import _GpioMonitor
    (r1, r2), = _GpioMonitor(page=1).format_screens({"gpio_pins": []})
    assert len(r1) == 16
    assert len(r2) == 16
    assert r1[3:13] == " " * 10
