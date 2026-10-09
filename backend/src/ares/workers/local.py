"""Development entry point for the supervised durable consumer."""

from ares.config import get_settings
from ares.workers.daemon import main as run_worker


def main() -> None:
    if get_settings().environment != "development":
        raise SystemExit("Local integration worker is development-only")
    run_worker()


if __name__ == "__main__":
    main()
