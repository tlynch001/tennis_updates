"""Optional Phase 3: publishing the finished daily video to YouTube.

Disabled by default (``youtube.enabled: false`` - see
:class:`~wta_daily.config.YouTubeConfig`). :mod:`wta_daily.pipeline` and
:mod:`wta_daily.cli` do unconditionally import this package (it's a normal,
lightweight, stdlib-only import - the same as any other internal module),
but that import alone has no side effects: every function in
:mod:`wta_daily.youtube.uploader`/:mod:`wta_daily.youtube.auth` that talks
to Google defers its ``google-*``/``googleapiclient`` imports to inside the
function body, and :func:`wta_daily.youtube.uploader.publish_report`
checks ``config.enabled`` before doing anything else. So while
``youtube.enabled`` is ``false``, none of the following ever happens: the
optional Google packages (see ``requirements-youtube.txt``) being required,
an OAuth credential file being read, a network call to Google, or an
upload attempt - and the rest of the pipeline behaves exactly as it did
before this package existed.

See :func:`wta_daily.youtube.uploader.publish_report` for the single
entry point the rest of the application uses.
"""

from __future__ import annotations
