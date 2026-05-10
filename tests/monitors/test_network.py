from types import SimpleNamespace
from unittest.mock import patch

import pytest

import porcupine.monitors.network as net_mod


def _counter(recv, sent):
    return SimpleNamespace(bytes_recv=recv, bytes_sent=sent)


def _stats(up=True):
    return SimpleNamespace(isup=up)


@pytest.fixture(autouse=True)
def reset_state():
    net_mod._prev_counters = None
    net_mod._prev_time = 0.0
    yield
    net_mod._prev_counters = None
    net_mod._prev_time = 0.0


def test_first_call_returns_zero_rates():
    counters = {"eth0": _counter(1024 * 1024, 512 * 1024)}
    stats = {"eth0": _stats(True)}
    with patch("porcupine.monitors.network.psutil.net_io_counters", return_value=counters), \
         patch("porcupine.monitors.network.psutil.net_if_stats", return_value=stats), \
         patch("porcupine.monitors.network.time.monotonic", return_value=100.0):
        result = net_mod.read()

    assert result["interface"] == "eth0"
    assert result["rx_bps"] == 0.0
    assert result["tx_bps"] == 0.0
    assert result["rx_total_mb"] == 1.0
    assert result["tx_total_mb"] == 0.5


def test_second_call_computes_rate():
    stats = {"eth0": _stats(True)}

    with patch("porcupine.monitors.network.psutil.net_if_stats", return_value=stats):
        # First call — establishes baseline
        with patch("porcupine.monitors.network.psutil.net_io_counters",
                   return_value={"eth0": _counter(0, 0)}), \
             patch("porcupine.monitors.network.time.monotonic", return_value=0.0):
            net_mod.read()

        # Second call — 1 s later, 1024 bytes received
        with patch("porcupine.monitors.network.psutil.net_io_counters",
                   return_value={"eth0": _counter(1024, 512)}), \
             patch("porcupine.monitors.network.time.monotonic", return_value=1.0):
            result = net_mod.read()

    assert result["rx_bps"] == 1024.0
    assert result["tx_bps"] == 512.0


def test_missing_interface_returns_zeros():
    with patch("porcupine.monitors.network.psutil.net_io_counters", return_value={}), \
         patch("porcupine.monitors.network.psutil.net_if_stats",
               return_value={"eth0": _stats(True)}), \
         patch("porcupine.monitors.network.time.monotonic", return_value=1.0):
        result = net_mod.read()

    assert result["rx_bps"] == 0.0
    assert result["tx_bps"] == 0.0


def test_best_interface_prefers_eth0_over_wlan0():
    stats = {"wlan0": _stats(True), "eth0": _stats(True)}
    with patch("porcupine.monitors.network.psutil.net_if_stats", return_value=stats):
        assert net_mod._best_interface() == "eth0"


def test_best_interface_falls_back_to_active():
    stats = {"lo": _stats(True), "usb0": _stats(True)}
    with patch("porcupine.monitors.network.psutil.net_if_stats", return_value=stats):
        assert net_mod._best_interface() == "usb0"
