import pytest

from metacua.args import Args
from metacua.errors import CLIError


def test_string_flag_forms_and_boolean_flags():
    args = Args(["--model", "m", "--base-url=https://example.test", "--overlay"])
    assert args.string("model") == "m"
    assert args.string("base-url") == "https://example.test"
    assert args.flag("overlay") is True
    assert args.string("overlay") is None


def test_unknown_positional_raises_code_2():
    with pytest.raises(CLIError) as exc:
        Args(["positional"])
    assert exc.value.code == 2


def test_int_and_double_validation_errors():
    with pytest.raises(CLIError) as exc:
        Args(["--n", "nope"]).int("n")
    assert exc.value.code == 2
    with pytest.raises(CLIError) as exc:
        Args(["--x", "nan"]).double("x")
    assert exc.value.code == 2


def test_flag_followed_by_value_gotcha_is_value_not_flag():
    args = Args(["--overlay", "true"])
    assert args.flag("overlay") is False
    assert args.string("overlay") == "true"
