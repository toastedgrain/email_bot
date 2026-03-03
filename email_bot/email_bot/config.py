"""Central configuration constants and paths."""

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = DATA_DIR / "token.json"
DB_FILE = DATA_DIR / "emailbot.sqlite"

# ── Gmail API ────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_MAX_PER_RUN = 50
DEFAULT_MAX_PER_MINUTE = 20
DEFAULT_SENDER_NAME = ""  # empty → Gmail uses account default

# ── Test-mode allowlist ──────────────────────────────────────────────────
# When test mode is active only addresses in this list receive mail.
# Override via --disable-allowlist flag on the send command.
TEST_ALLOWLIST: list[str] = []  # populated at runtime from CLI / env
