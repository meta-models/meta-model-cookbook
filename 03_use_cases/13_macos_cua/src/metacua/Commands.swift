import CoreGraphics
import Foundation

/// Common setup for every action: verify permission, then bring the app forward.
private func preflight(app: String) throws {
  try requireTrust()
  try activateApp(app)
}

func runClick(_ raw: [String]) throws {
  let args = try Args(raw)
  let x = try args.requiredDouble("x")
  let y = try args.requiredDouble("y")
  let clickCount = try args.int("click-count") ?? args.int("clicks") ?? 1
  let button = try MouseButton.parse(args.string(["mouse-button", "button"]) ?? "left")
  let app = try args.requiredString("app")
  let point = CGPoint(x: x, y: y)

  try preflight(app: app)
  performClick(at: point, button: button, clickCount: clickCount, source: eventSource())
  print("clicked \(button.rawValue) x\(max(1, clickCount)) at (\(x), \(y)) in \(app)")
}

func runShot(_ raw: [String]) throws {
  let args = try Args(raw)
  try requireScreenRecording()
  let scale = try args.double("scale") ?? 1.0
  let shot = try captureScreenshot(scale: scale)
  guard let data = Data(base64Encoded: shot.pngBase64) else {
    throw CLIError("failed to decode the captured screenshot")
  }
  let outPath =
    args.string(["out", "o"])
    ?? FileManager.default.temporaryDirectory.appendingPathComponent("metacua-shot.png").path
  let url = URL(fileURLWithPath: (outPath as NSString).expandingTildeInPath)
  try data.write(to: url)
  let sizeLabel =
    shot.imageWidth == shot.width && shot.imageHeight == shot.height
    ? "\(shot.imageWidth)x\(shot.imageHeight)"
    : "\(shot.imageWidth)x\(shot.imageHeight) image, \(shot.width)x\(shot.height) coords"
  print("captured \(sizeLabel) screenshot -> \(url.path) (\(data.count) bytes)")
}

func runMove(_ raw: [String]) throws {
  let args = try Args(raw)
  let x = try args.requiredDouble("x")
  let y = try args.requiredDouble("y")
  let app = try args.requiredString("app")
  let point = CGPoint(x: x, y: y)

  try preflight(app: app)
  moveMouse(to: point, source: eventSource())
  print("moved pointer to (\(x), \(y)) in \(app)")
}

func runScroll(_ raw: [String]) throws {
  let args = try Args(raw)
  let direction = try ScrollDirection.parse(try args.requiredString("direction"))
  let pages = try args.int("pages") ?? 1
  let linesPerPage = try args.int("lines-per-page") ?? 10
  let app = try args.requiredString("app")

  let xOpt = try args.double("x")
  let yOpt = try args.double("y")
  if (xOpt == nil) != (yOpt == nil) {
    throw CLIError("--x and --y must be provided together", code: 2)
  }
  var point: CGPoint?
  if let x = xOpt, let y = yOpt {
    point = CGPoint(x: x, y: y)
  }

  try preflight(app: app)
  performScroll(
    direction: direction, pages: pages, linesPerPage: linesPerPage, at: point, source: eventSource()
  )
  print("scrolled \(direction.rawValue) \(pages) page(s) in \(app)")
}

func runDrag(_ raw: [String]) throws {
  let args = try Args(raw)
  let fromX = try args.requiredDouble("from-x")
  let fromY = try args.requiredDouble("from-y")
  let toX = try args.requiredDouble("to-x")
  let toY = try args.requiredDouble("to-y")
  let button = try MouseButton.parse(args.string(["mouse-button", "button"]) ?? "left")
  let app = try args.requiredString("app")
  let from = CGPoint(x: fromX, y: fromY)
  let to = CGPoint(x: toX, y: toY)

  try preflight(app: app)
  performDrag(from: from, to: to, button: button, source: eventSource())
  print("dragged from (\(fromX), \(fromY)) to (\(toX), \(toY)) in \(app)")
}

func runPressKey(_ raw: [String]) throws {
  let args = try Args(raw)
  let key = try args.requiredString("key")
  let app = try args.requiredString("app")
  let combo = try parseKeyCombo(key)

  try preflight(app: app)
  performKeyCombo(code: combo.code, flags: combo.flags, source: eventSource())
  print("pressed '\(key)' in \(app)")
}

func runTypeText(_ raw: [String]) throws {
  let args = try Args(raw)
  let text = try args.requiredString("text")
  let app = try args.requiredString("app")

  try preflight(app: app)
  try performTypeText(text, source: eventSource())
  print("inserted \(text.count) character(s) in \(app)")
}
