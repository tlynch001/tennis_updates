"""wta_daily - Automated daily WTA Top N ranking video asset generator.

This package is organized as a set of small, independently testable modules
connected through plugin registries (see :mod:`wta_daily.plugins.registry`).
Each pluggable concern - rankings data, match data, script writing, voice
synthesis, video assembly - implements a small abstract interface defined in
:mod:`wta_daily.plugins.base`. Adding support for a new tour (e.g. ATP) or a
new "Top 25" variant means adding a new module and registering it; the
pipeline, CLI, and configuration loader never need to change.
"""

__version__ = "0.1.0"
