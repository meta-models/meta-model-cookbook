"""paths.py resolves the pinned clone from its own checkout, never from the cwd."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PATHS_PY = Path(__file__).resolve().parent / "paths.py"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        env=ENV,
        check=True,
        capture_output=True,
    )


def make_repo(root: Path) -> Path:
    """A git repo with its own pygments/pygments/lexer.py and a copy of paths.py."""
    (root / "pygments" / "pygments").mkdir(parents=True)
    (root / "pygments" / "pygments" / "lexer.py").write_text("")
    (root / "pygments-rs" / "tools").mkdir(parents=True)
    shutil.copy(PATHS_PY, root / "pygments-rs" / "tools" / "paths.py")
    (root / ".gitignore").write_text("pygments/\n")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")
    return root


def resolve(tools: Path, cwd: Path) -> Path:
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import paths; print(paths.find_pygments_dir()); print(paths.repo_root())",
        ],
        cwd=cwd,
        env={**ENV, "PYTHONPATH": str(tools)},
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\n")
    assert Path(out[1]) == Path(out[0]).parent, out
    return Path(out[0])


class PathsTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp)
        self.main = make_repo(tmp / "main")
        self.decoy = make_repo(tmp / "decoy")
        self.tmp = tmp

    def test_foreign_cwd_decoy_repo_is_ignored(self):
        got = resolve(self.main / "pygments-rs" / "tools", self.decoy)
        self.assertEqual(got, self.main / "pygments")

    def test_linked_worktree_uses_main_checkout_clone(self):
        wt = self.tmp / "wt"
        git(self.main, "worktree", "add", "-q", str(wt))
        (wt / "pygments" / "pygments").mkdir(parents=True)
        (wt / "pygments" / "pygments" / "lexer.py").write_text("")
        got = resolve(wt / "pygments-rs" / "tools", self.decoy)
        self.assertEqual(got, self.main / "pygments")


if __name__ == "__main__":
    unittest.main()
