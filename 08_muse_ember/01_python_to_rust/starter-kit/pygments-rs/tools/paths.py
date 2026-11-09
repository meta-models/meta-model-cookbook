"""Locate the pinned `pygments/` clone from the main checkout or a git worktree.

The clone lives in the main checkout and is git-ignored, so a linked
worktree does not contain it. The clone is resolved from the checkout that
contains this file, never from the current working directory: run in this
file's directory, `git rev-parse --git-common-dir` points at the main
checkout's `.git` directory from either place, and the clone is found
relative to that directory's parent.
"""

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def find_pygments_dir(start: Path | None = None) -> Path:
    """Return the root of the `pygments/` clone (containing `pygments/lexer.py`).

    `start` is a path inside the checkout to resolve from; it defaults to this
    file's directory, not the current working directory.
    """
    start = (start or HERE).resolve()
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=start,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.strip()
    # The common dir is `<main-checkout>/.git`; the clone is in the checkout.
    candidate = Path(common).parent / "pygments"
    if not (candidate / "pygments" / "lexer.py").is_file():
        raise FileNotFoundError(f"no pygments/ clone at {candidate}")
    return candidate


# Backwards-friendly alias.
pygments_clone_dir = find_pygments_dir


def repo_root(start: Path | None = None) -> Path:
    """The main checkout root (the directory containing `pygments/`)."""
    return find_pygments_dir(start).parent


if __name__ == "__main__":
    print(find_pygments_dir())
