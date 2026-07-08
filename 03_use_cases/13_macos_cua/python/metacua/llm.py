"""Backend-neutral LLM types, GUI tool specs, and shared HTTP."""

import enum
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import CLIError


class CoordSpace(enum.Enum):
    """How the model expresses coordinates in tool calls."""

    PIXEL = "pixel"
    NORMALIZED1000 = "normalized1000"

    @staticmethod
    def parse(raw: str) -> Optional["CoordSpace"]:
        low = raw.lower()
        if low in ("pixel", "pixels", "px"):
            return CoordSpace.PIXEL
        if low in ("normalized", "normalized1000", "0-1000", "norm"):
            return CoordSpace.NORMALIZED1000
        return None


@dataclass
class ToolSpec:
    """A model-backend-neutral tool description."""

    name: str
    description: str
    schema: Dict[str, Any]


@dataclass
class LLMToolCall:
    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class LLMResult:
    """One model turn, normalized across the agent."""

    assistant_items: List[Dict[str, Any]]
    tool_calls: List[LLMToolCall]
    text: str
    thinking: str
    finish: str
    refusal_reason: Optional[str] = None
    response_id: Optional[str] = None
    session_ids: List[str] = field(default_factory=list)
    raw_response: Dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    # OSWorld / pyautogui backends populate these instead of tool_calls: a parsed
    # list of Action objects to execute, and an optional control token
    # ('wait' | 'done' | 'fail'). Function-calling backends leave both as None.
    actions: Optional[List[Any]] = None
    control: Optional[str] = None


@dataclass
class ToolRun:
    """The result of running one tool call locally."""

    call_id: str
    name: str
    output: str
    is_error: bool


class LLMBackend:
    """Interface the agent loop is written against; never touches the wire format."""

    label: str = ""
    coord_space: CoordSpace = CoordSpace.NORMALIZED1000

    def initial_conversation(self, goal_text: str, screenshot) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def send(self, system: str, conversation: List[Dict[str, Any]]) -> LLMResult:
        raise NotImplementedError

    def tool_result_items(
        self, runs: List[ToolRun], screenshot, notes: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError


def make_backend(config) -> LLMBackend:
    if getattr(config, "syntax", "function") == "pyautogui":
        from .osworld import OSWorldBackend

        return OSWorldBackend(config)

    from .muse_spark import MuseSparkBackend

    return MuseSparkBackend(config)


def api_reasoning_effort(effort: str) -> str:
    """Map CLI effort levels to the API's accepted low|medium|high values."""
    if effort in ("minimal", "low"):
        return "low"
    if effort == "medium":
        return "medium"
    return "high"


def retain_most_recent_images(
    conversation: List[Dict[str, Any]], max_images: int
) -> List[Dict[str, Any]]:
    """Return a conversation copy with older image blocks replaced."""
    limit = max(1, int(max_images))
    total_images = sum(_count_image_blocks(item) for item in conversation)
    if total_images <= limit:
        return list(conversation)

    remove_count = total_images - limit
    seen_images = [0]
    return [
        _retain_most_recent_images_in_value(item, remove_count, limit, seen_images)
        for item in conversation
    ]


def _count_image_blocks(value: Any) -> int:
    if isinstance(value, dict):
        self_count = 1 if _is_image_block(value) else 0
        return self_count + sum(_count_image_blocks(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_image_blocks(child) for child in value)
    return 0


def _retain_most_recent_images_in_value(
    value: Any, remove_count: int, max_images: int, seen_images: List[int]
) -> Any:
    if isinstance(value, dict):
        if _is_image_block(value):
            seen_images[0] += 1
            if seen_images[0] <= remove_count:
                return {
                    "type": "input_text",
                    "text": "[Screenshot has been truncated to save context]",
                }
            return dict(value)
        return {
            key: _retain_most_recent_images_in_value(
                child, remove_count, max_images, seen_images
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _retain_most_recent_images_in_value(child, remove_count, max_images, seen_images)
            for child in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _retain_most_recent_images_in_value(child, remove_count, max_images, seen_images)
            for child in value
        )
    return value


def _is_image_block(value: Dict[str, Any]) -> bool:
    image_url = value.get("image_url")
    return isinstance(image_url, str) and image_url.startswith("data:image/")


def agent_tool_specs(include_bash: bool = False, batched: bool = False) -> List[ToolSpec]:
    """The GUI tools the agent exposes. Coordinate units are described in the system prompt."""

    coordinate_array = {
        "description": "[x, y] relative coordinates (integers in [0, 1000]).",
        "items": {"type": "integer"},
        "maxItems": 2,
        "minItems": 2,
        "type": "array",
    }
    nullable_coordinate_array = {
        "anyOf": [
            {"items": {"type": "integer"}, "type": "array"},
            {"type": "null"},
        ],
        "default": None,
    }
    batched_action_enum = [
        "key",
        "type",
        "mouse_move",
        "left_click",
        "left_click_drag",
        "right_click",
        "middle_click",
        "double_click",
        "triple_click",
        "left_press",
        "scroll",
        "hold_key",
        "release_key",
        "left_mouse_down",
        "left_mouse_up",
        "wait",
    ]
    action_item_schema = {
        "properties": {
            "action": {
                "description": (
                    "The action to perform. Same action types as the single-action "
                    "computer tool form."
                ),
                "enum": batched_action_enum,
                "type": "string",
            },
            "text": {
                "description": (
                    "For 'type': text to type. For 'key': key combo, e.g. 'ctrl+s'. "
                    "For click/scroll: modifier key to hold during action."
                ),
                "type": "string",
            },
            "coordinate": coordinate_array,
            "start_coordinate": {
                "description": "[x, y] start coordinates for left_click_drag.",
                "items": {"type": "integer"},
                "maxItems": 2,
                "minItems": 2,
                "type": "array",
            },
            "scroll_direction": {
                "description": "Direction to scroll. Required for action=scroll.",
                "enum": ["up", "down", "left", "right"],
                "type": "string",
            },
            "scroll_amount": {
                "description": "Number of scroll clicks. Required for action=scroll.",
                "type": "integer",
            },
            "duration": {
                "description": "Duration in seconds for hold_key or wait.",
                "type": "number",
            },
        },
        "required": ["action"],
        "type": "object",
    }

    single_coordinate = dict(nullable_coordinate_array)
    single_coordinate["description"] = (
        "[x, y] relative coordinates (integers in [0, 1000]) for mouse actions. "
        "Required for click, move, and drag actions."
    )
    single_start_coordinate = dict(nullable_coordinate_array)
    single_start_coordinate["description"] = (
        "[x, y] relative starting coordinates (integers in [0, 1000]) for "
        "left_click_drag."
    )
    single_action_schema_properties = {
        "action": {
            "description": (
                "The action to perform. One of: left_click, right_click, double_click, "
                "middle_click, triple_click, left_press, left_click_drag, mouse_move, key, "
                "type, hold_key, release_key, left_mouse_down, left_mouse_up, scroll, "
                "screenshot, wait"
            ),
            "type": "string",
        },
        "coordinate": single_coordinate,
        "text": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "description": (
                "Text input for keyboard actions. For 'key': key combo string, e.g. "
                "'ctrl+c' or 'Return'. For 'type': text to type character by character. "
                "For 'hold_key'/'release_key': keys to hold/release. For click actions: "
                "modifier keys to hold, e.g. 'shift' or 'ctrl+shift'."
            ),
        },
        "start_coordinate": single_start_coordinate,
        "scroll_direction": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "description": "Scroll direction: 'up', 'down', 'left', or 'right'.",
        },
        "scroll_amount": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "default": None,
            "description": "Number of scroll clicks.",
        },
        "duration": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "default": None,
            "description": "Duration in seconds for move/drag actions and wait actions.",
        },
    }

    computer_description = (
        "Control the computer via mouse, keyboard, and screen actions.\n\n"
        "This matches Anthropic's computer_20251124 tool interface, but uses "
        "relative coordinates (integers in [0, 1000]) instead of absolute pixels."
    )
    if batched:
        computer_schema = {
            "properties": {
                "actions": {
                    "description": (
                        "List of actions to execute in sequence in a single tool call. "
                        "Each item: {action: str, coordinate?: [x,y], text?: str, ...}. "
                        "Batch as many predictable actions as possible; only split when "
                        "the next step depends on observing a screenshot."
                    ),
                    "items": action_item_schema,
                    "type": "array",
                }
            },
            "required": ["actions"],
            "type": "object",
            "additionalProperties": False,
        }
    else:
        computer_schema = {
            "properties": single_action_schema_properties,
            "required": ["action"],
            "type": "object",
            "additionalProperties": False,
        }

    specs = [
        ToolSpec("computer.computer", computer_description, computer_schema),
        ToolSpec(
            "computer.stop",
            "Stop the session and submit your final answer.",
            {
                "properties": {
                    "answer": {
                        "description": (
                            "Brief description of what you accomplished, or why you cannot "
                            "proceed safely."
                        ),
                        "type": "string",
                    }
                },
                "required": ["answer"],
                "type": "object",
                "additionalProperties": False,
            },
        ),
    ]
    if include_bash:
        specs.append(
            ToolSpec(
                "bash",
                "Execute a shell command on this Mac with /bin/bash -lc. Returns exit code, "
                "stdout, and stderr. Commands run in metacua's current working directory.",
                {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout_ms": {"type": "integer"},
                    },
                    "required": ["command"],
                },
            )
        )
    return specs


class _RetryableHTTPError(Exception):
    """Wraps a CLIError that should trigger a retry with backoff."""

    def __init__(self, error: CLIError):
        super().__init__(error.message)
        self.error = error


def http_post_json(
    url: str,
    headers: Dict[str, str],
    body: Dict[str, Any],
    timeout: float = 300,
    max_retries: int = 10,
    initial_retry_delay: float = 1.0,
) -> Dict[str, Any]:
    """POST a JSON body and return the parsed JSON object.

    Retries on transient failures (network errors and 408/429/5xx statuses) with
    exponential backoff. Raises CLIError with the server's message otherwise.
    """
    payload = json.dumps(body).encode("utf-8")
    all_headers = dict(headers)
    all_headers["Content-Type"] = "application/json"

    attempts = max(0, max_retries) + 1
    delay = max(0.1, initial_retry_delay)
    last_error: Optional[CLIError] = None

    for attempt in range(1, attempts + 1):
        try:
            return _perform_post(url, payload, all_headers, timeout)
        except _RetryableHTTPError as exc:
            last_error = exc.error
            if attempt >= attempts:
                raise exc.error
            _log_http_retry(exc.error, attempt, max_retries, delay)
            _sleep_for_retry(delay)
            delay = min(delay * 2, 8.0)

    raise last_error or CLIError("request failed")


def _perform_post(
    url: str,
    payload: bytes,
    all_headers: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    request = urllib.request.Request(url, data=payload, headers=all_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise _RetryableHTTPError(CLIError(f"network error: {exc.reason}"))
    except OSError as exc:
        raise _RetryableHTTPError(CLIError(f"network error: {exc}"))

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        parsed = None
    if not isinstance(parsed, dict):
        parsed = None

    if not (200 <= status <= 299):
        message = raw
        if parsed is not None:
            err = parsed.get("error")
            if isinstance(err, dict) and isinstance(err.get("message"), str):
                message = err["message"]
            elif isinstance(err, str):
                message = err
        error = CLIError(f"API error {status}: {message}")
        if _is_retryable_http_status(status):
            raise _RetryableHTTPError(error)
        raise error

    if parsed is None:
        raise CLIError("could not parse API response as JSON")
    return parsed


def _is_retryable_http_status(status: int) -> bool:
    return status == 408 or status == 429 or (500 <= status <= 599)


def _log_http_retry(error: CLIError, attempt: int, max_retries: int, delay: float) -> None:
    message = f"warning: {error.message}; retrying in {delay:.1f}s ({attempt}/{max_retries})\n"
    sys.stderr.write(message)


def _sleep_for_retry(seconds: float) -> None:
    time.sleep(max(0.0, min(seconds, 60.0)))


def _extract_session_ids(value: Any) -> List[str]:
    ids: List[str] = []
    _collect_session_ids(value, ids)
    return ids


def _collect_session_ids(value: Any, ids: List[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("session_id", "sessionId", "llm_session_id"):
                if isinstance(child, str) and child and child not in ids:
                    ids.append(child)
            if key in ("session_ids", "sessionIds", "llm_session_ids"):
                if isinstance(child, list):
                    for item in child:
                        if isinstance(item, str) and item and item not in ids:
                            ids.append(item)
            _collect_session_ids(child, ids)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _collect_session_ids(child, ids)
