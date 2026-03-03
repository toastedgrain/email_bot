"""Reporting helpers: status summaries and CSV export."""

from __future__ import annotations

import csv
import io
from typing import Any

from email_bot.db import Database


def campaign_summary(db: Database, campaign_id: str) -> dict[str, Any]:
    """Return a summary dict for a campaign."""
    camp = db.get_campaign(campaign_id)
    if camp is None:
        raise SystemExit(f"Campaign '{campaign_id}' not found.")

    stats = db.campaign_send_stats(campaign_id)
    total_recipients = db.recipient_count(campaign_id)

    return {
        "campaign_id": campaign_id,
        "campaign_name": camp["name"],
        "total_recipients": total_recipients,
        "sent": stats.get("sent", 0),
        "failed": stats.get("failed", 0),
        "skipped": stats.get("skipped", 0),
        "pending": stats.get("pending", 0),
        "dry_run": stats.get("dry_run", 0),
    }


def export_csv(db: Database, campaign_id: str) -> str:
    """Return a CSV string of the full send_log for *campaign_id*."""
    rows = db.get_send_log(campaign_id)
    if not rows:
        return ""

    buf = io.StringIO()
    fieldnames = [
        "recipient_email",
        "template_hash",
        "status",
        "gmail_message_id",
        "error",
        "created_at",
        "updated_at",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()
