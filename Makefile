.PHONY: test install uninstall check

test:
	python3 -m pytest

install:
	sudo bash install/setup.sh

uninstall:
	sudo bash install/setup.sh --uninstall

check:
	bash install/check.sh
