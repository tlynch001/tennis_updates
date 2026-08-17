"""Local record of successful YouTube uploads (``youtube-uploads.json``).

Exists purely for duplicate-upload protection (see
:mod:`wta_daily.youtube.uploader`'s "Avoid accidental duplicate uploads"
requirement): this project will eventually run unattended every morning on
a Raspberry Pi, and re-running it for a date that already published
successfully - a re-triggered scheduler run, a manual re-run to regenerate
something unrelated, etc. - must never silently upload a second copy of
the same day's video.

Mirrors :class:`~wta_daily.persistence.snapshot_store.RankingsSnapshotStore`'s
shape (one small JSON file under ``data_dir``, atomic write-then-rename) -
deliberately its own small file rather than folded into
``rankings-history.json``, since this tracks a completely different kind
of fact (an external publish action, not ranking data) with its own
lifecycle.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp_path, path)


@dataclass(frozen=True)
class YouTubeUploadRecord:
    """Everything recorded about one successful upload."""

    report_date: date
    tour: str
    video_id: str
    video_url: str
    title: str
    uploaded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.report_date.isoformat(),
            "tour": self.tour,
            "video_id": self.video_id,
            "video_url": self.video_url,
            "title": self.title,
            "uploaded_at": self.uploaded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> YouTubeUploadRecord:
        return cls(
            report_date=date.fromisoformat(data["date"]),
            tour=str(data.get("tour", "wta")),
            video_id=str(data["video_id"]),
            video_url=str(data["video_url"]),
            title=str(data.get("title", "")),
            uploaded_at=str(data.get("uploaded_at", "")),
        )


class YouTubeUploadStore:
    """Reads/writes ``youtube-uploads.json`` under the configured ``data_dir``."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

    @property
    def path(self) -> Path:
        return self._data_dir / "youtube-uploads.json"

    @staticmethod
    def _key(report_date: date, tour: str) -> str:
        return f"{tour}:{report_date.isoformat()}"

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def get_upload(self, report_date: date, tour: str) -> YouTubeUploadRecord | None:
        """Return the recorded upload for ``report_date``/``tour``, if any -
        the single source of truth :meth:`~wta_daily.youtube.uploader.publish_report`
        checks before uploading, so a report already published successfully
        is skipped rather than re-uploaded."""

        raw = self._load().get(self._key(report_date, tour))
        return YouTubeUploadRecord.from_dict(raw) if raw else None

    def record_upload(
        self,
        report_date: date,
        tour: str,
        *,
        video_id: str,
        video_url: str,
        title: str,
        uploaded_at: datetime | None = None,
    ) -> YouTubeUploadRecord:
        record = YouTubeUploadRecord(
            report_date=report_date,
            tour=tour,
            video_id=video_id,
            video_url=video_url,
            title=title,
            uploaded_at=(uploaded_at or datetime.now(UTC)).isoformat(),
        )
        data = self._load()
        data[self._key(report_date, tour)] = record.to_dict()
        _atomic_write_json(self.path, data)
        logger.info(
            "Recorded YouTube upload for %s (%s) -> %s at %s",
            report_date.isoformat(),
            tour,
            video_id,
            self.path,
        )
        return record
