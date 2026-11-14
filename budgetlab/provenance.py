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
        # Git prints UTF-8 (branch names such as 前端优化). text=True would decode with the
        # locale encoding, which is cp1252 on Windows and fails on those bytes.
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() if strip else completed.stdout


# Outputs and prose never change behaviour, so they do not make a checkout "dirty".
NON_CODE_PREFIXES = ("results/", "docs/")
NON_CODE_SUFFIXES = (".md",)


def _affects_code(path: str) -> bool:
    path = path.strip().strip('"')
    if " -> " in path:  # rename: judge the new path
        path = path.split(" -> ", 1)[1]
    return not (path.startswith(NON_CODE_PREFIXES) or path.endswith(NON_CODE_SUFFIXES))


def git_info(root: Path) -> dict[str, Any] | None:
    commit = _git(root, "rev-parse", "HEAD")
    if commit is None:
        return None
    # Untracked-but-not-ignored files count too: a new module or config changes behaviour.
    status = _git(root, "status", "--porcelain", "--untracked-files=all", strip=False) or ""
    changed = [line[3:] for line in status.splitlines() if line.strip()]
    changed = [path for path in changed if _affects_code(path)]
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
