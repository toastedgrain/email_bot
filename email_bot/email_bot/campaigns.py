"""Campaign management helpers."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from email_bot.config import TEMPLATES_DIR
from email_bot.db import Database


def create_campaign(
    db: Database,
    name: str,
    template_dir: str | None = None,
    sender_name: str = "",
    signature: str = "",
) -> dict[str, Any]:
    """Create a new campaign and return its row dict."""
    campaign_id = uuid.uuid4().hex[:12]
    tpl_dir = template_dir or str(TEMPLATES_DIR / name)

    # Validate template directory exists
    tpl_path = Path(tpl_dir)
    if not tpl_path.is_dir():
        raise FileNotFoundError(
            f"Template directory not found: {tpl_path}\n"
            f"Create it with at least subject.txt and body.txt inside."
        )

    db.create_campaign(
        campaign_id=campaign_id,
        name=name,
        template_dir=tpl_dir,
        sender_name=sender_name,
        signature=signature,
    )
    return db.get_campaign(campaign_id)  # type: ignore[return-value]


def resolve_campaign(db: Database, campaign_id: str) -> dict[str, Any]:
    """Fetch a campaign or raise."""
    camp = db.get_campaign(campaign_id)
    if camp is None:
        raise SystemExit(f"Campaign '{campaign_id}' not found.")
    return camp
