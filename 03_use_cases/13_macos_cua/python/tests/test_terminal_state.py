from metacua.terminal_state import StopClassification, classify_stop_answer, is_stop_tool_name


def test_classify_stop_answer_infeasible_words():
    assert classify_stop_answer("This is infeasible.")[0] == StopClassification.INFEASIBLE
    assert classify_stop_answer("unfeasible safely")[0] == StopClassification.INFEASIBLE
    assert classify_stop_answer("I completed it.")[0] == StopClassification.SUCCESS


def test_classify_stop_answer_messages():
    assert classify_stop_answer("done")[1] == "done: done"
    assert classify_stop_answer("infeasible")[1] == "task infeasible: infeasible"


def test_is_stop_tool_name_aliases():
    assert is_stop_tool_name("computer.stop")
    assert is_stop_tool_name("computer_stop")
    assert is_stop_tool_name("stop")
    assert not is_stop_tool_name("computer.computer")
