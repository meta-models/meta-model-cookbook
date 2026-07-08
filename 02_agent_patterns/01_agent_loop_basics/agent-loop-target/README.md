# agent-loop-target

A tiny Python project that ships **green except for five intentionally failing
tests**. Each failing test pins down one bug, and "fixing the bug" means "make
that test pass." It's the sample project for the *Basic Agent Loop* recipe: point
a coding agent at one failing test and watch it run the read → think → act →
observe → repeat loop to green.

## The five bugs (increasing difficulty)

| # | Module | Category | Failing test |
|---|--------|----------|--------------|
| 1 | `agent_loop_target/pagination.py` | off-by-one in a list operation | `tests/test_pagination.py` |
| 2 | `agent_loop_target/grades.py` | wrong comparison operator | `tests/test_grades.py` |
| 3 | `agent_loop_target/normalize.py` | missing edge case | `tests/test_normalize.py` |
| 4 | `agent_loop_target/weather.py` | incorrect API response parsing | `tests/test_weather.py` |
| 5 | `agent_loop_target/async_counter.py` | race condition in async code | `tests/test_async_counter.py` |

Each module's docstring describes the *intended* behavior; the test encodes it.
No source file contains a "this is the bug" comment — finding it is the point.

## Run the tests

No install step needed (pytest reads `pythonpath` from `pyproject.toml`):

```bash
pip install pytest          # once
pytest                      # all five files fail on a fresh checkout
pytest tests/test_grades.py # work one bug at a time
```

"Done" for a bug = its test file is green and nothing else regressed
(`pytest` exits 0 across the whole suite).

## A Go mirror

`go-example/` re-implements the same five bugs in Go with `go test` cases, for
the secondary-language walkthrough. See `go-example/README.md`.
