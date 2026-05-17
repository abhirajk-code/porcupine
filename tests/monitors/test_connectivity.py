"""Connectivity monitor tests — no hardware required."""
import math
from unittest.mock import patch, MagicMock

import porcupine.monitors.connectivity as connectivity


def test_read_returns_required_keys():
    with patch("socket.create_connection", return_value=MagicMock(__enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False))):
        data = connectivity.read()
    assert "reachable"   in data
    assert "conn_host"   in data
    assert "latency_ms"  in data


def test_read_reachable():
    with patch("socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__ = MagicMock(return_value=None)
        mock_conn.return_value.__exit__  = MagicMock(return_value=False)
        data = connectivity.read(host="8.8.8.8")
    assert data["reachable"]  is True
    assert data["conn_host"]  == "8.8.8.8"
    assert not math.isnan(data["latency_ms"])
    assert data["latency_ms"] >= 0


def test_read_unreachable_on_oserror():
    with patch("socket.create_connection", side_effect=OSError("refused")):
        data = connectivity.read(host="1.2.3.4")
    assert data["reachable"]  is False
    assert data["conn_host"]  == "1.2.3.4"
    assert math.isnan(data["latency_ms"])


def test_read_custom_host_propagated():
    with patch("socket.create_connection", side_effect=OSError):
        data = connectivity.read(host="192.168.1.1")
    assert data["conn_host"] == "192.168.1.1"
