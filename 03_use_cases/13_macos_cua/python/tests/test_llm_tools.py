from metacua.llm import agent_tool_specs


def _specs_by_name(**kwargs):
    return {spec.name: spec for spec in agent_tool_specs(**kwargs)}


def test_agent_tool_specs_single_computer_schema():
    specs = _specs_by_name()
    assert list(specs) == ["computer.computer", "computer.stop"]
    computer = specs["computer.computer"]
    assert computer.description == (
        "Control the computer via mouse, keyboard, and screen actions.\n\n"
        "This matches Anthropic's computer_20251124 tool interface, but uses "
        "relative coordinates (integers in [0, 1000]) instead of absolute pixels."
    )
    assert computer.schema["required"] == ["action"]
    assert computer.schema["additionalProperties"] is False
    props = computer.schema["properties"]
    assert "screenshot" in props["action"]["description"]
    assert props["coordinate"]["anyOf"][1] == {"type": "null"}
    assert props["coordinate"]["default"] is None
    assert "actions" not in props
    assert specs["computer.stop"].schema["required"] == ["answer"]


def test_agent_tool_specs_batched_enum_and_bash_inclusion():
    specs = _specs_by_name(include_bash=True, batched=True)
    assert list(specs) == ["computer.computer", "computer.stop", "bash"]
    computer = specs["computer.computer"]
    assert computer.schema["required"] == ["actions"]
    enum = computer.schema["properties"]["actions"]["items"]["properties"]["action"]["enum"]
    assert enum == [
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
    assert "screenshot" not in enum
    assert specs["bash"].schema["required"] == ["command"]


def test_old_flat_gui_tools_are_not_advertised():
    names = set(_specs_by_name(include_bash=True).keys())
    assert not {
        "click",
        "moveto",
        "scroll",
        "drag",
        "press_key",
        "type_text",
        "wait",
        "screenshot",
    } & names
