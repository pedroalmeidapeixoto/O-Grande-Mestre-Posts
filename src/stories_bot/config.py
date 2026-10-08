"""Runtime configuration, read from environment variables (never from files)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote


class ConfigError(RuntimeError):
    """Required configuration is missing."""


@dataclass(frozen=True)
class Settings:
    ig_user_id: str
    ig_access_token: str
    media_base_url: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Build settings, deriving the media URL from GitHub Actions variables when unset."""
        env = os.environ if environ is None else environ

        base = env.get("MEDIA_BASE_URL", "")
        if not base and env.get("GITHUB_REPOSITORY"):
            branch = env.get("GITHUB_REF_NAME", "main")
            base = f"https://raw.githubusercontent.com/{env['GITHUB_REPOSITORY']}/{branch}/media"

        values = {
            "IG_USER_ID": env.get("IG_USER_ID", ""),
            "IG_ACCESS_TOKEN": env.get("IG_ACCESS_TOKEN", ""),
            "MEDIA_BASE_URL (or GITHUB_REPOSITORY)": base,
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigError(f"missing environment variable(s): {', '.join(missing)}")

        return cls(
            ig_user_id=values["IG_USER_ID"],
            ig_access_token=values["IG_ACCESS_TOKEN"],
            media_base_url=base,
        )


def media_url(base_url: str, filename: str) -> str:
    """Public URL Meta will download the media from (the repo must be public)."""
    return f"{base_url.rstrip('/')}/{quote(filename)}"
