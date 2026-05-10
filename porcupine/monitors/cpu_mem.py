"""CPU and memory usage."""
import psutil


def read() -> dict:
    per_core = psutil.cpu_percent(percpu=True)
    mem = psutil.virtual_memory()
    return {
        "cpu_pct": per_core,
        "cpu_avg_pct": round(sum(per_core) / len(per_core), 1),
        "mem_pct": mem.percent,
        "mem_used_mb": mem.used // (1024 * 1024),
        "mem_total_mb": mem.total // (1024 * 1024),
    }
