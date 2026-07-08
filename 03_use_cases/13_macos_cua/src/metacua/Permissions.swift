import ApplicationServices
import CoreGraphics
import Foundation

/// Whether the controlling process is trusted for Accessibility, which is
/// required for `CGEvent.post` to actually deliver synthetic events.
func isTrusted() -> Bool {
  AXIsProcessTrusted()
}

/// Whether the process can capture the screen (required for screenshots). On
/// macOS 11+ this reflects the Screen Recording privacy permission.
func hasScreenRecordingAccess() -> Bool {
  CGPreflightScreenCaptureAccess()
}

/// Returns true if screen capture is allowed; when `prompt` is true and it is
/// not yet allowed, asks the system to surface the Screen Recording dialog.
@discardableResult
func ensureScreenRecording(prompt: Bool) -> Bool {
  if CGPreflightScreenCaptureAccess() { return true }
  if prompt { return CGRequestScreenCaptureAccess() }
  return false
}

/// Throws a helpful error if Screen Recording permission has not been granted.
func requireScreenRecording() throws {
  guard ensureScreenRecording(prompt: false) else {
    throw CLIError(
      """
      Screen Recording permission is not granted, so screenshots would be \
      blank. Enable your terminal (or the metacua binary) under System Settings \
      → Privacy & Security → Screen Recording, then retry. \
      Run `metacua permissions --prompt` to open the system dialog.
      """,
      code: 3
    )
  }
}

/// Returns true if trusted. When `prompt` is true and not yet trusted, asks the
/// system to show the "grant Accessibility access" dialog.
@discardableResult
func ensureTrusted(prompt: Bool) -> Bool {
  if AXIsProcessTrusted() { return true }
  if prompt {
    // Key string is stable across SDKs; avoids Unmanaged<CFString> import quirks.
    let options = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
    return AXIsProcessTrustedWithOptions(options)
  }
  return false
}

/// Throws a helpful error if Accessibility permission has not been granted.
func requireTrust() throws {
  guard ensureTrusted(prompt: false) else {
    throw CLIError(
      """
      Accessibility permission is not granted, so synthetic events would be \
      silently dropped. Enable your terminal (or the metacua binary) under \
      System Settings → Privacy & Security → Accessibility, then retry. \
      Run `metacua permissions --prompt` to open the system dialog.
      """,
      code: 3
    )
  }
}

func runPermissions(_ raw: [String]) throws {
  let args = try Args(raw)
  let wantsPrompt = args.flag("prompt")

  let trusted = ensureTrusted(prompt: wantsPrompt)
  let screen = ensureScreenRecording(prompt: wantsPrompt)

  print(
    "Accessibility:    \(trusted ? "GRANTED" : "NOT granted") — needed to post mouse/keyboard events"
  )
  print(
    "Screen Recording: \(screen ? "GRANTED" : "NOT granted") — needed for the agent to take screenshots"
  )

  if !trusted || !screen {
    print("")
    print("Grant the missing permission(s) to your terminal (or the metacua binary) under")
    print("System Settings → Privacy & Security → {Accessibility, Screen Recording}.")
    if wantsPrompt {
      print("A system dialog was requested where possible; grant access, then re-run.")
    } else {
      print("Run `metacua permissions --prompt` to open the system dialog(s).")
    }
    exit(3)
  }
  print("\nAll set — `metacua agent` is ready to run.")
}
