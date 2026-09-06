"""Local record of successful YouTube uploads (``youtube-uploads.json``).

Exists purely for duplicate-upload protection. Landscape and vertical uploads
for the same report date are tracked independently so a successful standard
video never blocks its companion Short.
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

LANDSCAPE_VARIANT = "landscape"
VERTICAL_VARIANT = "vertical"
_VALID_VARIANTS = {LANDSCAPE_VARIANT, VERTICAL_VARIANT}


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp_path, path)


def _validate_variant(variant: str) -> str:
    normalized = variant.strip().lower()
    if normalized not in _VALID_VARIANTS:
        raise ValueError(f"Unsupported YouTube upload variant: {variant!r}")
    return normalized


@dataclass(frozen=True)
class YouTubeUploadRecord:
    """Everything recorded about one successful upload."""

    report_date: date
    tour: str
    video_id: str
    video_url: str
    title: str
    uploaded_at: str
    variant: str = LANDSCAPE_VARIANT

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.report_date.isoformat(),
            "tour": self.tour,
            "variant": self.variant,
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
            variant=str(data.get("variant", LANDSCAPE_VARIANT)),
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
    def _key(report_date: date, tour: str, variant: str = LANDSCAPE_VARIANT) -> str:
        variant = _validate_variant(variant)
        return f"{tour}:{report_date.isoformat()}:{variant}"

    @staticmethod
    def _legacy_key(report_date: date, tour: str) -> str:
        return f"{tour}:{report_date.isoformat()}"

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def get_upload(
        self,
        report_date: date,
        tour: str,
        variant: str = LANDSCAPE_VARIANT,
    ) -> YouTubeUploadRecord | None:
        """Return the recorded upload for a date/tour/format.

        Old pre-vertical records used ``tour:date`` keys. Those are treated as
        landscape uploads so existing duplicate protection remains intact.
        """

        variant = _validate_variant(variant)
        data = self._load()
        raw = data.get(self._key(report_date, tour, variant))
        if raw is None and variant == LANDSCAPE_VARIANT:
            raw = data.get(self._legacy_key(report_date, tour))
        if not raw:
            return None
        record = YouTubeUploadRecord.from_dict(raw)
        if "variant" not in raw:
            record = YouTubeUploadRecord(
                report_date=record.report_date,
                tour=record.tour,
                variant=LANDSCAPE_VARIANT,
                video_id=record.video_id,
                video_url=record.video_url,
                title=record.title,
                uploaded_at=record.uploaded_at,
            )
        return record

    def record_upload(
        self,
        report_date: date,
        tour: str,
        *,
        video_id: str,
        video_url: str,
        title: str,
        variant: str = LANDSCAPE_VARIANT,
        uploaded_at: datetime | None = None,
    ) -> YouTubeUploadRecord:
        variant = _validate_variant(variant)
        record = YouTubeUploadRecord(
            report_date=report_date,
            tour=tour,
            variant=variant,
            video_id=video_id,
            video_url=video_url,
            title=title,
            uploaded_at=(uploaded_at or datetime.now(UTC)).isoformat(),
        )
        data = self._load()
        data[self._key(report_date, tour, variant)] = record.to_dict()
        _atomic_write_json(self.path, data)
        logger.info(
            "Recorded %s YouTube upload for %s (%s) -> %s at %s",
            variant,
            report_date.isoformat(),
            tour,
            video_id,
            self.path,
        )
        return record
