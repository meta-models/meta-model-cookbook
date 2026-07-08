"""OSWorld-style pyautogui backend for Muse Spark.

The model was trained on the OSWorld action space: it observes a screenshot at a
fixed resolution (1920x1080) and emits `pyautogui` code as text. This backend
speaks that native language instead of OpenAI function-calling:

- It sends the screenshot aspect-fit into the training resolution with black
  letterbox bars when needed.
- It prompts for a ```python code block of pyautogui calls (or WAIT/DONE/FAIL).
- It parses that code (via `ast`, never `exec`) into a list of `Action`s.

The agent executes the parsed actions, mapping coordinates from the model's
letterboxed 1920x1080 space back to the real display.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .config import AgentConfig
from .llm import (
    CoordSpace,
    LLMBackend,
    LLMResult,
    ToolRun,
    _extract_session_ids,
    api_reasoning_effort,
    http_post_json,
    retain_most_recent_images,
)

if TYPE_CHECKING:
    from .screenshot import Screenshot

MODEL_RESOLUTION: Tuple[int, int] = (1920, 1080)

_SYSTEM_PROMPT = """You are an autonomous agent operating a real macOS computer to complete the user's task.

At each step you receive a screenshot of the screen ({width}x{height} pixels) and you control the computer with pyautogui.

OUTPUT FORMAT:
- Return your next action as a single ```python code block of pyautogui calls.
- Coordinates are absolute pixels in the {width}x{height} screenshot, origin at the top-left (x increases right, y increases down). Read them off the screenshot; do not guess.
- If the display aspect ratio differs from {width}x{height}, the screenshot may include black letterbox bars; the usable screen is the non-black region.
- Take one small step at a time, then wait for the next screenshot before continuing.
- You may write multiple lines and use time.sleep(seconds) between them when the UI needs a moment to update.
- Do NOT use pyautogui.screenshot() or pyautogui.locateCenterOnScreen(). Do NOT define variables or functions; nothing persists between steps.

MACOS NOTES:
- Use the 'command' modifier for shortcuts. pyautogui.hotkey('command', 'space') opens Spotlight; type an app name and press 'return' to launch it.
- Click a text field before typing. Use pyautogui.write('text') to type and pyautogui.press('return') to confirm.
- Prefer search fields and keyboard shortcuts over hunting for small targets. To jump to the top/bottom of a list or document, click it then pyautogui.hotkey('command', 'up') / pyautogui.hotkey('command', 'down').

SPECIAL RESPONSES (return exactly one, alone in a code block):
- WAIT  - nothing to do yet; wait and re-observe.
- DONE  - the task is complete.
- FAIL  - the task cannot be completed.

Stop when you finish.

Think briefly about what you see, then act. This controls the user's real machine, so be deliberate and avoid irreversible actions unless the task clearly requires them."""


@dataclass
class Action:
    """A normalized action parsed from pyautogui code, in model pixel space."""

    kind: str
    x: Optional[float] = None
    y: Optional[float] = None
    button: str = "left"
    clicks: int = 1
    amount: int = 0
    keys: List[str] = field(default_factory=list)
    text: str = ""
    seconds: float = 0.0
    note: str = ""


# ---- Parsing --------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_CONTROL = {"WAIT": "wait", "DONE": "done", "FAIL": "fail"}


def _extract_code(text: str) -> str:
    blocks = _FENCE_RE.findall(text)
    if blocks:
        # If the model explains, then acts, the action is the last block.
        return blocks[-1].strip()
    return text.strip()


def _dotted_name(func: ast.AST) -> str:
    parts: List[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _lit(node: Optional[ast.AST]) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _call_to_action(call: ast.Call) -> Optional[Action]:
    name = _dotted_name(call.func)
    short = name.split(".")[-1].lower()
    args = [_lit(a) for a in call.args]
    kwargs = {kw.arg: _lit(kw.value) for kw in call.keywords if kw.arg}

    def arg(idx: int, key: str) -> Any:
        if key in kwargs and kwargs[key] is not None:
            return kwargs[key]
        return args[idx] if idx < len(args) else None

    if short in ("moveto", "movto"):
        return Action("move", x=_num(arg(0, "x")), y=_num(arg(1, "y")))
    if short == "click":
        return Action(
            "click", x=_num(arg(0, "x")), y=_num(arg(1, "y")),
            button=str(kwargs.get("button") or (args[4] if len(args) > 4 else "left")),
            clicks=int(_num(kwargs.get("clicks")) or (args[2] if len(args) > 2 and _num(args[2]) else 1)),
        )
    if short == "doubleclick":
        return Action("click", x=_num(arg(0, "x")), y=_num(arg(1, "y")), clicks=2)
    if short == "tripleclick":
        return Action("click", x=_num(arg(0, "x")), y=_num(arg(1, "y")), clicks=3)
    if short == "rightclick":
        return Action("click", x=_num(arg(0, "x")), y=_num(arg(1, "y")), button="right")
    if short == "middleclick":
        return Action("click", x=_num(arg(0, "x")), y=_num(arg(1, "y")), button="middle")
    if short in ("dragto", "drag"):
        return Action(
            "drag", x=_num(arg(0, "x")), y=_num(arg(1, "y")),
            button=str(kwargs.get("button") or "left"),
        )
    if short == "scroll":
        return Action(
            "scroll", amount=int(_num(arg(0, "clicks")) or 0),
            x=_num(kwargs.get("x")), y=_num(kwargs.get("y")),
        )
    if short == "hscroll":
        return Action("hscroll", amount=int(_num(arg(0, "clicks")) or 0))
    if short == "hotkey":
        keys = [str(a) for a in args if isinstance(a, str)]
        return Action("hotkey", keys=keys) if keys else None
    if short == "press":
        target = arg(0, "keys")
        if isinstance(target, str):
            keys = [target]
        elif isinstance(target, (list, tuple)):
            keys = [str(k) for k in target]
        else:
            return None
        presses = int(_num(kwargs.get("presses")) or 1)
        return Action("press", keys=keys * max(1, presses))
    if short == "keydown":
        target = arg(0, "key")
        return Action("keydown", keys=[str(target)]) if isinstance(target, str) else None
    if short == "keyup":
        target = arg(0, "key")
        return Action("keyup", keys=[str(target)]) if isinstance(target, str) else None
    if short in ("write", "typewrite"):
        target = arg(0, "message")
        if isinstance(target, (list, tuple)):
            target = "".join(str(k) for k in target)
        return Action("write", text=str(target)) if target is not None else None
    if short == "sleep":
        return Action("sleep", seconds=float(_num(arg(0, "secs")) or 0.0))

    return Action("note", note=f"unsupported call {name}(...)")


def _visit(stmts: List[ast.stmt], actions: List[Action]) -> None:
    for stmt in stmts:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            action = _call_to_action(stmt.value)
            if action is not None:
                actions.append(action)
        elif isinstance(stmt, (ast.For, ast.While, ast.If, ast.With)):
            _visit(stmt.body, actions)
        # Assignments / imports / everything else are irrelevant to GUI actions.


def parse_actions(text: str) -> Tuple[Optional[str], List[Action]]:
    """Parse model output into (control_token, actions).

    control_token is 'wait' | 'done' | 'fail' | None. When a control token is
    returned, actions is empty.
    """
    code = _extract_code(text)
    bare = code.strip().strip("`").strip()
    if bare.upper() in _CONTROL:
        return _CONTROL[bare.upper()], []

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None, [Action("note", note=f"could not parse code: {code[:80]}")]

    actions: List[Action] = []
    _visit(tree.body, actions)
    return None, actions


# ---- Backend --------------------------------------------------------------


class OSWorldBackend(LLMBackend):
    model_resolution: Tuple[int, int] = MODEL_RESOLUTION

    def __init__(self, config: AgentConfig):
        self.config = config

    @property
    def label(self) -> str:
        return f"Muse Spark {self.config.model} (pyautogui)"

    @property
    def coord_space(self) -> CoordSpace:
        return CoordSpace.PIXEL

    def system_prompt(self) -> str:
        width, height = self.model_resolution
        return _SYSTEM_PROMPT.format(width=width, height=height)

    def _image_block(self, shot: "Screenshot") -> Dict[str, Any]:
        from .screenshot import scaled_letterboxed_png_base64

        width, height = self.model_resolution
        b64, _fit = scaled_letterboxed_png_base64(shot, width, height)
        return {"type": "input_image", "image_url": "data:image/png;base64," + b64}

    def initial_conversation(self, goal_text: str, screenshot: "Screenshot") -> List[Dict[str, Any]]:
        return [
            {
                "role": "user",
                "type": "message",
                "content": [
                    {"type": "input_text", "text": goal_text},
                    self._image_block(screenshot),
                ],
            }
        ]

    def send(self, system: str, conversation: List[Dict[str, Any]]) -> LLMResult:
        url = self.config.base_url + "/responses"
        body: Dict[str, Any] = {
            "model": self.config.model,
            "instructions": system,
            "input": retain_most_recent_images(conversation, self.config.max_images),
            "stream": False,
            "store": False,
            "max_output_tokens": 4096,
            "reasoning": {"effort": api_reasoning_effort(self.config.effort)},
        }
        obj = http_post_json(
            url,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            body=body,
        )

        output = obj.get("output") or []
        text = ""
        thinking = ""
        refused = False
        for item in output:
            item_type = item.get("type")
            if item_type == "message":
                for content in item.get("content") or []:
                    ctype = content.get("type")
                    if ctype == "output_text":
                        text += content.get("text") or ""
                    elif ctype == "refusal":
                        refused = True
                        text += content.get("refusal") or ""
            elif item_type == "reasoning":
                for summary in item.get("summary") or []:
                    thinking += summary.get("text") or ""

        incomplete = obj.get("incomplete_details")
        truncated = (
            isinstance(incomplete, dict) and incomplete.get("reason") == "max_output_tokens"
        ) or obj.get("status") == "incomplete"

        if refused:
            finish = "refusal"
        elif truncated:
            finish = "max_tokens"
        else:
            finish = "stop"

        control, actions = (None, []) if refused else parse_actions(text)

        # Drop reasoning items from the replayed conversation (see MuseSparkBackend).
        replay_items = [item for item in output if item.get("type") != "reasoning"]

        return LLMResult(
            assistant_items=replay_items,
            tool_calls=[],
            text=text,
            thinking=thinking,
            finish=finish,
            refusal_reason=text if refused else None,
            response_id=obj.get("id") or obj.get("response_id"),
            session_ids=_extract_session_ids(obj),
            raw_response=obj,
            truncated=truncated,
            actions=actions,
            control=control,
        )

    def tool_result_items(
        self, runs: List[ToolRun], screenshot, notes: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        # OSWorld has no function-call outputs; the model just needs the next frame.
        content: List[Dict[str, Any]] = []
        if notes:
            content.append(
                {
                    "type": "input_text",
                    "text": "Some actions were not executed: " + "; ".join(notes),
                }
            )
        if screenshot is None:
            content.append(
                {
                    "type": "input_text",
                    "text": "screenshot failed; the previous screen may be stale",
                }
            )
        else:
            content.extend(
                [
                    {"type": "input_text", "text": "Here is the screenshot after your last action:"},
                    self._image_block(screenshot),
                ]
            )
        return [
            {
                "role": "user",
                "type": "message",
                "content": content,
            }
        ]
