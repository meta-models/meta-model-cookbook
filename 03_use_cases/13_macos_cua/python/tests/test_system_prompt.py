import re

from metacua.system_prompt import build_system_prompt


def test_system_prompt_contains_date_and_computer_tools():
    prompt = build_system_prompt(
        coord_desc="The screenshot image is 100x100.",
        allow_bash=False,
        batched_actions=False,
    )
    assert re.search(r"^Current date: [A-Z][a-z]+, [A-Z][a-z]+ \d{1,2}, \d{4}\.", prompt)
    assert "Use `computer.computer` for computer actions" in prompt
    assert "`computer.stop`" in prompt
    assert "`bash` tool" not in prompt
    assert "- Focus on ONE action at a time." in prompt


def test_system_prompt_batched_and_bash_variants():
    prompt = build_system_prompt(
        coord_desc="The screenshot image is 100x100.",
        allow_bash=True,
        batched_actions=True,
    )
    assert "The optional `bash` tool is also available" in prompt
    assert "via the `actions` array" in prompt
