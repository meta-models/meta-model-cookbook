import pytest

Quartz = pytest.importorskip("Quartz")

from metacua.errors import CLIError
from metacua.keyboard import parse_key_combo


def test_parse_key_combo_basic_and_plus():
    code, flags = parse_key_combo("cmd+shift+a")
    assert code == 0x00
    assert flags & Quartz.kCGEventFlagMaskCommand
    assert flags & Quartz.kCGEventFlagMaskShift
    code, flags = parse_key_combo("plus")
    assert code == 0x18
    assert flags & Quartz.kCGEventFlagMaskShift


def test_parse_key_combo_rejects_bad_forms():
    with pytest.raises(CLIError):
        parse_key_combo("cmd+")
    with pytest.raises(CLIError):
        parse_key_combo("cmd+shift")
    with pytest.raises(CLIError):
        parse_key_combo("a+b")
