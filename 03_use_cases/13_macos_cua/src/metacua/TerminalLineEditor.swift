import Darwin
import Foundation

final class TerminalLineEditor {
  private let prompt: String
  private let useColor: Bool
  private let catalog: SlashCommandCatalog
  private var buffer: [Character] = []
  private var cursor = 0

  init(prompt: String, useColor: Bool, catalog: SlashCommandCatalog = SlashCommandCatalog()) {
    self.prompt = prompt
    self.useColor = useColor
    self.catalog = catalog
  }

  func readLine() -> String? {
    guard let rawMode = TerminalRawMode() else {
      print(prompt, terminator: "")
      fflush(stdout)
      return Swift.readLine()
    }
    defer { rawMode.restore() }

    render()
    while let byte = readByte() {
      switch byte {
      case 3:
        raise(SIGINT)
      case 4:
        if buffer.isEmpty {
          write("\n")
          return nil
        }
      case 9:
        completeSlashCommand()
      case 10, 13:
        write("\n")
        return String(buffer)
      case 27:
        handleEscapeSequence()
      case 1:
        cursor = 0
      case 5:
        cursor = buffer.count
      case 21:
        buffer.removeAll()
        cursor = 0
      case 8, 127:
        deleteBackward()
      default:
        insert(byte: byte)
      }
      render()
    }

    write("\n")
    return nil
  }

  private func insert(byte: UInt8) {
    guard byte >= 32 else { return }
    var bytes = [byte]
    let remaining = expectedUTF8ContinuationCount(firstByte: byte)
    for _ in 0..<remaining {
      guard let next = readByte(timeoutMilliseconds: 20) else { return }
      bytes.append(next)
    }
    guard let text = String(data: Data(bytes), encoding: .utf8) else { return }
    for character in text {
      buffer.insert(character, at: cursor)
      cursor += 1
    }
  }

  private func deleteBackward() {
    guard cursor > 0 else { return }
    buffer.remove(at: cursor - 1)
    cursor -= 1
  }

  private func handleEscapeSequence() {
    guard let first = readByte(timeoutMilliseconds: 20) else { return }
    guard first == 91 else { return }
    guard let second = readByte(timeoutMilliseconds: 20) else { return }
    switch second {
    case 67:
      cursor = min(buffer.count, cursor + 1)
    case 68:
      cursor = max(0, cursor - 1)
    case 51:
      if readByte(timeoutMilliseconds: 20) == 126, cursor < buffer.count {
        buffer.remove(at: cursor)
      }
    default:
      break
    }
  }

  private func completeSlashCommand() {
    guard let token = slashToken(), token.cursorIsInCommand else {
      listSlashCommands()
      return
    }

    let matches = catalog.matchingNames(prefix: token.value)
    guard !matches.isEmpty else { return }

    if matches.count == 1 {
      replaceSlashToken(token, with: matches[0], appendSpace: true)
      return
    }

    let common = catalog.commonPrefix(for: matches)
    if common.count > token.value.count {
      replaceSlashToken(token, with: common, appendSpace: false)
      return
    }

    listMatches(matches)
  }

  private func listSlashCommands() {
    let names = catalog.specs.map(\.name)
    listMatches(names)
  }

  private func listMatches(_ matches: [String]) {
    write("\n")
    let columns = matches.map { $0.padding(toLength: 18, withPad: " ", startingAt: 0) }
    write(dim(columns.joined()) + "\n")
  }

  private func replaceSlashToken(_ token: SlashToken, with replacement: String, appendSpace: Bool) {
    let replacementChars = Array(replacement)
    buffer.replaceSubrange(token.start..<token.end, with: replacementChars)
    cursor = token.start + replacementChars.count
    if appendSpace, cursor == buffer.count {
      buffer.append(" ")
      cursor += 1
    }
  }

  private func render() {
    let line = String(buffer)
    let ghost = completionGhost(for: line)
    write("\r\u{001B}[2K")
    write(prompt)
    write(line)
    if !ghost.isEmpty {
      write(dim(ghost))
    }

    let moveLeft = max(0, buffer.count - cursor + ghost.count)
    if moveLeft > 0 {
      write("\u{001B}[\(moveLeft)D")
    }
    fflush(stdout)
  }

  private func completionGhost(for line: String) -> String {
    guard line.hasPrefix("/"), cursor == buffer.count, let token = slashToken() else { return "" }
    guard token.cursorIsInCommand || cursor >= token.end else { return "" }

    let matches = catalog.matchingNames(prefix: token.value)
    if token.cursorIsInCommand {
      if matches.count == 1, let match = matches.first {
        let suffix = String(match.dropFirst(token.value.count))
        let hint = catalog.spec(named: match).map { argumentHint($0, leadingSpace: true) } ?? ""
        return suffix + hint
      }
      let common = catalog.commonPrefix(for: matches)
      if common.count > token.value.count {
        return String(common.dropFirst(token.value.count))
      }
      return ""
    }

    guard let spec = catalog.spec(named: token.value) else { return "" }
    if line == token.value {
      return argumentHint(spec, leadingSpace: true)
    }
    if line == token.value + " " {
      return argumentHint(spec, leadingSpace: false)
    }
    return ""
  }

  private func argumentHint(_ spec: SlashCommandSpec, leadingSpace: Bool) -> String {
    guard !spec.arguments.isEmpty else { return "" }
    return leadingSpace ? " \(spec.arguments)" : spec.arguments
  }

  private func slashToken() -> SlashToken? {
    guard buffer.first == "/" else { return nil }
    let end = buffer.firstIndex(where: { $0 == " " || $0 == "\t" }) ?? buffer.count
    let value = String(buffer[0..<end])
    return SlashToken(value: value, start: 0, end: end, cursorIsInCommand: cursor <= end)
  }

  private func dim(_ text: String) -> String {
    guard useColor, !text.isEmpty else { return text }
    return "\u{001B}[2m\(text)\u{001B}[0m"
  }

  private func write(_ text: String) {
    FileHandle.standardOutput.write(Data(text.utf8))
  }

  private func readByte(timeoutMilliseconds: Int? = nil) -> UInt8? {
    if let timeoutMilliseconds {
      var pollDescriptor = pollfd(fd: STDIN_FILENO, events: Int16(POLLIN), revents: 0)
      guard poll(&pollDescriptor, 1, Int32(timeoutMilliseconds)) > 0 else { return nil }
    }

    var byte: UInt8 = 0
    let count = Darwin.read(STDIN_FILENO, &byte, 1)
    return count == 1 ? byte : nil
  }

  private func expectedUTF8ContinuationCount(firstByte: UInt8) -> Int {
    if firstByte & 0b1000_0000 == 0 { return 0 }
    if firstByte & 0b1110_0000 == 0b1100_0000 { return 1 }
    if firstByte & 0b1111_0000 == 0b1110_0000 { return 2 }
    if firstByte & 0b1111_1000 == 0b1111_0000 { return 3 }
    return 0
  }
}

private struct SlashToken {
  let value: String
  let start: Int
  let end: Int
  let cursorIsInCommand: Bool
}

private final class TerminalRawMode {
  private let original: termios

  init?() {
    var current = termios()
    guard tcgetattr(STDIN_FILENO, &current) == 0 else { return nil }
    original = current

    var raw = current
    raw.c_lflag &= ~tcflag_t(ECHO | ICANON)
    setControlCharacter(&raw, VMIN, 1)
    setControlCharacter(&raw, VTIME, 0)

    guard tcsetattr(STDIN_FILENO, TCSANOW, &raw) == 0 else { return nil }
  }

  func restore() {
    var restored = original
    tcsetattr(STDIN_FILENO, TCSANOW, &restored)
  }
}

private func setControlCharacter(_ term: inout termios, _ index: Int32, _ value: cc_t) {
  withUnsafeMutablePointer(to: &term.c_cc) { pointer in
    pointer.withMemoryRebound(to: cc_t.self, capacity: Int(NCCS)) { controlCharacters in
      controlCharacters[Int(index)] = value
    }
  }
}
