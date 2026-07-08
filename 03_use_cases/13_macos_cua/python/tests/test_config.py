import pytest

from metacua.args import Args
from metacua.config import (
    _normalize_base_url,
    _parse_max_images,
    _parse_screenshot_scale,
    normalize_syntax,
    resolve_agent_config,
)
from metacua.errors import CLIError


def test_normalize_syntax():
    assert normalize_syntax("osworld") == "pyautogui"
    assert normalize_syntax("pyauto") == "pyautogui"
    assert normalize_syntax("tools") == "function"
    assert normalize_syntax("nope") is None
    assert normalize_syntax(None) is None


def test_normalize_base_url():
    assert _normalize_base_url(" https://example.test///") == "https://example.test"


def test_parse_screenshot_scale_bounds():
    assert _parse_screenshot_scale(None) is None
    assert _parse_screenshot_scale("0.5") == 0.5
    for raw in ["0", "-1", "1.1", "nan", "bad"]:
        with pytest.raises(CLIError):
            _parse_screenshot_scale(raw)


def test_parse_max_images_bounds():
    assert _parse_max_images(None) is None
    assert _parse_max_images("1") == 1
    assert _parse_max_images("5") == 5
    for raw in ["0", "-1", "bad"]:
        with pytest.raises(CLIError):
            _parse_max_images(raw)


def test_effort_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "key")
    cfg = resolve_agent_config(Args(["--effort", "xhigh"]))
    assert cfg.effort == "xhigh"
    with pytest.raises(CLIError) as exc:
        resolve_agent_config(Args(["--effort", "turbo"]))
    assert exc.value.code == 2


def test_allow_bash_agent_flag_forms(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "key")

    assert resolve_agent_config(Args(["--allow-bash"])).allow_bash is True
    assert resolve_agent_config(Args(["--allow-bash", "true"])).allow_bash is True
    assert resolve_agent_config(Args(["--allow-bash", "false"])).allow_bash is False


def test_allow_bash_agent_invalid_value_raises_code_2(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "key")

    with pytest.raises(CLIError) as exc:
        resolve_agent_config(Args(["--allow-bash", "maybe"]))
    assert exc.value.code == 2
    assert "usage: --allow-bash" in exc.value.message


def test_batched_actions_agent_flag_env_and_file_forms(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "key")

    assert resolve_agent_config(Args(["--batched-actions"])).batched_actions is True
    assert resolve_agent_config(Args(["--batched-actions", "true"])).batched_actions is True
    assert resolve_agent_config(Args(["--batched-actions", "false"])).batched_actions is False
    assert resolve_agent_config(Args(["--no-batched-actions"])).batched_actions is False

    monkeypatch.setenv("METACUA_BATCHED_ACTIONS", "on")
    assert resolve_agent_config(Args([])).batched_actions is True
    monkeypatch.delenv("METACUA_BATCHED_ACTIONS")
    monkeypatch.setenv("LLM_BATCHED_ACTIONS", "yes")
    assert resolve_agent_config(Args([])).batched_actions is True


def test_batched_actions_conflicting_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "key")

    with pytest.raises(CLIError) as exc:
        resolve_agent_config(Args(["--batched-actions", "--no-batched-actions"]))
    assert exc.value.code == 2


def test_max_images_agent_flag_and_env_forms(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "key")

    assert resolve_agent_config(Args([])).max_images == 5
    assert resolve_agent_config(Args(["--max-images", "7"])).max_images == 7

    monkeypatch.setenv("METACUA_MAX_IMAGES", "9")
    assert resolve_agent_config(Args([])).max_images == 9
    monkeypatch.delenv("METACUA_MAX_IMAGES")
    monkeypatch.setenv("LLM_MAX_IMAGES", "11")
    assert resolve_agent_config(Args([])).max_images == 11
