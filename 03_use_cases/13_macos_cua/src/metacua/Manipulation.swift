import CoreGraphics
import Foundation

protocol ManipulationBackend {
  var label: String { get }
  var requiresAccessibility: Bool { get }
  var requiresScreenRecording: Bool { get }
  var supportsBackground: Bool { get }
  var supportsMultipleCursors: Bool { get }

  func screenshot(scale: Double) throws -> Screenshot
  func move(to point: CGPoint) throws
  func click(at point: CGPoint, button: MouseButton, clickCount: Int) throws
  func mouseDown(at point: CGPoint, button: MouseButton) throws
  func mouseUp(at point: CGPoint, button: MouseButton) throws
  func scroll(direction: ScrollDirection, pages: Int, linesPerPage: Int, at point: CGPoint?) throws
  func drag(from: CGPoint, to: CGPoint, button: MouseButton) throws
  func pressKey(_ key: String) throws
  func keyDown(_ key: String) throws
  func keyUp(_ key: String) throws
  func typeText(_ text: String) throws
  func wait(ms: Int) throws
}

func makeManipulationBackend(_ config: AgentConfig) throws -> ManipulationBackend {
  CGEventManipulationBackend()
}

final class CGEventManipulationBackend: ManipulationBackend {
  let label = "CGEvent foreground"
  let requiresAccessibility = true
  let requiresScreenRecording = true
  let supportsBackground = false
  let supportsMultipleCursors = false

  private let source = eventSource()

  func screenshot(scale: Double) throws -> Screenshot {
    try captureScreenshot(scale: scale)
  }

  func move(to point: CGPoint) throws {
    smoothMove(to: point, source: source)
  }

  func click(at point: CGPoint, button: MouseButton, clickCount: Int) throws {
    performClick(at: point, button: button, clickCount: clickCount, source: source)
  }

  func mouseDown(at point: CGPoint, button: MouseButton) throws {
    performMouseDown(at: point, button: button, source: source)
  }

  func mouseUp(at point: CGPoint, button: MouseButton) throws {
    performMouseUp(at: point, button: button, source: source)
  }

  func scroll(direction: ScrollDirection, pages: Int, linesPerPage: Int, at point: CGPoint?) throws {
    performScroll(
      direction: direction, pages: pages, linesPerPage: linesPerPage, at: point, source: source)
  }

  func drag(from: CGPoint, to: CGPoint, button: MouseButton) throws {
    performDrag(from: from, to: to, button: button, source: source)
  }

  func pressKey(_ key: String) throws {
    let combo = try parseKeyCombo(key)
    performKeyCombo(code: combo.code, flags: combo.flags, source: source)
  }

  func keyDown(_ key: String) throws {
    try performKeyDown(key, source: source)
  }

  func keyUp(_ key: String) throws {
    try performKeyUp(key, source: source)
  }

  func typeText(_ text: String) throws {
    try performTypeText(text, source: source)
  }

  func wait(ms: Int) throws {
    usleep(useconds_t(ms) * 1000)
  }
}
