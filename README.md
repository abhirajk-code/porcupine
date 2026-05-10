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
