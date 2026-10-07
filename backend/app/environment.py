"""Coleta de informações de ambiente para reprodutibilidade (SPEC §13)."""

import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from .version import PROTOCOL_VERSION, SOFTWARE_VERSION

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = out.stdout.strip()
    return commit if out.returncode == 0 and commit else None


def _pkg_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def collect_environment() -> dict:
    return {
        "software_version": SOFTWARE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "git_commit": _git_commit(),
        "python_version": sys.version.split()[0],
        "os": platform.platform(),
        "libraries": {
            "scipy": _pkg_version("scipy"),
            "fastapi": _pkg_version("fastapi"),
            "pydantic": _pkg_version("pydantic"),
            "httpx": _pkg_version("httpx"),
        },
    }
