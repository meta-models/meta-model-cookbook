import CryptoKit
import Foundation

struct StoredLLMCallRef {
  let recordId: String
  let displayId: String
  let traceId: String
  let storagePath: String
}

/// Extracts inline base64 images into sidecar files next to the trace.
///
/// Screenshots are written once per unique content hash under
/// `<traces>/<trace_id>/` so the JSONL keeps one small reference per image
/// instead of a multi-hundred-KB data URI. Deduping by hash means a screenshot
/// that reappears across turns/records is stored a single time.
final class TraceImageWriter {
  private let imageDir: URL
  private let relPrefix: String
  private var byHash: [String: String] = [:]
  private var createdDir = false
  private(set) var savedCount = 0

  init(imageDir: URL, relPrefix: String) {
    self.imageDir = imageDir
    self.relPrefix = relPrefix
  }

  /// Write the image and return a reference string, or nil to fall back to redaction.
  func save(prefix: String, encoded: String) -> String? {
    guard
      let raw = Data(base64Encoded: encoded, options: [.ignoreUnknownCharacters]),
      !raw.isEmpty
    else {
      return nil
    }
    let hex = Insecure.SHA1.hash(data: raw).map { String(format: "%02x", $0) }.joined()
    let short = String(hex.prefix(16))
    let relpath: String
    if let existing = byHash[short] {
      relpath = existing
    } else {
      let name = "\(short)\(Self.imageExtension(prefix))"
      writeFile(name: name, raw: raw)
      relpath = "\(relPrefix)/\(name)"
      byHash[short] = relpath
      savedCount += 1
    }
    return "\(prefix),<saved \(relpath) (\(raw.count) bytes)>"
  }

  private func writeFile(name: String, raw: Data) {
    let fileManager = FileManager.default
    if !createdDir {
      try? fileManager.createDirectory(
        at: imageDir,
        withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700]
      )
      createdDir = true
    }
    let path = imageDir.appendingPathComponent(name)
    if fileManager.fileExists(atPath: path.path) { return }
    guard (try? raw.write(to: path, options: [.atomic])) != nil else { return }
    try? fileManager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
  }

  /// Map a `data:image/<subtype>;base64` prefix to a file extension.
  static func imageExtension(_ prefix: String) -> String {
    guard let range = prefix.range(of: "image/") else { return ".png" }
    var rest = String(prefix[range.upperBound...])
    for stop in [";", ",", "+"] {
      if let idx = rest.range(of: stop) {
        rest = String(rest[..<idx.lowerBound])
      }
    }
    let subtype = rest.trimmingCharacters(in: .whitespaces).lowercased()
    if subtype == "jpeg" || subtype == "jpg" { return ".jpg" }
    if !subtype.isEmpty && subtype.allSatisfy({ $0.isLetter || $0.isNumber }) {
      return ".\(subtype)"
    }
    return ".png"
  }
}

final class SessionStore {
  static let shared = SessionStore()

  private init() {}

  var storageURL: URL {
    metacuaHomeURL().appendingPathComponent("traces")
  }

  private var legacyTraceStorageURL: URL {
    FileManager.default.homeDirectoryForCurrentUser
      .appendingPathComponent(".local/share/metacua/traces")
  }

  private var legacyGlobalStorageURL: URL {
    FileManager.default.homeDirectoryForCurrentUser
      .appendingPathComponent(".local/share/metacua/llm-sessions.jsonl")
  }

  func appendLLMCall(
    config: AgentConfig,
    backendLabel: String,
    goalId: String,
    goal: String,
    step: Int,
    requestConversation: [[String: Any]],
    result: LLMResult
  ) throws -> StoredLLMCallRef {
    let recordId = UUID().uuidString
    let traceId = Self.safeTraceId(goalId)
    let traceURL = traceFileURL(traceId: traceId)
    let messageHistory = requestConversation + result.assistantItems
    let imageWriter = TraceImageWriter(
      imageDir: storageURL.appendingPathComponent(traceId),
      relPrefix: traceId
    )
    var record: [String: Any] = [
      "record_id": recordId,
      "timestamp": Self.isoTimestamp(),
      "trace_id": traceId,
      "trace_file": traceURL.path,
      "backend": backendLabel,
      "model": config.model,
      "base_url": config.baseURL,
      "goal_id": goalId,
      "goal": goal,
      "step": step,
      "response_id": result.responseId ?? NSNull(),
      "session_ids": result.sessionIds,
      "finish": result.finish,
      "text": result.text,
      "thinking": result.thinking,
      "tool_calls": result.toolCalls.map { Self.toolCallObject($0, imageWriter: imageWriter) },
      "request": [
        "conversation": Self.sanitizedJSON(requestConversation, imageWriter: imageWriter)
      ],
      "response": Self.sanitizedJSON(result.rawResponse, imageWriter: imageWriter),
      "message_history": Self.sanitizedJSON(messageHistory, imageWriter: imageWriter),
    ]
    if imageWriter.savedCount > 0 {
      record["images"] = [
        "dir": storageURL.appendingPathComponent(traceId).path,
        "count": imageWriter.savedCount,
      ]
    }

    try append(record: record, to: traceURL)
    let displayId = result.sessionIds.first ?? result.responseId ?? recordId
    return StoredLLMCallRef(
      recordId: recordId,
      displayId: displayId,
      traceId: traceId,
      storagePath: traceURL.path
    )
  }

  func loadRecent(limit: Int) throws -> [[String: Any]] {
    let allRecords = try loadAll()
    let count = max(0, limit)
    guard count > 0 else { return [] }
    return Array(allRecords.suffix(count).reversed())
  }

  func loadMatching(id: String) throws -> [String: Any]? {
    let needle = id.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !needle.isEmpty else { return nil }
    for record in try loadAll().reversed() where Self.record(record, matches: needle) {
      return record
    }
    return nil
  }

  func traceFileURL(traceId: String) -> URL {
    storageURL.appendingPathComponent("\(Self.safeTraceId(traceId)).jsonl")
  }

  private func append(record: [String: Any], to url: URL) throws {
    let fileManager = FileManager.default
    try fileManager.createDirectory(
      at: url.deletingLastPathComponent(),
      withIntermediateDirectories: true,
      attributes: [.posixPermissions: 0o700]
    )
    if !fileManager.fileExists(atPath: url.path) {
      guard
        fileManager.createFile(
          atPath: url.path, contents: nil, attributes: [.posixPermissions: 0o600])
      else {
        throw CLIError("failed to create session history at \(url.path)")
      }
    }
    let data = try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys])
    guard let handle = try? FileHandle(forWritingTo: url) else {
      throw CLIError("failed to open session history at \(url.path)")
    }
    defer { try? handle.close() }
    try handle.seekToEnd()
    handle.write(data)
    handle.write(Data("\n".utf8))
  }

  private func loadAll() throws -> [[String: Any]] {
    let fileManager = FileManager.default
    var records: [[String: Any]] = []

    if fileManager.fileExists(atPath: legacyGlobalStorageURL.path) {
      records.append(contentsOf: try loadRecords(from: legacyGlobalStorageURL))
    }

    records.append(contentsOf: try loadTraceRecords(from: legacyTraceStorageURL))
    records.append(contentsOf: try loadTraceRecords(from: storageURL))

    return records.sorted {
      (Self.string($0["timestamp"]) ?? "") < (Self.string($1["timestamp"]) ?? "")
    }
  }

  private func loadTraceRecords(from directoryURL: URL) throws -> [[String: Any]] {
    let fileManager = FileManager.default
    var records: [[String: Any]] = []

    guard fileManager.fileExists(atPath: directoryURL.path) else {
      return []
    }

    let urls = try fileManager.contentsOfDirectory(
      at: directoryURL,
      includingPropertiesForKeys: nil
    )
    for url in urls where url.pathExtension == "jsonl" {
      records.append(contentsOf: try loadRecords(from: url))
    }
    return records
  }

  private func loadRecords(from url: URL) throws -> [[String: Any]] {
    let data = try Data(contentsOf: url)
    guard let text = String(data: data, encoding: .utf8) else {
      throw CLIError("could not read session history as UTF-8")
    }
    var records: [[String: Any]] = []
    for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
      guard
        let lineData = String(line).data(using: .utf8),
        let record = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any]
      else {
        continue
      }
      records.append(record)
    }
    return records
  }

  private static func toolCallObject(
    _ call: LLMToolCall, imageWriter: TraceImageWriter? = nil
  ) -> [String: Any] {
    [
      "id": call.id,
      "name": call.name,
      "input": sanitizedJSON(call.input, imageWriter: imageWriter),
    ]
  }

  private static func sanitizedJSON(_ value: Any, imageWriter: TraceImageWriter? = nil) -> Any {
    if let dict = value as? [String: Any] {
      var out: [String: Any] = [:]
      for (key, child) in dict {
        out[key] = sanitizedJSON(child, imageWriter: imageWriter)
      }
      return out
    }
    if let array = value as? [Any] {
      return array.map { sanitizedJSON($0, imageWriter: imageWriter) }
    }
    if let string = value as? String {
      return sanitizedString(string, imageWriter: imageWriter)
    }
    if let number = value as? NSNumber {
      return number
    }
    if value is NSNull {
      return NSNull()
    }
    return String(describing: value)
  }

  private static func sanitizedString(
    _ value: String, imageWriter: TraceImageWriter? = nil
  ) -> String {
    guard value.hasPrefix("data:image/") else { return value }
    guard let comma = value.firstIndex(of: ",") else {
      return "data:image/<redacted>"
    }
    let prefix = String(value[..<comma])
    let encoded = value[value.index(after: comma)...]
    if let imageWriter, let reference = imageWriter.save(prefix: prefix, encoded: String(encoded)) {
      return reference
    }
    return "\(prefix),<redacted \(encoded.utf8.count) base64 bytes>"
  }

  private static func record(_ record: [String: Any], matches id: String) -> Bool {
    if string(record["record_id"]) == id { return true }
    if string(record["response_id"]) == id { return true }
    if string(record["trace_id"]) == id { return true }
    if string(record["goal_id"]) == id { return true }
    if let traceFile = string(record["trace_file"]) {
      let url = URL(fileURLWithPath: traceFile)
      if url.lastPathComponent == id { return true }
      if url.deletingPathExtension().lastPathComponent == id { return true }
    }
    if let sessionIds = record["session_ids"] as? [String], sessionIds.contains(id) {
      return true
    }
    return false
  }

  private static func safeTraceId(_ raw: String) -> String {
    let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    let source = trimmed.isEmpty ? UUID().uuidString : trimmed
    let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
    let scalars = source.unicodeScalars.map { scalar -> Character in
      allowed.contains(scalar) ? Character(scalar) : "-"
    }
    let safe = String(scalars).trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    return safe.isEmpty ? UUID().uuidString : safe
  }

  private static func string(_ value: Any?) -> String? {
    guard let value, !(value is NSNull) else { return nil }
    return value as? String
  }

  private static func isoTimestamp() -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.string(from: Date())
  }
}

func runSessions(_ raw: [String]) throws {
  let args = try Args(raw)
  let store = SessionStore.shared
  if args.flag("path") {
    print(store.storageURL.path)
    return
  }

  let id = args.string("id") ?? args.string("session-id") ?? args.string("response-id")
  let json = args.flag("json")
  let history = args.flag("history")

  if let id {
    guard let record = try store.loadMatching(id: id) else {
      throw CLIError("no stored LLM session matched '\(id)'", code: 2)
    }
    if history {
      let messageHistory = record["message_history"] ?? []
      try printPrettyJSON(messageHistory)
    } else if json {
      try printPrettyJSON(record)
    } else {
      for line in sessionDetailLines(record: record, storagePath: store.storageURL.path) {
        print(line)
      }
    }
    return
  }

  if history {
    throw CLIError("--history requires --id", code: 2)
  }

  let limit = try args.int("limit") ?? 20
  let records = try store.loadRecent(limit: limit)
  if json {
    try printPrettyJSON(records)
  } else {
    for line in sessionSummaryLines(records: records, storagePath: store.storageURL.path) {
      print(line)
    }
  }
}

func sessionSummaryLines(records: [[String: Any]], storagePath: String) -> [String] {
  guard !records.isEmpty else {
    return ["No stored LLM sessions at \(storagePath)"]
  }

  var lines = ["Stored LLM sessions at \(storagePath)"]
  for record in records {
    let timestamp = stringField(record, "timestamp") ?? "unknown-time"
    let model = stringField(record, "model") ?? "unknown-model"
    let finish = stringField(record, "finish") ?? "unknown"
    let step = intField(record, "step").map(String.init) ?? "?"
    let trace = stringField(record, "trace_id") ?? stringField(record, "goal_id") ?? "-"
    let session = primarySessionId(record) ?? "-"
    let response = stringField(record, "response_id") ?? "-"
    let goal = excerpt(stringField(record, "goal") ?? "", maxLength: 54)
    let text = excerpt(stringField(record, "text") ?? "", maxLength: 72)
    lines.append(
      "\(timestamp) trace=\(trace) step=\(step) finish=\(finish) model=\(model) session=\(session) response=\(response)"
    )
    if !goal.isEmpty {
      lines.append("  goal: \(goal)")
    }
    if !text.isEmpty {
      lines.append("  text: \(text)")
    }
  }
  return lines
}

func sessionDetailLines(record: [String: Any], storagePath: String) -> [String] {
  var lines: [String] = []
  lines.append("LLM session")
  lines.append("  record_id   \(stringField(record, "record_id") ?? "-")")
  lines.append("  timestamp   \(stringField(record, "timestamp") ?? "-")")
  let traceId = stringField(record, "trace_id") ?? stringField(record, "goal_id") ?? "-"
  lines.append("  trace_id    \(traceId)")
  let sessions = sessionIds(record)
  lines.append("  session_ids \(sessions.isEmpty ? "-" : sessions.joined(separator: ", "))")
  lines.append("  response_id \(stringField(record, "response_id") ?? "-")")
  lines.append("  backend     \(stringField(record, "backend") ?? "-")")
  lines.append("  model       \(stringField(record, "model") ?? "-")")
  lines.append("  step        \(intField(record, "step").map(String.init) ?? "-")")
  lines.append("  finish      \(stringField(record, "finish") ?? "-")")
  lines.append("  goal        \(stringField(record, "goal") ?? "")")
  let text = stringField(record, "text") ?? ""
  if !text.isEmpty {
    lines.append("  text        \(text)")
  }
  let toolCalls = (record["tool_calls"] as? [[String: Any]]) ?? []
  if !toolCalls.isEmpty {
    lines.append("  tool_calls")
    for call in toolCalls {
      let name = stringField(call, "name") ?? "-"
      let id = stringField(call, "id") ?? "-"
      lines.append("    \(name) id=\(id)")
    }
  }
  if let images = record["images"] as? [String: Any], let count = intField(images, "count") {
    let dir = stringField(images, "dir") ?? "-"
    lines.append("  images      \(count) saved in \(dir)")
  }
  if let traceFile = stringField(record, "trace_file") {
    lines.append("  trace_file  \(traceFile)")
  }
  lines.append("  storage     \(storagePath)")
  lines.append("Use `metacua sessions --id <id> --json` for the full sanitized record.")
  lines.append("Use `metacua sessions --id <id> --history` for sanitized message history only.")
  return lines
}

func printPrettyJSON(_ value: Any) throws {
  let data = try JSONSerialization.data(
    withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
  guard let text = String(data: data, encoding: .utf8) else {
    throw CLIError("could not render JSON")
  }
  print(text)
}

private func primarySessionId(_ record: [String: Any]) -> String? {
  sessionIds(record).first
}

private func sessionIds(_ record: [String: Any]) -> [String] {
  (record["session_ids"] as? [String]) ?? []
}

private func stringField(_ record: [String: Any], _ key: String) -> String? {
  guard let value = record[key], !(value is NSNull) else { return nil }
  return value as? String
}

private func intField(_ record: [String: Any], _ key: String) -> Int? {
  if let value = record[key] as? Int { return value }
  if let number = record[key] as? NSNumber { return number.intValue }
  return nil
}

private func excerpt(_ value: String, maxLength: Int) -> String {
  let oneLine =
    value
    .replacingOccurrences(of: "\n", with: " ")
    .trimmingCharacters(in: .whitespacesAndNewlines)
  guard oneLine.count > maxLength else { return oneLine }
  return String(oneLine.prefix(max(0, maxLength - 3))) + "..."
}
