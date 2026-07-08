import Darwin
import Foundation

private let bashToolMaxOutputBytes = 128 * 1024

private final class ProcessOutputBuffer {
  private let lock = NSLock()
  private var data = Data()
  private var droppedByteCount = 0

  func append(_ chunk: Data) {
    guard !chunk.isEmpty else { return }

    lock.lock()
    defer { lock.unlock() }

    let remaining = bashToolMaxOutputBytes - data.count
    if remaining > 0 {
      data.append(chunk.prefix(remaining))
    }
    if chunk.count > remaining {
      droppedByteCount += chunk.count - max(remaining, 0)
    }
  }

  func snapshot() -> (text: String, droppedBytes: Int) {
    lock.lock()
    defer { lock.unlock() }

    let text = String(data: data, encoding: .utf8) ?? String(decoding: data, as: UTF8.self)
    return (text, droppedByteCount)
  }
}

func runBashTool(command: String, timeoutMS: Int) throws -> String {
  let trimmed = command.trimmingCharacters(in: .whitespacesAndNewlines)
  guard !trimmed.isEmpty else {
    throw CLIError("bash command must not be empty")
  }

  let process = Process()
  process.executableURL = URL(fileURLWithPath: "/bin/bash")
  process.arguments = ["-lc", command]
  process.currentDirectoryURL = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)

  let stdoutPipe = Pipe()
  let stderrPipe = Pipe()
  let stdout = ProcessOutputBuffer()
  let stderr = ProcessOutputBuffer()
  let finished = DispatchSemaphore(value: 0)

  process.standardOutput = stdoutPipe
  process.standardError = stderrPipe
  stdoutPipe.fileHandleForReading.readabilityHandler = { handle in
    stdout.append(handle.availableData)
  }
  stderrPipe.fileHandleForReading.readabilityHandler = { handle in
    stderr.append(handle.availableData)
  }
  process.terminationHandler = { _ in
    finished.signal()
  }

  do {
    try process.run()
  } catch {
    stdoutPipe.fileHandleForReading.readabilityHandler = nil
    stderrPipe.fileHandleForReading.readabilityHandler = nil
    throw CLIError("failed to launch bash: \(error.localizedDescription)")
  }

  let waitResult = finished.wait(timeout: .now() + .milliseconds(timeoutMS))
  let timedOut = waitResult == .timedOut
  if timedOut {
    stdoutPipe.fileHandleForReading.readabilityHandler = nil
    stderrPipe.fileHandleForReading.readabilityHandler = nil
    if process.isRunning {
      process.terminate()
    }
    if finished.wait(timeout: .now() + .seconds(2)) == .timedOut, process.isRunning {
      kill(process.processIdentifier, SIGKILL)
      _ = finished.wait(timeout: .now() + .seconds(2))
    }
  }

  stdoutPipe.fileHandleForReading.readabilityHandler = nil
  stderrPipe.fileHandleForReading.readabilityHandler = nil
  stdout.append(stdoutPipe.fileHandleForReading.readDataToEndOfFile())
  stderr.append(stderrPipe.fileHandleForReading.readDataToEndOfFile())

  let result = formatBashToolResult(
    command: trimmed,
    timeoutMS: timeoutMS,
    timedOut: timedOut,
    exitCode: process.terminationStatus,
    stdout: stdout.snapshot(),
    stderr: stderr.snapshot()
  )

  if timedOut {
    throw CLIError(result)
  }
  if process.terminationStatus != 0 {
    throw CLIError(result)
  }
  return result
}

private func formatBashToolResult(
  command: String,
  timeoutMS: Int,
  timedOut: Bool,
  exitCode: Int32,
  stdout: (text: String, droppedBytes: Int),
  stderr: (text: String, droppedBytes: Int)
) -> String {
  var parts: [String] = []
  parts.append("command: \(command)")
  if timedOut {
    parts.append("status: timed out after \(timeoutMS)ms")
  } else {
    parts.append("status: exit \(exitCode)")
  }
  parts.append(formatStream(name: "stdout", stream: stdout))
  parts.append(formatStream(name: "stderr", stream: stderr))
  return parts.joined(separator: "\n")
}

private func formatStream(name: String, stream: (text: String, droppedBytes: Int)) -> String {
  let text = stream.text.trimmingCharacters(in: .newlines)
  let rendered = text.isEmpty ? "<empty>" : text
  if stream.droppedBytes > 0 {
    return "\(name):\n\(rendered)\n[\(stream.droppedBytes) byte(s) truncated]"
  }
  return "\(name):\n\(rendered)"
}
