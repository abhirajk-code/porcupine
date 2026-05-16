# Porcupine — Project Plan

## Overview

Porcupine is a Raspberry Pi system monitor package that launches on boot and exposes hardware telemetry through a physical interface: an LCD display, GPIO button, and buzzer.

---

## Feature 1: Boot-time System Monitor Daemon

### Goal

Build a Python package (`porcupine`) that installs as a `systemd` service and starts automatically when the Pi powers on. It collects and displays configurable system metrics via an LCD screen, accepts button input to navigate/toggle options or control the Pi, and triggers a buzzer on alert conditions.

---

## Architecture

```
porcupine/
├── __init__.py
├── main.py              # entry point, parses flags, starts daemon loop
├── config.py            # flag/config management
├── monitors/
│   ├── __init__.py
│   ├── power.py         # power-up count & uptime tracking
│   ├── cpu_mem.py       # CPU and memory usage
│   ├── temperature.py   # CPU/GPU temperature
│   └── network.py       # network rx/tx usage
├── interfaces/
│   ├── __init__.py
│   ├── lcd.py           # LCD driver & display logic
│   ├── button.py        # GPIO button input handler
│   └── buzzer.py        # buzzer alert driver
├── daemon.py            # main event loop, wires monitors to interfaces
└── install/
    ├── porcupine.service # systemd unit file
    └── setup.sh          # install script
```

---

## Monitors

Each monitor is a module with a `read() -> dict` function that returns the latest metric values.

| Monitor | `every` flag | Metrics Collected |
|---|---|---|
| `boot.py` | `--boot-every` | boot count, uptime |
| `power.py` | `--power-every` | power source, battery % |
| `cpu_mem.py` | `--cpu-every` | CPU % per core, RAM % used |
| `temperature.py` | `--temp-every` | CPU temp (°C) |
| `network.py` | `--net-every` | rx/tx bytes/s, active interface |
| `gpio_pins.py` | `--gpio-every` | BCM pin states (two screens) |

Each monitor has an `every` value: 0 = disabled, 1 = every cycle, N = every Nth cycle.
At runtime, `effective_every` can drop to 1 when a threshold is breached, increasing
the read cadence for that monitor until the value returns to normal.

---

## Interfaces

### LCD

- Driver targets 16×2 or 20×4 I2C LCD (HD44780 + PCF8574 backpack).
- Display cycles through enabled monitors on a configurable interval (default 3 s).
- Layout: line 1 = metric label, line 2 = value.
- Supports a "menu" mode triggered by button hold.

### GPIO Button

Single button, three interaction modes:

| Interaction | Action |
|---|---|
| Short press | Toggle monitoring on/off (backlight + cycling) |
| Short + short (within 5 s) | 20-second reboot countdown |
| Short + long (within 5 s) | 20-second shutdown countdown |
| Any press during countdown | Cancel |

### Buzzer

Alert beeps fire immediately on breach and again each time the breached monitor's screen
is displayed. A `!` marker at column 15 of every screen's first line gives a persistent
visual cue while any alert is active.

| Condition | Default threshold | Pattern |
|---|---|---|
| CPU temp critical | > 80 °C (`temp_warn`) | 3 × 200 ms beeps, 100 ms gap |
| CPU usage high | > 90 % (`cpu_warn`) | 2 × 200 ms beeps, 100 ms gap |
| RAM usage high | > 90 % (`mem_warn`) | 2 × 200 ms beeps, 100 ms gap |
| Battery low | < 40 % (`bat_warn`) | 1 × 600 ms beep |

---

## Configuration

Runtime flags (CLI / systemd `ExecStart`):

```
porcupine [--boot-every N] [--power-every N] [--cpu-every N]
          [--temp-every N] [--net-every N]  [--gpio-every N]
          [--lcd-addr 0x27] [--button-pin 4] [--buzzer-pin 18]
          [--ina219-addr 0x41] [--refresh 5]
          [--temp-warn 80] [--cpu-warn 90] [--mem-warn 90] [--bat-warn 40]
          [--config /etc/porcupine/porcupine.conf]
```

A `porcupine.conf` file in `/etc/porcupine/` can hold persistent defaults so flags do not need to be repeated across reboots.

---

## Installation

```bash
git clone git@github.com:abhirajk-code/porcupine.git
cd porcupine
sudo bash install/setup.sh
```

`setup.sh` will:
1. Install Python dependencies (`pip install -r requirements.txt`).
2. Copy `porcupine.service` to `/etc/systemd/system/`.
3. Enable and start the service (`systemctl enable --now porcupine`).

---

## Implementation Milestones

| # | Milestone | Deliverable |
|---|---|---|
| 1 | Project scaffold | Package structure, `setup.py`, empty modules |
| 2 | Monitor modules | `power`, `cpu_mem`, `temperature`, `network` — each with `read()` + unit tests |
| 3 | LCD interface | I2C LCD driver, display loop, screen cycling |
| 4 | Button interface | GPIO edge detection, short/long press, menu FSM |
| 5 | Buzzer interface | Alert thresholds, beep patterns |
| 6 | Daemon wiring | `daemon.py` ties monitors + interfaces into event loop |
| 7 | Config & flags | CLI flag parsing, `/etc/porcupine/porcupine.conf` support |
| 8 | Install tooling | `setup.sh`, `porcupine.service`, smoke test on real Pi |

---

## Dependencies

| Package | Purpose |
|---|---|
| `psutil` | CPU, memory, network metrics |
| `RPi.GPIO` | GPIO button and buzzer |
| `RPLCD` | HD44780 I2C LCD driver |
| `smbus2` | I2C bus access |

---

## Open Questions

- LCD size: 16×2 or 20×4? Determines screen layout design.
- Single button or multi-button? Plan assumes one button with long/short press logic; more buttons simplify menu navigation.
- Persistent boot count storage: flat file (`/var/lib/porcupine/bootcount`) or SQLite?
- Alert delivery: buzzer only, or also write to a log / push a notification?
