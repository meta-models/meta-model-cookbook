"""Terminal rendering, colored output, and readline prompt."""

import enum
import os
import sys
import threading

try:
    import readline  # noqa: F401  (enables line editing/history for input())

    _HAS_READLINE = True
except ImportError:  # pragma: no cover
    _HAS_READLINE = False

from .llm import CoordSpace, agent_tool_specs
from .permissions import has_screen_recording_access, is_trusted
from .session_store import (
    SessionStore,
    session_detail_lines,
    session_summary_lines,
)
from .slash_commands import SLASH_COMMAND_SPECS, SlashCommandCatalog
from .errors import CLIError


class AgentLogKind(enum.Enum):
    GOAL = "goal"
    STATUS = "status"
    THINKING = "thinking"
    MESSAGE = "message"
    TOOL = "tool"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


def default_agent_logger(kind: AgentLogKind, message: str) -> None:
    labels = {
        AgentLogKind.GOAL: "goal",
        AgentLogKind.STATUS: "status",
        AgentLogKind.THINKING: "thinking",
        AgentLogKind.MESSAGE: "assistant",
        AgentLogKind.TOOL: "tool",
        AgentLogKind.SUCCESS: "done",
        AgentLogKind.WARNING: "warning",
        AgentLogKind.ERROR: "error",
    }
    sys.stderr.write(f"[{labels[kind]}] {message}\n")


class _Style(enum.Enum):
    BOLD = "1"
    DIM = "2"
    CYAN = "36"
    GREEN = "32"
    YELLOW = "33"
    RED = "31"
    MAGENTA = "35"


class TerminalUI:
    def __init__(self, use_color=None, show_prompt=None):
        self._use_color = self.should_use_color() if use_color is None else use_color
        self._show_prompt = self.should_show_prompt() if show_prompt is None else show_prompt
        self._lock = threading.Lock()

        # Line editing (arrow-key history, cursor movement) only makes sense on an
        # interactive terminal; piped input keeps using a plain read.
        self._history_path = None
        self._catalog = SlashCommandCatalog()
        if self._show_prompt and _HAS_READLINE:
            path = os.path.expanduser("~/.metacua_history")
            self._history_path = path
            try:
                readline.read_history_file(path)
            except (OSError, FileNotFoundError):
                pass
            # Tab-complete slash commands in interactive terminals.
            readline.set_completer(self._complete_slash_command)
            readline.set_completer_delims(" \t")
            readline.parse_and_bind("tab: complete")

    def _complete_slash_command(self, text, state):
        if not text.startswith("/"):
            return None
        matches = self._catalog.matching_names(text)
        return matches[state] if state < len(matches) else None

    @staticmethod
    def should_use_color() -> bool:
        return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @staticmethod
    def should_show_prompt() -> bool:
        return sys.stdin.isatty()

    # MARK: - Headers and panels

    def print_header(self, config, backend_label, manipulation_label, max_steps, overlay) -> None:
        coords = "0-1000" if config.coords == CoordSpace.NORMALIZED1000 else "pixel"
        overlay_label = "on" if overlay else "off"
        bash_label = "on" if config.allow_bash else "off"
        batch_label = "on" if config.batched_actions else "off"
        max_steps_label = str(max_steps) if max_steps is not None else "unlimited"
        self._write_line("")
        self._write_line(
            f"{self._style('metacua', _Style.BOLD)} "
            f"{self._style('computer-use agent', _Style.DIM)}"
        )
        self._write_line(self._style(f"backend {backend_label}", _Style.DIM))
        self._write_line(self._style(f"manipulation {manipulation_label}", _Style.DIM))
        self._write_line(
            self._style(
                f"base {config.base_url} | syntax {config.syntax} | coords {coords} | "
                f"effort {config.effort} | max images {config.max_images} | "
                f"max steps {max_steps_label} | "
                f"overlay {overlay_label} | bash {bash_label} | batch {batch_label}",
                _Style.DIM,
            )
        )
        if config.allow_bash:
            self._write_line(
                self._style(
                    "bash tool enabled — the model can run shell commands on this Mac",
                    _Style.RED,
                )
            )
        self._write_line(
            self._style(f"screenshot scale {self._format_scale(config.screenshot_scale)}", _Style.DIM)
        )
        self._write_line(
            self._style("type a goal, /help for commands, or /quit to exit", _Style.DIM)
        )
        self._write_line("")

    def print_interactive_help(self) -> None:
        self._write_line("")
        self._write_line(self._style("commands", _Style.BOLD))
        for command in SLASH_COMMAND_SPECS:
            padded = command.display_command.ljust(24)
            self._write_line(f"  {padded} {command.description}")
        self._write_line("")

    def print_config(self, config, backend_label, manipulation_label, max_steps, overlay) -> None:
        coords = "0-1000" if config.coords == CoordSpace.NORMALIZED1000 else "pixel"
        overlay_label = "on" if overlay else "off"
        bash_label = "on" if config.allow_bash else "off"
        batch_label = "on" if config.batched_actions else "off"
        max_steps_label = str(max_steps) if max_steps is not None else "unlimited"
        self._write_line("")
        self._write_line(self._style("config", _Style.BOLD))
        self._write_line(f"  backend    {backend_label}")
        self._write_line(f"  model      {config.model}")
        self._write_line(f"  base-url   {config.base_url}")
        self._write_line(f"  syntax     {config.syntax}")
        self._write_line(f"  coords     {coords}")
        self._write_line(f"  effort     {config.effort}")
        self._write_line(f"  shot-scale {self._format_scale(config.screenshot_scale)}")
        self._write_line(f"  max-images {config.max_images}")
        self._write_line(f"  manip      {manipulation_label}")
        self._write_line(f"  max-steps  {max_steps_label}")
        self._write_line(f"  overlay    {overlay_label}")
        self._write_line(f"  bash       {bash_label}")
        self._write_line(f"  batch      {batch_label}")
        self._write_line("")

    def print_model(self, config, backend_label) -> None:
        self._write_line("")
        self._write_line(self._style("model", _Style.BOLD))
        self._write_line(f"  backend   {backend_label}")
        self._write_line(f"  model     {config.model}")
        self._write_line("")

    def print_status(self, config, backend_label, manipulation_label, max_steps, overlay) -> None:
        self.print_config(config, backend_label, manipulation_label, max_steps, overlay)
        self.print_permissions()

    def print_tools(self, allow_bash: bool = False, batched_actions: bool = False) -> None:
        self._write_line("")
        self._write_line(self._style("tools", _Style.BOLD))
        for tool in agent_tool_specs(include_bash=allow_bash, batched=batched_actions):
            self._write_line(f"  {tool.name:<11} {tool.description}")
        self._write_line("")

    def print_doctor(self, config, backend_label, manipulation_label, max_steps, overlay) -> None:
        max_steps_label = str(max_steps) if max_steps is not None else "unlimited"
        self._write_line("")
        self._write_line(self._style("doctor", _Style.BOLD))
        self._write_line(f"  config          {self._style('ok', _Style.GREEN)}")
        self._write_line(f"  backend         {backend_label}")
        self._write_line(f"  model           {config.model}")
        self._write_line(f"  shot-scale      {self._format_scale(config.screenshot_scale)}")
        self._write_line(f"  max-images      {config.max_images}")
        self._write_line(f"  manipulation    {manipulation_label}")
        self._write_line(f"  max-steps       {max_steps_label}")
        self._write_line(f"  overlay         {'on' if overlay else 'off'}")
        self._write_line(f"  bash            {'on' if config.allow_bash else 'off'}")
        self._write_line(f"  batch           {'on' if config.batched_actions else 'off'}")
        self._write_line(f"  accessibility   {self._status(is_trusted())}")
        self._write_line(f"  screen capture  {self._status(has_screen_recording_access())}")
        self._write_line("")

    def print_permissions(self) -> None:
        self._write_line("")
        self._write_line(self._style("permissions", _Style.BOLD))
        self._write_line(f"  Accessibility     {self._status(is_trusted())}")
        self._write_line(f"  Screen Recording  {self._status(has_screen_recording_access())}")
        self._write_line("")

    def print_stored_sessions(self, limit: int) -> None:
        try:
            store = SessionStore.shared
            records = store.load_recent(limit)
            self._write_line("")
            self._write_line(self._style("sessions", _Style.BOLD))
            for line in session_summary_lines(records, str(store.storage_url)):
                self._write_line(f"  {line}")
            self._write_line("")
        except CLIError as error:
            self.agent_log(AgentLogKind.ERROR, error.message)
        except Exception as error:  # noqa: BLE001
            self.agent_log(AgentLogKind.ERROR, str(error))

    def print_stored_session(self, id: str) -> None:
        try:
            store = SessionStore.shared
            record = store.load_matching(id)
            if record is None:
                self.agent_log(AgentLogKind.WARNING, f"no stored LLM session matched '{id}'")
                return
            self._write_line("")
            for line in session_detail_lines(record, str(store.storage_url)):
                self._write_line(f"  {line}")
            self._write_line("")
        except CLIError as error:
            self.agent_log(AgentLogKind.ERROR, error.message)
        except Exception as error:  # noqa: BLE001
            self.agent_log(AgentLogKind.ERROR, str(error))

    def print_goodbye(self) -> None:
        self._write_line("")
        self._write_line(self._style("session ended", _Style.DIM))

    def clear_screen(self) -> None:
        with self._lock:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

    # MARK: - Prompt

    def prompt(self):
        if not self._show_prompt:
            # Non-interactive (piped) input: plain line read, no editing.
            line = sys.stdin.readline()
            if line == "":
                return None
            return line.rstrip("\n")

        try:
            line = input(self._prompt_string())
        except EOFError:
            # ctrl-D: terminate the line cleanly so the goodbye isn't glued to the prompt.
            print("")
            return None

        trimmed = line.strip()
        # input() with readline auto-adds to history; keep only non-blank lines and
        # don't stack identical consecutive entries.
        if _HAS_READLINE:
            length = readline.get_current_history_length()
            if not trimmed:
                if length > 0:
                    readline.remove_history_item(length - 1)
            else:
                if length >= 2 and readline.get_history_item(length) == readline.get_history_item(
                    length - 1
                ):
                    readline.remove_history_item(length - 1)
                if self._history_path:
                    try:
                        readline.write_history_file(self._history_path)
                    except OSError:
                        pass
        return line

    def _prompt_string(self) -> str:
        if not self._use_color:
            return "metacua > "
        # Non-printing color escapes are wrapped in \001 / \002 so readline's cursor
        # math stays correct while the prompt keeps its colors.
        def wrap(code):
            return f"\001\033[{code}m\002"

        reset = "\001\033[0m\002"
        return f"{wrap(_Style.CYAN.value)}metacua{reset} {wrap(_Style.BOLD.value)}>{reset} "

    # MARK: - Agent log

    def agent_log(self, kind: AgentLogKind, message: str) -> None:
        if kind == AgentLogKind.GOAL:
            self._print_block("user", message, _Style.CYAN, blank_before=True)
        elif kind == AgentLogKind.STATUS:
            self._print_block("status", message, _Style.DIM, blank_before=False)
        elif kind == AgentLogKind.THINKING:
            self._print_block("thinking", message, _Style.DIM, blank_before=False)
        elif kind == AgentLogKind.MESSAGE:
            self._print_block("assistant", message, _Style.GREEN, blank_before=True)
        elif kind == AgentLogKind.TOOL:
            self._print_block("tool", message, _Style.MAGENTA, blank_before=False)
        elif kind == AgentLogKind.SUCCESS:
            self._print_block("done", message, _Style.GREEN, blank_before=False)
        elif kind == AgentLogKind.WARNING:
            self._print_block("warn", message, _Style.YELLOW, blank_before=False)
        elif kind == AgentLogKind.ERROR:
            self._print_block("error", message, _Style.RED, blank_before=False)

    def _print_block(self, label, message, color, blank_before) -> None:
        lines = message.split("\n")
        with self._lock:
            if blank_before:
                print("")
            rendered_label = self._style(label, color)
            if not lines:
                print(rendered_label)
            else:
                print(f"{rendered_label} {lines[0]}")
                for line in lines[1:]:
                    print(f"  {line}")
            sys.stdout.flush()

    def _write_line(self, line) -> None:
        with self._lock:
            print(line)
            sys.stdout.flush()

    def _status(self, ok) -> str:
        return self._style("granted", _Style.GREEN) if ok else self._style("missing", _Style.YELLOW)

    def _format_scale(self, value) -> str:
        return f"{value:.2g}"

    def _style(self, text, style) -> str:
        if not self._use_color:
            return text
        return f"\033[{style.value}m{text}\033[0m"
