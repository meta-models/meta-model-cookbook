#!/usr/bin/env python3
"""
Muse Spark as a container-sandboxed coding agent.

Give the model a shell it can only run *inside a disposable Docker container*,
then let it fix a real bug by itself: reproduce (red) -> edit -> re-run (green).
Nothing the model does can touch the host. The container is torn down at the end.

Pipeline for the one task in task.json (a real SWE-bench instance):
  1. SPIN UP   build/reuse the per-instance image, `docker run -d` a sandbox
  2. REPRODUCE the agent runs the failing tests and sees them fail
  3. FIX       the agent edits source in /testbed via its two tools
  4. VERIFY    the agent re-runs the tests until they pass (may iterate)
  5. TEAR DOWN `docker rm -f` — the sandbox and everything in it is gone

The model reaches muse-spark-1.1 directly over the ambient egress proxy; there is no
logging proxy. Its only powers over the world are the two tools below.

Usage:
  MODEL_API_KEY=... python sandbox_scaffold.py           # runs task.json
  MODEL_API_KEY=... python sandbox_scaffold.py --max-steps 25

Env:
  MODEL_API_KEY   (required) bearer token for the model endpoint
  MODEL_BASE_URL  default https://api.meta.ai/v1
  MODEL_NAME      default muse-spark-1.1
"""
import argparse
import base64
import json
import os
import re
import ssl
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request

from swebench.harness.docker_build import build_env_images, build_instance_image

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(s):
    return ANSI_RE.sub("", s)
from swebench.harness.test_spec.test_spec import make_test_spec

HERE = os.path.dirname(os.path.abspath(__file__))
WORKDIR = "/testbed"  # where every SWE-bench image checks out the repo
DEFAULT_MODEL_NAME = "muse-spark-1.1"

# ---------------------------------------------------------------------------
# terminal styling (screenshots look better with clear stage banners)
# ---------------------------------------------------------------------------
BOLD, DIM, RED, GRN, YEL, CYN, RST = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m",
)


def banner(n, title):
    print(f"\n{BOLD}{CYN}{'=' * 70}\n  STAGE {n}: {title}\n{'=' * 70}{RST}", flush=True)


def say(msg, color=""):
    print(f"{color}{msg}{RST}", flush=True)


# ---------------------------------------------------------------------------
# host + container shells
# ---------------------------------------------------------------------------
def sh(cmd, **kw):
    """Run a command on the host."""
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def dexec(container, cmd, workdir=WORKDIR, timeout=600):
    """Run a shell command *inside* the sandbox. Returns (exit_code, combined_output).

    `pipefail` so a failing command piped into `tail`/`head` still reports its real
    exit code (otherwise `pytest … | tail` always looks like success)."""
    r = subprocess.run(
        # PY_COLORS/FORCE_COLOR make pytest & friends emit color even when piped,
        # so the terminal (and screenshots) show real red/green.
        ["docker", "exec", "-e", "PY_COLORS=1", "-e", "FORCE_COLOR=1",
         "-w", workdir, container, "bash", "-lc", "set -o pipefail; " + cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout + r.stderr)


def dwrite(container, path, content):
    """Write a file inside the sandbox (base64 to sidestep all quoting)."""
    b64 = base64.b64encode(content.encode()).decode()
    target = path if path.startswith("/") else f"{WORKDIR}/{path}"
    r = subprocess.run(
        ["docker", "exec", "-i", container, "bash", "-lc",
         f"mkdir -p \"$(dirname '{target}')\" && base64 -d > '{target}'"],
        input=b64, capture_output=True, text=True,
    )
    return r.returncode, (r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# the two tools we expose to the model
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run",
            "description": (
                "Run a bash command inside the sandbox container, working dir /testbed. "
                "Use it to read code, run the tests, inspect failures — anything a shell can do. "
                "Returns exit code and combined stdout/stderr (truncated)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string", "description": "the bash command"}},
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a file inside the sandbox. Path is relative to /testbed "
                "(or absolute). Writes the full content you provide — send the complete file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
]

MAX_TOOL_OUTPUT = 6000  # chars fed back to the model per tool call
ECHO_LINES = 14         # lines of each command's output shown on the terminal


def echo_result(rc, out):
    """Print a trimmed, dimmed view of a command's output so a viewer (and a
    screenshot) can see what actually happened — the full text still goes to the model."""
    lines = out.rstrip("\n").split("\n") if out.strip() else []
    shown = lines if len(lines) <= ECHO_LINES else ["…"] + lines[-ECHO_LINES:]
    for ln in shown:
        # dim only the gutter; let the line keep its own color (pytest red/green)
        print(f"{DIM}  │ {RST}{ln}")
    say(f"{DIM}  └ exit {rc}{RST}")


def dispatch(container, name, args):
    """Execute one tool call against the sandbox, return the string result for the model."""
    if name == "run":
        cmd = args.get("cmd", "")
        say(f"{CYN}  $ {cmd}{RST}")
        rc, out = dexec(container, cmd)
        echo_result(rc, out)  # colored, for the terminal / screenshots
        clean = strip_ansi(out)  # model sees plain text, not color codes
        tail = clean if len(clean) <= MAX_TOOL_OUTPUT else "…(truncated)…\n" + clean[-MAX_TOOL_OUTPUT:]
        return f"exit_code: {rc}\n{tail}"
    if name == "write_file":
        path = args.get("path", "")
        say(f"{DIM}  ✎ write {path} ({len(args.get('content', ''))} bytes){RST}")
        rc, out = dwrite(container, path, args.get("content", ""))
        return f"exit_code: {rc}\n{out}" if rc else f"wrote {path}"
    return f"unknown tool: {name}"


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------
def https_context():
    """Use configured or packaged CA certificates when venv defaults omit them."""
    ca_files = [
        os.environ.get("SSL_CERT_FILE"),
        os.environ.get("REQUESTS_CA_BUNDLE"),
        os.environ.get("CURL_CA_BUNDLE"),
    ]
    try:
        import certifi

        ca_files.append(certifi.where())
    except Exception:
        pass

    for ca_file in ca_files:
        if ca_file and os.path.exists(ca_file):
            return ssl.create_default_context(cafile=ca_file)
    return ssl.create_default_context()


def chat(messages):
    """One call to the model's chat/completions endpoint. Uses only the standard
    library (urlopen honors the ambient HTTPS_PROXY egress), so the driver has no
    third-party HTTP dependency."""
    base = os.environ.get("MODEL_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
    key = os.environ["MODEL_API_KEY"]
    body = json.dumps({
        "model": os.environ.get("MODEL_NAME", DEFAULT_MODEL_NAME),
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    retryable = {429, 500, 502, 503, 504}
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=600, context=https_context()) as resp:
                return json.load(resp)["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code in retryable and attempt < 5:
                wait = min(2 ** attempt, 30)
                say(f"{YEL}model API HTTP {e.code}; retrying in {wait}s…{RST}")
                time.sleep(wait)
                continue
            raise RuntimeError(f"model API HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            if attempt < 5:
                wait = min(2 ** attempt, 30)
                say(f"{YEL}model API connection error; retrying in {wait}s…{RST}")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("model API request failed after retries")


SYSTEM = f"""You are a coding agent working entirely inside an isolated Docker sandbox.
The repository is checked out at {WORKDIR}. You have exactly two tools: `run` (a bash
shell in the sandbox) and `write_file`. You cannot touch anything outside the container.

Work like an engineer, and be decisive — you have a limited number of steps:
1. Reproduce the failure — run the failing tests and read the actual error.
2. Read the relevant source and find the root cause. Investigate just enough to be sure;
   do not inspect git history, changelogs, or broad edge cases unless your first fix fails.
3. As soon as you understand the fix, APPLY IT to the real source file in {WORKDIR}.
   For small edits, prefer a short Python/sed/perl edit through `run`; use `write_file`
   only when replacing a complete file is clearer. Do not keep researching after you can
   name the exact source line and replacement.
4. Re-run the failing tests to confirm they pass, then run the affected test file once
   as a quick regression check. Do not run the entire suite repeatedly.
Do NOT edit test files. As soon as the target tests pass and that check is clean, STOP
and give a one-paragraph summary of the root cause and your fix.
"""


def build_user_prompt(inst):
    f2p = "\n".join(f"  - {t}" for t in inst["FAIL_TO_PASS"])
    return f"""Fix this bug in the `{inst['repo']}` repository.

--- issue ---
{inst['problem_statement'].strip()}

--- failing tests (already present in the repo; make them pass, do not edit them) ---
{f2p}

Reproduce the failure, fix the source, and verify the tests pass — all inside /testbed.
"""


# ---------------------------------------------------------------------------
# sandbox lifecycle
# ---------------------------------------------------------------------------
def spin_up(inst):
    import docker

    spec = make_test_spec(inst, namespace=None, arch="x86_64")
    client = docker.from_env()
    tags = {t for im in client.images.list() for t in (im.tags or [])}
    if spec.env_image_key not in tags:
        say(f"  building environment image {spec.env_image_key}…", DIM)
        _, failed = build_env_images(client, [spec], force_rebuild=False, max_workers=1)
        if failed:
            raise RuntimeError(f"failed to build environment image {spec.env_image_key}")
        tags = {t for im in client.images.list() for t in (im.tags or [])}
    else:
        say(f"  reusing cached environment image {spec.env_image_key}", DIM)

    if spec.instance_image_key not in tags:
        say(f"  building instance image {spec.instance_image_key}…", DIM)
        build_instance_image(spec, client, None, nocache=False)
    else:
        say(f"  reusing cached instance image {spec.instance_image_key}", DIM)

    container = "muse-sandbox-" + inst["instance_id"].replace("__", "-")
    sh(["docker", "rm", "-f", container])  # clean any leftover
    r = sh(["docker", "run", "-d", "--name", container,
            spec.instance_image_key, "sleep", "infinity"])
    if r.returncode:
        raise RuntimeError(f"docker run failed: {r.stderr}")
    say(f"  sandbox up: {BOLD}{container}{RST}{DIM}  (image {spec.instance_image_key}){RST}", DIM)

    rc, _ = dexec(container, "python - <<'PY'\nimport pytest_mock\nPY")
    if rc:
        say("  installing optional test dependency pytest-mock…", DIM)
        rc, out = dexec(container, "python -m pip install -q 'pytest-mock<4'")
        if rc:
            raise RuntimeError(f"failed to install pytest-mock in sandbox:\n{out}")
    else:
        say("  reusing installed optional test dependency pytest-mock", DIM)

    # Option A: bring the task's tests into the sandbox so the agent can run the real
    # red->green loop, then commit them so HEAD = base+tests. The agent's edits then
    # show up as a source-only `git diff HEAD` (clean patch, no test contamination).
    _, _ = dexec(container, "git config user.email x@x && git config user.name x")
    with open(os.path.join(HERE, "_test.patch"), "w") as f:
        f.write(inst["test_patch"])
    sh(["docker", "cp", os.path.join(HERE, "_test.patch"), f"{container}:/tmp/test.patch"])
    os.remove(os.path.join(HERE, "_test.patch"))
    rc, out = dexec(container, "git apply /tmp/test.patch && git add -A && git commit -q -m tests")
    if rc:
        raise RuntimeError(f"failed to seed tests into sandbox:\n{out}")
    return container, spec


def tear_down(container):
    r = sh(["docker", "rm", "-f", container])
    say(f"  removed {container}: {r.stdout.strip() or r.stderr.strip()}", DIM)
    # prove the isolation
    left = sh(["docker", "ps", "-a", "--filter", f"name={container}", "-q"]).stdout.strip()
    say(f"  containers matching that name now: {'NONE' if not left else left}", DIM)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=os.path.join(HERE, "task.json"))
    ap.add_argument("--max-steps", type=int, default=50)
    args = ap.parse_args()

    if not os.environ.get("MODEL_API_KEY"):
        sys.exit("set MODEL_API_KEY (bearer token for the model endpoint)")

    inst = json.load(open(args.task))[0]
    say(f"{BOLD}task: {inst['instance_id']}  ({inst['repo']} @ {inst['base_commit'][:10]}){RST}")

    container = None
    t0 = time.time()
    try:
        banner(1, "SPIN UP — a fresh, isolated sandbox")
        container, spec = spin_up(inst)

        banner(2, "HAND THE SANDBOX TO MUSE SPARK — reproduce → fix → verify")
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_user_prompt(inst)},
        ]
        for step in range(1, args.max_steps + 1):
            msg = chat(messages)
            messages.append(msg)
            if msg.get("content"):
                say(f"{YEL}muse-spark-1.1:{RST}")
                for para in msg["content"].strip().split("\n"):
                    for line in (textwrap.wrap(para, 96) or [""]):
                        print(f"  {line}")
            calls = msg.get("tool_calls") or []
            if not calls:
                say(f"\n{GRN}agent finished after {step} model turns.{RST}")
                break
            for call in calls:
                fn = call["function"]
                try:
                    a = json.loads(fn["arguments"] or "{}")
                except json.JSONDecodeError:
                    a = {}
                result = dispatch(container, fn["name"], a)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        else:
            say(f"{RED}hit max steps ({args.max_steps}).{RST}")

        banner(3, "VERIFY — run the target tests one more time")
        f2p = " ".join(f"'{t}'" for t in inst["FAIL_TO_PASS"])
        rc, out = dexec(container, f"python -m pytest -q --no-header --color=yes {f2p} 2>&1 | tail -15")
        print(out)
        tests_passed = rc == 0
        say(("✓ FAIL_TO_PASS now PASS" if tests_passed else "✗ tests still failing"),
            GRN if tests_passed else RED)

        # capture the source-only patch before the sandbox is destroyed
        _, patch = dexec(container, "git -c core.fileMode=false diff HEAD")
        with open(os.path.join(HERE, "pred.patch"), "w") as f:
            f.write(patch)
        say(f"  saved source patch -> pred.patch ({patch.count(chr(10))} lines)", DIM)

        # transcript for the write-up
        with open(os.path.join(HERE, "transcript.json"), "w") as f:
            json.dump(messages, f, indent=1, default=str)

        if not tests_passed:
            raise RuntimeError("target tests still failing after agent run")
    finally:
        banner(5, "TEAR DOWN — the sandbox is disposable")
        if container:
            tear_down(container)
        say(f"\n{BOLD}done in {int(time.time() - t0)}s{RST}")


if __name__ == "__main__":
    main()
