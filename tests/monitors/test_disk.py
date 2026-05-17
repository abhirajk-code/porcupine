"""Disk monitor tests — no hardware required."""
import math
from unittest.mock import patch, MagicMock

import porcupine.monitors.disk as disk


def _usage(pct, used_gb, total_gb):
    u = MagicMock()
    u.percent   = pct
    u.used      = int(used_gb  * 1024 ** 3)
    u.total     = int(total_gb * 1024 ** 3)
    return u


def test_read_returns_required_keys():
    with patch("psutil.disk_usage", return_value=_usage(42.0, 13.4, 32.0)):
        data = disk.read()
    assert "disk_pct"      in data
    assert "disk_used_gb"  in data
    assert "disk_total_gb" in data


def test_read_values_correct():
    with patch("psutil.disk_usage", return_value=_usage(55.0, 17.6, 32.0)):
        data = disk.read()
    assert data["disk_pct"]      == 55.0
    assert abs(data["disk_used_gb"]  - 17.6) < 0.01
    assert abs(data["disk_total_gb"] - 32.0) < 0.01


def test_read_returns_nan_on_error():
    with patch("psutil.disk_usage", side_effect=PermissionError("no access")):
        data = disk.read()
    assert math.isnan(data["disk_pct"])
    assert math.isnan(data["disk_used_gb"])
    assert math.isnan(data["disk_total_gb"])
