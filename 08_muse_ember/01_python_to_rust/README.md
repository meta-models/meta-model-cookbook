# Port Python to Rust with Muse Wonder and Muse Ember

|  |  |
|---|---|
| **Section** | [Muse Ember](https://dev.meta.ai/docs/cookbook/muse-ember) |
| **Time to complete** | About 30–35 minutes |
| **Model** | `muse-wonder-1.0` (planner), `muse-ember-1.0` (port-workers) |
| **Harness** | Muse Code |
| **Prerequisites** | Linux, Git, Python 3.10+, Rust 1.98.1 through [rustup](https://rustup.rs), Muse Code |

## Summary

Port 16 Pygments lexers from Python to Rust with three prompts. Muse Wonder plans the work, writes each handoff and checks the results. Muse Ember port-workers do the coding, many of them in parallel.

A lexer splits source code into typed tokens such as keywords, names, strings and comments. Each port must match the Python lexer token for token, and Prompt 3 scores it on 62 held-out files the agents never saw.

The sample project includes the Rust lexing engine, so the run starts with the checker.

*Models are non-deterministic; your code, time and results may differ.*

## When To Use

- Does the work split into file-owned tasks?
- Do you have a reference implementation to compare against?
- Do the plan and the checks need a larger model, while most of the coding is bounded?

Use one agent when tasks share files or need serial design decisions.

## How The Work Is Split

| Role | Model | Does |
|---|---|---|
| Planner | Muse Wonder | Plans, writes each worker's handoff, dispatches, runs the checks and the final benchmarks |
| Port-workers | Muse Ember | Map the code, build and review the checker, write test inputs, close engine gaps, port one language each, merge |

A port is done when it matches the Python reference on every input and Rust is no slower than Python.

## Set Up The Sample Project

Install Muse Code with `curl -fsSL https://dev.meta.ai/install.sh | bash`. Sign in with your plan, or use an API key with a low spend limit.

In the commands below, `<recipe>` is this directory in your clone of the cookbook. Create the sample project **outside** it, so the agents can't see the prompts or the held-out list:

```bash
cp -r <recipe>/starter-kit ~/pygments-port
cd ~/pygments-port
git clone https://github.com/pygments/pygments.git pygments
git -C pygments checkout --detach a43b45dcf081b6010c6ab4428f149f7f6d2499c4
git init -q && git add -A && git commit -q -m "Starter kit"
(cd pygments-rs && cargo test --release)   # required: caches the crates the agents build against
```

[SETUP.md](SETUP.md) lists the full requirements, including the Git identity the commits use, and the checks to run before you launch.

## Launch Muse Code

```bash
export MODEL_API_KEY=...   # only if you use an API key
cd ~/pygments-port && bash <recipe>/launch/launch.sh
```

The script starts Muse Code with Muse Wonder as the planner at high reasoning effort and loads the Muse Ember port-workers from `agents/agents.json`. It runs unattended, so use a disposable sample project.

## Build The Checker With Prompt 1

Paste [`PROMPT_1.md`](prompts/PROMPT_1.md). Muse Wonder briefs one worker to write `diff.py`, which runs the Python reference and the Rust CLI on the same input and compares the exact token streams. The prompt lists the cases the checker must handle and requires a test for each. A second worker reviews the change, Muse Wonder runs the checks itself, and the run stops so you can read the report.

## Plan And Port With Prompt 2

Paste [`PROMPT_2.md`](prompts/PROMPT_2.md). Muse Wonder doesn't read the source itself. One worker reads the Python lexers, the engine and the checker and returns a map of how each lexer fits the engine, and Muse Wonder writes the plan and handoffs from it. One worker ports Python as the worked example while others write test inputs and close shared engine gaps.

Muse Wonder then freezes the checker, inputs and engine and starts 16 porters, one language each in its own worktree. A porter commits only when its port is done by the rule above. One merge worker brings the ports together and runs every check, and Muse Wonder runs each benchmark once on the merged code. Prompt 2 ends with the sample project's branch fast-forwarded to the final code and the hash from `git rev-parse HEAD` in the report.

Open `/workflows` to see each worker, its model, tokens and time.

## Score The Held-Out Files With Prompt 3

In a second terminal, download the held-out files (62 files from public repositories, pinned by SHA-256):

```bash
python3 <recipe>/heldout-tools/fetch.py --dest ~/pygments-port/heldout
```

Paste [`PROMPT_3.md`](prompts/PROMPT_3.md). It scores all 16 languages without any code changes.

## Recorded Results

Recorded from one of three runs of these prompts; all three passed every check and scored 62/62 on the held-out files.

| Lexer | Supplied inputs | Held-out files | Speedup |
|---|---:|---:|---:|
| Python (worked example) | 90/90 | — | 4.2x |
| Java | 18/18 | 4/4 | 5.6x |
| C | 26/26 | 4/4 | 3.8x |
| C++ | 22/22 | 4/4 | 3.0x |
| C# | 20/20 | 4/4 | 6.9x |
| Go | 13/13 | 4/4 | 5.9x |
| Rust | 17/17 | 4/4 | 4.7x |
| JavaScript | 28/28 | 4/4 | 5.5x |
| Lua | 12/12 | 4/4 | 5.3x |
| Swift | 8/8 | 4/4 | 5.0x |
| Kotlin | 16/16 | 4/4 | 5.8x |
| Scala | 48/48 | 4/4 | 3.1x |
| Perl | 13/13 | 4/4 | 4.0x |
| CSS | 8/8 | 2/2 | 7.3x |
| Haskell | 15/15 | 4/4 | 6.2x |
| SQL | 5/5 | 4/4 | — |
| R | 24/24 | 4/4 | 6.4x |

`bench.py` times the Python lexer and the Rust CLI on about 1 MB of input per language (median of 5 runs), after checking that both produce the same tokens; times include process startup. SQL has no speedup because the pinned Pygments clone has no SQL example files to benchmark.

| Role | Model calls | Input tokens | Cached input | Output tokens |
|---|---:|---:|---:|---:|
| Planner (Muse Wonder) | 56 | 4,412,412 | 4,306,528 | 41,953 |
| Port-workers (Muse Ember) | 1,466 | 157,557,148 | 154,039,752 | 986,319 |

Token counts cover all three prompts. Cached input is included in input tokens.

## Common Failure Modes

### A Turn Ends Before Its Work Is Done

Type `Continue.`

### A Worker Seems Stuck

Open `/workflows` and read the worker's conversation. Muse Wonder looks for the worker's commit before it redispatches the task.

### A Held-Out File Fails

Report the failure. Changing code in response turns the held-out files into another development set.

This recipe is part of the Meta Model API Cookbook and uses the repository's [LICENSE](../../LICENSE). Pygments uses BSD-2-Clause; the held-out manifest records each source's license.
