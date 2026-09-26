"""Tool-result shape for the Muse Spark backend.

The Swift backend (src/metacua/MuseSparkBackend.swift) returns a plain string
from `function_call_output` and sends the screenshot as a following user
message. These tests pin the Python backend to the same contract.
"""
import types

from metacua.llm import ToolRun
from metacua.muse_spark import MuseSparkBackend


def _backend():
    config = types.SimpleNamespace(
        base_url="http://localhost:1/v1", api_key="k", model="m",
        allow_bash=False, batched_actions=False, effort="low", max_images=5,
    )
    return MuseSparkBackend(config)


def _screenshot():
    shot = types.SimpleNamespace()
    shot.png_base64 = "AAAA"
    shot.width, shot.height = 100, 80
    return shot


def _runs(n=1):
    return [
        ToolRun(call_id=f"call_{i}", name="computer.computer",
                output="Action executed.", is_error=False)
        for i in range(n)
    ]


def test_function_call_output_is_a_string():
    """Images belong to computer_call_output, not function_call_output."""
    items = _backend().tool_result_items(_runs(), _screenshot())
    outputs = [i for i in items if i.get("type") == "function_call_output"]
    assert len(outputs) == 1
    assert isinstance(outputs[0]["output"], str)
    assert outputs[0]["call_id"] == "call_0"


def test_screenshot_is_sent_as_a_user_message():
    items = _backend().tool_result_items(_runs(), _screenshot())
    messages = [i for i in items if i.get("type") == "message"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    kinds = [part["type"] for part in messages[0]["content"]]
    assert "input_image" in kinds
    assert kinds.index("input_text") < kinds.index("input_image")


def test_no_image_parts_inside_any_tool_output():
    items = _backend().tool_result_items(_runs(3), _screenshot())
    for item in items:
        if item.get("type") == "function_call_output":
            assert "input_image" not in str(item["output"])


def test_every_run_gets_its_own_output_item():
    items = _backend().tool_result_items(_runs(3), _screenshot())
    outputs = [i for i in items if i.get("type") == "function_call_output"]
    assert [o["call_id"] for o in outputs] == ["call_0", "call_1", "call_2"]


def test_errors_are_marked():
    runs = [ToolRun(call_id="c", name="computer.computer",
                    output="boom", is_error=True)]
    items = _backend().tool_result_items(runs, _screenshot())
    output = next(i for i in items if i.get("type") == "function_call_output")
    assert output["output"].startswith("ERROR: ")


def test_missing_screenshot_still_reports_to_the_model():
    items = _backend().tool_result_items(_runs(), None)
    message = next(i for i in items if i.get("type") == "message")
    text = " ".join(p.get("text", "") for p in message["content"])
    assert "screenshot" in text.lower()
    assert all(p["type"] != "input_image" for p in message["content"])


def test_notes_are_surfaced():
    items = _backend().tool_result_items(_runs(), _screenshot(), notes=["skipped x"])
    message = next(i for i in items if i.get("type") == "message")
    text = " ".join(p.get("text", "") for p in message["content"])
    assert "skipped x" in text


def test_screenshot_survives_when_there_are_no_runs():
    """agent.py calls this with runs=[] after a step with no tool calls."""
    items = _backend().tool_result_items([], _screenshot())
    messages = [i for i in items if i.get("type") == "message"]
    assert len(messages) == 1
    assert any(p["type"] == "input_image" for p in messages[0]["content"])
