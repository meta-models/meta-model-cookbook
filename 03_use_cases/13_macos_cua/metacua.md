# metacua - a macOS computer-use agent

`metacua` is a Swift command-line tool that lets Muse Spark operate your Mac through the GUI. You give it a goal; it captures the screen, sends the image and GUI tool definitions to the model, executes the returned tool calls with native macOS events, then repeats until the task is done.

> [!CAUTION]
> ⚠️ **RUN AT YOUR OWN RISK.** `metacua` is an autonomous agent that takes real control of your Mac. It moves the mouse, types, clicks, and runs whatever the model decides, without asking for confirmation. It can open apps, change settings, send messages, and delete files, including **irreversible actions**. **If you choose to run `metacua` on your computer, you accept full responsibility for everything it does.**
> Unlike containerized computer-use demos that drive a throwaway Linux desktop in Docker, `metacua` drives **your actual machine** — your logged-in accounts, your files, your browser sessions, your network. There is no sandbox between the agent and the rest of your system. That makes the precautions below more important, not less.
>
> To reduce the risk consider:
>
> 1. **Run on a dedicated, low-privilege macOS account** (or a spare/test machine) rather than your primary account, so a mistake can't reach your important data.
> 2. **Keep sensitive data out of reach.** Do not stay logged into banking, email, password managers, or work accounts while the agent runs, and never hand it credentials or secrets.
> 3. **Limit what it can touch.** Prefer narrow, reversible goals; close apps and browser tabs you don't want it interacting with.
> 4. **Supervise every run and stay ready to stop it.** Watch the screen the whole time and intervene the moment it does something unexpected.
> 5. **Require your own confirmation for anything consequential** — purchases, sending messages, deleting files, accepting terms, or any action with real-world effects.

> [!NOTE]
> `metacua` defaults to the `muse-spark-1.1` model against `https://api.meta.ai/v1`, using normalized `0...1000` coordinates and a selectable effort level (`low`, `medium`, `high`, `xhigh`, `max`). Override any of these per run with flags, per shell with environment variables, or persistently with `metacua configure`.


## Tools

`metacua` advertises two model-facing tools, using the same dotted names as the Muse Spark reference agent. Tool calls run one at a time.

| Tool | Description |
| --- | --- |
| `computer.computer` | Perform GUI action(s) via synthetic mouse, keyboard, and screen events, then return a fresh screenshot. |
| `computer.stop` | End the session and submit a final `answer` describing what was accomplished, or why it could not proceed safely. |

`computer.computer` mirrors Anthropic's `computer_20251124` tool interface, except coordinates are **normalized integers in the `0...1000` range** with the origin at the top-left, rather than absolute pixels. The agent maps them to primary-display pixels before executing each action.

### Actions

By default, `computer.computer` uses the single-action schema: one `action` string plus the fields that action needs.

| Action | Parameters |
| --- | --- |
| `left_click`, `right_click`, `middle_click`, `double_click`, `triple_click` | `coordinate?`, `text?` (modifiers to hold) |
| `left_press` | `coordinate?`, `text?` |
| `left_click_drag` | `coordinate` (end), `start_coordinate?` |
| `mouse_move` | `coordinate` |
| `left_mouse_down`, `left_mouse_up` | `coordinate?` |
| `scroll` | `scroll_direction`, `scroll_amount`, `coordinate?`, `text?` |
| `key` | `text` (e.g. `ctrl+s`, `Return`) |
| `type` | `text` |
| `hold_key`, `release_key` | `text` |
| `wait` | `duration?` (seconds) |
| `screenshot` | — |

### Batched actions

Pass `--batched-actions` or run `/batched-actions on` to advertise the batched schema instead. `computer.computer` then takes an `actions` array whose items use the same fields as above; the tool validates the whole batch up front, executes the items in order, and returns a single screenshot at the end.

> [!TIP]
> Batch predictable steps into one call and split only when the next step depends on seeing the result. The `screenshot` action is single-action only — batched runs return one screenshot automatically after the last item.

The local `pointer` subcommand remains available for manual keyboard-driven pointer control from the terminal.


## Quickstart: running metacua

The `make` targets are the fastest way to drive `metacua` — each one builds if needed and then runs, so you never have to call SwiftPM directly. Run every command below from this package directory:

```sh
cd <path-to>/computer-use-demo
```

Pass arguments with `ARGS="..."`, switch to the release build with `CONFIG=release`, and add `SWIFT_FLAGS="--disable-sandbox"` if your environment blocks SwiftPM sandboxing. Building requires macOS with the Xcode command-line tools and Swift 5.9 or newer.

> [!TIP]
> Run `make help` to list every target.

### 1. Grant permissions

The native macOS event path needs two privacy permissions granted to the process that runs `metacua`, usually your terminal app:

- Accessibility: required to post synthetic mouse and keyboard events.
- Screen Recording: required to capture screenshots.

```sh
make permissions ARGS="--prompt"
```

Grant missing permissions under System Settings -> Privacy & Security -> Accessibility and Screen Recording.

> [!NOTE]
> Both permissions are granted to the **app that launches** `metacua` (for example Terminal or iTerm), not to `metacua` itself. If you switch terminals, grant them again for the new one. macOS may require you to quit and relaunch the terminal after granting.

### 2. Configure Muse Spark

Save your API key once:

```sh
make configure ARGS="--api-key LLM_..."
```

Configuration precedence is command flags, then environment variables, then `~/.metacua/config.json`, then defaults (existing configs under `~/.config/metacua/config.json` are still read as a fallback). The defaults are the `muse-spark-1.1` model against `https://api.meta.ai/v1`, normalized 0-1000 coordinates, `high` effort, screenshot scale `1.0`, recent image limit `5`, and batched actions off. Override any of them when saving:

```sh
make configure ARGS="--api-key LLM_... --model muse-spark-1.1 --coords normalized --effort high --screenshot-scale 1.0 --max-images 5"
```

Add `--batched-actions` to persist batched tool mode, or `--no-batched-actions` to turn it back off.

> [!TIP]
> You do not have to persist the key. Any flag can be passed per run, or exported as an environment variable for the current shell — handy on shared machines where you would rather not write the key to disk. The overrides are `MODEL_API_KEY` / `MUSE_SPARK_API_KEY`, `LLM_BASE_URL` / `MUSE_SPARK_BASE_URL`, `LLM_MODEL` / `MUSE_SPARK_MODEL`, `LLM_EFFORT`, `METACUA_SCREENSHOT_SCALE`, `METACUA_MAX_IMAGES`, and `METACUA_BATCHED_ACTIONS`.

### 3. Run the interactive session

```sh
make run
```

This drops you into the interactive `metacua >` shell: type a goal, watch the short plan and each step stream by, and use slash commands (`/help` for the full list) to change the model, effort, coordinates, and more between goals. The overlay is on by default.

Every completed LLM call is appended to a per-trajectory JSONL file under `~/.metacua/traces/`. The filename is the trajectory id (`goal_id`), and each line contains the response id, any `session_id` values found in the response, and sanitized message history. Screenshot data URLs are replaced with size placeholders. Existing traces under `~/.local/share/metacua/` are still read as a fallback.

> [!NOTE]
> Traces record the text of your goals and the model's messages, so anything typed or read on screen during a run may be written to disk. Screenshots are stripped to size placeholders, but treat the trace directory as sensitive and prune it periodically.

View recent stored calls with the `sessions` subcommand:

```sh
make run ARGS="sessions"
make run ARGS="sessions --limit 5"
make run ARGS="sessions --id <session-or-response-id>"
make run ARGS="sessions --id <session-or-response-id> --history"
make run ARGS="sessions --id <session-or-response-id> --json"
```

### Building without make

The `make` targets wrap SwiftPM; you can also call it directly. Build a release binary:

```sh
swift build -c release
```

If SwiftPM sandboxing is blocked by your environment, add `--disable-sandbox`:

```sh
swift build -c release --disable-sandbox
```

`swift run` builds if needed and then launches the executable, so it works for any subcommand:

```sh
swift run -c release metacua --help
swift run -c release metacua permissions --prompt
swift run -c release metacua agent --goal "Open Safari and search for the weather in Tokyo"
```

To run the exact binary that was just built without going through `swift run`:

```sh
BIN="$(swift build -c release --show-bin-path)/metacua"
"$BIN" --help
```

## Interactive Commands

```text
/help                    show command help
/model [name]            show or switch the active model
/effort [level]          show or set effort: low, medium, high, xhigh, max
/coords [mode]           show or set coordinates: pixel, normalized
/max-steps [n|off]       show, set, or clear per-goal step cap
/max-images [n]          show or set recent image limit
/batched-actions [on|off] show or toggle batched action tool schema
/overlay [on|off]        show or toggle cursor overlay
/plan [on|off]           show or skip a short plan before each goal
/status                  show session state and permissions
/tools                   list computer-use tools
/doctor                  check configuration and permissions
/config                  show active model settings
/sessions [n|id]         list saved LLM sessions, or show one by id
/permissions [--prompt]  show or request macOS permissions
/clear                   clear the terminal
/new, /reset             start a fresh goal context
/quit                    exit
```

In interactive terminals, slash commands show inline hints while typing. Press Tab to complete a command prefix or list matching commands.

## Coordinate Conventions

Agent mode defaults to Muse Spark's normalized 0-1000 coordinate convention. The agent converts normalized coordinates to primary-display pixels before executing local actions.

By default, screenshots sent to the model use full logical resolution. The first request sends the initial screenshot, and each tool-result turn sends a bounded recent-screenshot observation, oldest to newest. The default limit is the 5 most recent image blocks; older image blocks in explicit request input are replaced with text notes. The action coordinate space remains the full logical display size. Use a smaller value such as `--screenshot-scale 0.5` or `--screenshot-scale 0.25` only when you explicitly want smaller image payloads, or `--max-images N` to use a different recent image limit.

The screenshot image can be lower resolution than the display, but action coordinates always use the primary display's full logical coordinate space.

Scroll direction is normalized from the user's point of view: `down` reveals lower content regardless of the macOS natural scrolling preference.

> [!WARNING]
> `metacua` drives the **primary display only**. Coordinates outside its bounds are clamped to the screen edge, so windows on secondary monitors are out of reach. Move the target window to the main display before running a goal.

## Notes And Limits

- The agent is autonomous and controls your real machine; supervise it.
- The agent operates on the primary display.
- Avoid asking it to perform irreversible actions unless the goal clearly requires them.
- The `type` action inserts text into the focused field and does not automatically submit; use a `key` action with `Return` when submission is needed.
- Exit codes are `0` for success, `1` for runtime error, `2` for usage or validation error, and `3` for missing permission.
