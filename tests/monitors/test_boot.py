import time
from pathlib import Path
from unittest.mock import patch

import pytest

import porcupine.monitors.boot as boot_mod


@pytest.fixture(autouse=True)
def reset_boot_count():
    boot_mod._boot_count = 0
    yield
    boot_mod._boot_count = 0


def test_init_creates_file_and_sets_count(tmp_path):
    path = str(tmp_path / "bootcount")
    boot_mod.init(path)
    assert boot_mod._boot_count == 1
    assert Path(path).read_text() == "1"


def test_init_increments_existing_count(tmp_path):
    path = str(tmp_path / "bootcount")
    Path(path).write_text("4")
    boot_mod.init(path)
    assert boot_mod._boot_count == 5
    assert Path(path).read_text() == "5"


def test_init_recovers_from_corrupt_file(tmp_path):
    path = str(tmp_path / "bootcount")
    Path(path).write_text("not-a-number")
    boot_mod.init(path)
    assert boot_mod._boot_count == 1


def test_read_returns_expected_keys():
    boot_time = time.time() - 300
    with patch("porcupine.monitors.boot.psutil.boot_time", return_value=boot_time):
        result = boot_mod.read()
    assert set(result) == {"boot_count", "uptime_s"}
    assert result["uptime_s"] == pytest.approx(300.0, abs=1.0)
    assert result["boot_count"] == boot_mod._boot_count
