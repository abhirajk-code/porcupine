"""INA219-based power source and battery percentage monitor."""

_HAS_SMBUS = False
try:
    import smbus as _smbus
    _HAS_SMBUS = True
except ImportError:
    try:
        import smbus2 as _smbus  # type: ignore[no-redef]
        _HAS_SMBUS = True
    except ImportError:
        pass

_REG_CONFIG      = 0x00
_REG_BUSVOLTAGE  = 0x02
_REG_CURRENT     = 0x04
_REG_CALIBRATION = 0x05

# 16V / 5A calibration with 0.01 Ω shunt — matches scratchpad/INA219.py
_CAL_VALUE   = 26868
_CURRENT_LSB = 0.1524   # mA per raw LSB

# 3S Li-ion battery voltage range (3×3.0V = 9.0V min, 3×4.2V = 12.6V max)
_VBAT_MIN = 9.0
_VBAT_MAX = 12.6

_bus:  object = None
_addr: int    = 0x40


def init(addr: int = 0x40) -> None:
    """Initialise INA219 and write calibration register. Call once at startup."""
    global _bus, _addr
    _addr = addr
    if not _HAS_SMBUS:
        return
    try:
        _bus = _smbus.SMBus(1)
        _write(_REG_CALIBRATION, _CAL_VALUE)
        # 16V range | gain /2 (80 mV) | 12-bit 32-sample bus & shunt | continuous
        config = (0x00 << 13) | (0x01 << 11) | (0x0D << 7) | (0x0D << 3) | 0x07
        _write(_REG_CONFIG, config)
    except Exception:
        _bus = None


def read() -> dict:
    if _bus is None:
        return {"power_source": "Unknown", "battery_pct": float("nan")}
    try:
        current_mA = _read_current()
        bus_v      = _read_bus_voltage()
        source = "Battery" if current_mA < 0 else "Plugged In"
        pct = (bus_v - _VBAT_MIN) / (_VBAT_MAX - _VBAT_MIN) * 100.0
        pct = max(0.0, min(100.0, pct))
        return {"power_source": source, "battery_pct": round(pct, 1)}
    except Exception:
        return {"power_source": "Unknown", "battery_pct": float("nan")}


def _read(reg: int) -> int:
    data = _bus.read_i2c_block_data(_addr, reg, 2)
    return (data[0] << 8) | data[1]


def _write(reg: int, value: int) -> None:
    _bus.write_i2c_block_data(_addr, reg, [value >> 8, value & 0xFF])


def _read_current() -> float:
    _write(_REG_CALIBRATION, _CAL_VALUE)
    raw = _read(_REG_CURRENT)
    if raw > 32767:
        raw -= 65536
    return raw * _CURRENT_LSB


def _read_bus_voltage() -> float:
    _write(_REG_CALIBRATION, _CAL_VALUE)
    raw = _read(_REG_BUSVOLTAGE)
    return (raw >> 3) * 0.004
