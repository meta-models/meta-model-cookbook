import AppKit
import Foundation

/// Identifiers that mean "act on whatever app is already frontmost".
private let passthroughIdentifiers: Set<String> = ["current", "frontmost", "-", "active"]

/// Brings the named application to the front before events are posted.
///
/// `identifier` may be a bundle id (`com.apple.Safari`), an exact localized
/// name (`Safari`), or a case-insensitive substring of one. If the app is not
/// running, a launch is attempted via `open -a`. Returns once the app reports
/// itself active, or after a short timeout.
func activateApp(_ identifier: String) throws {
  if passthroughIdentifiers.contains(identifier.lowercased()) {
    return
  }

  var app = findRunningApp(identifier)
  if app == nil {
    try launchApp(identifier)
    // Poll for the freshly launched process to appear.
    let deadline = Date().addingTimeInterval(8.0)
    while app == nil && Date() < deadline {
      usleep(150_000)
      app = findRunningApp(identifier)
    }
  }

  guard let target = app else {
    throw CLIError("application not found and could not be launched: '\(identifier)'")
  }

  if #available(macOS 14.0, *) {
    target.activate()
  } else {
    target.activate(options: [.activateIgnoringOtherApps])
  }

  // Wait for the app to actually become frontmost so events land in it.
  let deadline = Date().addingTimeInterval(3.0)
  while !target.isActive && Date() < deadline {
    usleep(20_000)
  }
  usleep(120_000) // brief settle so the window is ready for input
}

private func findRunningApp(_ identifier: String) -> NSRunningApplication? {
  let needle = identifier.lowercased()
  let all = NSWorkspace.shared.runningApplications

  // Exact bundle id is an unambiguous, explicit selector — allow any policy.
  if let byBundle = all.first(where: { $0.bundleIdentifier?.lowercased() == needle }) {
    return byBundle
  }
  // Name / substring should resolve to a user-facing (.regular) app so a
  // background/accessory agent is never chosen as the activation target.
  let regular = all.filter { $0.activationPolicy == .regular }
  if let byName = regular.first(where: { $0.localizedName?.lowercased() == needle }) {
    return byName
  }
  return regular.first(where: { ($0.localizedName?.lowercased().contains(needle) ?? false) })
}

/// Heuristic: a reverse-DNS identifier (contains a dot, no spaces) is a bundle id.
private func looksLikeBundleID(_ identifier: String) -> Bool {
  identifier.contains(".") && !identifier.contains(" ")
}

private func launchApp(_ identifier: String) throws {
  let process = Process()
  process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
  // `open -a` takes an application NAME or path; bundle ids must use `-b`.
  process.arguments = looksLikeBundleID(identifier) ? ["-b", identifier] : ["-a", identifier]
  let pipe = Pipe()
  process.standardError = pipe
  do {
    try process.run()
  } catch {
    throw CLIError("failed to launch '\(identifier)': \(error.localizedDescription)")
  }
  process.waitUntilExit()
  if process.terminationStatus != 0 {
    throw CLIError(
      "application not found and could not be launched: '\(identifier)' "
        + "(launch requires an exact app name or bundle id)"
    )
  }
}
