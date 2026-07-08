"""Minimal, dependency-free `--flag value` / `--flag=value` parser."""

import math
import sys
from typing import List, Optional

from .errors import CLIError


class Args:
    def __init__(self, raw: List[str]):
        self._values: dict = {}
        self._flags: set = set()

        i = 0
        while i < len(raw):
            token = raw[i]
            if not token.startswith("--"):
                raise CLIError(
                    f"unexpected argument '{token}' (flags must start with --)", code=2
                )
            body = token[2:]
            if "=" in body:
                key, _, value = body.partition("=")
                self._values[key] = value
                i += 1
                continue
            if i + 1 < len(raw) and not raw[i + 1].startswith("--"):
                self._values[body] = raw[i + 1]
                i += 2
            else:
                self._flags.add(body)
                i += 1

    def string(self, name) -> Optional[str]:
        """Accepts a single name or a list of fallback names."""
        if isinstance(name, (list, tuple)):
            for n in name:
                if n in self._values:
                    return self._values[n]
            return None
        return self._values.get(name)

    def required_string(self, name: str) -> str:
        if name not in self._values:
            raise CLIError(f"missing required option --{name}", code=2)
        return self._values[name]

    def int(self, name: str) -> Optional[int]:
        if name not in self._values:
            return None
        value = self._values[name]
        try:
            return int(value)
        except ValueError:
            raise CLIError(f"--{name} must be an integer (got '{value}')", code=2)

    def double(self, name: str) -> Optional[float]:
        if name not in self._values:
            return None
        value = self._values[name]
        try:
            number = float(value)
        except ValueError:
            raise CLIError(f"--{name} must be a finite number (got '{value}')", code=2)
        if not math.isfinite(number):
            raise CLIError(f"--{name} must be a finite number (got '{value}')", code=2)
        return number

    def required_double(self, name: str) -> float:
        value = self.double(name)
        if value is None:
            raise CLIError(f"missing required option --{name}", code=2)
        return value

    def flag(self, name: str) -> bool:
        return name in self._flags


USAGE = """\
metacua - terminal-first macOS computer-use agent

USAGE:
  metacua                  Start the interactive agent session
  metacua <command> [options]

AGENT:
  agent       Run the agent: it screenshots the screen, sends it to Muse Spark, prints model output and tool calls, and executes GUI tool calls.
  sessions    View saved LLM session ids and sanitized per-trajectory message history.
  configure   Save endpoint, API key, model, coordinates, and effort to a config file.

MANUAL TOOLS:
  click       Click at pixel coordinates
  moveto      Move the pointer to pixel coordinates without clicking
  pointer     Control the pointer with arrow keys in the terminal
  screenshot  Capture a screenshot to PNG
  scroll      Scroll in a direction by N pages
  drag        Drag between two pixel coordinates
  press-key   Press a key or key-combination
  type-text   Type literal text via the keyboard
  permissions Show or request Accessibility and Screen Recording permission
  help        Show this help

MODEL TOOLS (function syntax):
  computer.computer  Control the computer via mouse, keyboard, and screen actions using normalized 0-1000 coordinates.
                     Default form is one action object: action, coordinate, text, start_coordinate, scroll_direction, scroll_amount, duration.
                     With --batched-actions, the schema is {"actions": [...]} and actions execute sequentially; first failure aborts the batch.
  computer.stop      End the goal with an answer. Answers containing infeasible or unfeasible are logged as task infeasible.
  bash               Optional third function tool when --allow-bash is enabled.

COMMON:
  --app <name|bundle-id>   Application to bring to front first. Use "current" or "frontmost" to skip activation.

click     --app A --x N --y N [--click-count N] [--mouse-button left|right|center]
moveto    --app A --x N --y N
pointer   [--app A] [--step N]
screenshot [--out PATH] [--scale 0.5]
scroll    --app A --direction up|down|left|right [--pages N] [--lines-per-page N] [--x N --y N]
drag      --app A --from-x N --from-y N --to-x N --to-y N [--mouse-button left|right|center]
press-key --app A --key "cmd+shift+a"
type-text --app A --text "hello world"

AGENT OPTIONS:
  metacua agent [--goal "..."] [--model NAME] [--base-url URL] [--api-key KEY] [--syntax function|pyautogui] [--coords pixel|normalized] [--effort low|medium|high|xhigh|max] [--screenshot-scale 0.5] [--max-images N] [--max-steps N|off] [--allow-bash [true|false]] [--batched-actions [true|false]] [--no-batched-actions] [--overlay] [--no-overlay]
  metacua sessions [--limit N] [--id ID] [--json] [--history] [--path]

  Default base URL: https://api.meta.ai/v1
  Default model:    muse-spark-1.1
  Default syntax:   function (OpenAI tools). Use pyautogui for the OSWorld action space (screenshot aspect-fit into 1920x1080 with black letterbox bars, coords inverse-mapped back).
  Default coords:   normalized (0-1000)
  Default screenshot scale: 1.0
  Default max images: 5. Older screenshots are replaced with: [Screenshot has been truncated to save context]
  Bash tool: off by default. Use bare --allow-bash or --allow-bash true to let the model run shell commands; use --allow-bash false to force it off.
  Batched actions: off by default. Use --batched-actions to advertise a batched computer.computer schema; use --no-batched-actions to force it off.
  Resolution order: flags -> env (MODEL_API_KEY / MUSE_SPARK_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_EFFORT, LLM_SYNTAX, METACUA_SCREENSHOT_SCALE, METACUA_MAX_IMAGES, LLM_MAX_IMAGES, METACUA_ALLOW_BASH, METACUA_BATCHED_ACTIONS, LLM_BATCHED_ACTIONS) -> config file -> defaults.
  Without --goal, the agent starts an interactive terminal session.
  Default max steps: 40. Use --max-steps off for unlimited.
  Function mode sends parallel_tool_calls=false. OSWorld mode sends no tools and keeps WAIT/DONE/FAIL control tokens.

INTERACTIVE SLASH COMMANDS:
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

  Slash command input supports inline hints and Tab completion in interactive terminals.

CONFIGURE:
  metacua configure --api-key KEY [--base-url URL] [--model NAME] [--syntax function|pyautogui] [--coords pixel|normalized] [--effort E] [--screenshot-scale 0.5] [--max-images N] [--allow-bash true|false] [--batched-actions true|false]

EXAMPLES:
  metacua configure --api-key LLM_...
  metacua agent --goal "Open Safari and search for the weather in Tokyo"
  metacua agent --syntax pyautogui --goal "Open System Settings and turn on Dark Mode"
  metacua click --app Finder --x 120 --y 90 --click-count 2
  metacua scroll --app Safari --direction down --pages 3
  metacua press-key --app Safari --key cmd+t

NOTE: Native macOS control needs Accessibility and Screen Recording permission. Run `metacua permissions --prompt` to open the system dialogs."""


def print_usage(to_stderr: bool = False) -> None:
    if to_stderr:
        sys.stderr.write(USAGE + "\n")
    else:
        print(USAGE)
