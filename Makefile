.PHONY: test install hardware-test enable uninstall

## Run unit tests
test:
	python3 -m pytest

## Step 1: install package and write config (interactive)
install:
	sudo bash install/1_install.sh

## Step 2: test hardware interfaces and monitors
hardware-test:
	sudo bash install/2_test.sh

## Step 3: enable porcupine as a systemd startup service
enable:
	sudo bash install/3_enable.sh

## Remove service and package (keeps config and data dirs)
uninstall:
	sudo bash install/setup.sh --uninstall
