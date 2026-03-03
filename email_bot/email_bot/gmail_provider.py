"""Gmail API integration — OAuth flow + message sending."""

from __future__ import annotations

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

from email_bot.config import CREDENTIALS_FILE, TOKEN_FILE, SCOPES

log = logging.getLogger(__name__)

# Transient HTTP status codes worth retrying
_RETRYABLE = {429, 500, 502, 503}


def authenticate(
    credentials_file: Path = CREDENTIALS_FILE,
    token_file: Path = TOKEN_FILE,
) -> Credentials:
    """Run the OAuth 2.0 installed-app flow (opens browser on first run)."""
    creds: Credentials | None = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not credentials_file.exists():
            raise FileNotFoundError(
                f"Missing {credentials_file}.\n"
                "Download your OAuth client JSON from the Google Cloud Console "
                "and save it as credentials.json in the project root."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
        creds = flow.run_local_server(port=0)

    # Persist for next run
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_service(creds: Credentials | None = None) -> Resource:
    """Return an authorised Gmail API service object."""
    if creds is None:
        creds = authenticate()
    return build("gmail", "v1", credentials=creds)


def compose_message(
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    sender_name: str = "",
) -> str:
    """Build an RFC 2822 message and return its base64url encoding."""
    if body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        msg = MIMEText(body_text, "plain", "utf-8")

    msg["To"] = to
    msg["Subject"] = subject
    # "From" is always overridden by Gmail to the authenticated account;
    # we set the display name only when configured.
    if sender_name:
        msg["From"] = f"{sender_name} <me>"

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return raw


def send_message(
    service: Resource,
    raw_b64: str,
) -> dict[str, Any]:
    """Call messages.send and return the API response dict.

    Raises
    ------
    HttpError  with a retryable status  → caller should retry.
    HttpError  with a permanent status  → caller should NOT retry.
    """
    body = {"raw": raw_b64}
    result = service.users().messages().send(userId="me", body=body).execute()
    return result


def is_retryable(err: HttpError) -> bool:
    """True when the Gmail error is transient and worth retrying."""
    return err.resp.status in _RETRYABLE
