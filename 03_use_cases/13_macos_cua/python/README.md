# metacua — a native macOS computer-use agent for Muse Spark

> [!WARNING]
> **Computer use is in beta and inherently risky.** Unlike sandboxed variants,
> this agent controls your real Mac: it moves your mouse, types on your keyboard,
> and sees your screen. Use at your own risk — preferably inside a virtual machine
> or a dedicated macOS user account. Do not give it access to sensitive data,
> logged-in accounts, or credentials. Anything visible on screen (web pages,
> emails, documents) can prompt-inject the agent into unintended actions. The
> optional `--allow-bash` / `--allow-bash true` flag additionally lets the model run shell commands;
> leave it off unless you are experimenting in an isolated environment. Supervise
> it while it runs.

|  |  |
| --- | --- |
| Section | Use cases |
| Time to complete | ~15 min |
| Model | `muse-spark-1.1` |
| Prerequisites | macOS 12+, Python 3.9+, a Meta API key (`MODEL_API_KEY`) |

For an isolated, cross-platform variant, see the OpenCode + Cua recipe in this
folder's sibling directory: [`../`](../).

`metacua` is a hackable terminal CLI that lets Muse Spark operate a real Mac. It
captures the screen, sends the observation to `POST {base}/responses`, parses
the model's next action, executes it with native macOS APIs, then repeats.

## What you'll learn

- How to build a look-act-look computer-use loop against `/responses`.
- How to expose a CUA-guide-aligned `computer.computer` tool plus a terminal
  `computer.stop` tool through OpenAI-style function calling.
- How to run an OSWorld-style `pyautogui` action syntax where code is parsed with
  `ast` and never executed.
- How coordinate conventions differ: normalized 0-1000 tool coordinates vs fixed
  1920x1080 OSWorld pixels vs real display pixels.
- How to run and modify the agent as a terminal-first Python CLI.

## Tools

These are the model tools in the default function-calling syntax:

| Tool | Description |
| --- | --- |
| `computer.computer` | Control the computer via mouse, keyboard, and screen actions. Coordinates are relative integers in `[0, 1000]`, where `(0,0)` is the top-left and `(1000,1000)` is the bottom-right. |
| `computer.stop` | Stop the session and submit a final answer or safety/infeasibility explanation. |
| `bash` | **Opt-in only** with bare `--allow-bash` or `--allow-bash true`; run bounded shell commands on this Mac. |

By default `computer.computer` takes one action object per tool call:

```json
{"action": "left_click", "coordinate": [300, 200]}
```

Supported single-action names are `left_click`, `right_click`, `double_click`,
`middle_click`, `triple_click`, `left_press`, `left_click_drag`, `mouse_move`,
`key`, `type`, `hold_key`, `release_key`, `left_mouse_down`, `left_mouse_up`,
`scroll`, `screenshot`, and `wait`.

With `--batched-actions`, the tool schema changes to a single `actions` array:

```json
{
  "actions": [
    {"action": "left_click", "coordinate": [300, 200]},
    {"action": "type", "text": "hello"},
    {"action": "key", "text": "return"}
  ]
}
```

Batches execute sequentially and stop at the first failed action; the error is
returned to the model as `Action [<index>] (<action>): <message>`. Use short,
predictable batches and split whenever the next action depends on observing the
screen. In batched mode the action enum excludes `screenshot` because a fresh
screenshot is returned after the whole batch.

`computer.stop` is terminal in function-calling mode. When the model calls it,
`metacua` logs the answer and ends the goal without executing any additional tool
calls. Answers containing `infeasible` or `unfeasible` are logged as task
infeasible; all other answers are logged as success.

Manual CLI tools are also available for debugging and calibration: `click`,
`moveto`, `pointer`, `screenshot`, `scroll`, `drag`, `press-key`, `type-text`,
and `permissions`. The `pointer` command is manual-only: it lets you move the
mouse with arrow keys or WASD from the terminal.

## Install

Requires macOS and Python 3.9+.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs `metacua` into the virtual environment with the pyobjc frameworks
needed for Quartz, AppKit, and Accessibility APIs. To run without activating the
venv, use `.venv/bin/metacua`.

You can also run it as a module:

```sh
python3 -m metacua --help
```

## Permissions

Native macOS control requires privacy permissions for the process that runs
`metacua` — usually the Python interpreter or the terminal app hosting it.

- Accessibility: required to post mouse and keyboard events.
- Screen Recording: required to capture screenshots.

Check or request permissions:

```sh
metacua permissions
metacua permissions --prompt
```

Grant missing permissions under System Settings → Privacy & Security →
Accessibility and Screen Recording. If you change Python interpreters, you may
need to grant permissions again.

## Configure

The config file lives at `~/.metacua/config.json`.

```sh
metacua configure --api-key LLM_...
```

Persist optional settings when needed:

```sh
metacua configure \
  --api-key LLM_... \
  --base-url https://api.meta.ai/v1 \
  --model muse-spark-1.1 \
  --syntax function \
  --coords normalized \
  --effort high \
  --screenshot-scale 1.0 \
  --max-images 10 \
  --allow-bash false \
  --batched-actions false
```

Resolution order is flags → environment → config file → defaults.

| Setting | Flags | Environment | Config key | Default |
| --- | --- | --- | --- | --- |
| API key | `--api-key` | `MODEL_API_KEY`, `MUSE_SPARK_API_KEY` | `apiKey` | required |
| Base URL | `--base-url` | `LLM_BASE_URL`, `MUSE_SPARK_BASE_URL` | `baseURL` | `https://api.meta.ai/v1` |
| Model | `--model` | `LLM_MODEL`, `MUSE_SPARK_MODEL` | `model` | `muse-spark-1.1` |
| Effort | `--effort` | `LLM_EFFORT` | `effort` | `high` |
| Syntax | `--syntax` | `LLM_SYNTAX` | `syntax` | `function` |
| Screenshot scale | `--screenshot-scale` | `METACUA_SCREENSHOT_SCALE`, `LLM_SCREENSHOT_SCALE` | `screenshotScale` | `1.0` |
| Max images | `--max-images` | `METACUA_MAX_IMAGES`, `LLM_MAX_IMAGES` | `maxImages` | `10` |
| Bash tool | `--allow-bash`, `--allow-bash true|false` | `METACUA_ALLOW_BASH` | `allowBash` | `false` |
| Batched actions | `--batched-actions`, `--batched-actions true|false`, `--no-batched-actions` | `METACUA_BATCHED_ACTIONS`, `LLM_BATCHED_ACTIONS` | `batchedActions` | `false` |

`--allow-bash` by itself enables the bash tool. `--allow-bash true|yes|on|1` enables it, and `--allow-bash false|no|off|0` disables it.
`METACUA_ALLOW_BASH` accepts the same true/false value forms.
`metacua configure --allow-bash true|false` persists either state.

`--batched-actions` by itself enables the batched `computer.computer` schema.
`--batched-actions true|yes|on|1` enables it, `--batched-actions false|no|off|0`
disables it, and `--no-batched-actions` forces it off. `METACUA_BATCHED_ACTIONS`
and `LLM_BATCHED_ACTIONS` accept the same true/false value forms.

`--max-images N` must be at least 1. It controls screenshot retention in request
history; see “How this talks to the API” for the chunked truncation policy.

## Run the agent

Run one goal:

```sh
metacua agent --goal "Open Safari and search for the weather in Tokyo"
```

Start the interactive session:

```sh
metacua
```

Common options:

```sh
metacua agent \
  --goal "Open Notes and write today's date" \
  --model muse-spark-1.1 \
  --base-url https://api.meta.ai/v1 \
  --api-key LLM_... \
  --coords normalized \
  --effort high \
  --max-images 10 \
  --max-steps 40 \
  --overlay
```

The default per-goal step cap is 40. Use `--max-steps off` for unlimited steps,
or change it interactively with `/max-steps off`.

### OSWorld pyautogui mode

Use OSWorld-style actions when you want a text-in/code-out action space:

```sh
metacua agent --syntax pyautogui --goal "Open System Settings and turn on Dark Mode"
```

In this mode the observation is aspect-fit into the model's fixed 1920x1080
training resolution. If the display aspect differs, black letterbox bars are
added and the usable screen is the non-black region. The model returns
`pyautogui` calls in text; `metacua` parses them with Python `ast`, never `exec`s
them, and maps coordinates back through the inverse letterbox transform before
performing actions. OSWorld mode does not use function tools: it keeps the
`WAIT`, `DONE`, and `FAIL` control tokens, and `FAIL` is logged as task
infeasible.

## How this talks to the API

Function-calling mode calls `POST {base}/responses` with a body shaped like:

```json
{
  "model": "muse-spark-1.1",
  "instructions": "...system prompt...",
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {"type": "input_text", "text": "Open Safari"},
        {"type": "input_image", "image_url": "data:image/png;base64,..."}
      ]
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "computer.computer",
      "description": "Control the computer via mouse, keyboard, and screen actions.",
      "parameters": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}
    },
    {
      "type": "function",
      "name": "computer.stop",
      "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    }
  ],
  "parallel_tool_calls": false,
  "store": false,
  "stream": false,
  "reasoning": {"effort": "high"}
}
```

When `--allow-bash` is enabled, a third `bash` function tool is appended. When
`--batched-actions` is enabled, `computer.computer` uses an `actions` array
schema instead of a single action object. `parallel_tool_calls` is always `false`
in function-calling mode so computer actions remain serial and stateful.

OSWorld mode omits `tools` and `parallel_tool_calls` and asks for a `pyautogui`
code block instead. The CLI accepts `low`, `medium`, `high`, `xhigh`, and `max`
effort values; the API receives `low`, `medium`, or `high`.

Reasoning output items are not replayed into the next request. With `store:false`,
there is no server-side state for reasoning item IDs, and echoing them back can
trigger a persistence-service error. Message and function-call output items are
replayed.

Screenshot retention keeps at most `--max-images` image blocks in the replayed
conversation. The default is `--max-images 5`. Older screenshots are replaced in
place with this exact marker text:

```text
[Screenshot has been truncated to save context]
```

Per-step traces are written under `~/.metacua/traces/*.jsonl`. Image data is
redacted, but goals and text are stored. Delete that folder to clear local traces.

Inspect traces from the CLI:

```sh
metacua sessions
metacua sessions --id <trace-or-session-id> --history
```

## Interactive commands

```text
/help                    show command help
/model [name]            show or switch the active model
/syntax [mode]           show or set action syntax: function, pyautogui
/effort [level]          show or set effort: low, medium, high, xhigh, max
/coords [mode]           show or set coordinates: pixel, normalized
/max-steps [n|off]       show, set, or clear per-goal step cap
/max-images [n]          show or set retained image count
/batched-actions [on|off] show or toggle batched action tool schema
/overlay [on|off]        show or toggle cursor overlay
/debug [on|off]          show or hide backend reasoning text during execution
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

Slash command input supports Tab completion in interactive terminals. Press
Ctrl-C while a goal is running to interrupt that goal and return to the prompt;
press Ctrl-C at the idle prompt to exit.

## Coordinate conventions

Function-calling agent mode defaults to normalized 0-1000 coordinates. `(0, 0)`
is the top-left of the primary display, and `(1000, 1000)` is the bottom-right.
The agent converts normalized coordinates to primary-display pixels before
executing actions.

Manual tools use global display pixels directly:

```sh
metacua click --app Finder --x 120 --y 90 --click-count 2
metacua scroll --app Safari --direction down --pages 3
metacua press-key --app Safari --key cmd+t
```

OSWorld mode uses 1920x1080 screenshot pixels in the parsed `pyautogui` calls,
with black bars possible. Coordinates in the bars clamp to the nearest visible
screen edge after the inverse letterbox transform.

Screenshots are downscaled to logical points in function-calling mode so
coordinates map 1:1 to cursor position on Retina displays. Scroll direction is
normalized from the user's point of view: `down` reveals lower content regardless
of the macOS natural scrolling preference.

## Overlay

Launch with `--overlay` to show a transparent, click-through cursor overlay. It
displays pointer movement, click ripples, drag paths, and short action labels
without intercepting input.

```sh
metacua agent --goal "Open Calendar" --overlay
```

Preview the overlay without calling the model:

```sh
metacua demo
```

Manual pointer mode is useful for finding pixel coordinates:

```sh
metacua pointer --step 20
```

Use arrow keys or WASD to move, Space or Return to left-click, `+` and `-` to
change the step size, and `q` to quit.

## Demo

<!-- TODO: record on a Mac with --overlay before publishing -->

![metacua demo](screenshots/demo.gif)

## Notes and limits

- Supervise the agent while it runs; it controls your real mouse and keyboard.
- Prefer a VM or dedicated macOS user account, especially for experiments.
- Prompt injection is possible from anything visible on screen, including web
  pages, emails, documents, and chat messages.
- Avoid sensitive accounts, credentials, private documents, and irreversible
  actions unless you have isolated the environment.
- The agent operates on the primary display.
- In function-calling mode, the model must call `computer.stop` when the task is
  done or cannot proceed safely; answers containing `infeasible` or `unfeasible`
  are logged as task infeasible.
- `--allow-bash` or `--allow-bash true` lets the model run shell commands. Leave it off unless you are
  experimenting in an isolated environment.
- The default step cap is 40. Use `--max-steps off` or `/max-steps off` only when
  you are prepared to supervise a longer run.
- Exit codes are `0` for success, `1` for runtime error, `2` for usage or
  validation error, and `3` for missing permission.

## Testing

```sh
pip install -e ".[test]"
pytest tests/
```
