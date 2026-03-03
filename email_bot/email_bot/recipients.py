"""Parse and validate recipient lists (CSV / JSON)."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from email_bot.db import Database
from email_bot.utils import validate_email

log = logging.getLogger(__name__)


def _normalise(row: dict[str, Any]) -> dict[str, Any] | None:
    """Clean a single recipient dict. Returns None when invalid."""
    email = str(row.get("email", "")).strip().lower()
    if not email or not validate_email(email):
        return None

    name = str(row.get("name", "")).strip() or "there"

    # Collect extra columns (everything except email/name)
    extras: dict[str, str] = {}
    for k, v in row.items():
        if k.lower() not in ("email", "name"):
            extras[k] = str(v).strip() if v is not None else ""

    return {"email": email, "name": name, "extras": extras}


def _load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _load_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON file must contain a top-level array of objects.")
    return data


def import_recipients(
    file_path: Path,
    campaign_id: str,
    db: Database,
) -> dict[str, int]:
    """Import recipients from *file_path* into *campaign_id*.

    Returns counts: {imported, skipped_invalid, skipped_duplicate}.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        rows = _load_csv(file_path)
    elif suffix == ".json":
        rows = _load_json(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Use .csv or .json.")

    stats = {"imported": 0, "skipped_invalid": 0, "skipped_duplicate": 0}

    for i, raw in enumerate(rows, 1):
        cleaned = _normalise(raw)
        if cleaned is None:
            log.warning("Row %d: invalid email — skipped", i)
            stats["skipped_invalid"] += 1
            continue

        inserted = db.upsert_recipient(
            campaign_id=campaign_id,
            email=cleaned["email"],
            name=cleaned["name"],
            extra_json=json.dumps(cleaned["extras"]),
        )
        if inserted:
            stats["imported"] += 1
        else:
            log.info("Row %d (%s): duplicate — skipped", i, cleaned["email"])
            stats["skipped_duplicate"] += 1

    return stats
