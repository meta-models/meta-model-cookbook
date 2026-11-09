Build pygments-rs/tools/diff.py and its tests with one Muse Ember port-worker. You plan the task and check the result; the worker writes the code.

Work through to the end without stopping to ask for confirmation.

The checker runs the cloned Python reference and Rust CLI on the same input and compares the exact ordered token types and text, including empty-valued tokens.
- CLI: diff.py --lexer <alias> [--bin <exe>] [--inputs <dir>]. The default binary is the current checkout's or worktree's pygments-rs/target/release/pygments-rs.
- Default inputs: Pygments tests/examplefiles and tests/snippets for every alias, plus pygments-rs/corpus/crafted/<alias>. With --inputs, use only that directory. Follow the reference project's input-file conventions; skip ._* metadata.
- Print SCORE pass=<n> fail=<n> total=<n>. Exit nonzero on mismatch, malformed output, zero inputs, child errors or timeouts. Bound every child process with a timeout.
- Keep the reference tied to the cloned pygments/ from the main checkout, including from worktrees. No installed-Pygments fallback or saved expected-token files. Add --emit-reference for Python token JSON Lines. Split JSON Lines on "\n" only. tools/bench.py is supplied and frozen; don't change it.
- Test matching output and rejection of changed types/text, reordered/missing/extra tokens, malformed JSON, missing fields, empty output, child errors, timeout and zero inputs. Commit only diff.py and its tests.

The checker is accepted only if each of these holds and a test in the checker's test file demonstrates it:
- With a --bin that prints the pinned clone's own tokens, the default inputs score SCORE pass=<n> fail=0 total=<n> over every upstream snippet and example file for the alias, run from the checkout root and from a subdirectory. A stand-in binary that emits no tokens, or a copy of the starter build taken during Prompt 1, fails; never test this with the current build, which gains lexers in Prompt 2.
- A --bin that gives empty output, a changed type, changed text, reordered, missing or extra tokens, an extra empty-valued token, malformed JSON, a missing t or v field, a blank line, a nonzero exit, or that does not exist, fails.
- Two empty token streams fail, even when both children exit 0.
- A child that runs past the timeout fails with a message naming the timeout, both with --timeout <seconds> and with the default.
- Zero inputs, a directory holding only ._* files, an unreadable input and an input that is not valid UTF-8 each fail.
- Every input reaches the binary exactly as Pygments' own test harness passes it to the lexer (pygments/tests/conftest.py shows how snippets and example files are read): for a snippet, only its input, never its comments, ---input--- header or ---tokens--- section; for a file with CRLF line endings, the text the harness reads. Crafted inputs follow the same rule as example files.
- Reference tokens always come from the pinned pygments/ clone, in diff runs and with --emit-reference: with a decoy pygments on PYTHONPATH, with the working directory inside another git repository that has its own pygments/, and from a linked worktree that contains a decoy pygments/.
- In a linked worktree, the default binary is that worktree's build; with no build there, the run fails instead of using another checkout's binary.
- diff.py --help documents every option, including --timeout and --emit-reference. Running the checker leaves git status unchanged.
- The tests run with python3 -m unittest and the standard library only; pytest is not installed.

Have a fresh port-worker review the code and report its findings, and run the checks yourself. Verify a real matching stream passes and deliberately broken streams fail. In a separate git worktree, verify the default binary is that worktree's build and the Python reference is still the pinned clone. Report the commit and evidence, then wait before porting.

How workers run (this applies to every prompt):
- Spawn every worker with subagent_type port-worker. Never set worktree_isolation: under the public sandbox an isolated worktree's git dir is read-only, so its worker cannot commit. A worker that needs its own worktree creates it with git worktree add -b <step-id> /tmp/<step-id> <base> and commits there.
- Keep yourself and every brief inside the workspace, the worker worktrees and the pinned pygments/ clone; never search the filesystem root, the home directory or other checkouts. Never run find, locate, grep -r, du or any other recursive scan outside this checkout and its worktrees: scans outside the checkout can hang. Put this rule in every brief.
- Results arrive only through subagent_wait or your inbox. Workers write no report files; never search the filesystem for them. A "duplicate" spawn reply means that command_id's work already exists; read its result instead. While workers run, end your turn or wait on them; never poll. If a wait on a worker times out, or it shows running more than 5 minutes after its last activity, look for its commit with git log --all --oneline --grep='^<step-id>'. If the commit exists, treat the worker as STATUS: COMMITTED with that hash and move on; cancel it if it still shows running after one more timeout. Otherwise wait again or end your turn. If two consecutive tool calls return the same output, do something different.
- Read only a worker's STATUS line and the lines under it; open a full result only for a BLOCKED worker.
- Act on the first blocker. Never message a finished worker; to continue its work, spawn a fresh worker with its worktree path and the current base.

Run builds, tests and binaries under (ulimit -v 33554432; timeout 600 ...).
