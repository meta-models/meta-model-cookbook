"""Resolved configuration for the Muse Spark endpoint."""

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .args import Args
from .errors import CLIError
from .llm import CoordSpace

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.1"
DEFAULT_SCREENSHOT_SCALE = 1.0
DEFAULT_MAX_IMAGES = 5
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass
class AgentConfig:
    api_key: str
    base_url: str
    model: str
    coords: CoordSpace
    effort: str
    screenshot_scale: float
    max_images: int = DEFAULT_MAX_IMAGES
    allow_bash: bool = False
    batched_actions: bool = False
    syntax: str = "function"  # "function" (OpenAI tools) or "pyautogui" (OSWorld)


def metacua_home_url() -> Path:
    return Path.home() / ".metacua"


def normalize_syntax(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    low = raw.strip().lower()
    if low in ("pyautogui", "osworld", "pyauto"):
        return "pyautogui"
    if low in ("function", "tools", "functions"):
        return "function"
    return None


def _config_file_url() -> Path:
    return metacua_home_url() / "config.json"


def _legacy_config_file_urls() -> list:
    home = Path.home()
    return [
        home / ".config" / "metacua" / "config.json",
        home / ".config" / "gui-agent" / "config.json",
    ]


def _existing_config_file_url() -> Optional[Path]:
    primary = _config_file_url()
    if primary.exists():
        return primary
    for url in _legacy_config_file_urls():
        if url.exists():
            return url
    return None


def _load_config_file() -> Dict[str, str]:
    url = _existing_config_file_url()
    if url is None:
        return {}
    try:
        obj = json.loads(url.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(obj, dict):
        return {}
    return {k: v for k, v in obj.items() if isinstance(v, str)}


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    return value if value else None


def _normalize_base_url(url: str) -> str:
    normalized = url.strip()
    while normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def _parse_screenshot_scale(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise CLIError(f"screenshot scale must be > 0 and <= 1 (got '{raw}')", code=2)
    if not math.isfinite(value) or value <= 0 or value > 1:
        raise CLIError(f"screenshot scale must be > 0 and <= 1 (got '{raw}')", code=2)
    return value


def _parse_max_images(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise CLIError(f"max images must be >= 1 (got '{raw}')", code=2)
    if value < 1:
        raise CLIError(f"max images must be >= 1 (got '{raw}')", code=2)
    return value


def _parse_bool(raw: Optional[str], name: str) -> Optional[bool]:
    if raw is None:
        return None
    low = raw.strip().lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    raise CLIError(
        f"usage: {name} <true|false|yes|no|on|off|1|0>",
        code=2,
    )


def _parse_optional_bool_flag(args: Args, name: str, no_name: Optional[str] = None) -> Optional[bool]:
    if no_name is not None and (
        (args.flag(name) or args.string(name) is not None)
        and (args.flag(no_name) or args.string(no_name) is not None)
    ):
        raise CLIError(f"pass only one of --{name} or --{no_name}", code=2)
    if no_name is not None and args.flag(no_name):
        return False
    if no_name is not None and args.string(no_name) is not None:
        return _parse_bool(args.string(no_name), f"--{no_name}") is False
    if args.flag(name):
        return True
    value = args.string(name)
    if value is not None:
        return _parse_bool(value, f"--{name}")
    return None


def resolve_agent_config(args: Args) -> AgentConfig:
    """Resolve config with precedence: CLI flags -> environment -> config file -> defaults."""
    file = _load_config_file()

    api_key = (
        args.string("api-key")
        or _env("MODEL_API_KEY")
        or _env("MUSE_SPARK_API_KEY")
        or file.get("apiKey")
    )
    if not api_key:
        raise CLIError(
            "No API key found. Provide one via --api-key, MODEL_API_KEY / "
            "MUSE_SPARK_API_KEY, or `metacua configure --api-key <KEY>`.",
            code=2,
        )

    base_url = (
        args.string("base-url")
        or _env("LLM_BASE_URL")
        or _env("MUSE_SPARK_BASE_URL")
        or file.get("baseURL")
        or DEFAULT_BASE_URL
    )

    model = (
        args.string("model")
        or _env("LLM_MODEL")
        or _env("MUSE_SPARK_MODEL")
        or file.get("model")
        or DEFAULT_MODEL
    )

    raw_coords = args.string("coords") or file.get("coords")
    coords = (CoordSpace.parse(raw_coords) if raw_coords else None) or CoordSpace.NORMALIZED1000
    effort = (args.string("effort") or _env("LLM_EFFORT") or file.get("effort") or "high").lower()
    if effort not in VALID_EFFORTS:
        raise CLIError("usage: /effort <low|medium|high|xhigh|max>", code=2)
    screenshot_scale = (
        _parse_screenshot_scale(
            args.string("screenshot-scale")
            or _env("METACUA_SCREENSHOT_SCALE")
            or _env("LLM_SCREENSHOT_SCALE")
            or file.get("screenshotScale")
        )
        or DEFAULT_SCREENSHOT_SCALE
    )
    max_images = (
        _parse_max_images(
            args.string("max-images")
            or _env("METACUA_MAX_IMAGES")
            or _env("LLM_MAX_IMAGES")
            or file.get("maxImages")
        )
        or DEFAULT_MAX_IMAGES
    )

    raw_syntax = args.string("syntax") or _env("LLM_SYNTAX") or file.get("syntax")
    syntax = normalize_syntax(raw_syntax) or "function"

    allow_bash = False
    cli_allow_bash = _parse_optional_bool_flag(args, "allow-bash")
    env_allow_bash = _env("METACUA_ALLOW_BASH")
    if cli_allow_bash is not None:
        allow_bash = cli_allow_bash
    elif env_allow_bash is not None:
        allow_bash = _parse_bool(env_allow_bash, "METACUA_ALLOW_BASH") is True
    elif file.get("allowBash") is not None:
        allow_bash = _parse_bool(file.get("allowBash"), "allowBash") is True

    batched_actions = False
    cli_batched_actions = _parse_optional_bool_flag(
        args, "batched-actions", "no-batched-actions"
    )
    env_batched_actions = _env("METACUA_BATCHED_ACTIONS") or _env("LLM_BATCHED_ACTIONS")
    if cli_batched_actions is not None:
        batched_actions = cli_batched_actions
    elif env_batched_actions is not None:
        batched_actions = _parse_bool(env_batched_actions, "METACUA_BATCHED_ACTIONS") is True
    elif file.get("batchedActions") is not None:
        batched_actions = _parse_bool(file.get("batchedActions"), "batchedActions") is True

    return AgentConfig(
        api_key=api_key,
        base_url=_normalize_base_url(base_url),
        model=model,
        coords=coords,
        effort=effort,
        screenshot_scale=screenshot_scale,
        max_images=max_images,
        allow_bash=allow_bash,
        batched_actions=batched_actions,
        syntax=syntax,
    )


def run_configure(raw) -> None:
    """`metacua configure` - persist endpoint, key, and model settings to the config file."""
    args = Args(raw)
    file = _load_config_file()

    if args.string("api-key"):
        file["apiKey"] = args.string("api-key")
    if args.string("base-url"):
        file["baseURL"] = _normalize_base_url(args.string("base-url"))
    if args.string("model"):
        file["model"] = args.string("model")
    if args.string("coords"):
        file["coords"] = args.string("coords")
    if args.string("effort"):
        file["effort"] = args.string("effort")
    scale = _parse_screenshot_scale(args.string("screenshot-scale"))
    if scale is not None:
        file["screenshotScale"] = str(scale)
    max_images = _parse_max_images(args.string("max-images"))
    if max_images is not None:
        file["maxImages"] = str(max_images)
    if args.string("syntax"):
        syntax = normalize_syntax(args.string("syntax"))
        if syntax is None:
            raise CLIError("--syntax must be function|pyautogui", code=2)
        file["syntax"] = syntax
    if args.flag("allow-bash"):
        raise CLIError("--allow-bash must be true|false", code=2)
    allow_bash = _parse_bool(args.string("allow-bash"), "--allow-bash")
    if allow_bash is not None:
        file["allowBash"] = "true" if allow_bash else "false"
    batched_actions = _parse_optional_bool_flag(args, "batched-actions", "no-batched-actions")
    if batched_actions is not None:
        file["batchedActions"] = "true" if batched_actions else "false"

    if not file:
        raise CLIError(
            "nothing to save - pass --api-key, --base-url, --model, --coords, --effort, "
            "--screenshot-scale, --max-images, --syntax, --allow-bash, and/or "
            "--batched-actions",
            code=2,
        )

    url = _config_file_url()
    url.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(url.parent, 0o700)
    data = json.dumps(file, indent=2, sort_keys=True)
    url.write_text(data)
    os.chmod(url, 0o600)

    shown_key = f"set ({len(file['apiKey'])} chars)" if file.get("apiKey") else "not set"
    print(f"Saved config to {url}")
    print(f"  baseURL: {file.get('baseURL', DEFAULT_BASE_URL)}")
    print(f"  model:   {file.get('model', DEFAULT_MODEL)}")
    print(f"  coords:  {file.get('coords', 'normalized')}")
    print(f"  effort:  {file.get('effort', 'high')}")
    print(f"  scale:   {file.get('screenshotScale', str(DEFAULT_SCREENSHOT_SCALE))}")
    print(f"  images:  {file.get('maxImages', str(DEFAULT_MAX_IMAGES))}")
    print(f"  syntax:  {file.get('syntax', 'function')}")
    print(f"  bash:    {file.get('allowBash', 'false')}")
    print(f"  batch:   {file.get('batchedActions', 'false')}")
    print(f"  apiKey:  {shown_key}")
