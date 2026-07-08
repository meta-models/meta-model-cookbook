import AppKit
import CoreGraphics
import Foundation

/// `metacua demo` - preview the cursor overlay and smooth movement without an LLM.
/// It glides the real cursor and plays the click/type/drag effects at a few
/// screen points; it does NOT click, type, or drag anything (no app is touched).
func runDemo(_ raw: [String]) throws {
  try requireTrust()

  let app = NSApplication.shared
  app.setActivationPolicy(.accessory)
  let overlay = OverlayController()
  let src = eventSource()

  guard let screen = primaryScreen() else { throw CLIError("no display found") }
  let w = screen.frame.width
  let h = screen.frame.height
  func pt(_ fx: CGFloat, _ fy: CGFloat) -> CGPoint { CGPoint(x: w * fx, y: h * fy) }

  DispatchQueue.global(qos: .userInitiated).async {
    // Two quick clicks — the cursor stays visible across rapid actions.
    let a = pt(0.34, 0.34)
    smoothMove(to: a, source: src)
    overlay.showClick("click", at: a)
    usleep(650_000)
    let b = pt(0.6, 0.44)
    smoothMove(to: b, source: src)
    overlay.showClick("double-click", at: b)
    usleep(650_000)

    // Pause long enough to watch it linger, then fade out…
    usleep(2_200_000)

    // …then reappear for a type label.
    let c = pt(0.45, 0.6)
    smoothMove(to: c, source: src)
    overlay.showAction("type: hello world", at: c)
    usleep(1_900_000)

    // A drag (overlay + real cursor glide only — nothing is actually dragged).
    let from = pt(0.3, 0.7)
    let to = pt(0.62, 0.72)
    smoothMove(to: from, source: src)
    overlay.showDrag("drag", from: from, to: to, duration: 0.6)
    smoothMove(to: to, source: src)
    usleep(2_200_000)

    DispatchQueue.main.async { app.terminate(nil) }
  }
  app.run()
}
