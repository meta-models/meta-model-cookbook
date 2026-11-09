#!/usr/bin/env python3
"""Benchmark the pinned Python Pygments lexer against the Rust CLI for one lexer.

Assembles about 1 MB of input from the pinned clone's tests/examplefiles and
tests/snippets files for the lexer. Before timing, both implementations lex
that input once and their token streams (type and text, in order) must be
identical; otherwise the first mismatch is printed and the run fails.

Both sides are timed as whole commands on the same input file, median of 5
runs, output to /dev/null:
  python_s  `python3 -c <snippet> <clone> <alias> <file>`: imports the pinned
            clone, reads the file, calls the lexer's get_tokens() in that
            process and writes one JSON line per token
  rust_s    `<bin> --lexer <alias> --input <file>`
Process start, file read and JSON output count on both sides.

Prints: BENCH <alias> bytes=<n> python_s=<f> rust_s=<f> speedup=<f>
"""

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import find_pygments_dir

TARGET_BYTES = 1_000_000
RUNS = 5
TIMEOUT_S = 120
DEFAULT_BIN = Path(__file__).resolve().parents[1] / "target" / "release" / "pygments-rs"
PYTHON_SNIPPET = r"""
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import pygments
assert pathlib.Path(pygments.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
from pygments.lexers import get_lexer_by_name
out = sys.stdout
for token, value in get_lexer_by_name(sys.argv[2]).get_tokens(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8")):
    out.write(json.dumps({"t": str(token), "v": value}) + "\n")
"""


def load_lexer(pygments_dir: Path, alias: str):
    sys.path.insert(0, str(pygments_dir))
    import pygments
    from pygments.lexers import get_lexer_by_name

    assert Path(pygments.__file__).resolve().is_relative_to(pygments_dir.resolve()), (
        pygments.__file__
    )
    return get_lexer_by_name(alias)


def collect_input(pygments_dir: Path, lexer) -> str:
    chunks: list[str] = []
    for root_name in ("examplefiles", "snippets"):
        for name in lexer.aliases:
            directory = pygments_dir / "tests" / root_name / name
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*")):
                if (
                    not path.is_file()
                    or path.name.startswith("._")
                    or path.name.endswith(".output")
                ):
                    continue
                try:
                    chunks.append(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    continue
    if not chunks:
        raise SystemExit(
            f"no examplefiles/snippets inputs found for lexer {lexer.aliases[0]!r}"
        )

    corpus = "\n".join(chunks)
    text = ""
    while len(text.encode("utf-8")) < TARGET_BYTES:
        text += corpus
        if not text.endswith("\n"):
            text += "\n"
    # Trim to about 1 MB on a character boundary.
    return text.encode("utf-8")[:TARGET_BYTES].decode("utf-8", errors="ignore")


def run(cmd: list[str], stdout) -> bytes:
    proc = subprocess.run(
        cmd, check=False, stdout=stdout, stderr=subprocess.PIPE, timeout=TIMEOUT_S
    )
    if proc.returncode:
        raise SystemExit(
            f"{' '.join(cmd)} exited {proc.returncode}: {proc.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout


def median_time(fn) -> float:
    times = []
    for _ in range(RUNS):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--lexer", required=True, help="lexer alias")
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_BIN,
        help="pygments-rs executable (default: this checkout's target/release/pygments-rs)",
    )
    args = parser.parse_args()

    if not args.bin.is_file():
        raise SystemExit(
            f"no Rust binary at {args.bin}; build it first with cargo build --release"
        )
    registered = run([str(args.bin), "--list"], subprocess.PIPE).decode().split()
    if args.lexer not in registered:
        raise SystemExit(
            f"lexer {args.lexer!r} is not registered in {args.bin} "
            f"(registered: {', '.join(registered) or 'none, the registry is empty'})"
        )

    pygments_dir = find_pygments_dir()
    lexer = load_lexer(pygments_dir, args.lexer)
    text = collect_input(pygments_dir, lexer)
    data = text.encode("utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / "input.txt"
        input_path.write_bytes(data)
        rust_cmd = [str(args.bin), "--lexer", args.lexer, "--input", str(input_path)]

        python_tokens = [(repr(t), v) for t, v in lexer.get_tokens(text)]
        lines = run(rust_cmd, subprocess.PIPE).decode("utf-8").split("\n")
        assert lines.pop() == "", "Rust output does not end with a newline"
        rust_tokens = [(d["t"], d["v"]) for d in map(json.loads, lines)]
        if python_tokens != rust_tokens:
            i = next(
                (
                    i
                    for i, (p, r) in enumerate(zip(python_tokens, rust_tokens))
                    if p != r
                ),
                min(len(python_tokens), len(rust_tokens)),
            )
            show = lambda tokens: (
                repr(tokens[i])[:200] if i < len(tokens) else "<end of stream>"
            )
            raise SystemExit(
                f"PARITY FAIL {args.lexer}: token streams differ on the benchmark input at index {i}: "
                f"python={show(python_tokens)} rust={show(rust_tokens)} "
                f"(python {len(python_tokens)} tokens, rust {len(rust_tokens)})"
            )

        python_cmd = [
            sys.executable,
            "-c",
            PYTHON_SNIPPET,
            str(pygments_dir),
            args.lexer,
            str(input_path),
        ]
        python_s = median_time(lambda: run(python_cmd, subprocess.DEVNULL))
        rust_s = median_time(lambda: run(rust_cmd, subprocess.DEVNULL))

    print(
        f"BENCH {args.lexer} bytes={len(data)} "
        f"python_s={python_s:.4f} rust_s={rust_s:.4f} speedup={python_s / rust_s:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
