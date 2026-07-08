import AppKit
import CoreGraphics
import Foundation

/// A captured screen image plus the logical coordinate space it represents.
struct Screenshot {
  let pngBase64: String
  let width: Int // logical points - the coordinate space the agent operates in
  let height: Int
  let imageWidth: Int
  let imageHeight: Int
}

/// The primary display whose top-left is the global coordinate origin.
func primaryScreen() -> NSScreen? {
  NSScreen.screens.first
}

/// Capture the primary display and encode a possibly downsampled image while
/// retaining the full logical display coordinate space for CGEvent actions.
/// Uses `screencapture` (requires Screen Recording permission) to avoid the
/// deprecated CGDisplayCreateImage path.
func captureScreenshot(scale: Double = 1.0) throws -> Screenshot {
  // CGDisplayBounds is thread-safe (this runs on the agent's background thread,
  // where NSScreen would be unsafe). Its size is in logical points, matching the
  // CGEvent global coordinate space the agent operates in.
  let bounds = CGDisplayBounds(CGMainDisplayID())
  let logicalWidth = Int(bounds.width.rounded())
  let logicalHeight = Int(bounds.height.rounded())
  guard logicalWidth > 0, logicalHeight > 0 else {
    throw CLIError("no display found to capture")
  }
  guard scale.isFinite, scale > 0, scale <= 1 else {
    throw CLIError("screenshot scale must be > 0 and <= 1 (got \(scale))", code: 2)
  }
  let imageWidth = max(1, Int((Double(logicalWidth) * scale).rounded()))
  let imageHeight = max(1, Int((Double(logicalHeight) * scale).rounded()))

  let tmp = FileManager.default.temporaryDirectory
    .appendingPathComponent("metacua-\(ProcessInfo.processInfo.processIdentifier)-shot.png")
  defer { try? FileManager.default.removeItem(at: tmp) }

  let process = Process()
  process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
  // -x: no capture sound, -t png, -D 1: main display.
  process.arguments = ["-x", "-t", "png", "-D", "1", tmp.path]
  let errPipe = Pipe()
  process.standardError = errPipe
  try process.run()
  process.waitUntilExit()
  guard process.terminationStatus == 0, let raw = try? Data(contentsOf: tmp) else {
    throw CLIError(
      "screencapture failed (status \(process.terminationStatus)). "
        + "Grant Screen Recording permission and retry."
    )
  }

  guard let source = NSBitmapImageRep(data: raw) else {
    throw CLIError("could not decode the captured screenshot")
  }

  // Downscale into a fresh RGBA bitmap. The encoded image may be lower
  // resolution than the logical coordinate space used for actions.
  guard
    let scaled = NSBitmapImageRep(
      bitmapDataPlanes: nil,
      pixelsWide: imageWidth,
      pixelsHigh: imageHeight,
      bitsPerSample: 8,
      samplesPerPixel: 4,
      hasAlpha: true,
      isPlanar: false,
      colorSpaceName: .deviceRGB,
      bytesPerRow: 0,
      bitsPerPixel: 0
    )
  else {
    throw CLIError("could not allocate a bitmap for downscaling")
  }
  scaled.size = NSSize(width: imageWidth, height: imageHeight)

  NSGraphicsContext.saveGraphicsState()
  NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: scaled)
  NSGraphicsContext.current?.imageInterpolation = .high
  source.draw(in: NSRect(x: 0, y: 0, width: imageWidth, height: imageHeight))
  NSGraphicsContext.restoreGraphicsState()

  guard let png = scaled.representation(using: .png, properties: [:]) else {
    throw CLIError("could not re-encode the screenshot as PNG")
  }

  return Screenshot(
    pngBase64: png.base64EncodedString(),
    width: logicalWidth,
    height: logicalHeight,
    imageWidth: imageWidth,
    imageHeight: imageHeight
  )
}

/// Persists screenshots captured during an agent run to `~/.metacua/screenshots/<goalId>/`,
/// so the actual images can be inspected locally instead of only the base64 blobs in traces.
enum ScreenshotStore {
  static var storageURL: URL {
    metacuaHomeURL().appendingPathComponent("screenshots")
  }

  @discardableResult
  static func save(_ screenshot: Screenshot, goalId: String, label: String) throws -> URL {
    guard let data = Data(base64Encoded: screenshot.pngBase64) else {
      throw CLIError("failed to decode screenshot for saving")
    }
    let directory = storageURL.appendingPathComponent(goalId)
    try FileManager.default.createDirectory(
      at: directory,
      withIntermediateDirectories: true,
      attributes: [.posixPermissions: 0o700]
    )
    let url = directory.appendingPathComponent("\(label).png")
    try data.write(to: url, options: [.atomic])
    try? FileManager.default.setAttributes(
      [.posixPermissions: 0o600], ofItemAtPath: url.path)
    return url
  }
}
