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
