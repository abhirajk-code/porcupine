"""Entry point."""
from .config import parse_args
from .daemon import run


def main():
    args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
