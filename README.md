# Email Bot

A CLI tool for sending personalized emails via the **Gmail API** with OAuth 2.0. Built for Google Workspace accounts (e.g. `@uci.edu`), but works with any Gmail account.

May look to improve usability in the future.

No SMTP. No app passwords. Just OAuth.

## Features

- **Personalized templates** - Jinja2 with `{{ name }}`, `{{ company }}`, or any custom field
- **CSV / JSON import** - bring your own recipient list with any columns
- **Campaign system** - manage multiple email campaigns independently
- **Safety first** - mandatory dry-run before live send, hard cap per run (default 50), test-mode allowlist
- **Idempotent** - SQLite tracks every send; reruns never send duplicates
- **Rate limiting** - configurable emails-per-minute throttle
- **Retry logic** - exponential backoff on transient Gmail errors
- **HTML + plain text** - multipart emails with optional HTML body
- **Reports** - status dashboard and CSV export of all send attempts

## Quick Start

### 1. Prerequisites

- Python 3.11+
- A Google Cloud project with the Gmail API enabled
- An OAuth 2.0 Desktop client credential (`credentials.json`)

> **Don't have `credentials.json` yet?** See [Google Cloud Setup](#google-cloud-setup) below.

### 2. Install

```bash
git clone https://github.com/YOUR_USERNAME/email-bot.git
cd email-bot
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e .
```

### 3. Authenticate

Place your `credentials.json` in the project root, then:

```bash
emailbot auth
```

This opens your browser to authorize the app. The token is saved locally in `data/token.json` and reused automatically.

### 4. Send Your First Email

```bash
# Create a campaign (uses templates/example_campaign/)
emailbot campaign-create example_campaign

# Import recipients (replace CAMPAIGN_ID with the ID printed above)
emailbot import-recipients examples/recipients.csv -c CAMPAIGN_ID

# Preview what emails will look like
emailbot preview -c CAMPAIGN_ID

# Dry run (required before live send)
emailbot send --dry-run -c CAMPAIGN_ID

# Send for real (to yourself first!)
emailbot send --live -c CAMPAIGN_ID --allowlist "you@gmail.com"

# Send to everyone
emailbot send --live -c CAMPAIGN_ID --disable-allowlist
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `emailbot auth` | Authenticate with Gmail (opens browser on first run) |
| `emailbot campaign-create <name>` | Create a new campaign |
| `emailbot campaign-list` | List all campaigns |
| `emailbot import-recipients <file> -c <id>` | Import recipients from CSV or JSON |
| `emailbot preview -c <id> [--limit N]` | Preview rendered emails without sending |
| `emailbot send --dry-run -c <id>` | Simulate sending (required before live) |
| `emailbot send --live -c <id>` | Send emails for real |
| `emailbot status -c <id>` | Show campaign send stats |
| `emailbot export-report -c <id> [-o file.csv]` | Export send log as CSV |

### Send Options

| Flag | Default | Description |
|------|---------|-------------|
| `--max` | 50 | Hard cap on emails per run |
| `--rate` | 20 | Max emails per minute |
| `--allowlist "a@x.com,b@y.com"` | none | Only send to these addresses (test mode) |
| `--disable-allowlist` | false | Send to all recipients |
| `--max-retries` | 3 | Retry count for transient errors |

## Templates

Each campaign has a template directory with these files:

```
templates/my_campaign/
  subject.txt      # Subject line (one line, Jinja2)
  body.txt         # Plain-text body (Jinja2)
  body.html        # Optional HTML body (Jinja2)
```

### Example `subject.txt`

```
Hi {{ name }} - quick intro
```

### Example `body.txt`

```
Hi {{ name }},

{{ custom_line }}

I'd love to connect. Let me know if you're free for a quick chat.

Best,
Andrew
```

### Available Variables

| Variable | Source |
|----------|--------|
| `{{ name }}` | Recipient name (defaults to "there" if missing) |
| `{{ email }}` | Recipient email address |
| `{{ signature }}` | Campaign signature (set with `--signature`) |
| Any CSV/JSON column | Automatically available (e.g. `{{ company }}`, `{{ role }}`) |

Missing optional variables render as empty strings, so templates won't break.

## Recipient Format

### CSV

```csv
email,name,company,role,custom_line
alice@example.com,Alice,Acme Corp,Engineer,Loved your talk!
bob@example.com,Bob,,,
```

### JSON

```json
[
  {"email": "alice@example.com", "name": "Alice", "company": "Acme Corp"},
  {"email": "bob@example.com"}
]
```

**Rules:**
- `email` is the only required column
- Missing `name` defaults to "there"
- All other columns are optional and passed directly to templates
- Emails are lowercased and validated; invalid/duplicate rows are skipped with a report

## Google Cloud Setup

One-time setup (~5 minutes):

1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Go to **APIs & Services > Library**, search **Gmail API**, and **Enable** it
4. Go to **APIs & Services > Credentials**
5. If prompted, configure the **OAuth consent screen**:
   - User type: **Internal** (for Workspace accounts like @uci.edu) or **External**
   - Add scope: `https://www.googleapis.com/auth/gmail.send`
6. Click **+ CREATE CREDENTIALS > OAuth client ID**
   - Application type: **Desktop app**
   - Click **Create**
7. Download the JSON and save it as `credentials.json` in the project root

## Project Structure

```
email-bot/
  pyproject.toml
  credentials.json         # you provide (gitignored)
  email_bot/
    cli.py                 # CLI entry point
    config.py              # paths, scopes, defaults
    db.py                  # SQLite schema + queries
    gmail_provider.py      # OAuth + Gmail API
    recipients.py          # CSV/JSON import + validation
    templating.py          # Jinja2 rendering
    campaigns.py           # campaign management
    rate_limit.py          # throttling
    reporting.py           # status + CSV export
    utils.py               # email validation, hashing
  templates/               # one subdirectory per campaign
  examples/                # sample recipient files
  data/                    # SQLite DB + OAuth token (gitignored)
```

## Safety

- **Dry run required** before any live send (same template must be dry-run first)
- **Hard cap** of 50 emails per run (override with `--max`)
- **Allowlist mode** to restrict sends during testing
- **Idempotent** sends tracked in SQLite; reruns skip already-sent recipients
- **Rate limiting** prevents hitting API quotas
- **From address** is always the authenticated Gmail account

## License

MIT
