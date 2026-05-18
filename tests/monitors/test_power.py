"""Unit tests for porcupine.monitors.power (INA219 monitor)."""
import math
from unittest.mock import MagicMock, patch

import pytest

import porcupine.monitors.power as power_mod


@pytest.fixture(autouse=True)
def reset_power_state():
    """Reset module-level state before each test."""
    orig_bus  = power_mod._bus
    orig_addr = power_mod._addr
    yield
    power_mod._bus  = orig_bus
    power_mod._addr = orig_addr


# ---------------------------------------------------------------------------
# init()
# ---------------------------------------------------------------------------

def test_init_without_smbus_does_not_raise():
    """init() should be a no-op when smbus is unavailable."""
    with patch.object(power_mod, "_HAS_SMBUS", False):
        power_mod._bus = None
        power_mod.init(addr=0x41)
    # _bus stays None; addr is still updated
    assert power_mod._addr == 0x41


def test_init_with_smbus_opens_bus_and_writes_calibration():
    mock_bus = MagicMock()
    fake_smbus = MagicMock()
    fake_smbus.SMBus.return_value = mock_bus

    with patch.object(power_mod, "_HAS_SMBUS", True), \
         patch.object(power_mod, "_smbus", fake_smbus, create=True):
        power_mod.init(addr=0x41)

    fake_smbus.SMBus.assert_called_once_with(1)
    # Calibration register must be the first write
    first_write = mock_bus.write_i2c_block_data.call_args_list[0]
    assert first_write[0][1] == power_mod._REG_CALIBRATION


def test_init_smbus_exception_leaves_bus_none():
    """If SMBus raises, _bus must be set to None (no partial state)."""
    fake_smbus = MagicMock()
    fake_smbus.SMBus.side_effect = OSError("no i2c")

    with patch.object(power_mod, "_HAS_SMBUS", True), \
         patch.object(power_mod, "_smbus", fake_smbus, create=True):
        power_mod.init(addr=0x41)

    assert power_mod._bus is None


# ---------------------------------------------------------------------------
# read() — no hardware
# ---------------------------------------------------------------------------

def test_read_without_bus_returns_unknown():
    power_mod._bus = None
    result = power_mod.read()
    assert result["power_source"] == "Unknown"
    assert math.isnan(result["battery_pct"])


# ---------------------------------------------------------------------------
# read() — with mock hardware
# ---------------------------------------------------------------------------

def _make_mock_bus(current_raw: int, bus_voltage_raw: int) -> MagicMock:
    """Return a mock _bus that yields given raw register words."""
    mock = MagicMock()

    def _read_block(addr, reg, length):
        if reg == power_mod._REG_CURRENT:
            v = current_raw & 0xFFFF
        else:
            v = bus_voltage_raw & 0xFFFF
        return [v >> 8, v & 0xFF]

    mock.read_i2c_block_data.side_effect = _read_block
    return mock


def test_read_plugged_in_positive_current():
    # Positive current (charging / plugged in)
    # current_raw=100 → 100 * 0.1524 mA ≈ 15.24 mA (positive → "Plugged In")
    # bus_voltage_raw: encode 11.0 V → raw = int(11.0 / 0.004) << 3 = 2750 << 3
    v_raw = (int(11.0 / 0.004)) << 3
    power_mod._bus  = _make_mock_bus(current_raw=100, bus_voltage_raw=v_raw)
    power_mod._addr = 0x41

    result = power_mod.read()
    assert result["power_source"] == "Plugged In"
    assert 0.0 <= result["battery_pct"] <= 100.0


def test_read_on_battery_negative_current():
    # Negative current (discharging) — raw is two's-complement 16-bit
    # current_raw = 65536 - 100 = 65436 → negative after subtraction
    v_raw = (int(10.5 / 0.004)) << 3
    power_mod._bus  = _make_mock_bus(current_raw=65436, bus_voltage_raw=v_raw)
    power_mod._addr = 0x41

    result = power_mod.read()
    assert result["power_source"] == "Battery"


def test_read_battery_pct_clamped_to_0_100():
    # Voltage below minimum → 0 %
    v_raw_low = (int(8.0 / 0.004)) << 3
    power_mod._bus  = _make_mock_bus(current_raw=65436, bus_voltage_raw=v_raw_low)
    result = power_mod.read()
    assert result["battery_pct"] == 0.0

    # Voltage above maximum → 100 %
    v_raw_high = (int(13.5 / 0.004)) << 3
    power_mod._bus  = _make_mock_bus(current_raw=65436, bus_voltage_raw=v_raw_high)
    result = power_mod.read()
    assert result["battery_pct"] == 100.0


def test_read_smbus_exception_returns_unknown():
    mock_bus = MagicMock()
    mock_bus.read_i2c_block_data.side_effect = OSError("i2c error")
    power_mod._bus  = mock_bus
    power_mod._addr = 0x41

    result = power_mod.read()
    assert result["power_source"] == "Unknown"
    assert math.isnan(result["battery_pct"])


def test_read_returns_expected_keys():
    power_mod._bus = None
    result = power_mod.read()
    assert set(result) == {"power_source", "battery_pct"}


def test_read_does_not_write_calibration_register():
    """read() must not re-write the calibration register; init() owns that."""
    v_raw = (int(11.0 / 0.004)) << 3
    mock_bus = _make_mock_bus(current_raw=100, bus_voltage_raw=v_raw)
    power_mod._bus  = mock_bus
    power_mod._addr = 0x41

    power_mod.read()

    written_regs = [c[0][1] for c in mock_bus.write_i2c_block_data.call_args_list]
    assert power_mod._REG_CALIBRATION not in written_regs
