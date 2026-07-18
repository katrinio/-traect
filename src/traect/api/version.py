"""Asset versioning for cache busting on deployment."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def get_version_string() -> str:
    """Get version string based on git commit hash or fallback to timestamp."""
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

    # Fallback to environment variable or a default
    return os.environ.get("TRAECT_VERSION", "local")
