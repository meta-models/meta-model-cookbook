"""Muse Spark backend, POST {base}/responses.

The model's output items are echoed back verbatim each turn; tool results are
sent as function call output items.
"""

import json
from typing import Any, Dict, List, Optional

from .config import AgentConfig
from .errors import CLIError
from .llm import (
    CoordSpace,
    LLMBackend,
    LLMResult,
    LLMToolCall,
    ToolRun,
    _extract_session_ids,
    agent_tool_specs,
    api_reasoning_effort,
    http_post_json,
    retain_most_recent_images,
)
from .screenshot import Screenshot


class MuseSparkBackend(LLMBackend):
    def __init__(self, config: AgentConfig):
        self.config = config

    @property
    def label(self) -> str:
        return f"Muse Spark {self.config.model}"

    @property
    def coord_space(self) -> CoordSpace:
        return self.config.coords

    def _tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.schema,
            }
            for spec in agent_tool_specs(
                include_bash=self.config.allow_bash,
                batched=self.config.batched_actions,
            )
        ]

    def _image_block(self, s: Screenshot) -> Dict[str, Any]:
        return {"type": "input_image", "image_url": "data:image/png;base64," + s.png_base64}

    def initial_conversation(self, goal_text: str, screenshot: Screenshot) -> List[Dict[str, Any]]:
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
            "tools": self._tools(),
            "stream": False,
            "store": False,
            "parallel_tool_calls": False,
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
        calls: List[LLMToolCall] = []
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
                    elif ctype == "reasoning_text":
                        thinking = _append_fragments(
                            _extract_reasoning_fragments(content), thinking
                        )
            elif item_type == "reasoning":
                thinking = _append_fragments(_extract_reasoning_fragments(item), thinking)
            elif item_type == "function_call":
                args_string = item.get("arguments") or "{}"
                try:
                    parsed = json.loads(args_string)
                except (ValueError, TypeError):
                    parsed = {}
                if not isinstance(parsed, dict):
                    parsed = {}
                calls.append(
                    LLMToolCall(
                        id=item.get("call_id") or "",
                        name=item.get("name") or "",
                        input=parsed,
                    )
                )

        incomplete = obj.get("incomplete_details")
        truncated = (
            isinstance(incomplete, dict) and incomplete.get("reason") == "max_output_tokens"
        ) or obj.get("status") == "incomplete"

        if calls:
            finish = "tool_use"
        elif refused:
            finish = "refusal"
        elif truncated:
            finish = "max_tokens"
        else:
            finish = "stop"

        # Replay messages and function calls, but drop reasoning items: with
        # store:false there is no server-side state to resolve their opaque ids
        # against, and echoing them back triggers the endpoint's "persistence
        # service error" on the next turn.
        replay_items = [item for item in output if item.get("type") != "reasoning"]

        return LLMResult(
            assistant_items=replay_items,
            tool_calls=calls,
            text=text,
            thinking=thinking,
            finish=finish,
            refusal_reason=text if refused else None,
            response_id=obj.get("id") or obj.get("response_id"),
            session_ids=_extract_session_ids(obj),
            raw_response=obj,
            truncated=truncated,
        )

    def tool_result_items(
        self, runs: List[ToolRun], screenshot, notes: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for index, run in enumerate(runs):
            output_text = ("ERROR: " + run.output) if run.is_error else run.output
            output: Any = output_text
            if index == len(runs) - 1:
                content: List[Dict[str, Any]] = [{"type": "input_text", "text": output_text}]
                if screenshot is not None:
                    content.append(
                        {
                            "type": "input_text",
                            "text": "Screen observation after the action:",
                        }
                    )
                    content.append(self._image_block(screenshot))
                else:
                    content.append({"type": "input_text", "text": "[screenshot unavailable]"})
                output = content
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": run.call_id,
                    "output": output,
                }
            )
        return items


def _extract_reasoning_fragments(item: Dict[str, Any]) -> List[str]:
    fragments: List[str] = []
    for summary in item.get("summary") or []:
        if isinstance(summary, dict):
            text = summary.get("text")
            if isinstance(text, str) and text:
                fragments.append(text)
    _collect_reasoning_fragments(item, fragments)
    return fragments


def _collect_reasoning_fragments(value: Any, fragments: List[str]) -> None:
    if isinstance(value, dict):
        if value.get("type") == "reasoning_text":
            text = value.get("text")
            if isinstance(text, str) and text:
                fragments.append(text)
        for child in value.values():
            _collect_reasoning_fragments(child, fragments)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _collect_reasoning_fragments(child, fragments)


def _append_fragments(fragments: List[str], existing: str) -> str:
    cleaned = [frag.strip() for frag in fragments if isinstance(frag, str)]
    cleaned = [frag for frag in cleaned if frag]
    if not cleaned:
        return existing
    suffix = "\n\n".join(cleaned)
    return suffix if not existing else existing + "\n\n" + suffix
