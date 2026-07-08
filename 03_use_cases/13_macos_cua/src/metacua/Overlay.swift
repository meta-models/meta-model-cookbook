import AppKit
import QuartzCore

/// A transparent, click-through, always-on-top overlay that renders a small
/// glowing animated cursor at each action the agent performs, so the user can
/// watch the LLM drive the machine. After each action the cursor lingers briefly
/// and then fades out. All public methods are thread-safe (they hop to the main
/// thread); the agent loop calls them from its background thread.
final class OverlayController {
  // A warm rose accent (not blue), with a soft glow.
  private let accent = NSColor(calibratedRed: 1.0, green: 0.36, blue: 0.52, alpha: 1.0)
  private let radius: CGFloat = 13 // smaller cursor
  private let holdSeconds = 1.1 // linger after the last action
  private let fadeSeconds = 0.45

  private var window: NSWindow?
  private var hostLayer: CALayer?
  private var cursorLayer: CALayer?
  private var labelContainer: CALayer?
  private var labelText: CATextLayer?
  private var statusContainer: CALayer?
  private var statusTitle: CATextLayer?
  private var statusBody: CATextLayer?
  private var screenHeight: CGFloat = 0
  private var hideWork: DispatchWorkItem?

  /// Build the overlay window. Must be called on the main thread.
  init() {
    guard let screen = primaryScreen() else { return }
    screenHeight = screen.frame.height

    let window = NSWindow(
      contentRect: screen.frame,
      styleMask: .borderless,
      backing: .buffered,
      defer: false
    )
    window.isOpaque = false
    window.backgroundColor = .clear
    window.hasShadow = false
    window.ignoresMouseEvents = true
    window.level = NSWindow.Level(rawValue: Int(CGShieldingWindowLevel()))
    window.collectionBehavior = [
      .canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle,
    ]

    let view = NSView(frame: NSRect(origin: .zero, size: screen.frame.size))
    view.wantsLayer = true
    let host = CALayer()
    host.frame = view.bounds
    view.layer = host
    window.contentView = view

    let scale = screen.backingScaleFactor

    // Cursor group: glowing ring + center dot, anchored at its center.
    let cursor = CALayer()
    let d = radius * 2
    cursor.bounds = CGRect(x: 0, y: 0, width: d, height: d)
    cursor.opacity = 0 // hidden until the first action

    let ring = CAShapeLayer()
    ring.path = CGPath(
      ellipseIn: CGRect(x: 1.5, y: 1.5, width: d - 3, height: d - 3), transform: nil)
    ring.fillColor = accent.withAlphaComponent(0.12).cgColor
    ring.strokeColor = accent.cgColor
    ring.lineWidth = 2
    ring.shadowColor = accent.cgColor
    ring.shadowRadius = 7
    ring.shadowOpacity = 0.85
    ring.shadowOffset = .zero
    ring.frame = cursor.bounds
    cursor.addSublayer(ring)

    let dot = CAShapeLayer()
    let dotR: CGFloat = 3
    dot.path = CGPath(
      ellipseIn: CGRect(
        x: radius - dotR, y: radius - dotR,
        width: dotR * 2, height: dotR * 2), transform: nil)
    dot.fillColor = accent.cgColor
    dot.frame = cursor.bounds
    cursor.addSublayer(dot)

    host.addSublayer(cursor)

    // Action label pill below the cursor.
    let pill = CALayer()
    pill.backgroundColor = NSColor.black.withAlphaComponent(0.68).cgColor
    pill.cornerRadius = 8
    pill.opacity = 0
    let text = CATextLayer()
    text.fontSize = 11
    text.foregroundColor = NSColor.white.cgColor
    text.alignmentMode = .center
    text.truncationMode = .end
    text.contentsScale = scale
    pill.addSublayer(text)
    host.addSublayer(pill)

    let status = CALayer()
    status.backgroundColor = NSColor.black.withAlphaComponent(0.72).cgColor
    status.cornerRadius = 10
    status.opacity = 0
    status.shadowColor = NSColor.black.cgColor
    status.shadowOpacity = 0.28
    status.shadowRadius = 12
    status.shadowOffset = CGSize(width: 0, height: -2)

    let title = CATextLayer()
    title.fontSize = 12
    title.foregroundColor = accent.cgColor
    title.alignmentMode = .left
    title.truncationMode = .end
    title.contentsScale = scale
    status.addSublayer(title)

    let body = CATextLayer()
    body.fontSize = 12
    body.foregroundColor = NSColor.white.cgColor
    body.alignmentMode = .left
    body.truncationMode = .end
    body.isWrapped = true
    body.contentsScale = scale
    status.addSublayer(body)
    host.addSublayer(status)

    self.window = window
    self.hostLayer = host
    self.cursorLayer = cursor
    self.labelContainer = pill
    self.labelText = text
    self.statusContainer = status
    self.statusTitle = title
    self.statusBody = body

    window.orderFrontRegardless()
  }

  // MARK: - Public API (global top-left coordinates)

  /// Move the cursor to a point and set the action label (no click ripple).
  func showAction(_ label: String, at point: CGPoint) {
    onMain {
      self.placeCursor(at: point, animated: true, label: label)
      self.scheduleHide()
    }
  }

  /// Move the cursor to a point, set the label, and play a click ripple.
  func showClick(_ label: String, at point: CGPoint) {
    onMain {
      self.placeCursor(at: point, animated: true, label: label)
      self.ripple(at: point)
      self.bounce()
      self.scheduleHide()
    }
  }

  /// Animate a drag from one point to another over `duration` seconds.
  func showDrag(_ label: String, from: CGPoint, to: CGPoint, duration: Double) {
    onMain {
      self.placeCursor(at: from, animated: true, label: label)
      self.ripple(at: from)
      self.placeCursor(at: to, animated: true, label: label, duration: max(0.2, duration))
      self.scheduleHide()
    }
  }

  /// Show a fixed, click-through status panel so progress remains visible when Terminal is hidden.
  func showStatus(title: String, body: String) {
    onMain {
      self.setStatus(title: title, body: body)
    }
  }

  func hideStatus() {
    onMain {
      self.statusContainer?.opacity = 0
    }
  }

  // MARK: - Internals (main thread only)

  private func placeCursor(
    at point: CGPoint, animated: Bool, label: String, duration: Double = 0.22
  ) {
    guard let cursor = cursorLayer else { return }
    cancelHide()
    let p = toView(point)

    CATransaction.begin()
    CATransaction.setAnimationDuration(animated ? duration : 0)
    CATransaction.setAnimationTimingFunction(CAMediaTimingFunction(name: .easeInEaseOut))
    cursor.position = p
    cursor.opacity = 1
    positionLabel(under: p)
    CATransaction.commit()

    setLabel(label)
  }

  private func positionLabel(under p: CGPoint) {
    guard let pill = labelContainer, let text = labelText else { return }
    let width: CGFloat = 170
    let height: CGFloat = 18
    pill.bounds = CGRect(x: 0, y: 0, width: width, height: height)
    pill.position = CGPoint(x: p.x, y: p.y - radius - 15)
    text.frame = CGRect(x: 7, y: 2, width: width - 14, height: height - 4)
  }

  private func setLabel(_ label: String) {
    guard let pill = labelContainer, let text = labelText else { return }
    text.string = label
    pill.opacity = label.isEmpty ? 0 : 1
  }

  private func setStatus(title: String, body: String) {
    guard let panel = statusContainer, let titleLayer = statusTitle, let bodyLayer = statusBody,
      let host = hostLayer
    else {
      return
    }
    let margin: CGFloat = 18
    let width = min(CGFloat(420), max(CGFloat(280), host.bounds.width - margin * 2))
    let height: CGFloat = 108
    panel.bounds = CGRect(x: 0, y: 0, width: width, height: height)
    panel.position = CGPoint(x: margin + width / 2, y: host.bounds.height - margin - height / 2)
    titleLayer.frame = CGRect(x: 14, y: height - 30, width: width - 28, height: 18)
    bodyLayer.frame = CGRect(x: 14, y: 12, width: width - 28, height: height - 44)
    titleLayer.string = title
    bodyLayer.string = body
    panel.opacity = 1
  }

  private func ripple(at point: CGPoint) {
    guard let host = hostLayer else { return }
    let p = toView(point)
    let d = radius * 2.2
    let ripple = CAShapeLayer()
    ripple.path = CGPath(ellipseIn: CGRect(x: 0, y: 0, width: d, height: d), transform: nil)
    ripple.bounds = CGRect(x: 0, y: 0, width: d, height: d)
    ripple.position = p
    ripple.fillColor = NSColor.clear.cgColor
    ripple.strokeColor = accent.cgColor
    ripple.lineWidth = 2
    host.addSublayer(ripple)

    let scale = CABasicAnimation(keyPath: "transform.scale")
    scale.fromValue = 0.4
    scale.toValue = 1.7
    let fade = CABasicAnimation(keyPath: "opacity")
    fade.fromValue = 0.85
    fade.toValue = 0
    let group = CAAnimationGroup()
    group.animations = [scale, fade]
    group.duration = 0.5
    group.timingFunction = CAMediaTimingFunction(name: .easeOut)
    group.isRemovedOnCompletion = true
    ripple.opacity = 0
    ripple.add(group, forKey: "ripple")

    DispatchQueue.main.asyncAfter(deadline: .now() + 0.55) { ripple.removeFromSuperlayer() }
  }

  private func bounce() {
    guard let cursor = cursorLayer else { return }
    let bounce = CAKeyframeAnimation(keyPath: "transform.scale")
    bounce.values = [1.0, 0.82, 1.0]
    bounce.keyTimes = [0, 0.4, 1.0]
    bounce.duration = 0.26
    bounce.timingFunction = CAMediaTimingFunction(name: .easeOut)
    cursor.add(bounce, forKey: "bounce")
  }

  /// Cancel any pending fade and make the cursor/label fully visible.
  private func cancelHide() {
    hideWork?.cancel()
    hideWork = nil
    cursorLayer?.removeAnimation(forKey: "hide")
    labelContainer?.removeAnimation(forKey: "hide")
  }

  /// After the linger interval, fade the cursor and label out.
  private func scheduleHide() {
    hideWork?.cancel()
    let work = DispatchWorkItem { [weak self] in self?.fadeOut() }
    hideWork = work
    DispatchQueue.main.asyncAfter(deadline: .now() + holdSeconds, execute: work)
  }

  private func fadeOut() {
    for layer in [cursorLayer, labelContainer].compactMap({ $0 }) {
      let fade = CABasicAnimation(keyPath: "opacity")
      fade.fromValue = layer.presentation()?.opacity ?? layer.opacity
      fade.toValue = 0
      fade.duration = fadeSeconds
      fade.timingFunction = CAMediaTimingFunction(name: .easeOut)
      fade.fillMode = .forwards
      fade.isRemovedOnCompletion = false
      layer.add(fade, forKey: "hide")
      layer.opacity = 0
    }
  }

  private func toView(_ p: CGPoint) -> CGPoint {
    CGPoint(x: p.x, y: screenHeight - p.y)
  }

  private func onMain(_ work: @escaping () -> Void) {
    if Thread.isMainThread {
      work()
    } else {
      DispatchQueue.main.async(execute: work)
    }
  }
}
