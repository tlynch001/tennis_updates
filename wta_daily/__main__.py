"""Allows ``python -m wta_daily`` as a shortcut for ``python -m wta_daily.cli``."""

from wta_daily.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
