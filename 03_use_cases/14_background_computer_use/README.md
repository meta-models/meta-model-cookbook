# Background computer use with Muse models and Cua Driver

| | |
|---|---|
| **Section** | [Use cases](../README.md) |
| **Model** | `muse-spark-1.3` for the API walkthrough; optional local Muse setup |
| **Harness** | OpenCode + Cua Driver MCP |
| **Platforms** | macOS, Windows, and Linux, subject to the app and window-system limits below |

Give Muse a task in a desktop app while you keep another app active. This recipe
connects OpenCode to [Cua Driver](https://github.com/trycua/cua/tree/main/libs/cua-driver),
which supplies window screenshots, accessibility state, and targeted actions.
The exercise is small: calculate `6 * 7` in an already-open calculator and verify
its display without bringing it forward.

The integration separates the model from desktop control:

```text
Muse model -> agent harness -> Cua Driver MCP -> target desktop app
```

The main walkthrough uses Muse Spark through the Meta API. You can also use a
compatible local Muse model and harness; see [Local models](#local-models).
Changing the model does not change the driver's platform constraints.

Unlike the [Cua sandbox recipe](../12_computer_use/README.md), this recipe operates
the desktop session where Cua Driver runs. A virtual machine can provide that
desktop, but background delivery itself is not a sandbox.

## What background means

Cua Driver defaults to best-effort background delivery: it attempts to preserve
the user's frontmost app, window order, and real mouse pointer while acting on a
target window. Accessibility actions and window-specific capture can work even
when the target is occluded. Some apps reject background input. Treat those
cases as limitations, not as successful automation.

For this exercise, do not escalate to foreground input. A successful calculation
after taking focus does not prove background computer use. An agent cursor
overlay is separate from the real pointer and does not by itself prove that the
real pointer stayed unchanged.

See the [background contract](https://cua.ai/docs/concepts/the-no-foreground-contract)
and [platform support](https://cua.ai/docs/reference/cua-driver/platform-support).

## Before you start

You need OpenCode with the Meta provider, a Meta API key, an interactive desktop,
and an installed calculator. Use Calculator on macOS or Windows, or a desktop
calculator such as GNOME Calculator on Linux. Keep the exercise in a session
containing only data you intend the model to see. Screenshots and accessibility
content passed to Muse Spark leave the machine for API inference.

The commands below use Cua Driver's default authorization mode. That mode can
reach applications across the desktop; the task prompt is not an access-control
boundary. For an enforced application allowlist, configure a
[bounded runtime](https://cua.ai/docs/how-to-guides/driver/write-a-bounded-manifest).

## 1. Install Cua Driver in the target desktop

Run installation and setup in the session the agent will operate. If the target
is a VM, run the driver there rather than controlling its viewer window.

### macOS

Requires macOS 14 or later on Apple Silicon or Intel. Install and start the app:

```bash
/bin/bash -c "$(curl -fsSL https://cua.ai/driver/install.sh)"
open -n -g -a CuaDriver --args serve
cua-driver permissions grant
```

Enable Accessibility and Screen Recording for CuaDriver in System Settings.
Accept a requested app restart, then check the grants:

```bash
cua-driver permissions status
```

### Windows

Requires Windows 10/11 or Windows Server with an interactive desktop. Run in
PowerShell in that user's desktop session:

```powershell
irm https://cua.ai/driver/install.ps1 | iex
cua-driver autostart kick
```

Open a new PowerShell window if the installed command is not on PATH. If the
autostart task could not be registered, run `cua-driver serve` in a desktop
terminal and leave it open. A service or SSH process outside the interactive
desktop is not equivalent to this setup.

### Linux distributions and display sessions

Requires an x86_64 desktop, a display server, and AT-SPI 2. Start with an X11
session for this walkthrough. Run the driver from a terminal in the logged-in
desktop so it inherits the display and accessibility bus.

On a minimal Debian or Ubuntu installation, install the runtime dependencies:

```bash
sudo apt install libxi6 at-spi2-core
```

On other distributions, install the packages providing `libXi.so.6` and AT-SPI 2
through that distribution's package manager. A distribution name alone does not
identify the desktop or display server: record those separately. Then install:

```bash
/bin/bash -c "$(curl -fsSL https://cua.ai/driver/install.sh)"
cua-driver serve
```

Leave the daemon terminal open and use a second terminal for the following steps.
The [installation guide](https://cua.ai/docs/how-to-guides/driver/install) covers
PATH setup and additional environment requirements.

| Linux session | Background behavior and limits |
|---|---|
| X11/Xorg | Semantic AT-SPI actions and window-targeted routes are available. Raw background events remain toolkit-dependent. |
| XWayland app on Wayland | X11 routes require a real X11 window for that app; do not assume every native Wayland app has one. |
| Native Wayland | Opt-in backend with compositor-specific prerequisites. Semantic actions may work; arbitrary raw background keyboard input is not generally available. |
| Sway, GNOME, KDE, Hyprland | Each has a separate support entry. Do not infer support in one compositor from another. |

For native Wayland, follow the exact environment setup in
[Linux platform support](https://cua.ai/docs/reference/cua-driver/platform-support#linux-window-systems)
before attempting this exercise. The distinction between a distribution, desktop,
and compositor is explained in
[Linux desktops and computer use](https://cua.ai/docs/concepts/linux-desktops-and-computer-use).

### Check desktop access

On every platform, run:

```bash
cua-driver --version
cua-driver status
cua-driver doctor
cua-driver call list_apps
```

Read the diagnostic warnings, not just the exit code. Confirm that the driver can
see an app in the intended desktop. Resolve missing permissions, display access,
or accessibility services before connecting the model. The installer reports
the driver's telemetry defaults; see
[telemetry and privacy](https://cua.ai/docs/reference/cua-driver/telemetry).

## 2. Connect Muse Spark and the driver to OpenCode

Install [OpenCode](https://opencode.ai) if needed. In OpenCode, run `/connect`,
select **Meta**, and enter your API key through its credential prompt. Keep the
key out of repository files. This follows the provider setup in the
[existing computer-use recipe](../12_computer_use/README.md).

Generate the Cua Driver configuration on the target machine:

```bash
cua-driver mcp-config --client opencode
```

Apply the generated configuration to OpenCode, preserving any existing entries.
Use the generated absolute executable path so an app-launched harness does not
depend on your interactive shell's PATH. The underlying server command is
`cua-driver mcp`; it preserves screenshots as MCP image blocks. No custom
`computer-server` bridge is needed.

Start a new OpenCode session:

```bash
opencode -m meta/muse-spark-1.3
```

Use `/mcp` to confirm the driver is connected. Confirm that the selected model is
Muse Spark 1.3. Keep other computer-control integrations disabled for this
exercise so the task's tool route is unambiguous.

## 3. Prepare the background exercise

Open the calculator yourself before the measured task. App launch can raise a
window, so it is deliberately outside the background interaction being tested.
Clear the calculator and leave it open, not minimized. Bring OpenCode or a
scratch editor to the foreground, partially covering the calculator, and place
the real pointer away from the calculator's controls.

Submit this prompt, then leave the foreground app active while the agent works:

```text
Use only the Cua Driver MCP tools for desktop interaction. Start a driver
session and discover the already-open calculator from fresh app/window state.
Do not launch another app. Calculate 6 * 7 in that calculator and verify its
display from a fresh window snapshot. Do not answer from arithmetic alone.

Keep every action in background delivery mode. Do not activate, raise, or move
windows, switch apps, or use foreground or desktop-wide input. If an action
cannot work in the background, stop and report the limitation.

Take fresh target-window state before and after each action. Prefer accessible
controls when available; otherwise use coordinates from that window's fresh
screenshot. Use only the pid, window_id, and element references returned by
current state. Bound accessibility reads to max_elements=25 and max_depth=3
unless more detail is necessary. Do not use shell commands or another computer
tool to perform the calculation. End the driver session when finished.

Report the observed calculator value, the action route, and any refusal or
unverifiable effect. Do not claim focus or pointer preservation unless observed.
```

If OpenCode asks you to approve tool use, review the request. Establish the
foreground baseline again after interacting with an approval prompt; distinguish
your own focus changes from driver-caused changes.

## 4. Verify the result and the background behavior

A passing run has two independent outcomes:

1. Fresh calculator state shows **42** after the agent used the calculator's
   controls. The model's final answer alone is insufficient.
2. During those actions, the foreground app keeps focus, the target is not
   raised, the real pointer is not moved by the driver, and no calculator input
   lands in the foreground app.

For a reproducible demonstration, record the desktop and retain the action
evidence using [Cua Driver recording](https://cua.ai/docs/how-to-guides/driver/record-and-render-a-trajectory).
Review the complete interaction, not just the final frame. Keep any typing in a
synthetic scratch document and verify that it received only your intended text.
Do not publish API keys, unrelated windows, or personal content in recordings.

Record the model identifier, OpenCode and Driver versions, OS version, calculator
version, and the observed result. On Linux, also record the distribution, desktop,
X11/Wayland session, compositor when applicable, and whether the app uses XWayland.
A successful run on one combination does not certify the others.

## Local models

Cua Driver is independent of the inference provider. A different model needs
image input and tool calling, and its harness must retain MCP image blocks.
Verify each model/runtime/harness combination rather than assuming compatibility.

The existing [local Muse guide](https://cua.ai/docs/how-to-guides/driver/run-with-local-model)
documents Muse Glimmer 30B with llama.cpp, Claude Code, and Cua Driver in a macOS
Lume guest, plus an Ollama setup path. Its recorded Notes and Reminders examples
are separate from this Spark walkthrough. It also shows how to reduce context
growth with a filtered tool catalog and bounded accessibility reads. A schema
filter reduces model context; it is not a permission boundary.

## Troubleshooting

- **Tools connect but the model cannot see screenshots:** preserve MCP image
  blocks; do not flatten results through a text-only shell wrapper.
- **An action reports dispatch but nothing changes:** read fresh app state. A
  dispatched event does not establish an app-visible effect.
- **The calculator requires focus:** report the app/platform limitation. An
  explicitly authorized foreground retry is a different exercise.
- **Context grows quickly:** use target-window snapshots, bounded accessibility
  reads, and only the tools the task needs.
- **Linux behavior differs between machines:** compare the toolkit, display
  server, and compositor as well as the distribution. See the platform matrix
  before changing input modes.

## Sources

This walkthrough draws on Cua's [first-app tutorial](https://cua.ai/docs/tutorials/drive-your-first-app),
[agent integration guide](https://cua.ai/docs/how-to-guides/driver/connect-your-agent),
and [action policy](https://cua.ai/docs/reference/cua-driver/action-selection-policy).
The existing cookbook [Linux sandbox](../12_computer_use/README.md) and
[macOS metacua](../13_macos_cua/README.md) recipes provide alternative architectures.
