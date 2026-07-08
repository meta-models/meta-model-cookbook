import CoreGraphics
import Foundation

/// Which physical mouse button an action uses.
enum MouseButton: String {
  case left
  case right
  case center

  static func parse(_ raw: String) throws -> MouseButton {
    switch raw.lowercased() {
    case "left", "l", "primary": return .left
    case "right", "r", "secondary": return .right
    case "center", "middle", "c", "m": return .center
    default:
      throw CLIError("--mouse-button must be left|right|center (got '\(raw)')", code: 2)
    }
  }

  var cgButton: CGMouseButton {
    switch self {
    case .left: return .left
    case .right: return .right
    case .center: return .center
    }
  }

  /// Down / up event types for this button.
  var clickTypes: (down: CGEventType, up: CGEventType) {
    switch self {
    case .left: return (.leftMouseDown, .leftMouseUp)
    case .right: return (.rightMouseDown, .rightMouseUp)
    case .center: return (.otherMouseDown, .otherMouseUp)
    }
  }

  var dragType: CGEventType {
    switch self {
    case .left: return .leftMouseDragged
    case .right: return .rightMouseDragged
    case .center: return .otherMouseDragged
    }
  }
}

/// Vertical / horizontal scroll direction.
enum ScrollDirection: String {
  case up, down, left, right

  static func parse(_ raw: String) throws -> ScrollDirection {
    guard let d = ScrollDirection(rawValue: raw.lowercased()) else {
      throw CLIError("--direction must be up|down|left|right (got '\(raw)')", code: 2)
    }
    return d
  }
}

/// Shared event source for all generated events.
func eventSource() -> CGEventSource? {
  CGEventSource(stateID: .combinedSessionState)
}

private func post(_ event: CGEvent?) {
  event?.post(tap: .cghidEventTap)
}

/// Warp the cursor to a point in one event (instant; used per-step internally).
func moveMouse(to point: CGPoint, source: CGEventSource?) {
  post(
    CGEvent(
      mouseEventSource: source,
      mouseType: .mouseMoved,
      mouseCursorPosition: point,
      mouseButton: .left))
}

/// Current cursor location in global (top-left origin) coordinates.
func currentMouseLocation() -> CGPoint {
  CGEvent(source: nil)?.location ?? .zero
}

/// Glide the cursor to `target` along an eased path instead of teleporting, so
/// the motion looks smooth and human. Interpolates from the current position;
/// the step count scales with distance and is capped for responsiveness.
func smoothMove(to target: CGPoint, source: CGEventSource?) {
  let start = currentMouseLocation()
  let dx = target.x - start.x
  let dy = target.y - start.y
  let distance = (dx * dx + dy * dy).squareRoot()
  guard distance >= 1 else {
    moveMouse(to: target, source: source)
    return
  }
  let steps = max(12, min(60, Int(distance / 12)))
  for i in 1...steps {
    let t = Double(i) / Double(steps)
    let e = t < 0.5 ? 2 * t * t : 1 - pow(-2 * t + 2, 2) / 2 // ease-in-out
    moveMouse(to: CGPoint(x: start.x + dx * e, y: start.y + dy * e), source: source)
    usleep(6_000)
  }
}

/// Click at a point. `clickCount` >= 2 produces a proper multi-click by
/// incrementing the click-state field on each successive down/up pair, which is
/// what AppKit inspects to recognise double/triple clicks.
func performClick(
  at point: CGPoint,
  button: MouseButton,
  clickCount: Int,
  source: CGEventSource?
) {
  let count = max(1, clickCount)
  let types = button.clickTypes

  smoothMove(to: point, source: source)
  usleep(12_000)

  for n in 1...count {
    let down = CGEvent(
      mouseEventSource: source,
      mouseType: types.down,
      mouseCursorPosition: point,
      mouseButton: button.cgButton)
    down?.setIntegerValueField(.mouseEventClickState, value: Int64(n))
    post(down)
    usleep(12_000)

    let up = CGEvent(
      mouseEventSource: source,
      mouseType: types.up,
      mouseCursorPosition: point,
      mouseButton: button.cgButton)
    up?.setIntegerValueField(.mouseEventClickState, value: Int64(n))
    post(up)
    usleep(12_000)
  }
}

func performMouseDown(at point: CGPoint, button: MouseButton, source: CGEventSource?) {
  smoothMove(to: point, source: source)
  usleep(12_000)
  let down = CGEvent(
    mouseEventSource: source,
    mouseType: button.clickTypes.down,
    mouseCursorPosition: point,
    mouseButton: button.cgButton)
  down?.setIntegerValueField(.mouseEventClickState, value: 1)
  post(down)
}

func performMouseUp(at point: CGPoint, button: MouseButton, source: CGEventSource?) {
  let up = CGEvent(
    mouseEventSource: source,
    mouseType: button.clickTypes.up,
    mouseCursorPosition: point,
    mouseButton: button.cgButton)
  up?.setIntegerValueField(.mouseEventClickState, value: 1)
  post(up)
}

/// Press at `from`, drag through interpolated points, release at `to`.
func performDrag(
  from: CGPoint,
  to: CGPoint,
  button: MouseButton,
  source: CGEventSource?
) {
  let types = button.clickTypes

  smoothMove(to: from, source: source)
  usleep(20_000)

  let down = CGEvent(
    mouseEventSource: source,
    mouseType: types.down,
    mouseCursorPosition: from,
    mouseButton: button.cgButton)
  down?.setIntegerValueField(.mouseEventClickState, value: 1)
  post(down)
  usleep(40_000)

  let steps = 40
  for i in 1...steps {
    let t = Double(i) / Double(steps)
    let p = CGPoint(
      x: from.x + (to.x - from.x) * t,
      y: from.y + (to.y - from.y) * t)
    let drag = CGEvent(
      mouseEventSource: source,
      mouseType: button.dragType,
      mouseCursorPosition: p,
      mouseButton: button.cgButton)
    drag?.setIntegerValueField(.mouseEventClickState, value: 1)
    post(drag)
    usleep(8_000)
  }

  usleep(30_000)
  let up = CGEvent(
    mouseEventSource: source,
    mouseType: types.up,
    mouseCursorPosition: to,
    mouseButton: button.cgButton)
  up?.setIntegerValueField(.mouseEventClickState, value: 1)
  post(up)
}

/// Whether macOS "natural scrolling" is enabled (the default for trackpads).
/// When on, the system inverts the relationship between a wheel delta and the
/// direction content moves, so we flip our signs to keep `direction` meaning the
/// same thing (e.g. `down` always reveals content further down the document).
func naturalScrollingEnabled() -> Bool {
  if let value = CFPreferencesCopyAppValue(
    "com.apple.swipescrolldirection" as CFString,
    kCFPreferencesAnyApplication
  ) {
    return (value as? Bool) ?? false
  }
  return false
}

/// Scroll `pages` pages in a direction, optionally after moving the cursor to a
/// point first (so the scroll targets the element under that point).
///
/// `direction` is interpreted from the user's point of view: `down`/`right`
/// reveal content further down/right in the document, `up`/`left` reveal content
/// above/left — and this holds regardless of the "natural scrolling" preference
/// (we read it and flip the wheel signs to compensate).
///
/// Scrolling is emitted in small line-unit steps for smoothness and broad app
/// compatibility. `linesPerPage` controls how much one "page" moves.
func performScroll(
  direction: ScrollDirection,
  pages: Int,
  linesPerPage: Int,
  at point: CGPoint?,
  source: CGEventSource?
) {
  if let point = point {
    smoothMove(to: point, source: source)
    usleep(12_000)
  }

  // Raw CoreGraphics convention (natural scrolling OFF): positive wheel1
  // reveals content above ("up"), positive wheel2 reveals content to the left.
  // Flip when natural scrolling is ON so the user-facing direction is stable.
  let flip: Int32 = naturalScrollingEnabled() ? -1 : 1
  let totalLines = max(1, pages) * max(1, linesPerPage)
  for _ in 0..<totalLines {
    var wheel1: Int32 = 0 // vertical
    var wheel2: Int32 = 0 // horizontal
    switch direction {
    case .up: wheel1 = 1
    case .down: wheel1 = -1
    case .left: wheel2 = 1
    case .right: wheel2 = -1
    }
    let event = CGEvent(
      scrollWheelEvent2Source: source,
      units: .line,
      wheelCount: 2,
      wheel1: wheel1 * flip,
      wheel2: wheel2 * flip,
      wheel3: 0)
    post(event)
    usleep(6_000)
  }
}
