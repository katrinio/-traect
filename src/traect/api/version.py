"""Asset versioning for cache busting on deployment."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class AssetVersionError(RuntimeError):
    """Raised when a production deployment does not provide a cache-busting version."""


def get_version_string() -> str:
    """Get a stable asset version for cache busting.

    Development can use the local git SHA or the explicit fallback ``local``.
    Production must provide a non-local version through ``TRAECT_VERSION`` or
    include git metadata so the current commit SHA can be resolved.
    """
    version = os.environ.get("TRAECT_VERSION", "").strip()
    if version and version != "local":
        return version

    try:
        git_dir = Path(__file__).resolve().parents[2] / ".git"
        if git_dir.exists():
            output = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=git_dir.parent,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if output:
                return output
    except subprocess.CalledProcessError, FileNotFoundError:
        pass

    if _is_production_environment():
        raise AssetVersionError(
            "TRAECT_VERSION must be set to a non-local commit SHA, git tag, or build id in production"
        )

    return version or "local"


def _is_production_environment() -> bool:
    value = (
        (os.environ.get("TRAECT_ENV") or os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "")
        .strip()
        .lower()
    )
    return value in {"production", "prod"}
