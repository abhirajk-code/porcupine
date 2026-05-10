from types import SimpleNamespace
from unittest.mock import patch

import porcupine.monitors.cpu_mem as cpu_mem_mod


def _mem(used_mb, total_mb, pct):
    used = used_mb * 1024 ** 2
    total = total_mb * 1024 ** 2
    return SimpleNamespace(used=used, total=total, percent=pct)


def test_read_returns_expected_keys():
    per_core = [10.0, 20.0, 30.0, 40.0]
    mem = _mem(used_mb=512, total_mb=1024, pct=50.0)
    with patch("porcupine.monitors.cpu_mem.psutil.cpu_percent", return_value=per_core), \
         patch("porcupine.monitors.cpu_mem.psutil.virtual_memory", return_value=mem):
        result = cpu_mem_mod.read()

    assert result["cpu_pct"] == per_core
    assert result["cpu_avg_pct"] == 25.0
    assert result["mem_pct"] == 50.0
    assert result["mem_used_mb"] == 512
    assert result["mem_total_mb"] == 1024


def test_cpu_avg_rounds_correctly():
    per_core = [10.0, 20.0, 30.0]
    mem = _mem(256, 1024, 25.0)
    with patch("porcupine.monitors.cpu_mem.psutil.cpu_percent", return_value=per_core), \
         patch("porcupine.monitors.cpu_mem.psutil.virtual_memory", return_value=mem):
        result = cpu_mem_mod.read()
    assert result["cpu_avg_pct"] == 20.0
