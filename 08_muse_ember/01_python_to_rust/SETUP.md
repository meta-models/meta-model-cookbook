# Setup

Do this once, in the shell you will launch Muse Code from.

## Requirements

- **Network access** to github.com (the Pygments clone), raw.githubusercontent.com (the held-out files, after Prompt 2), crates.io (`index.crates.io` and `static.crates.io`, for the setup `cargo test`), the Muse Code installer and model API, and the Rust installer (`sh.rustup.rs`, `static.rust-lang.org`). If your network needs a proxy, export `https_proxy` (and `http_proxy`, `no_proxy`) for these setup commands and `fetch.py`: git, rustup, cargo and `fetch.py` read them as usual.
- **Muse Code**, with `muse` on your `PATH` (the launch script finds it there):

  ```bash
  curl -fsSL https://dev.meta.ai/install.sh | bash
  # restart your shell, then:
  command -v muse                                                  # prints the path to muse
  ```

- **Rust 1.98.1** through [rustup](https://rustup.rs). Keep the default `~/.cargo` and `~/.rustup` locations: the launch script does not pass `CARGO_HOME` or `RUSTUP_HOME`.

  ```bash
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh   # skip if rustup is installed
  . "$HOME/.cargo/env"
  rustup toolchain install 1.98.1 && rustup default 1.98.1
  ```

- **git 2.31 or newer, with an identity.** The setup commit and the agents' commits use it:

  ```bash
  git config --global user.name "Your Name"
  git config --global user.email "you@example.com"
  ```

- **Python 3.10 or newer** (standard library only).

## Create the workspace

Create the workspace outside this package, so the agents cannot see the prompts or the held-out list. These commands use `~/pygments-port`; `<package>` is the directory that holds this file.

```bash
cp -r <package>/starter-kit ~/pygments-port
cd ~/pygments-port
git clone https://github.com/pygments/pygments.git pygments
git -C pygments checkout --detach a43b45dcf081b6010c6ab4428f149f7f6d2499c4
git init -q && git add -A && git commit -q -m "Starter kit"
```

`pygments/` is the pinned Python reference (Pygments 2.21.0). It is git-ignored, so it is not part of the commit.

## Check the workspace

Run these from `~/pygments-port` before you launch Muse Code. The `cargo test` is required: it downloads the crates the port builds against into `~/.cargo`. The agents' sandboxed shells have no network, so they build from this cache; launch Muse Code with the same `HOME`.

```bash
rustc --version                                                    # rustc 1.98.1 (...)
(cd pygments-rs && cargo test --release)                           # tests/engine.rs: "test result: ok. 27 passed"; the other test result lines report 0 passed
python3 -m unittest discover -s pygments-rs/tools -p 'test_*.py'   # Ran 2 tests ... OK
git status --short                                                 # empty
```

The workspace has no held-out files. You download them only after Prompt 2 finishes (README, Prompt 3).
