"""Typer CLI for Email Bot."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from email_bot import __version__
from email_bot.campaigns import create_campaign, resolve_campaign
from email_bot.config import (
    DEFAULT_MAX_PER_MINUTE,
    DEFAULT_MAX_PER_RUN,
    TEMPLATES_DIR,
)
from email_bot.db import Database
from email_bot.gmail_provider import (
    authenticate,
    compose_message,
    get_service,
    is_retryable,
    send_message,
)
from email_bot.rate_limit import RateLimiter
from email_bot.recipients import import_recipients
from email_bot.reporting import campaign_summary, export_csv
from email_bot.templating import CampaignTemplate
from email_bot.utils import template_hash

app = typer.Typer(
    name="emailbot",
    help="Send personalised emails via Gmail API.",
    add_completion=False,
)
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("emailbot")


def _db() -> Database:
    return Database()


# ── campaign create ──────────────────────────────────────────────────────


@app.command("campaign-create")
def cmd_campaign_create(
    name: str = typer.Argument(..., help="Campaign name (also used as template dir name by default)"),
    template_dir: Optional[str] = typer.Option(None, "--template-dir", "-t", help="Path to template directory"),
    sender_name: str = typer.Option("", "--sender-name", "-s", help="Display name for From header"),
    signature: str = typer.Option("", "--signature", help="Signature appended via {{signature}} placeholder"),
) -> None:
    """Create a new campaign."""
    db = _db()
    try:
        camp = create_campaign(db, name, template_dir, sender_name, signature)
    finally:
        db.close()
    console.print(Panel(f"[bold green]Campaign created[/]\nID: {camp['id']}\nName: {camp['name']}"))


# ── campaign list ────────────────────────────────────────────────────────


@app.command("campaign-list")
def cmd_campaign_list() -> None:
    """List all campaigns."""
    db = _db()
    try:
        camps = db.list_campaigns()
    finally:
        db.close()

    if not camps:
        console.print("[yellow]No campaigns yet.[/]")
        return

    table = Table(title="Campaigns")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Template Dir")
    table.add_column("Created")
    for c in camps:
        table.add_row(c["id"], c["name"], c["template_dir"], c["created_at"][:19])
    console.print(table)


# ── import-recipients ────────────────────────────────────────────────────


@app.command("import-recipients")
def cmd_import(
    file: Path = typer.Argument(..., exists=True, readable=True, help="CSV or JSON file"),
    campaign: str = typer.Option(..., "--campaign", "-c", help="Campaign ID"),
) -> None:
    """Import recipients from a CSV or JSON file into a campaign."""
    db = _db()
    try:
        resolve_campaign(db, campaign)
        stats = import_recipients(file, campaign, db)
    finally:
        db.close()

    console.print(
        Panel(
            f"[green]Imported:[/] {stats['imported']}  "
            f"[yellow]Dup skipped:[/] {stats['skipped_duplicate']}  "
            f"[red]Invalid skipped:[/] {stats['skipped_invalid']}",
            title="Import Results",
        )
    )


# ── preview ──────────────────────────────────────────────────────────────


@app.command("preview")
def cmd_preview(
    campaign: str = typer.Option(..., "--campaign", "-c", help="Campaign ID"),
    limit: int = typer.Option(5, "--limit", "-l", help="Max recipients to preview"),
) -> None:
    """Render emails for review without sending."""
    db = _db()
    try:
        camp = resolve_campaign(db, campaign)
        recipients = db.get_recipients(campaign)
    finally:
        db.close()

    if not recipients:
        console.print("[yellow]No recipients imported for this campaign.[/]")
        return

    tpl = CampaignTemplate(Path(camp["template_dir"]))

    for i, r in enumerate(recipients[:limit]):
        rendered = tpl.render_for_recipient(r, signature=camp.get("signature", ""))
        console.print(
            Panel(
                f"[bold]To:[/]      {r['email']}\n"
                f"[bold]Subject:[/] {rendered['subject']}\n"
                f"{'─' * 50}\n"
                f"{rendered['body_text']}"
                + (f"\n{'─' * 50}\n[dim](HTML body available)[/]" if rendered.get("body_html") else ""),
                title=f"Preview {i + 1}/{min(limit, len(recipients))}",
                border_style="blue",
            )
        )


# ── send ─────────────────────────────────────────────────────────────────


@app.command("send")
def cmd_send(
    campaign: str = typer.Option(..., "--campaign", "-c", help="Campaign ID"),
    live: bool = typer.Option(False, "--live", help="Actually send emails (requires prior dry run)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate sending without Gmail API calls"),
    max_emails: int = typer.Option(DEFAULT_MAX_PER_RUN, "--max", help="Hard cap on emails this run"),
    rate: int = typer.Option(DEFAULT_MAX_PER_MINUTE, "--rate", help="Max emails per minute"),
    allowlist: Optional[str] = typer.Option(None, "--allowlist", help="Comma-separated allowlist of emails (test mode)"),
    disable_allowlist: bool = typer.Option(False, "--disable-allowlist", help="Disable test-mode allowlist"),
    max_retries: int = typer.Option(3, "--max-retries", help="Max retries for transient failures"),
) -> None:
    """Send emails for a campaign. Requires --dry-run first, then --live."""
    if not live and not dry_run:
        console.print("[red]Specify either --dry-run or --live.[/]")
        raise typer.Exit(1)
    if live and dry_run:
        console.print("[red]Cannot use --live and --dry-run together.[/]")
        raise typer.Exit(1)

    db = _db()
    try:
        camp = resolve_campaign(db, campaign)
        recipients = db.get_recipients(campaign)

        if not recipients:
            console.print("[yellow]No recipients for this campaign.[/]")
            raise typer.Exit(0)

        tpl = CampaignTemplate(Path(camp["template_dir"]))
        tpl_hash = template_hash(tpl.subject_src, tpl.body_src, tpl.html_src)

        # ── live-mode guard: must have completed a dry run first ─────
        if live:
            marker_key = f"dry_run_completed:{tpl_hash}"
            if db.get_marker(campaign, marker_key) is None:
                console.print(
                    "[red]You must complete a --dry-run with this template before --live send.[/]"
                )
                raise typer.Exit(1)

        # ── allowlist filtering ──────────────────────────────────────
        allowed: set[str] | None = None
        if allowlist and not disable_allowlist:
            allowed = {a.strip().lower() for a in allowlist.split(",")}

        # ── set up Gmail service for live mode ───────────────────────
        service = None
        if live:
            creds = authenticate()
            service = get_service(creds)

        limiter = RateLimiter(rate)

        sent = failed = skipped = already = 0

        for r in recipients:
            if sent + failed >= max_emails:
                log.info("Reached max cap (%d). Stopping.", max_emails)
                break

            email = r["email"]

            # allowlist check
            if allowed is not None and email not in allowed:
                log.info("Skipped %s (not in allowlist)", email)
                skipped += 1
                continue

            # idempotency
            if db.already_sent(campaign, email, tpl_hash):
                log.info("Skipped %s (already sent)", email)
                already += 1
                continue

            rendered = tpl.render_for_recipient(r, signature=camp.get("signature", ""))

            if dry_run:
                db.log_attempt(campaign, email, tpl_hash, status="dry_run")
                log.info("[DRY RUN] Would send to %s — Subject: %s", email, rendered["subject"])
                sent += 1
                continue

            # ── live send with retry ─────────────────────────────────
            raw = compose_message(
                to=email,
                subject=rendered["subject"],
                body_text=rendered["body_text"],
                body_html=rendered.get("body_html") or None,
                sender_name=camp.get("sender_name", ""),
            )

            success = False
            last_err = ""
            for attempt in range(1, max_retries + 1):
                limiter.wait()
                try:
                    result = send_message(service, raw)
                    gmail_id = result.get("id", "")
                    db.log_attempt(campaign, email, tpl_hash, status="sent", gmail_message_id=gmail_id)
                    log.info("Sent to %s (gmail id: %s)", email, gmail_id)
                    sent += 1
                    success = True
                    break
                except Exception as exc:
                    from googleapiclient.errors import HttpError

                    retryable = isinstance(exc, HttpError) and is_retryable(exc)
                    last_err = str(exc)

                    if retryable and attempt < max_retries:
                        wait = 2 ** attempt
                        log.warning(
                            "Transient error sending to %s (attempt %d/%d). Retrying in %ds: %s",
                            email, attempt, max_retries, wait, exc,
                        )
                        time.sleep(wait)
                    else:
                        break

            if not success:
                db.log_attempt(campaign, email, tpl_hash, status="failed", error=last_err)
                log.error("Failed to send to %s: %s", email, last_err)
                failed += 1

        # ── dry run marker ───────────────────────────────────────────
        if dry_run:
            marker_key = f"dry_run_completed:{tpl_hash}"
            db.set_marker(campaign, marker_key)
            console.print("[green]Dry run completed. You may now use --live.[/]")

        # ── summary ──────────────────────────────────────────────────
        console.print(
            Panel(
                f"[green]Sent:[/]         {sent}\n"
                f"[red]Failed:[/]       {failed}\n"
                f"[yellow]Skipped:[/]      {skipped}\n"
                f"[dim]Already sent:[/] {already}",
                title="Run Summary",
            )
        )
    finally:
        db.close()


# ── status ───────────────────────────────────────────────────────────────


@app.command("status")
def cmd_status(
    campaign: str = typer.Option(..., "--campaign", "-c", help="Campaign ID"),
) -> None:
    """Show campaign send status."""
    db = _db()
    try:
        summary = campaign_summary(db, campaign)
    finally:
        db.close()

    table = Table(title=f"Campaign: {summary['campaign_name']} ({summary['campaign_id']})")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Total recipients", str(summary["total_recipients"]))
    table.add_row("Sent", f"[green]{summary['sent']}[/]")
    table.add_row("Failed", f"[red]{summary['failed']}[/]")
    table.add_row("Skipped", f"[yellow]{summary['skipped']}[/]")
    table.add_row("Pending", str(summary["pending"]))
    table.add_row("Dry-run", f"[cyan]{summary['dry_run']}[/]")
    console.print(table)


# ── export-report ────────────────────────────────────────────────────────


@app.command("export-report")
def cmd_export(
    campaign: str = typer.Option(..., "--campaign", "-c", help="Campaign ID"),
    output: Path = typer.Option("report.csv", "--output", "-o", help="Output CSV path"),
) -> None:
    """Export the send log as a CSV report."""
    db = _db()
    try:
        csv_text = export_csv(db, campaign)
    finally:
        db.close()

    if not csv_text:
        console.print("[yellow]No send log entries for this campaign.[/]")
        return

    output.write_text(csv_text, encoding="utf-8")
    console.print(f"[green]Report written to {output}[/]")


# ── auth (convenience) ──────────────────────────────────────────────────


@app.command("auth")
def cmd_auth() -> None:
    """Authenticate with Gmail (opens browser on first run)."""
    authenticate()
    console.print("[green]Authentication successful. Token stored.[/]")


# ── version ──────────────────────────────────────────────────────────────


@app.command("version")
def cmd_version() -> None:
    """Show version."""
    console.print(f"emailbot {__version__}")


# ── entry point ──────────────────────────────────────────────────────────


def app_entry() -> None:
    app()


if __name__ == "__main__":
    app_entry()
