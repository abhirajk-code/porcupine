"""Internet connectivity probe via TCP socket to a well-known host."""
import logging
import socket
import time

_TIMEOUT = 2.0


def read(host: str = "8.8.8.8", port: int = 53) -> dict:
    """Attempt a TCP connection to host:port; measure latency."""
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=_TIMEOUT):
            pass
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return {"reachable": True,  "conn_host": host, "latency_ms": latency_ms}
    except OSError:
        return {"reachable": False, "conn_host": host, "latency_ms": float("nan")}
    except Exception:
        logging.warning("connectivity monitor read failed", exc_info=True)
        return {"reachable": False, "conn_host": host, "latency_ms": float("nan")}
