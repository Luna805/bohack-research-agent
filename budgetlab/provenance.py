"""Which code and environment produced a run, so results from several machines stay comparable."""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGES = ("scikit-learn", "pandas", "numpy", "pydantic", "pydantic-ai-slim")


def _git(root: Path, *args: str, strip: bool = True) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() if strip else completed.stdout


def git_info(root: Path) -> dict[str, Any] | None:
    commit = _git(root, "rev-parse", "HEAD")
    if commit is None:
        return None
    status = _git(root, "status", "--porcelain", "--untracked-files=no", strip=False) or ""
    changed = [line[3:] for line in status.splitlines() if line.strip()]
    return {
        "commit": commit,
        "short": commit[:7],
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(changed),
        "dirty_files": changed[:20],
    }


def environment_info() -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": versions,
    }


def code_version_label(git: dict[str, Any] | None) -> str:
    if git is None:
        return "unknown (not a git checkout)"
    return git["short"] + ("-dirty" if git["dirty"] else "")
