"""The self-contained computer-use agent and `metacua agent` entry point."""

import json
import math
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from Quartz import CGPointMake

from .args import Args
from .bash_tool import run_bash_tool
from .computer_actions import normalize_computer_actions
from .config import AgentConfig, DEFAULT_MODEL, resolve_agent_config
from .errors import CLIError
from .llm import CoordSpace, LLMBackend, LLMResult, ToolRun, make_backend
from .letterbox import inverse_fit_point
from .manipulation import ManipulationBackend, make_manipulation_backend
from .mouse import MouseButton, ScrollDirection
from .permissions import (
    ensure_screen_recording,
    ensure_trusted,
    require_screen_recording,
    require_trust,
)
from .screenshot import primary_screen
from .session_store import SessionStore
from .system_prompt import build_system_prompt
from .terminal_attention import TerminalAttention
from .terminal_state import StopClassification, classify_stop_answer, is_stop_tool_name
from .terminal_ui import AgentLogKind, TerminalUI, default_agent_logger

DEFAULT_MAX_STEPS = 40

# pyautogui key names -> our keyboard.py names (see osworld.py).
_KEY_ALIASES = {
    "ctrl": "ctrl", "ctrlleft": "ctrl", "ctrlright": "ctrl", "control": "ctrl",
    "alt": "option", "altleft": "option", "altright": "option",
    "option": "option", "optionleft": "option", "optionright": "option",
    "shift": "shift", "shiftleft": "shift", "shiftright": "shift",
    "command": "cmd", "cmd": "cmd", "win": "cmd", "winleft": "cmd",
    "winright": "cmd", "super": "cmd", "meta": "cmd",
    "enter": "return", "return": "return",
    "esc": "esc", "escape": "esc",
    "delete": "forwarddelete", "del": "forwarddelete", "backspace": "backspace",
    "pageup": "pageup", "pagedown": "pagedown", "space": "space", "tab": "tab",
    "home": "home", "end": "end", "up": "up", "down": "down",
    "left": "left", "right": "right",
}


def _translate_key(key: str) -> str:
    low = str(key).strip().lower()
    return _KEY_ALIASES.get(low, low)


def _button_name(button: str) -> str:
    low = (button or "left").lower()
    return "center" if low == "middle" else low


class Agent:
    """Screenshot, send to Muse Spark with GUI tools, execute returned tool calls,
    and feed back a fresh screenshot each step.
    """

    _settle_micros = 450_000

    def __init__(self, config: AgentConfig, backend: LLMBackend,
                 manipulation: ManipulationBackend, overlay,
                 max_steps: Optional[int], screenshot_scale: float,
                 shows_reasoning_text: bool, logger=default_agent_logger):
        self._config = config
        self._backend = backend
        self._manipulation = manipulation
        self._overlay = overlay
        self._max_steps = max_steps
        self._coord_space = backend.coord_space
        self._screenshot_scale = screenshot_scale
        self._shows_reasoning_text = shows_reasoning_text
        self._logger = logger
        self._screen_w = 0
        self._screen_h = 0
        self._logged_session_save = False

        screen = primary_screen()
        if screen is not None:
            frame = screen.frame()
            self._last_point = CGPointMake(frame.size.width / 2, frame.size.height / 2)
        else:
            self._last_point = CGPointMake(400, 300)

    # MARK: - Loop

    def run(self, goal: str) -> None:
        if self._manipulation.requires_screen_recording:
            require_screen_recording()
        self._log(AgentLogKind.GOAL, goal)
        self._logged_session_save = False

        # OSWorld/pyautogui backends expose model_resolution and own their prompt;
        # actions come back as parsed pyautogui in the model's fixed pixel space,
        # which we scale to the real display when executing.
        model_res = getattr(self._backend, "model_resolution", None)
        shot_scale = 1.0 if model_res is not None else self._screenshot_scale
        shot = self._manipulation.screenshot(shot_scale)
        self._log(
            AgentLogKind.STATUS,
            f"screenshot {shot.image_width}x{shot.image_height} image, "
            f"{shot.width}x{shot.height} coords "
            f"({len(shot.png_base64) // 1024} KB b64)",
        )
        self._screen_w = shot.width
        self._screen_h = shot.height

        if model_res is not None:
            self._sent_w, self._sent_h = model_res
            system = self._backend.system_prompt()
        else:
            self._sent_w, self._sent_h = shot.width, shot.height
            system = self._system_prompt(
                shot.width, shot.height, shot.image_width, shot.image_height
            )

        conversation = self._backend.initial_conversation(goal, shot)
        goal_id = str(uuid.uuid4())

        step = 1
        while self._max_steps is None or step <= self._max_steps:
            self._log(AgentLogKind.STATUS, f"step {step}: calling {self._backend.label}")
            request_conversation = list(conversation)
            result = self._backend.send(system, conversation)
            self._record_llm_call(goal_id, goal, step, request_conversation, result)
            conversation.extend(result.assistant_items)
            if result.truncated and result.tool_calls:
                self._log(
                    AgentLogKind.WARNING,
                    f"response was truncated but included tool calls (step {step}); continuing.",
                )

            if self._shows_reasoning_text and result.thinking:
                self._log(AgentLogKind.THINKING, result.thinking)
            if result.text:
                self._log(AgentLogKind.MESSAGE, result.text)

            if result.finish == "refusal":
                self._log(
                    AgentLogKind.ERROR,
                    f"model refused: {result.refusal_reason or result.text}",
                )
                return
            if result.finish == "max_tokens":
                self._log(
                    AgentLogKind.WARNING,
                    f"response truncated at the token cap (step {step}); stopping.",
                )
                return

            # OSWorld / pyautogui mode: execute parsed actions, then re-observe.
            if result.actions is not None:
                outcome, notes = self._handle_osworld_step(result, step)
                if outcome == "stop":
                    return
                time.sleep(self._settle_micros / 1_000_000.0)
                try:
                    after = self._manipulation.screenshot(shot_scale)
                    self._screen_w = after.width
                    self._screen_h = after.height
                except Exception:  # noqa: BLE001
                    after = None
                conversation.extend(self._backend.tool_result_items([], after, notes=notes))
                step += 1
                continue

            if not result.tool_calls:
                self._log(AgentLogKind.SUCCESS, f"done (step {step})")
                return

            stop_call = None
            for call in result.tool_calls:
                if is_stop_tool_name(call.name):
                    stop_call = call
                    break
            if stop_call is not None:
                answer = stop_call.input.get("answer")
                answer = answer.strip() if isinstance(answer, str) else ""
                if answer:
                    self._log(AgentLogKind.MESSAGE, answer)
                classification, message = classify_stop_answer(answer)
                kind = (
                    AgentLogKind.ERROR
                    if classification == StopClassification.INFEASIBLE
                    else AgentLogKind.SUCCESS
                )
                self._log(kind, message)
                return

            runs: List[ToolRun] = []
            for call in result.tool_calls:
                is_error = False
                compact = self._compact_json(call.input)
                self._log(AgentLogKind.TOOL, f"{call.name}{(' ' + compact) if compact else ''}")
                try:
                    text = self._execute(call.name, call.input)
                    self._log(AgentLogKind.STATUS, f"tool result: {text}")
                except CLIError as error:
                    if error.code == 3:
                        raise
                    text = f"error: {error.message}"
                    is_error = True
                    self._log(AgentLogKind.WARNING, text)
                except Exception as error:  # noqa: BLE001
                    text = f"error: {error}"
                    is_error = True
                    self._log(AgentLogKind.WARNING, text)
                runs.append(ToolRun(call.id, call.name, text, is_error))

            time.sleep(self._settle_micros / 1_000_000.0)
            try:
                after = self._manipulation.screenshot(self._screenshot_scale)
            except Exception:  # noqa: BLE001
                after = None
            conversation.extend(self._backend.tool_result_items(runs, after))
            step += 1

        if self._max_steps is not None:
            self._log(
                AgentLogKind.WARNING,
                f"reached max steps ({self._max_steps}) without finishing; "
                "use /max-steps off for unlimited",
            )

    # MARK: - Tool execution

    def _execute(self, name: str, input: Dict[str, Any]) -> str:
        if not isinstance(input, dict):
            raise CLIError("tool input must be an object")
        if self._manipulation.requires_accessibility and self._tool_requires_accessibility(
            name, input
        ):
            require_trust()

        if name in ("computer.computer", "computer", "computer_computer"):
            return self._execute_computer(input)

        if name in ("computer.stop", "stop", "computer_stop"):
            value = input.get("answer")
            return value if isinstance(value, str) else "DONE"

        if name == "screenshot":
            if self._overlay:
                self._overlay.show_action("look", self._last_point)
            return "Captured a fresh screenshot."

        if name == "moveto":
            point = self._point(input, "x", "y")
            self._last_point = point
            if self._overlay:
                self._overlay.show_action("move", point)
            self._manipulation.move(point)
            return f"Moved pointer to ({self._coord(point.x)}, {self._coord(point.y)})."

        if name == "click":
            point = self._point(input, "x", "y")
            button = MouseButton.parse(input.get("button") or "left")
            clicks = self._clamp_int(self._num(input.get("clicks")), 1, 3, default=1)
            self._last_point = point
            if clicks >= 3:
                label = "triple-click"
            elif clicks == 2:
                label = "double-click"
            elif button == MouseButton.RIGHT:
                label = "right-click"
            elif button == MouseButton.CENTER:
                label = "middle-click"
            else:
                label = "click"
            if self._overlay:
                self._overlay.show_click(label, point)
            self._manipulation.click(point, button, clicks)
            return f"{label} at ({self._coord(point.x)}, {self._coord(point.y)})."

        if name == "scroll":
            direction = ScrollDirection.parse(self._string(input, "direction"))
            pages = self._clamp_int(self._num(input.get("pages")), 1, 100, default=1)
            point = None
            if input.get("x") is not None or input.get("y") is not None:
                point = self._point(input, "x", "y")
                self._last_point = point
            if self._overlay:
                self._overlay.show_action(f"scroll {direction.value}", point or self._last_point)
            self._manipulation.scroll(direction, pages, 10, point)
            return f"Scrolled {direction.value} {pages} page(s)."

        if name == "drag":
            from_point = self._point(input, "from_x", "from_y")
            to_point = self._point(input, "to_x", "to_y")
            button = MouseButton.parse(input.get("button") or "left")
            self._last_point = to_point
            if self._overlay:
                self._overlay.show_drag("drag", from_point, to_point, 0.5)
            self._manipulation.drag(from_point, to_point, button)
            return (
                f"Dragged from ({self._coord(from_point.x)}, {self._coord(from_point.y)}) "
                f"to ({self._coord(to_point.x)}, {self._coord(to_point.y)})."
            )

        if name == "press_key":
            key = self._string(input, "key")
            if self._overlay:
                self._overlay.show_action(f"key {key}", self._last_point)
            self._manipulation.press_key(key)
            return f"Pressed {key}."

        if name == "type_text":
            text = self._string(input, "text")
            preview = (text[:30] + "...") if len(text) > 30 else text
            if self._overlay:
                self._overlay.show_action(f"type: {preview}", self._last_point)
            self._manipulation.type_text(text)
            return f"Typed {len(text)} character(s)."

        if name == "bash":
            if not self._config.allow_bash:
                raise CLIError(
                    "the bash tool is disabled; restart with --allow-bash to enable it"
                )
            command = self._string(input, "command")
            timeout_ms = self._clamp_int(
                self._num(input.get("timeout_ms")), 1_000, 120_000, default=20_000
            )
            if self._overlay:
                self._overlay.show_action("bash", self._last_point)
            return run_bash_tool(command, timeout_ms)

        if name == "wait":
            ms = self._clamp_int(self._num(input.get("ms")), 0, 10_000, default=500)
            if self._overlay:
                self._overlay.show_action(f"wait {ms}ms", self._last_point)
            self._manipulation.wait(ms)
            return f"Waited {ms}ms."

        raise CLIError(f"unknown tool '{name}'")

    def _tool_requires_accessibility(self, name: str, input: Dict[str, Any]) -> bool:
        if name in ("screenshot", "wait", "bash", "computer.stop", "computer_stop", "stop"):
            return False
        if name in ("computer.computer", "computer", "computer_computer"):
            try:
                actions = self._normalized_computer_actions(input)
            except CLIError:
                return False
            for action in actions:
                action_name = action.get("action")
                if action_name not in ("screenshot", "wait"):
                    return True
            return False
        return True

    def _execute_computer(self, input: Dict[str, Any]) -> str:
        was_batched_call = input.get("actions") is not None
        actions = self._normalized_computer_actions(input)
        if not actions:
            raise CLIError("`actions` must be a non-empty list")
        for index, action in enumerate(actions):
            action_name = action.get("action") or "?"
            try:
                self._execute_computer_action(action)
            except CLIError as error:
                raise CLIError(f"Action [{index}] ({action_name}): {error.message}")
        if not self._config.batched_actions and not was_batched_call and len(actions) == 1:
            return f"Action executed: {self._single_computer_action_description(actions[0])}"
        descriptions = ", ".join(self._computer_action_description(a) for a in actions)
        return f"Batch executed: computer(actions=[{descriptions}])"

    def _normalized_computer_actions(self, input: Dict[str, Any]) -> List[Dict[str, Any]]:
        return normalize_computer_actions(input)

    def _execute_computer_action(self, action: Dict[str, Any]) -> None:
        action_name = self._string(action, "action")

        if action_name == "screenshot":
            if self._overlay:
                self._overlay.show_action("look", self._last_point)
            return

        if action_name == "mouse_move":
            point = self._optional_relative_point(action.get("coordinate")) or self._last_point
            self._last_point = point
            if self._overlay:
                self._overlay.show_action("move", point)
            self._manipulation.move(point)
            return

        if action_name in (
            "left_click",
            "right_click",
            "middle_click",
            "double_click",
            "triple_click",
        ):
            with self._held_modifier(action.get("text")):
                point = self._optional_relative_point(action.get("coordinate")) or self._last_point
                self._last_point = point
                button = self._computer_mouse_button(action_name)
                clicks = self._computer_click_count(action_name)
                if self._overlay:
                    self._overlay.show_click(action_name, point)
                self._manipulation.click(point, button, clicks)
            return

        if action_name == "left_press":
            with self._held_modifier(action.get("text")):
                point = self._optional_relative_point(action.get("coordinate")) or self._last_point
                self._last_point = point
                if self._overlay:
                    self._overlay.show_click(action_name, point)
                self._manipulation.mouse_down(point, MouseButton.LEFT)
                self._manipulation.wait(1_000)
                self._manipulation.mouse_up(point, MouseButton.LEFT)
            return

        if action_name == "left_click_drag":
            to_point = self._relative_point(action.get("coordinate"))
            from_point = self._optional_relative_point(action.get("start_coordinate")) or self._last_point
            self._last_point = to_point
            if self._overlay:
                self._overlay.show_drag("drag", from_point, to_point, 0.5)
            self._manipulation.drag(from_point, to_point, MouseButton.LEFT)
            return

        if action_name == "key":
            self._manipulation.press_key(self._string(action, "text"))
            return

        if action_name == "type":
            self._manipulation.type_text(self._string(action, "text"))
            return

        if action_name == "hold_key":
            self._manipulation.key_down(self._string(action, "text"))
            return

        if action_name == "release_key":
            self._manipulation.key_up(self._string(action, "text"))
            return

        if action_name == "left_mouse_down":
            point = self._optional_relative_point(action.get("coordinate")) or self._last_point
            self._last_point = point
            self._manipulation.mouse_down(point, MouseButton.LEFT)
            return

        if action_name == "left_mouse_up":
            point = self._optional_relative_point(action.get("coordinate")) or self._last_point
            self._last_point = point
            self._manipulation.mouse_up(point, MouseButton.LEFT)
            return

        if action_name == "scroll":
            with self._held_modifier(action.get("text")):
                direction = ScrollDirection.parse(self._string(action, "scroll_direction"))
                amount = self._clamp_int(
                    self._num(action.get("scroll_amount")), 1, 100, default=3
                )
                point = self._optional_relative_point(action.get("coordinate"))
                if point is not None:
                    self._last_point = point
                if self._overlay:
                    self._overlay.show_action(
                        f"scroll {direction.value}", point or self._last_point
                    )
                self._manipulation.scroll(direction, amount, 1, point)
            return

        if action_name == "wait":
            duration = self._num(action.get("duration"))
            duration = 0.5 if duration is None else duration
            ms = int(min(10_000, max(0, round(duration * 1000))))
            if self._overlay:
                self._overlay.show_action(f"wait {ms}ms", self._last_point)
            self._manipulation.wait(ms)
            return

        raise CLIError(f"Invalid action: {action_name}")

    # MARK: - OSWorld / pyautogui execution

    def _handle_osworld_step(self, result, step: int):
        """Run one OSWorld turn. Returns ('stop'|'continue', notes)."""
        notes: List[str] = []
        if result.control == "done":
            self._log(AgentLogKind.SUCCESS, f"done (step {step})")
            return "stop", notes
        if result.control == "fail":
            self._log(AgentLogKind.ERROR, "task infeasible (model reported FAIL)")
            return "stop", notes
        if result.control == "wait":
            self._log(AgentLogKind.STATUS, "model requested wait; re-observing")
            return "continue", notes
        if not result.actions:
            # No actionable pyautogui and no control token — treat as finished.
            self._log(AgentLogKind.SUCCESS, f"done (step {step})")
            return "stop", notes

        if self._manipulation.requires_accessibility:
            require_trust()
        for action in result.actions:
            if action.kind == "note":
                note = action.note or "unsupported action"
                notes.append(note)
                self._log(AgentLogKind.WARNING, f"ignored: {note}")
                continue
            try:
                label = self._perform_osworld_action(action)
            except CLIError as error:
                if error.code == 3:
                    raise
                note = f"error: {error.message}"
                notes.append(note)
                self._log(AgentLogKind.WARNING, note)
                continue
            except Exception as error:  # noqa: BLE001
                note = f"error: {error}"
                notes.append(note)
                self._log(AgentLogKind.WARNING, note)
                continue
            if label:
                self._log(AgentLogKind.TOOL, label)
        return "continue", notes

    def _perform_osworld_action(self, a) -> Optional[str]:
        def scaled(ax: float, ay: float):
            cx, cy = inverse_fit_point(
                ax, ay, self._screen_w, self._screen_h, self._sent_w, self._sent_h
            )
            return CGPointMake(cx, cy)

        kind = a.kind
        if kind == "note":
            self._log(AgentLogKind.WARNING, f"ignored: {a.note}")
            return None

        if kind == "move":
            if a.x is None or a.y is None:
                return None
            point = scaled(a.x, a.y)
            self._last_point = point
            if self._overlay:
                self._overlay.show_action("move", point)
            self._manipulation.move(point)
            return f"moveTo ({self._coord(point.x)}, {self._coord(point.y)})"

        if kind == "click":
            point = scaled(a.x, a.y) if (a.x is not None and a.y is not None) else self._last_point
            button = MouseButton.parse(_button_name(a.button))
            clicks = max(1, min(3, a.clicks))
            self._last_point = point
            label = {2: "double-click", 3: "triple-click"}.get(clicks, "click")
            if self._overlay:
                self._overlay.show_click(label, point)
            self._manipulation.click(point, button, clicks)
            return f"{label} at ({self._coord(point.x)}, {self._coord(point.y)})"

        if kind == "drag":
            if a.x is None or a.y is None:
                return None
            to_point = scaled(a.x, a.y)
            from_point = self._last_point
            button = MouseButton.parse(_button_name(a.button))
            if self._overlay:
                self._overlay.show_drag("drag", from_point, to_point, 0.5)
            self._manipulation.drag(from_point, to_point, button)
            self._last_point = to_point
            return f"dragTo ({self._coord(to_point.x)}, {self._coord(to_point.y)})"

        if kind in ("scroll", "hscroll"):
            if a.amount == 0:
                return None
            lines = min(200, abs(a.amount))
            if kind == "scroll":
                direction = ScrollDirection.UP if a.amount > 0 else ScrollDirection.DOWN
            else:
                direction = ScrollDirection.LEFT if a.amount > 0 else ScrollDirection.RIGHT
            point = None
            if a.x is not None and a.y is not None:
                point = scaled(a.x, a.y)
                self._last_point = point
            if self._overlay:
                self._overlay.show_action(f"scroll {direction.value}", point or self._last_point)
            self._manipulation.scroll(direction, 1, lines, point)
            return f"scroll {direction.value} {lines}"

        if kind == "hotkey":
            combo = "+".join(_translate_key(k) for k in a.keys)
            if self._overlay:
                self._overlay.show_action(f"key {combo}", self._last_point)
            self._manipulation.press_key(combo)
            return f"hotkey {combo}"

        if kind == "press":
            pressed = []
            for key in a.keys:
                translated = _translate_key(key)
                self._manipulation.press_key(translated)
                pressed.append(translated)
            return f"press {', '.join(pressed)}"

        if kind == "keydown":
            key = _translate_key(a.keys[0]) if a.keys else ""
            self._manipulation.key_down(key)
            return f"keyDown {key}"

        if kind == "keyup":
            key = _translate_key(a.keys[0]) if a.keys else ""
            self._manipulation.key_up(key)
            return f"keyUp {key}"

        if kind == "write":
            preview = (a.text[:30] + "...") if len(a.text) > 30 else a.text
            if self._overlay:
                self._overlay.show_action(f"type: {preview}", self._last_point)
            self._manipulation.type_text(a.text)
            return f"write {len(a.text)} char(s)"

        if kind == "sleep":
            secs = min(5.0, max(0.0, a.seconds))
            time.sleep(secs)
            return f"sleep {secs:g}s"

        return f"unknown action {kind}"

    # MARK: - Helpers

    def _point(self, input: Dict[str, Any], x_key: str, y_key: str):
        rx = self._num(input.get(x_key))
        ry = self._num(input.get(y_key))
        if rx is None or ry is None:
            raise CLIError(f"missing numeric '{x_key}'/'{y_key}'")
        if not (math.isfinite(rx) and math.isfinite(ry)):
            raise CLIError("non-finite coordinates")

        x = rx
        y = ry
        if self._coord_space == CoordSpace.NORMALIZED1000:
            x = rx / 1000.0 * max(1, self._screen_w)
            y = ry / 1000.0 * max(1, self._screen_h)
        cx = min(max(0, x), self._screen_w - 1) if self._screen_w > 0 else x
        cy = min(max(0, y), self._screen_h - 1) if self._screen_h > 0 else y
        return CGPointMake(cx, cy)

    def _relative_point(self, value, field: str = "coordinate"):
        if not isinstance(value, list) or len(value) != 2:
            raise CLIError(f"missing relative {field} [x, y]")
        rx = self._num(value[0])
        ry = self._num(value[1])
        if rx is None or ry is None:
            raise CLIError(f"relative {field} must contain numeric x/y values")
        if not (math.isfinite(rx) and math.isfinite(ry)):
            raise CLIError(f"non-finite relative {field}")
        x = rx / 1000.0 * max(1, self._screen_w)
        y = ry / 1000.0 * max(1, self._screen_h)
        cx = min(max(0, x), self._screen_w - 1) if self._screen_w > 0 else x
        cy = min(max(0, y), self._screen_h - 1) if self._screen_h > 0 else y
        return CGPointMake(cx, cy)

    def _optional_relative_point(self, value, field: str = "coordinate"):
        if value is None:
            return None
        return self._relative_point(value, field)

    def _string(self, input: Dict[str, Any], key: str) -> str:
        value = input.get(key)
        if not isinstance(value, str):
            raise CLIError(f"missing string '{key}'")
        return value

    def _num(self, any_value) -> Optional[float]:
        if isinstance(any_value, bool):
            return None
        if isinstance(any_value, (int, float)):
            return float(any_value)
        if isinstance(any_value, str):
            try:
                value = float(any_value)
            except ValueError:
                return None
            return value if math.isfinite(value) else None
        return None

    def _clamp_int(self, value: Optional[float], lo: int, hi: int, default: int) -> int:
        if value is None or not math.isfinite(value):
            return default
        return int(min(hi, max(lo, round(value))))

    def _coord(self, value) -> str:
        return f"{round(value):.0f}"

    @contextmanager
    def _held_modifier(self, keys):
        if not isinstance(keys, str) or not keys.strip():
            yield
            return
        self._manipulation.key_down(keys)
        try:
            yield
        finally:
            try:
                self._manipulation.key_up(keys)
            except Exception:  # noqa: BLE001
                pass

    def _computer_mouse_button(self, action: str) -> MouseButton:
        if action == "right_click":
            return MouseButton.RIGHT
        if action == "middle_click":
            return MouseButton.CENTER
        return MouseButton.LEFT

    def _computer_click_count(self, action: str) -> int:
        if action == "double_click":
            return 2
        if action == "triple_click":
            return 3
        return 1

    def _computer_action_description(self, action: Dict[str, Any]) -> str:
        desc = str(action.get("action", "?"))
        if "coordinate" in action:
            desc += f", coordinate={action.get('coordinate')}"
        text = action.get("text")
        if isinstance(text, str) and text:
            desc += f", text='{self._clipped(text, 40)}'"
        return desc

    def _single_computer_action_description(self, action: Dict[str, Any]) -> str:
        return f"computer(action={self._computer_action_description(action)})"

    def _clipped(self, text: str, max_length: int = 180) -> str:
        one_line = text.replace("\n", " ").strip()
        if len(one_line) <= max_length:
            return one_line
        return one_line[: max(0, max_length - 3)] + "..."

    def _log(self, kind: AgentLogKind, message: str) -> None:
        self._logger(kind, message)

    def _record_llm_call(self, goal_id: str, goal: str, step: int,
                         request_conversation: List[Dict[str, Any]],
                         result: LLMResult) -> None:
        try:
            stored = SessionStore.shared.append_llm_call(
                config=self._config,
                backend_label=self._backend.label,
                goal_id=goal_id,
                goal=goal,
                step=step,
                request_conversation=request_conversation,
                result=result,
            )
            if step == 1 and not self._logged_session_save:
                self._log(
                    AgentLogKind.STATUS,
                    f"saved llm session {stored.display_id} in {stored.storage_path}",
                )
                self._logged_session_save = True
        except CLIError as error:
            self._log(AgentLogKind.WARNING, f"could not save llm session: {error.message}")
        except Exception as error:  # noqa: BLE001
            self._log(AgentLogKind.WARNING, f"could not save llm session: {error}")

    def _compact_json(self, value: Dict[str, Any]) -> Optional[str]:
        if not value:
            return None
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return None

    def _system_prompt(self, width: int, height: int, image_width: int, image_height: int) -> str:
        if self._coord_space == CoordSpace.PIXEL:
            coord_desc = (
                f"The screenshot image is {image_width}x{image_height}, downsampled from a "
                f"{width}x{height} logical display coordinate space. Coordinates are logical "
                f"display pixels with the origin at the top-left; pass integer coordinates inside "
                f"0..{width - 1} / 0..{height - 1}."
            )
        else:
            coord_desc = (
                f"The screenshot image is {image_width}x{image_height}, downsampled from a "
                f"{width}x{height} logical display coordinate space. Coordinates are normalized to "
                "a 0-1000 scale with the origin at the top-left: (0,0) is the top-left corner and "
                "(1000,1000) is the bottom-right corner. X increases left-to-right, Y "
                "top-to-bottom."
            )

        return build_system_prompt(
            coord_desc=coord_desc,
            allow_bash=self._config.allow_bash,
            batched_actions=self._config.batched_actions,
        )


# MARK: - `metacua agent` entry point


class AgentSession:
    def __init__(self, config: AgentConfig, max_steps, overlay_enabled, overlay_controller, ui):
        self.config = config
        self.max_steps = max_steps
        self.overlay_enabled = overlay_enabled
        self.debug_mode = False
        self._overlay_controller = overlay_controller
        self._ui = ui
        self._terminal_attention = TerminalAttention()

        backend = make_backend(config)
        manipulation = make_manipulation_backend(config)
        self.backend_label = backend.label
        self.manipulation_label = manipulation.label
        self._agent = Agent(
            config=config,
            backend=backend,
            manipulation=manipulation,
            overlay=overlay_controller if overlay_enabled else None,
            max_steps=max_steps,
            screenshot_scale=config.screenshot_scale,
            shows_reasoning_text=self.debug_mode,
            logger=ui.agent_log,
        )

    def print_header(self):
        self._ui.print_header(
            self.config, self.backend_label, self.manipulation_label,
            self.max_steps, self.overlay_enabled,
        )

    def run_goal(self, goal: str, interactive: bool = False):
        completion_kind = AgentLogKind.SUCCESS
        completion_message = "agent finished"
        should_log_completion = True
        try:
            self._agent.run(goal)
        except KeyboardInterrupt:
            if not interactive:
                should_log_completion = False
                raise
            completion_kind = AgentLogKind.WARNING
            completion_message = "goal interrupted"
        except CLIError as error:
            completion_kind = AgentLogKind.WARNING
            completion_message = "agent stopped after error"
            self._ui.agent_log(AgentLogKind.ERROR, error.message)
        except Exception as error:  # noqa: BLE001
            completion_kind = AgentLogKind.WARNING
            completion_message = "agent stopped after error"
            self._ui.agent_log(AgentLogKind.ERROR, str(error))
        finally:
            if should_log_completion:
                suffix = "; terminal reactivated" if self._terminal_attention.wake() else ""
                self._ui.agent_log(completion_kind, completion_message + suffix)

    def set_model(self, value: str) -> str:
        raw = value.strip()
        if not raw:
            raise CLIError("usage: /model <model-id>", code=2)
        self.config.model = DEFAULT_MODEL if raw == "muse-spark" else raw
        self._rebuild_agent()
        return f"model switched to {self.config.model}"

    def set_syntax(self, value: str) -> str:
        from .config import normalize_syntax

        syntax = normalize_syntax(value)
        if syntax is None:
            raise CLIError("usage: /syntax <function|pyautogui>", code=2)
        self.config.syntax = syntax
        self._rebuild_agent()
        return f"syntax set to {syntax}"

    def set_effort(self, value: str) -> str:
        raw = value.strip().lower()
        if raw not in ("low", "medium", "high", "xhigh", "max"):
            raise CLIError("usage: /effort <low|medium|high|xhigh|max>", code=2)
        self.config.effort = raw
        self._rebuild_agent()
        return f"effort set to {raw}"

    def set_coords(self, value: str) -> str:
        raw = value.strip()
        coords = CoordSpace.parse(raw)
        if coords is None:
            raise CLIError("usage: /coords <pixel|normalized>", code=2)
        self.config.coords = coords
        self._rebuild_agent()
        label = "normalized" if coords == CoordSpace.NORMALIZED1000 else "pixel"
        return f"coordinates set to {label}"

    def set_max_steps(self, value: str) -> str:
        raw = value.strip()
        if raw.lower() in ("off", "none", "unlimited", "0"):
            self.max_steps = None
            self._rebuild_agent()
            return "max steps disabled"
        try:
            nxt = int(raw)
        except ValueError:
            raise CLIError("usage: /max-steps <positive-integer|off>", code=2)
        if nxt < 1:
            raise CLIError("usage: /max-steps <positive-integer|off>", code=2)
        self.max_steps = nxt
        self._rebuild_agent()
        return f"max steps set to {nxt}"

    def set_max_images(self, value: str) -> str:
        raw = value.strip()
        try:
            nxt = int(raw)
        except ValueError:
            raise CLIError("usage: /max-images <positive-integer>", code=2)
        if nxt < 1:
            raise CLIError("usage: /max-images <positive-integer>", code=2)
        self.config.max_images = nxt
        self._rebuild_agent()
        return f"max images set to {nxt}"

    def set_batched_actions(self, value: str) -> str:
        raw = value.strip().lower()
        if raw == "":
            enabled = not self.config.batched_actions
        elif raw in ("on", "true", "yes", "1"):
            enabled = True
        elif raw in ("off", "false", "no", "0"):
            enabled = False
        else:
            raise CLIError("usage: /batched-actions [on|off]", code=2)
        self.config.batched_actions = enabled
        self._rebuild_agent()
        return f"batched actions {'enabled' if enabled else 'disabled'}"

    def set_overlay(self, value: str) -> str:
        raw = value.strip().lower()
        if raw in ("on", "true", "yes", "1"):
            enabled = True
        elif raw in ("off", "false", "no", "0"):
            enabled = False
        else:
            raise CLIError("usage: /overlay <on|off>", code=2)
        if enabled and self._overlay_controller is None:
            raise CLIError(
                "overlay was disabled at launch; restart with --overlay to enable it", code=2
            )
        self.overlay_enabled = enabled
        self._rebuild_agent()
        return f"overlay {'enabled' if enabled else 'disabled'}"

    def set_debug(self, value: str) -> str:
        raw = value.strip().lower()
        if raw == "":
            enabled = not self.debug_mode
        elif raw in ("on", "true", "yes", "1"):
            enabled = True
        elif raw in ("off", "false", "no", "0"):
            enabled = False
        else:
            raise CLIError("usage: /debug [on|off]", code=2)
        self.debug_mode = enabled
        self._rebuild_agent()
        return (
            "debug mode enabled; backend reasoning text will be shown during execution"
            if enabled
            else "debug mode disabled; backend reasoning text is hidden"
        )

    def reset(self) -> str:
        self._rebuild_agent()
        return "session context reset"

    def _rebuild_agent(self):
        backend = make_backend(self.config)
        manipulation = make_manipulation_backend(self.config)
        self.backend_label = backend.label
        self.manipulation_label = manipulation.label
        self._agent = Agent(
            config=self.config,
            backend=backend,
            manipulation=manipulation,
            overlay=self._overlay_controller if self.overlay_enabled else None,
            max_steps=self.max_steps,
            screenshot_scale=self.config.screenshot_scale,
            shows_reasoning_text=self.debug_mode,
            logger=self._ui.agent_log,
        )


def run_agent(raw: List[str]) -> None:
    args = Args(raw)

    config = resolve_agent_config(args)
    max_steps = _parse_max_steps(args)
    use_overlay = args.flag("overlay") and not args.flag("no-overlay")
    goal = args.string("goal")

    ui = TerminalUI()

    if use_overlay:
        import threading

        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        from .overlay import OverlayController

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        overlay = OverlayController()
        session = AgentSession(config, max_steps, use_overlay, overlay, ui)
        session.print_header()

        from .overlay import dispatch_main

        def worker():
            _run_goals(session, goal, ui)
            dispatch_main(lambda: app.terminate_(None))

        threading.Thread(target=worker, daemon=True).start()
        app.run()
    else:
        session = AgentSession(config, max_steps, use_overlay, None, ui)
        session.print_header()
        _run_goals(session, goal, ui)


def _run_goals(session: AgentSession, goal: Optional[str], ui: TerminalUI) -> None:
    if goal is not None:
        session.run_goal(goal, interactive=False)
        return

    while True:
        line = ui.prompt()
        if line is None:
            break
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in ("quit", "exit", "/quit", "/exit"):
            break
        if _handle_slash_command(stripped, session, ui):
            continue
        session.run_goal(stripped, interactive=True)
    ui.print_goodbye()


def _parse_max_steps(args: Args) -> Optional[int]:
    raw = args.string("max-steps")
    if raw is None:
        return DEFAULT_MAX_STEPS
    if raw.strip().lower() in ("off", "none", "unlimited", "0"):
        return None
    try:
        value = int(raw)
    except ValueError:
        raise CLIError(f"--max-steps must be a positive integer or off (got '{raw}')", code=2)
    if value < 1:
        raise CLIError(f"--max-steps must be >= 1 or off (got {value})", code=2)
    return value


def _handle_slash_command(input_str: str, session: AgentSession, ui: TerminalUI) -> bool:
    if not input_str.startswith("/"):
        return False
    parts = input_str.split()
    if not parts:
        return True
    command = parts[0].lower()
    argument = " ".join(parts[1:])

    try:
        if command in ("/help", "/?"):
            ui.print_interactive_help()
        elif command == "/model":
            if not argument:
                ui.print_model(session.config, session.backend_label)
            else:
                ui.agent_log(AgentLogKind.SUCCESS, session.set_model(argument))
        elif command == "/effort":
            if not argument:
                ui.agent_log(AgentLogKind.MESSAGE, f"effort: {session.config.effort}")
            else:
                ui.agent_log(AgentLogKind.SUCCESS, session.set_effort(argument))
        elif command == "/syntax":
            if not argument:
                ui.agent_log(AgentLogKind.MESSAGE, f"syntax: {session.config.syntax}")
            else:
                ui.agent_log(AgentLogKind.SUCCESS, session.set_syntax(argument))
        elif command in ("/coords", "/coordinates"):
            if not argument:
                label = (
                    "normalized"
                    if session.config.coords == CoordSpace.NORMALIZED1000
                    else "pixel"
                )
                ui.agent_log(AgentLogKind.MESSAGE, f"coordinates: {label}")
            else:
                ui.agent_log(AgentLogKind.SUCCESS, session.set_coords(argument))
        elif command in ("/max-steps", "/maxsteps"):
            if not argument:
                label = str(session.max_steps) if session.max_steps is not None else "unlimited"
                ui.agent_log(AgentLogKind.MESSAGE, f"max steps: {label}")
            else:
                ui.agent_log(AgentLogKind.SUCCESS, session.set_max_steps(argument))
        elif command in ("/max-images", "/maximages"):
            if not argument:
                ui.agent_log(AgentLogKind.MESSAGE, f"max images: {session.config.max_images}")
            else:
                ui.agent_log(AgentLogKind.SUCCESS, session.set_max_images(argument))
        elif command in ("/batched-actions", "/batch-actions", "/batching"):
            if not argument:
                ui.agent_log(
                    AgentLogKind.MESSAGE,
                    f"batched actions: {'on' if session.config.batched_actions else 'off'}",
                )
            else:
                ui.agent_log(AgentLogKind.SUCCESS, session.set_batched_actions(argument))
        elif command == "/overlay":
            if not argument:
                ui.agent_log(
                    AgentLogKind.MESSAGE,
                    f"overlay: {'on' if session.overlay_enabled else 'off'}",
                )
            else:
                ui.agent_log(AgentLogKind.SUCCESS, session.set_overlay(argument))
        elif command == "/debug":
            ui.agent_log(AgentLogKind.SUCCESS, session.set_debug(argument))
        elif command == "/status":
            ui.print_status(
                session.config, session.backend_label, session.manipulation_label,
                session.max_steps, session.overlay_enabled,
            )
        elif command == "/tools":
            ui.print_tools(session.config.allow_bash, session.config.batched_actions)
        elif command == "/doctor":
            ui.print_doctor(
                session.config, session.backend_label, session.manipulation_label,
                session.max_steps, session.overlay_enabled,
            )
        elif command == "/config":
            ui.print_config(
                session.config, session.backend_label, session.manipulation_label,
                session.max_steps, session.overlay_enabled,
            )
        elif command in ("/sessions", "/session-history", "/history"):
            if not argument:
                ui.print_stored_sessions(limit=10)
            elif argument.isdigit():
                ui.print_stored_sessions(limit=int(argument))
            else:
                ui.print_stored_session(id=argument)
        elif command in ("/permissions", "/permission"):
            if "--prompt" in parts:
                ensure_trusted(prompt=True)
                ensure_screen_recording(prompt=True)
            ui.print_permissions()
        elif command == "/clear":
            ui.clear_screen()
            session.print_header()
        elif command in ("/new", "/reset"):
            ui.agent_log(AgentLogKind.SUCCESS, session.reset())
        else:
            ui.agent_log(AgentLogKind.WARNING, f"unknown command {command}; type /help")
    except CLIError as error:
        ui.agent_log(AgentLogKind.ERROR, error.message)
    except Exception as error:  # noqa: BLE001
        ui.agent_log(AgentLogKind.ERROR, str(error))
    return True
