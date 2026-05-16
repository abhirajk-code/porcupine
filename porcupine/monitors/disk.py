"""Disk usage for the root filesystem."""
import logging

import psutil


def read() -> dict:
    try:
        usage = psutil.disk_usage("/")
        return {
            "disk_pct":      usage.percent,
            "disk_used_gb":  usage.used  / (1024 ** 3),
            "disk_total_gb": usage.total / (1024 ** 3),
        }
    except Exception:
        logging.warning("disk monitor read failed", exc_info=True)
        return {
            "disk_pct":      float("nan"),
            "disk_used_gb":  float("nan"),
            "disk_total_gb": float("nan"),
        }
