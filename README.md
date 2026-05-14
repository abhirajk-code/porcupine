# Porcupine

Portable PI with perfboard hat for experiments. Porcupine is a Raspberry Pi system monitor package that launches on boot and exposes hardware telemetry through a physical interface: an LCD display, GPIO button, and buzzer.

## Setup on Raspberry Pi

To set up Porcupine on your Raspberry Pi device, follow these steps:

1. Clone the repository:
   ```bash
   git clone git@github.com:abhirajk-code/porcupine.git
   cd porcupine
   ```

2. Run the installation script with sudo privileges:
   ```bash
   sudo bash install/setup.sh
   ```

The `setup.sh` script will automatically:
- Install required Python dependencies (`psutil`, `RPi.GPIO`, `RPLCD`, `smbus2`).
- Copy the `porcupine.service` systemd unit file to `/etc/systemd/system/`.
- Enable and start the porcupine service so it runs automatically on boot.

## Management CLI

After installation the `porcupine` command is available system-wide.

### Service control

| Command | Description |
|---|---|
| `porcupine start` | Start the monitoring service |
| `porcupine stop` | Stop the monitoring service |
| `porcupine status` | Show service state and current configuration |
| `porcupine test` | Run interactive hardware tests |

### Monitors

Each monitor has a cycle frequency that controls how often it appears in the display rotation.

```bash
sudo porcupine set boot-every  <n>   # 0 = disabled, 1 = every cycle (default), N = every Nth cycle
sudo porcupine set power-every <n>
sudo porcupine set cpu-every   <n>
sudo porcupine set temp-every  <n>
sudo porcupine set net-every   <n>
sudo porcupine set gpio-every  <n>
```

The `enable` / `disable` shortcuts set the frequency to `1` or `0`:

```bash
sudo porcupine enable  <monitor>   # sets {monitor}_every = 1
sudo porcupine disable <monitor>   # sets {monitor}_every = 0
```

### Settings

All `set` commands require `sudo` and restart the service automatically if it is running.

| Command | Description | Default |
|---|---|---|
| `sudo porcupine set refresh <seconds>` | Time between display pages | `5.0` |
| `sudo porcupine set only-alert <true\|false>` | LCD-off-until-breach mode | `false` |
| `sudo porcupine set temp-warn <°C>` | CPU temperature alert threshold | `80.0` |
| `sudo porcupine set cpu-warn <%>` | CPU usage alert threshold | `90.0` |
| `sudo porcupine set mem-warn <%>` | Memory usage alert threshold | `90.0` |
| `sudo porcupine set bat-warn <%>` | Battery level alert threshold | `40.0` |
| `sudo porcupine set lcd-addr <hex>` | LCD I2C address | `0x27` |
| `sudo porcupine set ina219-addr <hex>` | INA219 battery monitor I2C address | `0x41` |
| `sudo porcupine set button-pin <n>` | Button GPIO pin (BCM numbering) | `4` |
| `sudo porcupine set buzzer-pin <n>` | Buzzer GPIO pin (BCM numbering) | `18` |

### Logs

```bash
porcupine showlogs error   # warnings and errors only
porcupine showlogs all     # full service journal
```

Backed by `journalctl -u porcupine`. Use arrow keys to scroll, `q` to quit.

---

## Button

The button is wired to BCM pin 4 (configurable). A short press is under 2 seconds; a long press is held past 2 seconds.

| Action | Effect |
|---|---|
| Short press (LCD off) | Turn LCD back on |
| Short press (LCD on) | Start a 5-second window; LCD turns off if no follow-up |
| Short + short within 5 s | 20-second reboot countdown |
| Short + long within 5 s | 20-second shutdown countdown |
| Short press during countdown | Cancel countdown |

Data collection always continues regardless of LCD state. The LCD turning off only cuts the backlight.

---

## Buzzer

### Button feedback

| Event | Pattern |
|---|---|
| Press-down | 1 × 150 ms — immediate confirmation the press registered |
| Held past long-press threshold | 1 × 400 ms — cue to release for a long press |
| Service startup | 1 × 150 ms |

### Alert patterns

Alerts fire when a threshold is first crossed, and again each time the LCD screen cycles to that monitor's screen while the condition persists. The alert is silenced once the value drops back below the threshold.

| Condition | Pattern | Threshold setting |
|---|---|---|
| CPU temperature ≥ threshold | 3 × 200 ms with 100 ms gap | `sudo porcupine set temp-warn <°C>` |
| CPU usage ≥ threshold | 2 × 200 ms with 100 ms gap | `sudo porcupine set cpu-warn <%>` |
| Memory usage ≥ threshold | 2 × 200 ms with 100 ms gap | `sudo porcupine set mem-warn <%>` |
| Battery < threshold | 1 × 600 ms | `sudo porcupine set bat-warn <%>` |

Alerts only fire for monitors that are enabled. Disabling a monitor also silences its alert.

---

## LCD alert indicator

When any threshold is currently exceeded, `!` is placed at column 16 (the last character) of the first line on every screen — a persistent visual indicator that something needs attention regardless of which screen is currently showing.

```
 CPU   Mem      !    ← alert active on any monitor
 WARN   45%
```

Once all values drop below their thresholds the `!` disappears automatically.

---

## Only-alert mode

```bash
sudo porcupine set only-alert true
```

When `only_alert` is enabled the LCD stays off as long as all monitored values are within their thresholds. As soon as any threshold is breached:

- The LCD turns on automatically.
- Only the screen(s) for the breached monitor are shown (not the full rotation).
- The buzzer fires as normal.

Once all values return below their thresholds the LCD turns off again. The button still works while the LCD is on: short press starts the 5-second off-timer, and the reboot/shutdown sequences behave as usual.
