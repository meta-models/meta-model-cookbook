import AppKit
import CoreGraphics
import Foundation

/// ANSI US-layout virtual key codes, keyed by lower-cased name/alias. These
/// hardware codes are stable regardless of the active input source; the active
/// layout only affects which character the code produces, which is irrelevant
/// for shortcuts (cmd+c is the physical "c" key with the command flag).
private let keyCodes: [String: CGKeyCode] = {
  var m: [String: CGKeyCode] = [:]

  // Letters.
  let letters: [(String, CGKeyCode)] = [
    ("a", 0x00), ("s", 0x01), ("d", 0x02), ("f", 0x03), ("h", 0x04),
    ("g", 0x05), ("z", 0x06), ("x", 0x07), ("c", 0x08), ("v", 0x09),
    ("b", 0x0B), ("q", 0x0C), ("w", 0x0D), ("e", 0x0E), ("r", 0x0F),
    ("y", 0x10), ("t", 0x11), ("o", 0x1F), ("u", 0x20), ("i", 0x22),
    ("p", 0x23), ("l", 0x25), ("j", 0x26), ("k", 0x28), ("n", 0x2D),
    ("m", 0x2E),
  ]
  for (k, v) in letters { m[k] = v }

  // Digit row.
  let digits: [(String, CGKeyCode)] = [
    ("1", 0x12), ("2", 0x13), ("3", 0x14), ("4", 0x15), ("5", 0x17),
    ("6", 0x16), ("7", 0x1A), ("8", 0x1C), ("9", 0x19), ("0", 0x1D),
  ]
  for (k, v) in digits { m[k] = v }

  // Punctuation (named + symbol aliases).
  let punctuation: [(String, CGKeyCode)] = [
    ("=", 0x18), ("equal", 0x18), ("equals", 0x18),
    ("-", 0x1B), ("minus", 0x1B),
    ("]", 0x1E), ("rightbracket", 0x1E),
    ("[", 0x21), ("leftbracket", 0x21),
    ("'", 0x27), ("quote", 0x27), ("apostrophe", 0x27),
    (";", 0x29), ("semicolon", 0x29),
    ("\\", 0x2A), ("backslash", 0x2A),
    (",", 0x2B), ("comma", 0x2B),
    ("/", 0x2C), ("slash", 0x2C),
    (".", 0x2F), ("period", 0x2F), ("dot", 0x2F),
    ("`", 0x32), ("grave", 0x32), ("backtick", 0x32), ("tilde", 0x32),
  ]
  for (k, v) in punctuation { m[k] = v }

  // Named keys.
  let named: [(String, CGKeyCode)] = [
    ("return", 0x24), ("enter", 0x24), ("\n", 0x24),
    ("tab", 0x30), ("\t", 0x30),
    ("space", 0x31), ("spacebar", 0x31), (" ", 0x31),
    ("delete", 0x33), ("backspace", 0x33), ("bksp", 0x33),
    ("escape", 0x35), ("esc", 0x35),
    ("forwarddelete", 0x75), ("forward-delete", 0x75), ("fwddelete", 0x75), ("del", 0x75),
    ("keypadenter", 0x4C), ("kpenter", 0x4C),
    ("capslock", 0x39),
    ("help", 0x72), ("insert", 0x72),
    ("home", 0x73), ("end", 0x77),
    ("pageup", 0x74), ("pgup", 0x74),
    ("pagedown", 0x79), ("pgdn", 0x79), ("pagedn", 0x79),
    ("left", 0x7B), ("leftarrow", 0x7B),
    ("right", 0x7C), ("rightarrow", 0x7C),
    ("down", 0x7D), ("downarrow", 0x7D),
    ("up", 0x7E), ("uparrow", 0x7E),
  ]
  for (k, v) in named { m[k] = v }

  // Function keys F1–F20.
  let functionKeys: [(String, CGKeyCode)] = [
    ("f1", 0x7A), ("f2", 0x78), ("f3", 0x63), ("f4", 0x76),
    ("f5", 0x60), ("f6", 0x61), ("f7", 0x62), ("f8", 0x64),
    ("f9", 0x65), ("f10", 0x6D), ("f11", 0x67), ("f12", 0x6F),
    ("f13", 0x69), ("f14", 0x6B), ("f15", 0x71), ("f16", 0x6A),
    ("f17", 0x40), ("f18", 0x4F), ("f19", 0x50), ("f20", 0x5A),
  ]
  for (k, v) in functionKeys { m[k] = v }

  return m
}()

private func modifierFlag(_ name: String) -> CGEventFlags? {
  switch name {
  case "cmd", "command", "meta", "super", "win", "⌘": return .maskCommand
  case "shift", "⇧": return .maskShift
  case "ctrl", "control", "ctl", "⌃": return .maskControl
  case "opt", "option", "alt", "⌥": return .maskAlternate
  case "fn", "function": return .maskSecondaryFn
  default: return nil
  }
}

private let modifierKeyCodes: [String: CGKeyCode] = [
  "cmd": 0x37, "command": 0x37, "meta": 0x37, "super": 0x37, "win": 0x37, "⌘": 0x37,
  "shift": 0x38, "⇧": 0x38,
  "ctrl": 0x3B, "control": 0x3B, "ctl": 0x3B, "⌃": 0x3B,
  "opt": 0x3A, "option": 0x3A, "alt": 0x3A, "⌥": 0x3A,
  "fn": 0x3F, "function": 0x3F,
]

/// Parse a combo like `cmd+shift+a` into a base key code plus modifier flags.
///
/// Components are joined with `+`. A stray or trailing `+` (e.g. `cmd+` or
/// `cmd++`) is rejected rather than silently producing the wrong keystroke — to
/// press the literal plus key use `shift+=` or the name `plus`.
func parseKeyCombo(_ raw: String) throws -> (code: CGKeyCode, flags: CGEventFlags) {
  let trimmed = raw.trimmingCharacters(in: .whitespaces)
  guard !trimmed.isEmpty else { throw CLIError("--key is empty", code: 2) }

  let parts = trimmed.split(separator: "+", omittingEmptySubsequences: false).map {
    String($0).trimmingCharacters(in: .whitespaces).lowercased()
  }

  var flags: CGEventFlags = []
  var baseKey: String?

  for part in parts {
    guard !part.isEmpty else {
      throw CLIError(
        "malformed key combo '\(raw)': stray or trailing '+'. "
          + "To press the plus key use 'shift+=' or 'plus'.",
        code: 2
      )
    }
    if let flag = modifierFlag(part) {
      flags.insert(flag)
      continue
    }
    if baseKey != nil {
      throw CLIError("multiple non-modifier keys in '\(raw)' (only one allowed)", code: 2)
    }
    baseKey = part
  }

  guard let base = baseKey else {
    throw CLIError("no key specified in '\(raw)' (modifiers only)", code: 2)
  }

  // "plus" is the shifted '=' key.
  if base == "plus" {
    flags.insert(.maskShift)
    return (0x18, flags)
  }
  guard let code = keyCodes[base] else {
    throw CLIError("unknown key '\(base)' in '\(raw)'", code: 2)
  }
  return (code, flags)
}

/// Press and release a key code with the given modifier flags held.
func performKeyCombo(code: CGKeyCode, flags: CGEventFlags, source: CGEventSource?) {
  let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true)
  down?.flags = flags
  down?.post(tap: .cghidEventTap)
  usleep(12_000)

  let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false)
  up?.flags = flags
  up?.post(tap: .cghidEventTap)
  usleep(8_000)
}

func performKeyDown(_ raw: String, source: CGEventSource?) throws {
  for key in try keyHoldComponents(raw) {
    let down = CGEvent(keyboardEventSource: source, virtualKey: key, keyDown: true)
    down?.post(tap: .cghidEventTap)
    usleep(8_000)
  }
}

func performKeyUp(_ raw: String, source: CGEventSource?) throws {
  for key in try keyHoldComponents(raw).reversed() {
    let up = CGEvent(keyboardEventSource: source, virtualKey: key, keyDown: false)
    up?.post(tap: .cghidEventTap)
    usleep(8_000)
  }
}

private func keyHoldComponents(_ raw: String) throws -> [CGKeyCode] {
  let parts = raw.split(separator: "+", omittingEmptySubsequences: false).map {
    String($0).trimmingCharacters(in: .whitespaces).lowercased()
  }
  guard !parts.isEmpty, parts.allSatisfy({ !$0.isEmpty }) else {
    throw CLIError("malformed key hold '\(raw)'", code: 2)
  }
  return try parts.map { part in
    if let code = modifierKeyCodes[part] ?? keyCodes[part] {
      return code
    }
    throw CLIError("unknown key '\(part)' in '\(raw)'", code: 2)
  }
}

/// Insert literal text into the focused field without synthesizing one keyboard event per character.
func performTypeText(_ text: String, source: CGEventSource?) throws {
  let pasteboard = NSPasteboard.general
  let savedItems = SavedPasteboard.capture(from: pasteboard)

  pasteboard.clearContents()
  guard pasteboard.setString(text, forType: .string) else {
    savedItems.restore(to: pasteboard)
    throw CLIError("failed to stage text on the pasteboard")
  }

  usleep(80_000)
  performKeyCombo(code: 0x09, flags: [.maskCommand], source: source) // Command-V.
  usleep(pasteboardRestoreDelayMicros(for: text))
  savedItems.restore(to: pasteboard)
}

private func pasteboardRestoreDelayMicros(for text: String) -> useconds_t {
  let bytes = text.utf8.count
  let hasMultilineContent = text.contains("\n") || text.contains("\r")
  let minimum = hasMultilineContent || bytes > 200 ? 1_000_000 : 250_000
  let scaled = 120_000 + min(1_880_000, bytes * 1_000)
  return useconds_t(min(2_000_000, max(minimum, scaled)))
}

private struct SavedPasteboard {
  let items: [SavedPasteboardItem]

  static func capture(from pasteboard: NSPasteboard) -> SavedPasteboard {
    let items = pasteboard.pasteboardItems?.map(SavedPasteboardItem.init(item:)) ?? []
    return SavedPasteboard(items: items)
  }

  func restore(to pasteboard: NSPasteboard) {
    pasteboard.clearContents()
    guard !items.isEmpty else { return }
    _ = pasteboard.writeObjects(items.map { $0.makePasteboardItem() })
  }
}

private struct SavedPasteboardItem {
  let values: [(type: NSPasteboard.PasteboardType, data: Data)]

  init(item: NSPasteboardItem) {
    values = item.types.compactMap { type in
      guard let data = item.data(forType: type) else { return nil }
      return (type: type, data: data)
    }
  }

  func makePasteboardItem() -> NSPasteboardItem {
    let item = NSPasteboardItem()
    for value in values {
      item.setData(value.data, forType: value.type)
    }
    return item
  }
}
