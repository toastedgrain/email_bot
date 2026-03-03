"""Jinja2-based template rendering for subject and body."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, BaseLoader, StrictUndefined, UndefinedError


def _make_env() -> Environment:
    """Create a Jinja2 env with {{ }} delimiters and lenient undefined."""
    return Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


class CampaignTemplate:
    """Loads subject.txt, body.txt, and optional body.html from a directory."""

    def __init__(self, template_dir: Path) -> None:
        self.template_dir = template_dir

        subject_path = template_dir / "subject.txt"
        body_path = template_dir / "body.txt"
        html_path = template_dir / "body.html"

        if not subject_path.exists():
            raise FileNotFoundError(f"Missing {subject_path}")
        if not body_path.exists():
            raise FileNotFoundError(f"Missing {body_path}")

        self.subject_src = subject_path.read_text(encoding="utf-8").strip()
        self.body_src = body_path.read_text(encoding="utf-8")
        self.html_src: str | None = (
            html_path.read_text(encoding="utf-8") if html_path.exists() else None
        )

        self._env = _make_env()
        self._subject_tpl = self._env.from_string(self.subject_src)
        self._body_tpl = self._env.from_string(self.body_src)
        self._html_tpl = (
            self._env.from_string(self.html_src) if self.html_src else None
        )

    def render(
        self,
        name: str,
        email: str,
        extras: dict[str, Any] | None = None,
        signature: str = "",
    ) -> dict[str, str]:
        """Render templates for one recipient.

        Returns {"subject": ..., "body_text": ..., "body_html": ... | None}.
        """
        ctx: dict[str, Any] = {
            "name": name,
            "email": email,
            "signature": signature,
            **(extras or {}),
        }

        # Replace missing variables with empty string rather than erroring
        def _safe_render(tpl: Any) -> str:
            try:
                return tpl.render(ctx)
            except UndefinedError:
                # Fall back to a lenient env for this render
                lenient = Environment(loader=BaseLoader(), keep_trailing_newline=True)
                return lenient.from_string(tpl.source).render(ctx)

        result: dict[str, str] = {
            "subject": _safe_render(self._subject_tpl),
            "body_text": _safe_render(self._body_tpl),
        }
        if self._html_tpl:
            result["body_html"] = _safe_render(self._html_tpl)
        else:
            result["body_html"] = ""

        return result

    def render_for_recipient(
        self, recipient_row: dict[str, Any], signature: str = ""
    ) -> dict[str, str]:
        """Convenience: pass a DB recipient row directly."""
        extras = json.loads(recipient_row.get("extra_json", "{}"))
        return self.render(
            name=recipient_row["name"],
            email=recipient_row["email"],
            extras=extras,
            signature=signature,
        )
