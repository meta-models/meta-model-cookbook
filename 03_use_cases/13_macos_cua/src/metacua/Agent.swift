import AppKit
import CoreGraphics
import Foundation

/// The self-contained computer-use agent: screenshot, send to Muse Spark with GUI tools, execute returned tool calls, and feed back a fresh screenshot each step.
final class Agent {
  private let config: AgentConfig
  private let backend: LLMBackend
  private let manipulation: ManipulationBackend
  private let overlay: OverlayController?
  private let maxSteps: Int?
  private let coordSpace: CoordSpace
  private let screenshotScale: Double
  private let plansBeforeActing: Bool
  private let logger: AgentLogger

  private var lastPoint: CGPoint
  private let settleMicros: useconds_t = 450_000
  private var screenW = 0
  private var screenH = 0
  /// Trace id (goal id) of the most recent run, used to auto-render the HTML timeline.
  private(set) var lastGoalId: String?

  init(
    config: AgentConfig,
    backend: LLMBackend,
    manipulation: ManipulationBackend,
    overlay: OverlayController?,
    maxSteps: Int?,
    screenshotScale: Double,
    plansBeforeActing: Bool,
    logger: @escaping AgentLogger = defaultAgentLogger
  ) {
    self.config = config
    self.backend = backend
    self.manipulation = manipulation
    self.overlay = overlay
    self.maxSteps = maxSteps
    self.coordSpace = backend.coordSpace
    self.screenshotScale = screenshotScale
    self.plansBeforeActing = plansBeforeActing
    self.logger = logger
    if let screen = primaryScreen() {
      lastPoint = CGPoint(x: screen.frame.width / 2, y: screen.frame.height / 2)
    } else {
      lastPoint = CGPoint(x: 400, y: 300)
    }
  }

  // MARK: - Loop

  func run(goal: String) throws {
    if manipulation.requiresScreenRecording {
      try requireScreenRecording()
    }
    log(.goal, goal)
    let shot = try manipulation.screenshot(scale: screenshotScale)
    log(
      .status,
      "screenshot \(shot.imageWidth)x\(shot.imageHeight) image, \(shot.width)x\(shot.height) coords (\(shot.pngBase64.count / 1024) KB b64)"
    )
    screenW = shot.width
    screenH = shot.height
    let system = systemPrompt(
      width: shot.width,
      height: shot.height,
      imageWidth: shot.imageWidth,
      imageHeight: shot.imageHeight
    )
    var conversation = conversationForRequest(
      backend.initialConversation(goalText: goal, screenshot: shot)
    )
    let goalId = UUID().uuidString
    lastGoalId = goalId
    saveScreenshot(shot, goalId: goalId, label: "initial")
    if plansBeforeActing {
      showInitialPlan(system: system, conversation: conversation)
    }

    var step = 1
    while maxSteps.map({ step <= $0 }) ?? true {
      log(.status, "step \(step): calling \(backend.label)")
      overlayStatus(title: "Thinking", body: "Step \(step): choosing the next action.")
      let requestConversation = conversationForRequest(conversation)
      conversation = requestConversation
      let result = try backend.send(
        system: system,
        conversation: requestConversation
      )
      recordLLMCall(
        goalId: goalId,
        goal: goal,
        step: step,
        requestConversation: requestConversation,
        result: result
      )

      if !result.thinking.isEmpty { log(.thinking, result.thinking) }
      if !result.text.isEmpty { log(.message, result.text) }

      switch result.finish {
      case "refusal":
        overlayStatus(title: "Stopped", body: "Model refused the request.")
        log(.error, "model refused: \(result.refusalReason ?? result.text)")
        return
      case "max_tokens":
        overlayStatus(title: "Stopped", body: "Response was truncated at the token cap.")
        log(.warning, "response truncated at the token cap (step \(step)); stopping.")
        return
      default:
        break
      }

      if result.toolCalls.isEmpty {
        overlayStatus(
          title: "Done", body: result.text.isEmpty ? "Task finished." : clipped(result.text))
        log(.success, "done (step \(step))")
        return
      }

      if let stopCall = result.toolCalls.first(where: { isStopToolName($0.name) }) {
        let answer = ((stopCall.input["answer"] as? String) ?? "")
          .trimmingCharacters(in: .whitespacesAndNewlines)
        if !answer.isEmpty {
          log(.answer, answer)
        }
        overlayStatus(
          title: "Done",
          body: answer.isEmpty ? "Task finished." : clipped(answer))
        log(.success, "done (step \(step))")
        return
      }

      conversation.append(contentsOf: result.historyItems)

      var runs: [ToolRun] = []
      for call in result.toolCalls {
        var text: String
        var isError = false
        let summary = toolSummary(call)
        overlayStatus(title: "Acting", body: "Step \(step): \(summary)")
        log(.tool, "\(call.name)\(compactJSON(call.input).map { " \($0)" } ?? "")")
        do {
          text = try execute(name: call.name, input: call.input)
          log(.status, "tool result: \(text)")
        } catch let error as CLIError {
          if error.code == 3 { throw error }
          text = "error: \(error.message)"
          isError = true
          log(.warning, text)
        } catch {
          text = "error: \(error)"
          isError = true
          log(.warning, text)
        }
        runs.append(ToolRun(callId: call.id, name: call.name, output: text, isError: isError))
      }
      usleep(settleMicros)
      let after = try? manipulation.screenshot(scale: screenshotScale)
      if let after {
        saveScreenshot(after, goalId: goalId, label: "step-\(String(format: "%03d", step))")
      }
      conversation.append(contentsOf: backend.toolResultItems(runs, screenshot: after))
      step += 1
    }
    if let maxSteps {
      overlayStatus(
        title: "Stopped", body: "Reached max steps (\(maxSteps)) without finishing.")
      log(.warning, "reached max steps (\(maxSteps)) without finishing")
    }
  }

  // MARK: - Tool execution

  private func execute(name: String, input: [String: Any]) throws -> String {
    if manipulation.requiresAccessibility && toolRequiresAccessibility(name: name, input: input) {
      try requireTrust()
    }
    switch name {
    case "computer.computer", "computer", "computer_computer":
      return try executeComputerTool(input)

    case "computer.stop", "stop", "computer_stop":
      return (input["answer"] as? String) ?? "DONE"

    case "screenshot":
      overlay?.showAction("look", at: lastPoint)
      return "Captured a fresh screenshot."

    case "moveto":
      let point = try point(input, "x", "y")
      lastPoint = point
      overlay?.showAction("move", at: point)
      try manipulation.move(to: point)
      return "Moved pointer to (\(coord(point.x)), \(coord(point.y)))."

    case "click":
      let point = try point(input, "x", "y")
      let button = try MouseButton.parse((input["button"] as? String) ?? "left")
      let clicks = clampInt(num(input["clicks"]), 1, 3, default: 1)
      lastPoint = point
      let label =
        clicks >= 3
        ? "triple-click"
        : clicks == 2
          ? "double-click"
          : button == .right
            ? "right-click"
            : button == .center ? "middle-click" : "click"
      overlay?.showClick(label, at: point)
      try manipulation.click(at: point, button: button, clickCount: clicks)
      return "\(label) at (\(coord(point.x)), \(coord(point.y)))."

    case "scroll":
      let direction = try ScrollDirection.parse(try string(input, "direction"))
      let pages = clampInt(num(input["pages"]), 1, 100, default: 1)
      var point: CGPoint?
      if input["x"] != nil || input["y"] != nil {
        let pt = try self.point(input, "x", "y")
        point = pt
        lastPoint = pt
      }
      overlay?.showAction("scroll \(direction.rawValue)", at: point ?? lastPoint)
      try manipulation.scroll(direction: direction, pages: pages, linesPerPage: 10, at: point)
      return "Scrolled \(direction.rawValue) \(pages) page(s)."

    case "drag":
      let from = try point(input, "from_x", "from_y")
      let to = try point(input, "to_x", "to_y")
      let button = try MouseButton.parse((input["button"] as? String) ?? "left")
      lastPoint = to
      overlay?.showDrag("drag", from: from, to: to, duration: 0.5)
      try manipulation.drag(from: from, to: to, button: button)
      return
        "Dragged from (\(coord(from.x)), \(coord(from.y))) to (\(coord(to.x)), \(coord(to.y)))."

    case "press_key":
      let key = try string(input, "key")
      overlay?.showAction("key \(key)", at: lastPoint)
      try manipulation.pressKey(key)
      return "Pressed \(key)."

    case "type_text":
      let text = normalizedTypedText(try string(input, "text"))
      let preview = text.count > 30 ? String(text.prefix(30)) + "..." : text
      overlay?.showAction("type: \(preview)", at: lastPoint)
      try manipulation.typeText(text)
      return "Inserted \(text.count) character(s)."

    case "bash":
      let command = try string(input, "command")
      let timeoutMS = clampInt(num(input["timeout_ms"]), 1_000, 120_000, default: 20_000)
      overlay?.showAction("bash", at: lastPoint)
      return try runBashTool(command: command, timeoutMS: timeoutMS)

    case "wait":
      let ms = clampInt(num(input["ms"]), 0, 10_000, default: 500)
      overlay?.showAction("wait \(ms)ms", at: lastPoint)
      try manipulation.wait(ms: ms)
      return "Waited \(ms)ms."

    default:
      throw CLIError("unknown tool '\(name)'")
    }
  }

  // MARK: - Helpers

  private func point(_ input: [String: Any], _ xKey: String, _ yKey: String) throws -> CGPoint {
    guard let rx = num(input[xKey]), let ry = num(input[yKey]) else {
      throw CLIError("missing numeric '\(xKey)'/'\(yKey)'")
    }
    guard rx.isFinite, ry.isFinite else { throw CLIError("non-finite coordinates") }

    var x = rx
    var y = ry
    if coordSpace == .normalized1000 {
      x = rx / 1000.0 * Double(max(1, screenW))
      y = ry / 1000.0 * Double(max(1, screenH))
    }
    let cx = screenW > 0 ? min(max(0, x), Double(screenW - 1)) : x
    let cy = screenH > 0 ? min(max(0, y), Double(screenH - 1)) : y
    return CGPoint(x: cx, y: cy)
  }

  private func relativePoint(_ value: Any?, field: String = "coordinate") throws -> CGPoint {
    guard let values = value as? [Any], values.count == 2 else {
      throw CLIError("missing relative \(field) [x, y]")
    }
    guard let rx = num(values[0]), let ry = num(values[1]) else {
      throw CLIError("relative \(field) must contain numeric x/y values")
    }
    guard rx.isFinite, ry.isFinite else {
      throw CLIError("non-finite relative \(field)")
    }
    let x = rx / 1000.0 * Double(max(1, screenW))
    let y = ry / 1000.0 * Double(max(1, screenH))
    let cx = screenW > 0 ? min(max(0, x), Double(screenW - 1)) : x
    let cy = screenH > 0 ? min(max(0, y), Double(screenH - 1)) : y
    return CGPoint(x: cx, y: cy)
  }

  private func string(_ input: [String: Any], _ key: String) throws -> String {
    guard let value = input[key] as? String else { throw CLIError("missing string '\(key)'") }
    return value
  }

  private func num(_ any: Any?) -> Double? {
    if let number = any as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() {
      return number.doubleValue
    }
    if let double = any as? Double { return double }
    if let int = any as? Int { return Double(int) }
    if let string = any as? String, let double = Double(string), double.isFinite { return double }
    return nil
  }

  private func clampInt(_ value: Double?, _ lo: Int, _ hi: Int, default def: Int) -> Int {
    guard let value, value.isFinite else { return def }
    return Int(min(Double(hi), max(Double(lo), value.rounded())))
  }

  private func coord(_ value: CGFloat) -> String { String(format: "%.0f", value.rounded()) }

  private func log(_ kind: AgentLogKind, _ message: String) {
    logger(kind, message)
  }

  private func isStopToolName(_ name: String) -> Bool {
    ["computer.stop", "computer_stop", "stop"].contains(name)
  }

  private func toolRequiresAccessibility(name: String, input: [String: Any]) -> Bool {
    switch name {
    case "screenshot", "wait", "bash", "computer.stop", "computer_stop", "stop":
      return false
    case "computer.computer", "computer", "computer_computer":
      let actions = (try? normalizedComputerActions(input)) ?? []
      return actions.contains { action in
        let actionName = action["action"] as? String
        return actionName != "screenshot" && actionName != "wait"
      }
    default:
      return true
    }
  }

  private func executeComputerTool(_ input: [String: Any]) throws -> String {
    let wasBatchedCall = input["actions"] != nil
    let actions = try normalizedComputerActions(input)
    guard !actions.isEmpty else {
      throw CLIError("`actions` must be a non-empty list")
    }
    for (index, action) in actions.enumerated() {
      do {
        try executeComputerAction(action)
      } catch let error as CLIError {
        throw CLIError("Action [\(index)] (\(action["action"] ?? "?")): \(error.message)")
      }
    }
    if !config.batchedActions, !wasBatchedCall, actions.count == 1 {
      return "Action executed: \(singleComputerActionDescription(actions[0]))"
    }
    let descriptions =
      actions
      .map(computerActionDescription)
      .joined(separator: ", ")
    return "Batch executed: computer(actions=[\(descriptions)])"
  }

  private func normalizedComputerActions(_ input: [String: Any]) throws -> [[String: Any]] {
    if let actionsString = input["actions"] as? String {
      guard
        let data = actionsString.data(using: .utf8),
        let actions = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
      else {
        throw CLIError("`actions` must decode to a list of objects")
      }
      return actions
    }
    if let actions = input["actions"] as? [[String: Any]] {
      return actions
    }
    if input["action"] != nil {
      return [input]
    }
    return []
  }

  private func executeComputerAction(_ action: [String: Any]) throws {
    let actionName = try string(action, "action")
    switch actionName {
    case "screenshot":
      overlay?.showAction("look", at: lastPoint)

    case "mouse_move":
      let point = try relativePoint(action["coordinate"])
      lastPoint = point
      overlay?.showAction("move", at: point)
      try manipulation.move(to: point)

    case "left_click", "right_click", "middle_click", "double_click", "triple_click":
      try withHeldModifier(action["text"] as? String) {
        let point = try optionalRelativePoint(action["coordinate"]) ?? lastPoint
        lastPoint = point
        let button = computerMouseButton(for: actionName)
        let clicks = computerClickCount(for: actionName)
        overlay?.showClick(actionLabel(for: actionName), at: point)
        try manipulation.click(at: point, button: button, clickCount: clicks)
      }

    case "left_press":
      try withHeldModifier(action["text"] as? String) {
        let point = try optionalRelativePoint(action["coordinate"]) ?? lastPoint
        lastPoint = point
        overlay?.showClick("press", at: point)
        try manipulation.mouseDown(at: point, button: .left)
        try manipulation.wait(ms: 1_000)
        try manipulation.mouseUp(at: point, button: .left)
      }

    case "left_click_drag":
      let to = try relativePoint(action["coordinate"])
      let from = try optionalRelativePoint(action["start_coordinate"]) ?? lastPoint
      lastPoint = to
      overlay?.showDrag("drag", from: from, to: to, duration: 0.5)
      try manipulation.drag(from: from, to: to, button: .left)

    case "key":
      let key = try string(action, "text")
      overlay?.showAction("key \(key)", at: lastPoint)
      try manipulation.pressKey(key)

    case "type":
      let text = normalizedTypedText(try string(action, "text"))
      overlay?.showAction("type: \(clipped(text, maxLength: 40))", at: lastPoint)
      try manipulation.typeText(text)

    case "hold_key":
      let key = try string(action, "text")
      overlay?.showAction("hold \(key)", at: lastPoint)
      try manipulation.keyDown(key)

    case "release_key":
      let key = try string(action, "text")
      overlay?.showAction("release \(key)", at: lastPoint)
      try manipulation.keyUp(key)

    case "left_mouse_down":
      let point = try optionalRelativePoint(action["coordinate"]) ?? lastPoint
      lastPoint = point
      overlay?.showAction("mouse down", at: point)
      try manipulation.mouseDown(at: point, button: .left)

    case "left_mouse_up":
      let point = try optionalRelativePoint(action["coordinate"]) ?? lastPoint
      lastPoint = point
      overlay?.showAction("mouse up", at: point)
      try manipulation.mouseUp(at: point, button: .left)

    case "scroll":
      try withHeldModifier(action["text"] as? String) {
        let direction = try ScrollDirection.parse(try string(action, "scroll_direction"))
        let amount = clampInt(num(action["scroll_amount"]), 1, 100, default: 3)
        let point = try optionalRelativePoint(action["coordinate"])
        if let point {
          lastPoint = point
        }
        overlay?.showAction("scroll \(direction.rawValue)", at: point ?? lastPoint)
        try manipulation.scroll(direction: direction, pages: amount, linesPerPage: 1, at: point)
      }

    case "wait":
      let duration = num(action["duration"]) ?? 0.5
      let ms = Int(min(10_000, max(0, duration * 1000).rounded()))
      overlay?.showAction("wait \(ms)ms", at: lastPoint)
      try manipulation.wait(ms: ms)

    default:
      throw CLIError("Invalid action: \(actionName)")
    }
  }

  private func optionalRelativePoint(_ value: Any?) throws -> CGPoint? {
    guard value != nil, !(value is NSNull) else { return nil }
    return try relativePoint(value)
  }

  private func withHeldModifier(_ keys: String?, run action: () throws -> Void) throws {
    guard let keys, !keys.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
      try action()
      return
    }
    try manipulation.keyDown(keys)
    defer { try? manipulation.keyUp(keys) }
    try action()
  }

  private func computerMouseButton(for action: String) -> MouseButton {
    switch action {
    case "right_click": return .right
    case "middle_click": return .center
    default: return .left
    }
  }

  private func computerClickCount(for action: String) -> Int {
    switch action {
    case "double_click": return 2
    case "triple_click": return 3
    default: return 1
    }
  }

  private func actionLabel(for action: String) -> String {
    switch action {
    case "left_click": return "click"
    case "right_click": return "right click"
    case "middle_click": return "middle click"
    case "double_click": return "double click"
    case "triple_click": return "triple click"
    default: return action.replacingOccurrences(of: "_", with: " ")
    }
  }

  private func computerActionDescription(_ action: [String: Any]) -> String {
    let actionName = String(describing: action["action"] ?? "?")
    let coordinate = coordinateText(action["coordinate"])
    let startCoordinate = coordinateText(action["start_coordinate"])
    let text = (action["text"] as? String).map {
      quotedPreview(normalizedTypedText($0), maxLength: 40)
    }
    switch actionName {
    case "screenshot":
      return "look at the screen"
    case "mouse_move":
      return "move pointer\(coordinate.map { " to \($0)" } ?? "")"
    case "left_click", "right_click", "middle_click", "double_click", "triple_click":
      return "\(actionLabel(for: actionName))\(coordinate.map { " at \($0)" } ?? "")"
    case "left_press":
      return "press mouse\(coordinate.map { " at \($0)" } ?? "")"
    case "left_click_drag":
      let from = startCoordinate.map { " from \($0)" } ?? ""
      let to = coordinate.map { " to \($0)" } ?? ""
      return "drag\(from)\(to)"
    case "key":
      return "press key\(text.map { " \($0)" } ?? "")"
    case "type":
      return "type\(text.map { " \($0)" } ?? "")"
    case "hold_key":
      return "hold key\(text.map { " \($0)" } ?? "")"
    case "release_key":
      return "release key\(text.map { " \($0)" } ?? "")"
    case "left_mouse_down":
      return "mouse down\(coordinate.map { " at \($0)" } ?? "")"
    case "left_mouse_up":
      return "mouse up\(coordinate.map { " at \($0)" } ?? "")"
    case "scroll":
      let direction = action["scroll_direction"] as? String ?? "unknown"
      let amount = Int(num(action["scroll_amount"]) ?? 3)
      return "scroll \(direction) \(amount)x\(coordinate.map { " at \($0)" } ?? "")"
    case "wait":
      let duration = num(action["duration"]) ?? 0.5
      return "wait \(String(format: "%.1f", duration))s"
    default:
      return actionName.replacingOccurrences(of: "_", with: " ")
    }
  }

  private func coordinateText(_ value: Any?) -> String? {
    guard let values = value as? [Any], values.count == 2,
      let x = num(values[0]), let y = num(values[1])
    else {
      return nil
    }
    return "[\(Int(x.rounded())), \(Int(y.rounded()))]"
  }

  private func singleComputerActionDescription(_ action: [String: Any]) -> String {
    "computer(action=\(computerActionDescription(action)))"
  }

  private func overlayStatus(title: String, body: String) {
    overlay?.showStatus(title: title, body: clipped(body, maxLength: 220))
  }

  private func conversationForRequest(_ conversation: [[String: Any]]) -> [[String: Any]] {
    retainMostRecentImages(in: conversation, maxImages: config.maxImages)
  }

  private func showInitialPlan(system: String, conversation: [[String: Any]]) {
    overlayStatus(title: "Planning", body: "Reading the screen and preparing a plan.")
    do {
      guard let plan = try backend.plan(system: system, conversation: conversation), !plan.isEmpty
      else {
        return
      }
      log(.plan, plan)
      overlayStatus(title: "Plan", body: plan)
    } catch let error as CLIError {
      log(.warning, "could not create plan: \(error.message)")
    } catch {
      log(.warning, "could not create plan: \(error)")
    }
  }

  private func recordLLMCall(
    goalId: String,
    goal: String,
    step: Int,
    requestConversation: [[String: Any]],
    result: LLMResult
  ) {
    do {
      let stored = try SessionStore.shared.appendLLMCall(
        config: config,
        backendLabel: backend.label,
        goalId: goalId,
        goal: goal,
        step: step,
        requestConversation: requestConversation,
        result: result
      )
      log(.status, "saved llm session \(stored.displayId) in \(stored.storagePath)")
    } catch let error as CLIError {
      log(.warning, "could not save llm session: \(error.message)")
    } catch {
      log(.warning, "could not save llm session: \(error)")
    }
  }

  private func saveScreenshot(_ screenshot: Screenshot, goalId: String, label: String) {
    do {
      let url = try ScreenshotStore.save(screenshot, goalId: goalId, label: label)
      log(.status, "saved screenshot \(label) -> \(url.path)")
    } catch let error as CLIError {
      log(.warning, "could not save screenshot: \(error.message)")
    } catch {
      log(.warning, "could not save screenshot: \(error)")
    }
  }

  private func compactJSON(_ value: [String: Any]) -> String? {
    guard !value.isEmpty,
      JSONSerialization.isValidJSONObject(value),
      let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
      let text = String(data: data, encoding: .utf8)
    else {
      return nil
    }
    return text
  }

  private func toolSummary(_ call: LLMToolCall) -> String {
    switch call.name {
    case "computer.computer", "computer", "computer_computer":
      let actions = (try? normalizedComputerActions(call.input)) ?? []
      guard let first = actions.first else { return "Running computer actions." }
      if actions.count == 1 {
        return "Running \(computerActionDescription(first))."
      }
      return "Running \(actions.count) computer actions."
    case "computer.stop", "computer_stop", "stop":
      return "Finishing the task."
    case "screenshot":
      return "Looking at the current screen."
    case "moveto":
      return "Moving the pointer."
    case "click":
      return "Clicking at the target location."
    case "scroll":
      let direction = call.input["direction"] as? String ?? ""
      return direction.isEmpty ? "Scrolling." : "Scrolling \(direction)."
    case "drag":
      return "Dragging between two points."
    case "press_key":
      let key = call.input["key"] as? String ?? ""
      return key.isEmpty ? "Pressing a key." : "Pressing \(key)."
    case "type_text":
      let text = call.input["text"] as? String ?? ""
      let preview = text.isEmpty ? "" : ": " + clipped(text, maxLength: 60)
      return "Inserting text\(preview)"
    case "wait":
      return "Waiting for the UI to update."
    default:
      return "Running \(call.name)."
    }
  }

  private func clipped(_ text: String, maxLength: Int = 180) -> String {
    let oneLine = text.replacingOccurrences(of: "\n", with: " ")
      .trimmingCharacters(in: .whitespacesAndNewlines)
    guard oneLine.count > maxLength else { return oneLine }
    return String(oneLine.prefix(max(0, maxLength - 3))) + "..."
  }

  private func quotedPreview(_ text: String, maxLength: Int = 180) -> String {
    let preview = clipped(text, maxLength: maxLength)
    if let data = try? JSONEncoder().encode(preview),
      let encoded = String(data: data, encoding: .utf8)
    {
      return encoded
    }
    return String(reflecting: preview)
  }

  private func normalizedTypedText(_ text: String) -> String {
    guard
      text.contains("\\\"") || text.contains("\\n") || text.contains("\\r")
        || text.contains("\\t")
    else {
      return text
    }
    let escapedControls =
      text
      .replacingOccurrences(of: "\n", with: "\\n")
      .replacingOccurrences(of: "\r", with: "\\r")
      .replacingOccurrences(of: "\t", with: "\\t")
    let candidate = "\"\(escapedControls)\""
    guard
      let data = candidate.data(using: .utf8),
      let decoded = try? JSONSerialization.jsonObject(with: data) as? String
    else {
      return text
    }
    return decoded
  }

  private func systemPrompt(width: Int, height: Int, imageWidth: Int, imageHeight: Int) -> String {
    let coordDesc: String
    switch coordSpace {
    case .pixel:
      coordDesc =
        "The screenshot image is \(imageWidth)x\(imageHeight), downsampled from a \(width)x\(height) logical display coordinate space. Coordinates are logical display pixels with the origin at the top-left; pass integer coordinates inside 0..\(width - 1) / 0..\(height - 1)."
    case .normalized1000:
      coordDesc =
        "The screenshot image is \(imageWidth)x\(imageHeight), downsampled from a \(width)x\(height) logical display coordinate space. Coordinates are normalized to a 0-1000 scale with the origin at the top-left: (0,0) is the top-left corner and (1000,1000) is the bottom-right corner. X increases left-to-right, Y top-to-bottom."
    }
    let actionStrategy =
      config.batchedActions
      ? """
      - Batch actions whose outcome you can predict into a SINGLE `computer.computer` \
      tool call via the `actions` array. Each tool call has latency overhead, so \
      batching is more efficient.
      - Only use a separate call when you need to observe the screen before deciding \
      the next step.
      - Example: `actions=[{"action": "left_click", "coordinate": [300, 200]}, \
      {"action": "type", "text": "hello"}, {"action": "key", "text": "Tab"}, \
      {"action": "type", "text": "world"}]`
      - For form filling, keyboard shortcuts, and text editing, you almost never need \
      a screenshot between actions. Batch them together.
      """
      : """
      - Focus on ONE action at a time.
      - Only use the tools available to you.
      - After each action, a screenshot is automatically returned showing the result.
      """

    return """
      Current date: \(currentDateText()).

      You are an AI assistant specialized in computer use.
      You perceive the screen via screenshots and control the desktop using a fixed set of APIs.

      <SYSTEM_CAPABILITY>
      * You are using the user's current macOS machine.
      * DO NOT ask users for clarification. Take action using available tools.
      * Note: the machine's timezone may differ from the user's expectation. Check the visible clock if precise local time matters.
      * Home directory of this system is '\(FileManager.default.homeDirectoryForCurrentUser.path)'.
      * This controls the user's actual machine. Be deliberate and avoid irreversible actions unless the goal clearly requires them.
      </SYSTEM_CAPABILITY>

      # Available Tools
      The tool schema is provided separately by the API. Use `computer.computer` for computer actions and `computer.stop` when the task is complete or you cannot proceed safely.
      For `type` actions, put the literal text to paste in `text`; do not add backslashes before quotes unless those backslashes should visibly appear.
      Stop when you finish.

      # Screen And Coordinates
      \(coordDesc) Always read coordinates off the screenshot rather than guessing.

      # Task Execution Strategy
      \(actionStrategy)
      - When you believe the task is done, VERIFY the result before saving. Take a screenshot and confirm the change covers the ENTIRE target, not just part of it.
      - If you notice something is incomplete or wrong during verification, fix it before proceeding.

      # macOS Environment Notes (IMPORTANT)
      You were trained mainly on Ubuntu, but you are now operating a macOS machine. Follow these macOS-specific rules:

      ## 1. Input Method (IME) - never assume English
      - The active input source may not be English. It could be Chinese, Japanese, Korean, or another IME.
      - Check the input source indicator in the menu bar before typing. If you need English input but an IME is active, switch the input source first.
      - Common input-source switch keys are Ctrl+Space, Caps Lock, or the Fn/Globe key, depending on system settings. Verify the switch succeeded before typing.
      - When you need to type Chinese with an IME, type the pinyin and inspect the candidate window. The text is not committed until you pick a candidate.
      - Select the correct candidate by pressing its number key, usually 1-9, or Space for the first candidate. If the target word is not shown, use +/- or arrow keys to page through candidates.
      - After typing, visually verify that the committed text on screen matches what you intended. Uncommitted pinyin or a wrong candidate is a common failure mode.

      ## 2. You start inside Terminal
      - The session usually begins with a Terminal window focused. Before interacting with another app or the desktop, move focus away from Terminal.
      - Ways to switch focus: Cmd+Tab to cycle between apps, click the target window, use Spotlight to launch an app, or run `open -a "AppName"` from Terminal and then switch to it.
      - Never send GUI-intended keystrokes while Terminal still has focus. They will be typed into the shell instead.

      ## 3. Opening files - do not use Spotlight
      - Never use Spotlight Search, Cmd+Space, to open specific files. Use Spotlight for launching apps only.
      - Terminal file opening: `open /path/to/file` for the default app, `open -a "AppName" /path/to/file` for a specific app, or `open -R /path/to/file` to reveal it in Finder.
      - Finder file opening: navigate to the file manually, use Finder search for the exact name, or use Cmd+Shift+G to jump directly to a folder path.
      - If an app shows an Open or Save dialog, drag the target file into the dialog to jump to its folder.
      - Press Space on a selected file for Quick Look preview.
      - Cmd+Shift+. shows or hides hidden files in Finder.
      - To rename multiple files at once, select them, right-click, then choose Rename.

      ## 4. Useful macOS shortcuts and workflows
      - Cmd+Space can launch apps and evaluate calculator or unit-conversion queries. Remember: do not use it for specific files.
      - Cmd+Shift+4 then Space screenshots a specific window.
      - Cmd+Shift+5 opens the screenshot and screen-recording toolbar with options.
      - Cmd+Ctrl+Space opens the emoji and symbol picker anywhere you can type.
      - Cmd+Backtick cycles between windows of the same app.
      - Option+Cmd+Esc opens Force Quit for frozen apps.
      - Option+arrow jumps by word; Cmd+arrow jumps to line start or end.
      - Hold a letter key to get accented variants.
      - Text replacements can be customized in System Settings > Keyboard > Text Replacements.
      - Hold Option while clicking the Wi-Fi or Bluetooth menu bar icon for detailed diagnostics.
      - Hold Option while resizing a window to resize from the center; hold Shift to keep proportions.
      - Hot Corners are in System Settings > Desktop & Dock and can trigger actions such as locking the screen.
      - Cmd+click a folder name in a Finder window title bar to see the full path hierarchy.
      - Drag text onto the Notes or Mail icon in the Dock to create a new note or email with it.
      - `caffeinate` in Terminal keeps the Mac awake while it is running.

      <IMPORTANT>
      # 1. Understand The Task
      * Before acting, re-read the task instructions carefully. Pay attention to exact wording. Application-specific terms may differ from everyday language.
      * Follow the task literally. If a specific application is named, use that application. Do not substitute a faster tool or script.
      * Complete ALL requirements before stopping. If the task says "do X AND Y", both must be done.

      # 2. Verify. Never Guess, Believe, Or Assume
      * Every action that matters must be verified through a concrete check, not by interpreting ambiguous screenshots. If you find yourself thinking "probably worked", "appears to", "hard to tell", "seems like", or "better to trust", you have NOT verified.
      * After making a change, confirm it took effect by reading the result back through a different method than the one you used to make the change. Visual appearance alone is not sufficient when the task depends on exact state.
      * After completing a task, verify the visible or functional result.

      # 3. Interaction Principles
      * If an application is already open, use that instance. Do not launch a new instance via Open With from Finder. Use File > Open or drag-and-drop instead.
      * Do not guess or invent URLs. Use the site's visible navigation, menus, links, or search to find pages.
      * For precise text selection, use keyboard navigation such as arrow keys with Shift rather than guessing pixel coordinates between characters.

      # 4. Efficiency
      * For system and desktop settings, prefer the GUI Settings app. Verify that changes took effect in the GUI.
      * Once all requirements are met, save and stop. Do not add extra changes beyond what was asked.
      </IMPORTANT>
      """
  }

  private func currentDateText() -> String {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.dateFormat = "EEEE, MMMM d, yyyy"
    return formatter.string(from: Date())
  }
}

// MARK: - `metacua agent` entry point

private final class AgentSession {
  private let ui: TerminalUI
  private let overlayController: OverlayController?
  private let terminalAttention = TerminalAttention()

  private(set) var config: AgentConfig
  private(set) var maxSteps: Int?
  private(set) var overlayEnabled: Bool
  private(set) var planFirstEnabled: Bool
  private(set) var backendLabel: String
  private(set) var manipulationLabel: String

  private var agent: Agent

  init(
    config: AgentConfig,
    maxSteps: Int?,
    overlayEnabled: Bool,
    planFirstEnabled: Bool,
    overlayController: OverlayController?,
    ui: TerminalUI
  ) throws {
    self.config = config
    self.maxSteps = maxSteps
    self.overlayEnabled = overlayEnabled
    self.planFirstEnabled = planFirstEnabled
    self.overlayController = overlayController
    self.ui = ui

    let backend = makeBackend(config)
    let manipulation = try makeManipulationBackend(config)
    backendLabel = backend.label
    manipulationLabel = manipulation.label
    agent = Agent(
      config: config,
      backend: backend,
      manipulation: manipulation,
      overlay: overlayEnabled ? overlayController : nil,
      maxSteps: maxSteps,
      screenshotScale: config.screenshotScale,
      plansBeforeActing: planFirstEnabled,
      logger: ui.agentLog
    )
  }

  func printHeader() {
    ui.printHeader(
      config: config,
      backendLabel: backendLabel,
      manipulationLabel: manipulationLabel,
      maxSteps: maxSteps,
      overlay: overlayEnabled,
      planFirst: planFirstEnabled
    )
  }

  func runGoal(_ goal: String) {
    var completionKind: AgentLogKind = .success
    var completionMessage = "agent finished"
    defer {
      let suffix = terminalAttention.wake() ? "; terminal reactivated" : ""
      ui.agentLog(completionKind, completionMessage + suffix)
      renderTimeline()
    }

    do {
      if overlayEnabled {
        _ = terminalAttention.moveAside()
      }
      try agent.run(goal: goal)
    } catch let error as CLIError {
      completionKind = .warning
      completionMessage = "agent stopped after error"
      ui.agentLog(.error, error.message)
    } catch {
      completionKind = .warning
      completionMessage = "agent stopped after error"
      ui.agentLog(.error, "\(error)")
    }
  }

  /// After a run finishes, auto-render the trace into an HTML timeline next to the .jsonl.
  private func renderTimeline() {
    guard let goalId = agent.lastGoalId else { return }
    do {
      let out = try TraceHTML.render(traceId: goalId)
      ui.agentLog(.status, "rendered timeline: \(out.path)")
    } catch let error as CLIError {
      ui.agentLog(.warning, "could not render timeline: \(error.message)")
    } catch {
      ui.agentLog(.warning, "could not render timeline: \(error)")
    }
  }

  func setModel(_ value: String) throws -> String {
    let raw = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !raw.isEmpty else {
      throw CLIError("usage: /model <model-id>", code: 2)
    }
    config.model = raw == "muse-spark" ? AgentConfig.defaultModel : raw
    try rebuildAgent()
    return "model switched to \(config.model)"
  }

  func setEffort(_ value: String) throws -> String {
    let raw = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    guard ["low", "medium", "high", "xhigh", "max"].contains(raw) else {
      throw CLIError("usage: /effort <low|medium|high|xhigh|max>", code: 2)
    }
    config.effort = raw
    try rebuildAgent()
    return "effort set to \(raw)"
  }

  func setCoords(_ value: String) throws -> String {
    let raw = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard let coords = CoordSpace.parse(raw) else {
      throw CLIError("usage: /coords <pixel|normalized>", code: 2)
    }
    config.coords = coords
    try rebuildAgent()
    let label = coords == .normalized1000 ? "normalized" : "pixel"
    return "coordinates set to \(label)"
  }

  func setMaxSteps(_ value: String) throws -> String {
    let raw = value.trimmingCharacters(in: .whitespacesAndNewlines)
    if ["off", "none", "unlimited", "0"].contains(raw.lowercased()) {
      maxSteps = nil
      try rebuildAgent()
      return "max steps disabled"
    }
    guard let next = Int(raw), next >= 1 else {
      throw CLIError("usage: /max-steps <positive-integer|off>", code: 2)
    }
    maxSteps = next
    try rebuildAgent()
    return "max steps set to \(next)"
  }

  func setMaxImages(_ value: String) throws -> String {
    let raw = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard let next = Int(raw), next >= 1 else {
      throw CLIError("usage: /max-images <positive-integer>", code: 2)
    }
    config.maxImages = next
    try rebuildAgent()
    return "recent image limit set to \(next)"
  }

  func setBatchedActions(_ value: String) throws -> String {
    let raw = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let enabled: Bool
    switch raw {
    case "":
      enabled = !config.batchedActions
    case "on", "true", "yes", "1":
      enabled = true
    case "off", "false", "no", "0":
      enabled = false
    default:
      throw CLIError("usage: /batched-actions [on|off]", code: 2)
    }
    config.batchedActions = enabled
    try rebuildAgent()
    return "batched actions \(enabled ? "enabled" : "disabled")"
  }

  func setOverlay(_ value: String) throws -> String {
    let raw = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let enabled: Bool
    switch raw {
    case "on", "true", "yes", "1":
      enabled = true
    case "off", "false", "no", "0":
      enabled = false
    default:
      throw CLIError("usage: /overlay <on|off>", code: 2)
    }
    if enabled && overlayController == nil {
      throw CLIError(
        "overlay was disabled at launch; restart without --no-overlay to enable it", code: 2)
    }
    overlayEnabled = enabled
    try rebuildAgent()
    return "overlay \(enabled ? "enabled" : "disabled")"
  }

  func setPlanFirst(_ value: String) throws -> String {
    let raw = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let enabled: Bool
    switch raw {
    case "":
      enabled = !planFirstEnabled
    case "on", "true", "yes", "1":
      enabled = true
    case "off", "false", "no", "0":
      enabled = false
    default:
      throw CLIError("usage: /plan [on|off]", code: 2)
    }
    planFirstEnabled = enabled
    try rebuildAgent()
    return "plan-first \(enabled ? "enabled" : "disabled")"
  }

  func reset() throws -> String {
    try rebuildAgent()
    return "session context reset"
  }

  private func rebuildAgent() throws {
    let backend = makeBackend(config)
    let manipulation = try makeManipulationBackend(config)
    backendLabel = backend.label
    manipulationLabel = manipulation.label
    agent = Agent(
      config: config,
      backend: backend,
      manipulation: manipulation,
      overlay: overlayEnabled ? overlayController : nil,
      maxSteps: maxSteps,
      screenshotScale: config.screenshotScale,
      plansBeforeActing: planFirstEnabled,
      logger: ui.agentLog
    )
  }
}

func runAgent(_ raw: [String]) throws {
  let args = try Args(raw)

  let config = try resolveAgentConfig(args)
  let maxSteps = try args.int("max-steps")
  if let maxSteps, maxSteps < 1 {
    throw CLIError("--max-steps must be >= 1 (got \(maxSteps))", code: 2)
  }
  let useOverlay = !args.flag("no-overlay")
  let planFirst = !args.flag("no-plan")
  let goal = args.string("goal")

  let ui = TerminalUI()

  if useOverlay {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let overlay = OverlayController()
    let session = try AgentSession(
      config: config,
      maxSteps: maxSteps,
      overlayEnabled: useOverlay,
      planFirstEnabled: planFirst,
      overlayController: overlay,
      ui: ui
    )
    session.printHeader()

    DispatchQueue.global(qos: .userInitiated).async {
      runGoals(session: session, goal: goal, ui: ui)
      DispatchQueue.main.async { app.terminate(nil) }
    }
    app.run()
  } else {
    let session = try AgentSession(
      config: config,
      maxSteps: maxSteps,
      overlayEnabled: useOverlay,
      planFirstEnabled: planFirst,
      overlayController: nil,
      ui: ui
    )
    session.printHeader()
    runGoals(session: session, goal: goal, ui: ui)
  }
}

private func runGoals(session: AgentSession, goal: String?, ui: TerminalUI) {
  if let goal = goal {
    session.runGoal(goal)
    return
  }

  while true {
    guard let line = ui.prompt() else { break }
    let goal = line.trimmingCharacters(in: .whitespacesAndNewlines)
    if goal.isEmpty { continue }
    if goal == "quit" || goal == "exit" || goal == "/quit" || goal == "/exit" { break }
    if handleSlashCommand(goal, session: session, ui: ui) {
      continue
    }
    session.runGoal(goal)
  }
  ui.printGoodbye()
}

private func handleSlashCommand(_ input: String, session: AgentSession, ui: TerminalUI) -> Bool {
  guard input.hasPrefix("/") else { return false }
  let parts = input.split(whereSeparator: { $0 == " " || $0 == "\t" }).map(String.init)
  guard let command = parts.first?.lowercased() else { return true }
  let argument = parts.dropFirst().joined(separator: " ")

  do {
    switch command {
    case "/help", "/?":
      ui.printInteractiveHelp()
    case "/model":
      if argument.isEmpty {
        ui.printModel(config: session.config, backendLabel: session.backendLabel)
      } else {
        ui.agentLog(.success, try session.setModel(argument))
      }
    case "/effort":
      if argument.isEmpty {
        ui.agentLog(.message, "effort: \(session.config.effort)")
      } else {
        ui.agentLog(.success, try session.setEffort(argument))
      }
    case "/coords", "/coordinates":
      if argument.isEmpty {
        let label = session.config.coords == .normalized1000 ? "normalized" : "pixel"
        ui.agentLog(.message, "coordinates: \(label)")
      } else {
        ui.agentLog(.success, try session.setCoords(argument))
      }
    case "/max-steps", "/maxsteps":
      if argument.isEmpty {
        ui.agentLog(.message, "max steps: \(session.maxSteps.map(String.init) ?? "unlimited")")
      } else {
        ui.agentLog(.success, try session.setMaxSteps(argument))
      }
    case "/max-images", "/maximages":
      if argument.isEmpty {
        ui.agentLog(.message, "recent image limit: \(session.config.maxImages)")
      } else {
        ui.agentLog(.success, try session.setMaxImages(argument))
      }
    case "/batched-actions", "/batch-actions", "/batching":
      if argument.isEmpty {
        ui.agentLog(.message, "batched actions: \(session.config.batchedActions ? "on" : "off")")
      } else {
        ui.agentLog(.success, try session.setBatchedActions(argument))
      }
    case "/overlay":
      if argument.isEmpty {
        ui.agentLog(.message, "overlay: \(session.overlayEnabled ? "on" : "off")")
      } else {
        ui.agentLog(.success, try session.setOverlay(argument))
      }
    case "/plan":
      if argument.isEmpty {
        ui.agentLog(.message, "plan-first: \(session.planFirstEnabled ? "on" : "off")")
      } else {
        ui.agentLog(.success, try session.setPlanFirst(argument))
      }
    case "/status":
      ui.printStatus(
        config: session.config,
        backendLabel: session.backendLabel,
        manipulationLabel: session.manipulationLabel,
        maxSteps: session.maxSteps,
        overlay: session.overlayEnabled,
        planFirst: session.planFirstEnabled
      )
    case "/tools":
      ui.printTools(config: session.config)
    case "/doctor":
      ui.printDoctor(
        config: session.config,
        backendLabel: session.backendLabel,
        manipulationLabel: session.manipulationLabel,
        maxSteps: session.maxSteps,
        overlay: session.overlayEnabled,
        planFirst: session.planFirstEnabled
      )
    case "/config":
      ui.printConfig(
        config: session.config,
        backendLabel: session.backendLabel,
        manipulationLabel: session.manipulationLabel,
        maxSteps: session.maxSteps,
        overlay: session.overlayEnabled,
        planFirst: session.planFirstEnabled
      )
    case "/sessions", "/session-history", "/history":
      if argument.isEmpty {
        ui.printStoredSessions(limit: 10)
      } else if let limit = Int(argument), limit >= 0 {
        ui.printStoredSessions(limit: limit)
      } else {
        ui.printStoredSession(id: argument)
      }
    case "/permissions", "/permission":
      if parts.contains("--prompt") {
        _ = ensureTrusted(prompt: true)
        _ = ensureScreenRecording(prompt: true)
      }
      ui.printPermissions()
    case "/clear":
      ui.clearScreen()
      session.printHeader()
    case "/new", "/reset":
      ui.agentLog(.success, try session.reset())
    default:
      ui.agentLog(.warning, "unknown command \(command); type /help")
    }
  } catch let error as CLIError {
    ui.agentLog(.error, error.message)
  } catch {
    ui.agentLog(.error, "\(error)")
  }
  return true
}
