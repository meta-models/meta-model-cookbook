import AppKit
import Darwin
import Foundation

final class TerminalAttention {
  private let terminalApp: NSRunningApplication?
  private let enabled: Bool

  init(enabled: Bool = isatty(STDOUT_FILENO) == 1) {
    self.enabled = enabled
    terminalApp = enabled ? TerminalAttention.findLaunchingTerminalApp() : nil
  }

  @discardableResult
  func wake() -> Bool {
    guard enabled else { return false }
    FileHandle.standardOutput.write(Data("\u{7}".utf8))
    guard let terminalApp else { return false }

    let activate = {
      if #available(macOS 14.0, *) {
        _ = terminalApp.activate()
      } else {
        _ = terminalApp.activate(options: [.activateIgnoringOtherApps])
      }
    }

    if Thread.isMainThread {
      activate()
    } else {
      DispatchQueue.main.async(execute: activate)
    }
    return true
  }

  @discardableResult
  func moveAside() -> Bool {
    guard enabled, let terminalApp else { return false }

    let hide = {
      _ = terminalApp.hide()
    }

    if Thread.isMainThread {
      hide()
    } else {
      DispatchQueue.main.async(execute: hide)
    }
    return true
  }

  private static func findLaunchingTerminalApp() -> NSRunningApplication? {
    var pid = getppid()
    var seen: Set<pid_t> = []

    while pid > 1 && !seen.contains(pid) {
      seen.insert(pid)
      if let app = NSRunningApplication(processIdentifier: pid), app.activationPolicy == .regular {
        return app
      }
      guard let parent = parentProcessID(of: pid), parent != pid else { break }
      pid = parent
    }

    return fallbackTerminalApp()
  }

  private static func parentProcessID(of pid: pid_t) -> pid_t? {
    var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, pid]
    var info = kinfo_proc()
    var size = MemoryLayout<kinfo_proc>.stride
    let result = sysctl(&mib, u_int(mib.count), &info, &size, nil, 0)
    guard result == 0, size > 0 else { return nil }
    return info.kp_eproc.e_ppid
  }

  private static func fallbackTerminalApp() -> NSRunningApplication? {
    let candidates = terminalAppNameCandidates()
    return NSWorkspace.shared.runningApplications.first { app in
      guard app.activationPolicy == .regular, let name = app.localizedName else { return false }
      return candidates.contains(name)
    }
  }

  private static func terminalAppNameCandidates() -> Set<String> {
    switch ProcessInfo.processInfo.environment["TERM_PROGRAM"] {
    case "Apple_Terminal":
      return ["Terminal"]
    case "iTerm.app":
      return ["iTerm", "iTerm2"]
    case "vscode":
      return ["Visual Studio Code", "VS Code", "VS Code @ FB"]
    case "WezTerm":
      return ["WezTerm"]
    case "WarpTerminal":
      return ["Warp"]
    default:
      return ["Terminal", "iTerm", "iTerm2", "Visual Studio Code", "VS Code", "VS Code @ FB"]
    }
  }
}
