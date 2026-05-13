"""GPIO pin monitor tests — no hardware required."""
import pytest
import porcupine.monitors.gpio_pins as gpio_pins


# ---------------------------------------------------------------------------
# Fixed pin states
# ---------------------------------------------------------------------------

def test_read_returns_40_entries():
    result = gpio_pins.read()
    assert len(result["gpio_pins"]) == 40


def test_fixed_power_and_gnd_pins():
    result = gpio_pins.read()
    pins = result["gpio_pins"]
    # Physical pin 1 → index 0 → 3.3V
    assert pins[0] == "3v3"
    # Physical pin 2 → index 1 → 5V
    assert pins[1] == "5v"
    # Physical pin 4 → index 3 → 5V
    assert pins[3] == "5v"
    # Physical pin 6 → index 5 → GND
    assert pins[5] == "gnd"
    # Physical pin 17 → index 16 → 3.3V
    assert pins[16] == "3v3"
    # Physical pin 39 → index 38 → GND
    assert pins[38] == "gnd"


def test_unexported_gpio_returns_none():
    # BCM 4 (physical pin 7, index 6) — not exported in sysfs by default
    result = gpio_pins.read()
    pins = result["gpio_pins"]
    assert pins[6] is None


# ---------------------------------------------------------------------------
# GPIO sysfs reads (monkeypatched)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_sysfs(tmp_path, monkeypatch):
    monkeypatch.setattr(gpio_pins, "_SYSFS_ROOT", tmp_path)
    return tmp_path


def _make_gpio(sysfs_root, bcm: int, direction: str, value: int):
    d = sysfs_root / f"gpio{bcm}"
    d.mkdir()
    (d / "direction").write_text(direction)
    (d / "value").write_text(str(value))


def test_gpio_output_high(fake_sysfs):
    _make_gpio(fake_sysfs, bcm=4, direction="out", value=1)
    result = gpio_pins.read()
    assert result["gpio_pins"][6] == "out_h"   # physical pin 7 → index 6 → BCM 4


def test_gpio_output_low(fake_sysfs):
    _make_gpio(fake_sysfs, bcm=4, direction="out", value=0)
    result = gpio_pins.read()
    assert result["gpio_pins"][6] == "out_l"


def test_gpio_input_high(fake_sysfs):
    _make_gpio(fake_sysfs, bcm=17, direction="in", value=1)
    result = gpio_pins.read()
    assert result["gpio_pins"][10] == "in_h"   # physical pin 11 → index 10 → BCM 17


def test_gpio_input_low(fake_sysfs):
    _make_gpio(fake_sysfs, bcm=17, direction="in", value=0)
    result = gpio_pins.read()
    assert result["gpio_pins"][10] == "in_l"


def test_multiple_gpio_pins(fake_sysfs):
    _make_gpio(fake_sysfs, bcm=4,  direction="out", value=1)
    _make_gpio(fake_sysfs, bcm=17, direction="in",  value=0)
    pins = gpio_pins.read()["gpio_pins"]
    assert pins[6]  == "out_h"
    assert pins[10] == "in_l"


# ---------------------------------------------------------------------------
# _fmt_gpio character mapping (via daemon)
# Each page is a (row1, row2) tuple; rows are 16-char strings: "PP[CCCCCCCCCC]PP"
# Chars [3:13] are the 10 pin-status characters.
# ---------------------------------------------------------------------------

def test_fmt_gpio_row_lengths():
    from porcupine.daemon import _fmt_gpio
    data = {"gpio_pins": gpio_pins.read()["gpio_pins"]}
    pages = _fmt_gpio(data)
    assert len(pages) == 2
    for r1, r2 in pages:
        assert len(r1) == 16
        assert len(r2) == 16


def test_fmt_gpio_fixed_pin_chars():
    from porcupine.daemon import _fmt_gpio
    data = {"gpio_pins": gpio_pins.read()["gpio_pins"]}
    (r1_p1, r2_p1), _ = _fmt_gpio(data)
    # Page 1, row 1: odd-indexed pins (0,2,4,...) → pin 0 is 3v3 → "+" at bracket pos 0 = char[3]
    assert r1_p1[3] == "+"
    # Page 1, row 2: even-indexed pins (1,3,5,...) → pin 1 is 5v → "^" at char[3]
    assert r2_p1[3] == "^"
    # pin 5 is gnd → "_" at bracket pos 2 of row2 = char[5]
    assert r2_p1[5] == "_"


def test_fmt_gpio_gpio_chars(fake_sysfs):
    from porcupine.daemon import _fmt_gpio
    _make_gpio(fake_sysfs, bcm=4, direction="out", value=1)
    data = {"gpio_pins": gpio_pins.read()["gpio_pins"]}
    (r1_p1, _), _ = _fmt_gpio(data)
    # pin index 6 (BCM 4, out_h) is at row1 bracket pos 3 = char[6]
    assert r1_p1[6] == chr(0)


def test_fmt_gpio_unconfigured_is_space():
    from porcupine.daemon import _fmt_gpio
    data = {"gpio_pins": [None] * 40}
    (r1_p1, r2_p1), (r1_p2, r2_p2) = _fmt_gpio(data)
    for row in (r1_p1, r2_p1, r1_p2, r2_p2):
        assert row[3:13] == " " * 10


def test_fmt_gpio_short_list_padded():
    from porcupine.daemon import _fmt_gpio
    (r1, r2), _ = _fmt_gpio({"gpio_pins": []})
    assert len(r1) == 16
    assert len(r2) == 16
    assert r1[3:13] == " " * 10
