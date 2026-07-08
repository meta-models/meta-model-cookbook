import Darwin
import Foundation

enum AgentLogKind {
  case goal
  case plan
  case status
  case thinking
  case message
  case answer
  case tool
  case success
  case warning
  case error
}

typealias AgentLogger = (AgentLogKind, String) -> Void

func defaultAgentLogger(_ kind: AgentLogKind, _ message: String) {
  let label: String
  switch kind {
  case .goal: label = "goal"
  case .plan: label = "plan"
  case .status: label = "status"
  case .thinking: label = "thinking"
  case .message: label = "assistant"
  case .answer: label = "assistant"
  case .tool: label = "tool"
  case .success: label = "done"
  case .warning: label = "warning"
  case .error: label = "error"
  }
  FileHandle.standardError.write(Data("[\(label)] \(message)\n".utf8))
}

final class TerminalUI {
  private let useColor: Bool
  private let showPrompt: Bool
  private let lock = NSLock()

  init(useColor: Bool = TerminalUI.shouldUseColor, showPrompt: Bool = TerminalUI.shouldShowPrompt) {
    self.useColor = useColor
    self.showPrompt = showPrompt
  }

  static var shouldUseColor: Bool {
    isatty(STDOUT_FILENO) == 1 && ProcessInfo.processInfo.environment["NO_COLOR"] == nil
  }

  static var shouldShowPrompt: Bool {
    isatty(STDIN_FILENO) == 1
  }

  func printHeader(
    config: AgentConfig,
    backendLabel: String,
    manipulationLabel: String,
    maxSteps: Int?,
    overlay: Bool,
    planFirst: Bool
  ) {
    let coords = config.coords == .normalized1000 ? "0-1000" : "pixel"
    writeLine("")
    writeLine("\(style("metacua", .bold)) \(style("computer-use agent", .dim))")
    writeLine(style("backend \(backendLabel)", .dim))
    writeLine(style("manipulation \(manipulationLabel)", .dim))
    writeLine(
      style(
        "base \(config.baseURL) | coords \(coords) | effort \(config.effort)",
        .dim
      )
    )
    writeLine(style("screenshot scale \(formatScale(config.screenshotScale))", .dim))
    writeLine(style("type a goal, /help for commands, or /quit to exit", .dim))
    writeLine("")
  }

  func printInteractiveHelp() {
    writeLine("")
    writeLine("\(style("commands", .bold))")
    for command in slashCommandSpecs {
      let padded = command.displayCommand.padding(toLength: 24, withPad: " ", startingAt: 0)
      writeLine("  \(padded) \(command.description)")
    }
    writeLine("")
  }

  func printConfig(
    config: AgentConfig,
    backendLabel: String,
    manipulationLabel: String,
    maxSteps: Int?,
    overlay: Bool,
    planFirst: Bool
  ) {
    let coords = config.coords == .normalized1000 ? "0-1000" : "pixel"
    let overlayLabel = overlay ? "on" : "off"
    let planLabel = planFirst ? "on" : "off"
    let batchedLabel = config.batchedActions ? "on" : "off"
    let maxStepsLabel = maxSteps.map(String.init) ?? "unlimited"
    writeLine("")
    writeLine("\(style("config", .bold))")
    writeLine("  backend    \(backendLabel)")
    writeLine("  model      \(config.model)")
    writeLine("  base-url   \(config.baseURL)")
    writeLine("  coords     \(coords)")
    writeLine("  effort     \(config.effort)")
    writeLine("  shot-scale \(formatScale(config.screenshotScale))")
    writeLine("  max-images \(config.maxImages)")
    writeLine("  batched    \(batchedLabel)")
    writeLine("  manip      \(manipulationLabel)")
    writeLine("  plan-first \(planLabel)")
    writeLine("  max-steps  \(maxStepsLabel)")
    writeLine("  overlay    \(overlayLabel)")
    writeLine("")
  }

  func printModel(config: AgentConfig, backendLabel: String) {
    writeLine("")
    writeLine("\(style("model", .bold))")
    writeLine("  backend   \(backendLabel)")
    writeLine("  model     \(config.model)")
    writeLine("")
  }

  func printStatus(
    config: AgentConfig,
    backendLabel: String,
    manipulationLabel: String,
    maxSteps: Int?,
    overlay: Bool,
    planFirst: Bool
  ) {
    printConfig(
      config: config,
      backendLabel: backendLabel,
      manipulationLabel: manipulationLabel,
      maxSteps: maxSteps,
      overlay: overlay,
      planFirst: planFirst
    )
    printPermissions()
  }

  func printTools(config: AgentConfig) {
    writeLine("")
    writeLine("\(style("tools", .bold))")
    for tool in agentToolSpecs(enableBatchedActions: config.batchedActions) {
      let name = tool.name.padding(toLength: 18, withPad: " ", startingAt: 0)
      writeLine("  \(name) \(tool.description)")
    }
    writeLine("")
  }

  func printDoctor(
    config: AgentConfig,
    backendLabel: String,
    manipulationLabel: String,
    maxSteps: Int?,
    overlay: Bool,
    planFirst: Bool
  ) {
    let maxStepsLabel = maxSteps.map(String.init) ?? "unlimited"
    let planLabel = planFirst ? "on" : "off"
    let batchedLabel = config.batchedActions ? "on" : "off"
    writeLine("")
    writeLine("\(style("doctor", .bold))")
    writeLine("  config          \(style("ok", .green))")
    writeLine("  backend         \(backendLabel)")
    writeLine("  model           \(config.model)")
    writeLine("  shot-scale      \(formatScale(config.screenshotScale))")
    writeLine("  max-images      \(config.maxImages)")
    writeLine("  batched         \(batchedLabel)")
    writeLine("  manipulation    \(manipulationLabel)")
    writeLine("  plan-first      \(planLabel)")
    writeLine("  max-steps       \(maxStepsLabel)")
    writeLine("  overlay         \(overlay ? "on" : "off")")
    writeLine("  accessibility   \(status(isTrusted()))")
    writeLine("  screen capture  \(status(hasScreenRecordingAccess()))")
    writeLine("")
  }

  func printPermissions() {
    writeLine("")
    writeLine("\(style("permissions", .bold))")
    writeLine("  Accessibility     \(status(isTrusted()))")
    writeLine("  Screen Recording  \(status(hasScreenRecordingAccess()))")
    writeLine("")
  }

  func printStoredSessions(limit: Int) {
    do {
      let store = SessionStore.shared
      let records = try store.loadRecent(limit: limit)
      writeLine("")
      writeLine("\(style("sessions", .bold))")
      for line in sessionSummaryLines(records: records, storagePath: store.storageURL.path) {
        writeLine("  \(line)")
      }
      writeLine("")
    } catch let error as CLIError {
      agentLog(.error, error.message)
    } catch {
      agentLog(.error, "\(error)")
    }
  }

  func printStoredSession(id: String) {
    do {
      let store = SessionStore.shared
      guard let record = try store.loadMatching(id: id) else {
        agentLog(.warning, "no stored LLM session matched '\(id)'")
        return
      }
      writeLine("")
      for line in sessionDetailLines(record: record, storagePath: store.storageURL.path) {
        writeLine("  \(line)")
      }
      writeLine("")
    } catch let error as CLIError {
      agentLog(.error, error.message)
    } catch {
      agentLog(.error, "\(error)")
    }
  }

  func printGoodbye() {
    writeLine("")
    writeLine(style("session ended", .dim))
  }

  func clearScreen() {
    lock.lock()
    print("\u{001B}[2J\u{001B}[H", terminator: "")
    fflush(stdout)
    lock.unlock()
  }

  func prompt() -> String? {
    let promptText = "\(style("metacua", .cyan)) \(style(">", .bold)) "
    if showPrompt {
      lock.lock()
      defer { lock.unlock() }
      return TerminalLineEditor(prompt: promptText, useColor: useColor).readLine()
    } else {
      return readLine()
    }
  }

  func agentLog(_ kind: AgentLogKind, _ message: String) {
    switch kind {
    case .goal:
      printBlock(label: "user", message: message, color: .cyan, blankBefore: true)
    case .plan:
      printBlock(label: "plan", message: message, color: .cyan, blankBefore: false)
    case .status:
      printBlock(label: "status", message: message, color: .dim, blankBefore: false)
    case .thinking:
      printBlock(label: "thinking", message: message, color: .dim, blankBefore: false)
    case .message:
      printBlock(label: "assistant", message: message, color: .green, blankBefore: true)
    case .answer:
      let rendered = TerminalMarkdown.render(message, useColor: useColor)
      printBlock(label: "assistant", message: rendered, color: .green, blankBefore: true)
    case .tool:
      printBlock(label: "tool", message: message, color: .magenta, blankBefore: false)
    case .success:
      printBlock(label: "done", message: message, color: .green, blankBefore: false)
    case .warning:
      printBlock(label: "warn", message: message, color: .yellow, blankBefore: false)
    case .error:
      printBlock(label: "error", message: message, color: .red, blankBefore: false)
    }
  }

  private func printBlock(label: String, message: String, color: Style, blankBefore: Bool) {
    let lines = message.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
    lock.lock()
    if blankBefore { print("") }
    let renderedLabel = style(label, color)
    if lines.isEmpty {
      print("\(renderedLabel)")
    } else {
      print("\(renderedLabel) \(lines[0])")
      for line in lines.dropFirst() {
        print("  \(line)")
      }
    }
    fflush(stdout)
    lock.unlock()
  }

  private func writeLine(_ line: String) {
    lock.lock()
    print(line)
    fflush(stdout)
    lock.unlock()
  }

  private func status(_ ok: Bool) -> String {
    ok ? style("granted", .green) : style("missing", .yellow)
  }

  private func formatScale(_ value: Double) -> String {
    String(format: "%.2g", value)
  }

  private enum Style {
    case bold
    case dim
    case cyan
    case green
    case yellow
    case red
    case magenta

    var code: String {
      switch self {
      case .bold: return "1"
      case .dim: return "2"
      case .cyan: return "36"
      case .green: return "32"
      case .yellow: return "33"
      case .red: return "31"
      case .magenta: return "35"
      }
    }
  }

  private func style(_ text: String, _ style: Style) -> String {
    guard useColor else { return text }
    return "\u{001B}[\(style.code)m\(text)\u{001B}[0m"
  }
}
