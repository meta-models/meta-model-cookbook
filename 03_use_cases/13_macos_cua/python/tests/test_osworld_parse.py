from metacua.osworld import _extract_code, parse_actions


def one(text):
    control, actions = parse_actions(text)
    assert control is None
    assert len(actions) == 1
    return actions[0]


def test_extract_code_fenced_unfenced_and_last_block_wins():
    assert _extract_code("pyautogui.click(1, 2)") == "pyautogui.click(1, 2)"
    assert _extract_code("before\n```python\npyautogui.click(1, 2)\n```") == "pyautogui.click(1, 2)"
    text = "```python\npyautogui.click(1, 2)\n```\nthen\n```py\npyautogui.press('a')\n```"
    assert _extract_code(text) == "pyautogui.press('a')"


def test_control_tokens_bare_fenced_and_backticked():
    for raw, expected in [("WAIT", "wait"), ("done", "done"), ("`FAIL`", "fail")]:
        control, actions = parse_actions(raw)
        assert control == expected
        assert actions == []
    control, actions = parse_actions("```python\nWAIT\n```")
    assert control == "wait"
    assert actions == []


def test_click_variants_and_kwargs():
    a = one("pyautogui.click(10, 20)")
    assert (a.kind, a.x, a.y, a.button, a.clicks) == ("click", 10.0, 20.0, "left", 1)
    a = one("pyautogui.click(x=11, y=22, clicks=2, button='right')")
    assert (a.x, a.y, a.button, a.clicks) == (11.0, 22.0, "right", 2)
    assert one("pyautogui.doubleClick(1, 2)").clicks == 2
    assert one("pyautogui.tripleClick(1, 2)").clicks == 3
    assert one("pyautogui.rightClick(1, 2)").button == "right"
    assert one("pyautogui.middleClick(1, 2)").button == "middle"


def test_move_drag_scroll_and_hscroll():
    a = one("pyautogui.moveTo(100, 200)")
    assert (a.kind, a.x, a.y) == ("move", 100.0, 200.0)
    a = one("pyautogui.dragTo(x=300, y=400, button='right')")
    assert (a.kind, a.x, a.y, a.button) == ("drag", 300.0, 400.0, "right")
    a = one("pyautogui.scroll(-5, x=10, y=20)")
    assert (a.kind, a.amount, a.x, a.y) == ("scroll", -5, 10.0, 20.0)
    a = one("pyautogui.hscroll(7)")
    assert (a.kind, a.amount) == ("hscroll", 7)


def test_keyboard_and_text_actions():
    a = one("pyautogui.hotkey('command', 'space')")
    assert (a.kind, a.keys) == ("hotkey", ["command", "space"])
    a = one("pyautogui.press('tab', presses=3)")
    assert (a.kind, a.keys) == ("press", ["tab", "tab", "tab"])
    assert one("pyautogui.press(['a', 'b'])").keys == ["a", "b"]
    assert one("pyautogui.keyDown('shift')").kind == "keydown"
    assert one("pyautogui.keyUp('shift')").kind == "keyup"
    assert one("pyautogui.write('hello')").text == "hello"
    assert one("pyautogui.typewrite(['a', 'b', 'c'])").text == "abc"
    assert one("time.sleep(1.5)").seconds == 1.5


def test_unsupported_syntax_nested_and_assignment_ignored():
    a = one("pyautogui.locateCenterOnScreen('x.png')")
    assert a.kind == "note"
    assert "unsupported call" in a.note
    a = one("if True:\n    pyautogui.click(1, 2)\nelse:\n    pyautogui.click(3, 4)")
    assert (a.kind, a.x, a.y) == ("click", 1.0, 2.0)
    control, actions = parse_actions("x = pyautogui.click(1, 2)")
    assert control is None
    assert actions == []
    a = one("if")
    assert a.kind == "note"
    assert "could not parse code" in a.note


def test_positional_click_button_and_for_body_visited():
    a = one("pyautogui.click(10, 20, 2, 0, 'right')")
    assert (a.clicks, a.button) == (2, "right")
    a = one("for i in range(1):\n    pyautogui.press('escape')")
    assert (a.kind, a.keys) == ("press", ["escape"])
