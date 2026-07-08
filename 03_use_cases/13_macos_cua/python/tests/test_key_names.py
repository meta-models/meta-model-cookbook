import pytest

from metacua.errors import CLIError
from metacua.key_names import key_hold_components


def test_key_hold_components_splits_combo_in_order():
    assert key_hold_components("cmd+shift+a") == [0x37, 0x38, 0x00]
    assert key_hold_components(" control + option + return ") == [0x3B, 0x3A, 0x24]


def test_key_hold_components_rejects_bad_forms():
    with pytest.raises(CLIError):
        key_hold_components("cmd+")
    with pytest.raises(CLIError):
        key_hold_components("cmd++a")
    with pytest.raises(CLIError):
        key_hold_components("notakey")
