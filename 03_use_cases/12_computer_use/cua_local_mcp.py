#!/usr/bin/env python3
"""Local MCP bridge from an MCP client (such as OpenCode) to a Cua Docker sandbox.

Cua's built-in `cua serve-mcp` resolves cloud sandboxes only. This bridge talks
directly to a local container's computer-server, so it works with a sandbox
launched by `cua sandbox launch --local`.

Configuration comes from one environment variable:

    CUA_CMD_URL   the container's computer-server /cmd endpoint
                  (default http://127.0.0.1:8000/cmd)

Run it as a stdio MCP server:

    python cua_local_mcp.py
"""

import base64
import json
import os
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

CMD_URL = os.environ.get("CUA_CMD_URL", "http://127.0.0.1:8000/cmd")

server = FastMCP(name="cua-local")


def _cmd(command: str, params: dict | None = None) -> dict:
    resp = requests.post(
        CMD_URL, json={"command": command, "params": params or {}}, timeout=60
    )
    # The computer-server streams its reply as SSE: lines that start with "data: ".
    for line in resp.text.split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    return {"success": False, "error": f"no data in response: {resp.text[:200]}"}


@server.tool()
def screenshot() -> Any:
    """Take a screenshot of the desktop. Returns a PNG image."""
    r = _cmd("screenshot")
    if r.get("success") and r.get("image_data"):
        return Image(format="png", data=base64.b64decode(r["image_data"]))
    return json.dumps(r)


@server.tool()
def get_screen_size() -> str:
    """Get the screen dimensions (width, height) in pixels."""
    return json.dumps(_cmd("get_screen_size"))


@server.tool()
def left_click(x: int, y: int) -> str:
    """Left-click at pixel coordinates (x, y) in screenshot image space."""
    return json.dumps(_cmd("left_click", {"x": x, "y": y}))


@server.tool()
def double_click(x: int, y: int) -> str:
    """Double-click at pixel coordinates (x, y)."""
    return json.dumps(_cmd("double_click", {"x": x, "y": y}))


@server.tool()
def right_click(x: int, y: int) -> str:
    """Right-click at pixel coordinates (x, y)."""
    return json.dumps(_cmd("right_click", {"x": x, "y": y}))


@server.tool()
def move_cursor(x: int, y: int) -> str:
    """Move the mouse cursor to (x, y) without clicking."""
    return json.dumps(_cmd("move_cursor", {"x": x, "y": y}))


@server.tool()
def type_text(text: str) -> str:
    """Type a string of text on the keyboard."""
    return json.dumps(_cmd("type_text", {"text": text}))


@server.tool()
def press_key(key: str) -> str:
    """Press a single key, such as 'enter', 'tab', 'escape', or 'BackSpace'."""
    return json.dumps(_cmd("press_key", {"key": key}))


@server.tool()
def hotkey(keys: str) -> str:
    """Press a keyboard shortcut. Join keys with '+', such as 'ctrl+c'."""
    key_list = keys.replace("-", "+").split("+")
    return json.dumps(_cmd("hotkey", {"keys": key_list}))


@server.tool()
def scroll(direction: str = "down", clicks: int = 3) -> str:
    """Scroll the screen. direction is one of up, down, left, right."""
    return json.dumps(
        _cmd("scroll_direction", {"direction": direction, "clicks": clicks})
    )


@server.tool()
def open_path(path: str) -> str:
    """Open a file or URL with the default handler (xdg-open)."""
    return json.dumps(_cmd("open", {"path": path}))


@server.tool()
def run_command(command: str) -> str:
    """Run a shell command in the sandbox; returns stdout, stderr, and return_code.

    Use this to launch GUI apps in the background, such as
    run_command("gnome-calculator &").
    """
    return json.dumps(_cmd("run_command", {"command": command}))


if __name__ == "__main__":
    server.run()
