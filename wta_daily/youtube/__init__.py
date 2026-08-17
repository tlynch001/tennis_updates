"""Optional Phase 3: publishing the finished daily video to YouTube.

Disabled by default (``youtube.enabled: false`` - see
:class:`~wta_daily.config.YouTubeConfig`). Nothing in this package is
imported by :mod:`wta_daily.pipeline` or :mod:`wta_daily.cli` unless a
caller actually needs to publish, and every function in
:mod:`wta_daily.youtube.uploader`/:mod:`wta_daily.youtube.auth` that talks
to Google defers its ``google-*``/``googleapiclient`` imports to inside
the function body - so simply having this package on ``sys.path`` never
requires those (optional - see ``requirements-youtube.txt``) packages to
be installed, and never triggers an OAuth flow or network call on its own.

See :func:`wta_daily.youtube.uploader.publish_report` for the single
entry point the rest of the application uses.
"""

from __future__ import annotations
