import CoreGraphics
import Darwin
import Foundation

private enum PointerKey {
  case up
  case down
  case left
  case right
  case click
  case faster
  case slower
  case quit
}

func runPointerControl(_ raw: [String]) throws {
  guard isatty(STDIN_FILENO) == 1 else {
    throw CLIError("pointer mode requires an interactive terminal", code: 2)
  }

  let args = try Args(raw)
  var step = try args.int("step") ?? 20
  guard step >= 1 else {
    throw CLIError("--step must be >= 1", code: 2)
  }

  try requireTrust()
  if let app = args.string("app") {
    try activateApp(app)
  }

  let source = eventSource()
  var original = termios()
  guard tcgetattr(STDIN_FILENO, &original) == 0 else {
    throw CLIError("could not read terminal settings")
  }

  var rawMode = original
  rawMode.c_lflag &= ~tcflag_t(ECHO | ICANON | ISIG)
  rawMode.c_cc.16 = 0 // VMIN
  rawMode.c_cc.17 = 1 // VTIME, tenths of a second

  guard tcsetattr(STDIN_FILENO, TCSANOW, &rawMode) == 0 else {
    throw CLIError("could not enter raw terminal mode")
  }
  defer {
    var restore = original
    _ = tcsetattr(STDIN_FILENO, TCSANOW, &restore)
    FileHandle.standardOutput.write(Data("\n".utf8))
  }

  print("pointer mode: arrows/WASD move, space/return click, +/- changes step, q quits")
  print("step: \(step)")
  fflush(stdout)

  while true {
    guard let key = readPointerKey() else { continue }
    switch key {
    case .up:
      nudgePointer(dx: 0, dy: -CGFloat(step), source: source)
    case .down:
      nudgePointer(dx: 0, dy: CGFloat(step), source: source)
    case .left:
      nudgePointer(dx: -CGFloat(step), dy: 0, source: source)
    case .right:
      nudgePointer(dx: CGFloat(step), dy: 0, source: source)
    case .click:
      performClick(at: currentMouseLocation(), button: .left, clickCount: 1, source: source)
    case .faster:
      step = min(step * 2, 400)
      print("\rstep: \(step)   ", terminator: "")
      fflush(stdout)
    case .slower:
      step = max(step / 2, 1)
      print("\rstep: \(step)   ", terminator: "")
      fflush(stdout)
    case .quit:
      return
    }
  }
}

private func readPointerKey() -> PointerKey? {
  guard let byte = readByte() else { return nil }
  switch byte {
  case 3, 4, 27:
    if byte == 27, let next = readByte(), next == 91, let arrow = readByte() {
      switch arrow {
      case 65: return .up
      case 66: return .down
      case 67: return .right
      case 68: return .left
      default: return nil
      }
    }
    return .quit
  case 10, 13, 32:
    return .click
  case 43, 61:
    return .faster
  case 45, 95:
    return .slower
  case 65, 97:
    return .left
  case 68, 100:
    return .right
  case 81, 113:
    return .quit
  case 83, 115:
    return .down
  case 87, 119:
    return .up
  default:
    return nil
  }
}

private func readByte() -> UInt8? {
  var byte: UInt8 = 0
  let count = read(STDIN_FILENO, &byte, 1)
  return count == 1 ? byte : nil
}

private func nudgePointer(dx: CGFloat, dy: CGFloat, source: CGEventSource?) {
  let current = currentMouseLocation()
  moveMouse(to: clampToMainDisplay(CGPoint(x: current.x + dx, y: current.y + dy)), source: source)
}

private func clampToMainDisplay(_ point: CGPoint) -> CGPoint {
  let bounds = CGDisplayBounds(CGMainDisplayID())
  guard bounds.width > 0, bounds.height > 0 else { return point }
  return CGPoint(
    x: min(max(bounds.minX, point.x), bounds.maxX - 1),
    y: min(max(bounds.minY, point.y), bounds.maxY - 1)
  )
}
