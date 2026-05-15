import math
from unittest.mock import patch

import porcupine.monitors.temperature as temp_mod


def test_read_temp_normal():
    with patch("porcupine.monitors.temperature.Path") as MockPath:
        MockPath.return_value.read_text.return_value = "52340\n"
        temp = temp_mod._read_temp_c()
    assert temp == 52.3


def test_read_temp_missing_file():
    with patch("porcupine.monitors.temperature.Path") as MockPath:
        MockPath.return_value.read_text.side_effect = FileNotFoundError
        temp = temp_mod._read_temp_c()
    assert math.isnan(temp)


def test_read_throttle_not_throttled():
    with patch("porcupine.monitors.temperature.subprocess.check_output",
               return_value="throttled=0x0\n"):
        flags = temp_mod._read_throttle_flags()
    assert flags == 0


def test_read_throttle_throttled():
    with patch("porcupine.monitors.temperature.subprocess.check_output",
               return_value="throttled=0x50005\n"):
        flags = temp_mod._read_throttle_flags()
    assert flags == 0x50005


def test_read_throttle_unavailable():
    with patch("porcupine.monitors.temperature.subprocess.check_output",
               side_effect=FileNotFoundError):
        flags = temp_mod._read_throttle_flags()
    assert flags == -1


def test_read_returns_expected_keys():
    with patch("porcupine.monitors.temperature._read_temp_c", return_value=55.0), \
         patch("porcupine.monitors.temperature._read_throttle_flags", return_value=0):
        result = temp_mod.read()
    assert result == {"cpu_temp_c": 55.0, "throttled": False, "throttle_flags": 0}


def test_read_throttled_true():
    with patch("porcupine.monitors.temperature._read_temp_c", return_value=85.0), \
         patch("porcupine.monitors.temperature._read_throttle_flags", return_value=0x4):
        result = temp_mod.read()
    assert result["throttled"] is True


def test_read_throttle_none_when_unavailable():
    with patch("porcupine.monitors.temperature._read_temp_c", return_value=float("nan")), \
         patch("porcupine.monitors.temperature._read_throttle_flags", return_value=-1):
        result = temp_mod.read()
    assert result["throttled"] is None
