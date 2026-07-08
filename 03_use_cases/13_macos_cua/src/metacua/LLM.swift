import Foundation

/// How the model expresses coordinates in tool calls.
enum CoordSpace {
  case pixel
  case normalized1000

  static func parse(_ raw: String) -> CoordSpace? {
    switch raw.lowercased() {
    case "pixel", "pixels", "px": return .pixel
    case "normalized", "normalized1000", "0-1000", "norm": return .normalized1000
    default: return nil
    }
  }
}

/// A model-backend-neutral tool description.
struct ToolSpec {
  let name: String
  let description: String
  let schema: [String: Any]
}

struct LLMToolCall {
  let id: String
  let name: String
  let input: [String: Any]
}

/// One model turn, normalized across the agent.
struct LLMResult {
  let responseId: String?
  let sessionIds: [String]
  let assistantItems: [[String: Any]]
  /// Items to append to the conversation history so the next turn replays this
  /// turn's reasoning (with encrypted_content), message, and function calls —
  /// the client owns continuity since requests are sent statelessly.
  let historyItems: [[String: Any]]
  let toolCalls: [LLMToolCall]
  let text: String
  let thinking: String
  let finish: String
  let refusalReason: String?
  let rawResponse: [String: Any]
}

/// The result of running one tool call locally.
struct ToolRun {
  let callId: String
  let name: String
  let output: String
  let isError: Bool
}

/// The LLM backend. The agent loop is written against this and never touches the wire format.
protocol LLMBackend {
  var label: String { get }
  var coordSpace: CoordSpace { get }
  func initialConversation(goalText: String, screenshot: Screenshot) -> [[String: Any]]
  func plan(system: String, conversation: [[String: Any]]) throws -> String?
  func send(
    system: String,
    conversation: [[String: Any]]
  ) throws -> LLMResult
  func toolResultItems(_ runs: [ToolRun], screenshot: Screenshot?) -> [[String: Any]]
}

func makeBackend(_ config: AgentConfig) -> LLMBackend {
  MuseSparkBackend(config: config)
}

func retainMostRecentImages(in conversation: [[String: Any]], maxImages: Int) -> [[String: Any]] {
  let limit = max(1, maxImages)
  let totalImages = conversation.reduce(0) { count, item in
    count + countImageBlocks(in: item)
  }
  guard totalImages > limit else { return conversation }

  let removeImages = totalImages - limit

  var seenImages = 0
  return conversation.map { item in
    retainMostRecentImages(
      in: item,
      removeImages: removeImages,
      limit: limit,
      seenImages: &seenImages
    ) as? [String: Any] ?? item
  }
}

private func countImageBlocks(in value: Any) -> Int {
  if let dict = value as? [String: Any] {
    let selfCount = isImageBlock(dict) ? 1 : 0
    return dict.values.reduce(selfCount) { count, child in
      count + countImageBlocks(in: child)
    }
  }
  if let array = value as? [Any] {
    return array.reduce(0) { count, child in
      count + countImageBlocks(in: child)
    }
  }
  return 0
}

private func retainMostRecentImages(
  in value: Any,
  removeImages: Int,
  limit: Int,
  seenImages: inout Int
) -> Any {
  if var dict = value as? [String: Any] {
    if isImageBlock(dict) {
      seenImages += 1
      if seenImages <= removeImages {
        return [
          "type": "input_text",
          "text": "[Screenshot has been truncated to save context]",
        ]
      }
      return dict
    }

    for (key, child) in dict {
      dict[key] = retainMostRecentImages(
        in: child,
        removeImages: removeImages,
        limit: limit,
        seenImages: &seenImages
      )
    }
    return dict
  }

  if let array = value as? [Any] {
    return array.map { child in
      retainMostRecentImages(
        in: child,
        removeImages: removeImages,
        limit: limit,
        seenImages: &seenImages
      )
    }
  }

  return value
}

private func isImageBlock(_ dict: [String: Any]) -> Bool {
  if let imageURL = dict["image_url"] as? String, imageURL.hasPrefix("data:image/") {
    return true
  }
  return false
}

/// The GUI tools the agent exposes. Coordinate units are described in the system prompt.
func agentToolSpecs(enableBatchedActions: Bool = false) -> [ToolSpec] {
  let coordinateArray: [String: Any] = [
    "description": "[x, y] relative coordinates (integers in [0, 1000]).",
    "items": ["type": "integer"],
    "maxItems": 2,
    "minItems": 2,
    "type": "array",
  ]
  let nullableCoordinateArray: [String: Any] = [
    "anyOf": [
      ["items": ["type": "integer"], "type": "array"],
      ["type": "null"],
    ],
    "default": NSNull(),
  ]
  let batchedActionEnum = [
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "left_press",
    "scroll",
    "hold_key",
    "release_key",
    "left_mouse_down",
    "left_mouse_up",
    "wait",
  ]
  let singleActionEnum = batchedActionEnum + ["screenshot"]
  let actionItemSchema: [String: Any] = [
    "properties": [
      "action": [
        "description": """
        The action to perform. Same action types as the single-action \
        computer tool form.
        """,
        "enum": batchedActionEnum,
        "type": "string",
      ],
      "text": [
        "description": """
        For 'type': text to insert into the focused field. For 'key': key combo, e.g. 'ctrl+s'. \
        For click/scroll: modifier key to hold during action. For 'type', provide the literal \
        text to paste; do not add backslashes before quotes unless the visible text itself needs \
        backslashes.
        """,
        "type": "string",
      ],
      "coordinate": coordinateArray,
      "start_coordinate": [
        "description": "[x, y] start coordinates for left_click_drag.",
        "items": ["type": "integer"],
        "maxItems": 2,
        "minItems": 2,
        "type": "array",
      ],
      "scroll_direction": [
        "description": "Direction to scroll. Required for action=scroll.",
        "enum": ["up", "down", "left", "right"],
        "type": "string",
      ],
      "scroll_amount": [
        "description": "Number of scroll clicks. Required for action=scroll.",
        "type": "integer",
      ],
      "duration": [
        "description": "Duration in seconds for wait.",
        "type": "number",
      ],
    ],
    "required": ["action"],
    "type": "object",
    "additionalProperties": false,
  ]
  var singleCoordinate = nullableCoordinateArray
  singleCoordinate["description"] = """
    [x, y] relative coordinates (integers in [0, 1000]) for mouse actions. \
    Required for click, move, and drag actions.
    """
  var singleStartCoordinate = nullableCoordinateArray
  singleStartCoordinate["description"] = """
    [x, y] relative starting coordinates (integers in [0, 1000]) for \
    left_click_drag.
    """
  let singleActionSchemaProperties: [String: Any] = [
    "action": [
      "description": """
      The action to perform. One of: left_click, right_click, double_click, \
      middle_click, triple_click, left_press, left_click_drag, mouse_move, key, \
      type, hold_key, release_key, left_mouse_down, left_mouse_up, scroll, \
      screenshot, wait
      """,
      "enum": singleActionEnum,
      "type": "string",
    ],
    "coordinate": singleCoordinate,
    "text": [
      "anyOf": [["type": "string"], ["type": "null"]],
      "default": NSNull(),
      "description": """
      Text input for keyboard actions. For 'key': key combo string, e.g. \
      'ctrl+c' or 'Return'. For 'type': text to insert into the focused field. \
      For 'type', provide the literal text to paste; do not add backslashes before \
      quotes unless the visible text itself needs backslashes. \
      For 'hold_key'/'release_key': keys to hold/release. For click actions: \
      modifier keys to hold, e.g. 'shift' or 'ctrl+shift'.
      """,
    ],
    "start_coordinate": singleStartCoordinate,
    "scroll_direction": [
      "anyOf": [["type": "string"], ["type": "null"]],
      "default": NSNull(),
      "description": "Scroll direction: 'up', 'down', 'left', or 'right'.",
    ],
    "scroll_amount": [
      "anyOf": [["type": "integer"], ["type": "null"]],
      "default": NSNull(),
      "description": "Number of scroll clicks.",
    ],
    "duration": [
      "anyOf": [["type": "number"], ["type": "null"]],
      "default": NSNull(),
      "description": "Duration in seconds for wait actions.",
    ],
  ]

  let computerTool =
    enableBatchedActions
    ? ToolSpec(
      name: "computer.computer",
      description:
        """
        Batched-actions form of the computer tool with relative coordinates.

        The model emits a list of action items; the tool validates them upfront, \
        executes them in sequence, and returns a single screenshot at the end.
        """,
      schema: [
        "properties": [
          "actions": [
            "description": """
            List of actions to execute in sequence in a single tool call. \
            Each item: {action: str, coordinate?: [x,y], text?: str, ...}. \
            Batch as many predictable actions as possible; only split when \
            the next step depends on observing a screenshot.
            """,
            "items": actionItemSchema,
            "type": "array",
          ]
        ],
        "required": ["actions"],
        "type": "object",
        "additionalProperties": false,
      ])
    : ToolSpec(
      name: "computer.computer",
      description:
        """
        Control the computer via mouse, keyboard, and screen actions.

        This matches Anthropic's computer_20251124 tool interface, but uses \
        relative coordinates (integers in [0, 1000]) instead of absolute pixels.
        """,
      schema: [
        "properties": singleActionSchemaProperties,
        "required": ["action"],
        "type": "object",
        "additionalProperties": false,
      ])

  return [
    computerTool,
    ToolSpec(
      name: "computer.stop",
      description: "Stop the session and submit your final answer.",
      schema: [
        "properties": [
          "answer": [
            "description": """
            Brief description of what you accomplished, or why you cannot \
            proceed safely.
            """,
            "type": "string",
          ]
        ],
        "required": ["answer"],
        "type": "object",
        "additionalProperties": false,
      ]),
  ]
}

// MARK: - Shared HTTP

/// POST a JSON body and return the parsed JSON object, throwing a CLIError with the server's message on a non-2xx status.
func httpPostJSON(
  url: URL,
  headers: [String: String],
  body: [String: Any],
  timeout: TimeInterval = 300,
  maxRetries: Int = 10,
  initialRetryDelay: TimeInterval = 1.0
) throws -> [String: Any] {
  let bodyData = try JSONSerialization.data(withJSONObject: body)

  let tmp = FileManager.default.temporaryDirectory
  let token = UUID().uuidString
  let bodyFile = tmp.appendingPathComponent("metacua-req-\(token).json")
  let configFile = tmp.appendingPathComponent("metacua-curl-\(token).conf")
  defer {
    try? FileManager.default.removeItem(at: bodyFile)
    try? FileManager.default.removeItem(at: configFile)
  }

  guard
    FileManager.default.createFile(
      atPath: bodyFile.path, contents: bodyData, attributes: [.posixPermissions: 0o600])
  else {
    throw CLIError("could not stage request body")
  }

  var allHeaders = headers
  allHeaders["Content-Type"] = "application/json"
  var conf = """
    url = "\(url.absoluteString)"
    request = "POST"
    data-binary = "@\(bodyFile.path)"
    max-time = \(Int(timeout))
    silent
    show-error
    write-out = "\\n%{http_code}"

    """
  for (key, value) in allHeaders {
    conf += "header = \"\(key): \(curlEscape(value))\"\n"
  }
  guard
    FileManager.default.createFile(
      atPath: configFile.path, contents: Data(conf.utf8), attributes: [.posixPermissions: 0o600])
  else {
    throw CLIError("could not stage request config")
  }

  let attempts = max(0, maxRetries) + 1
  var delay = max(0.1, initialRetryDelay)
  var lastError: CLIError?

  for attempt in 1...attempts {
    do {
      return try runCurlJSONRequest(url: url, configFile: configFile)
    } catch let error as RetryableHTTPError {
      lastError = error.error
      guard attempt < attempts else { throw error.error }
      logHTTPRetry(error.error, attempt: attempt, maxRetries: maxRetries, delay: delay)
      sleepForRetry(delay)
      delay = min(delay * 2, 8.0)
    }
  }

  throw lastError ?? CLIError("request failed")
}

private struct RetryableHTTPError: Error {
  let error: CLIError
}

private func runCurlJSONRequest(url: URL, configFile: URL) throws -> [String: Any] {
  let process = Process()
  process.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
  process.arguments = ["--config", configFile.path]
  let outPipe = Pipe()
  let errPipe = Pipe()
  process.standardOutput = outPipe
  process.standardError = errPipe
  do {
    try process.run()
  } catch {
    throw CLIError("failed to launch curl: \(error.localizedDescription)")
  }
  let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
  let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
  process.waitUntilExit()

  guard process.terminationStatus == 0 else {
    let err = String(data: errData, encoding: .utf8) ?? "curl exited \(process.terminationStatus)"
    throw RetryableHTTPError(
      error: CLIError("network error: \(err.trimmingCharacters(in: .whitespacesAndNewlines))"))
  }

  let raw = String(data: outData, encoding: .utf8) ?? ""
  guard let nl = raw.lastIndex(of: "\n") else {
    throw RetryableHTTPError(error: CLIError("malformed response from \(url.absoluteString)"))
  }
  let statusCode = Int(raw[raw.index(after: nl)...].trimmingCharacters(in: .whitespaces)) ?? 0
  let bodyString = String(raw[..<nl])
  let json = (try? JSONSerialization.jsonObject(with: Data(bodyString.utf8))) as? [String: Any]

  guard (200...299).contains(statusCode) else {
    let message =
      (json?["error"] as? [String: Any])?["message"] as? String
      ?? (json?["error"] as? String)
      ?? bodyString
    let error = CLIError("API error \(statusCode): \(message)")
    if isRetryableHTTPStatus(statusCode) {
      throw RetryableHTTPError(error: error)
    }
    throw error
  }
  guard let obj = json else { throw CLIError("could not parse API response as JSON") }
  return obj
}

private func isRetryableHTTPStatus(_ statusCode: Int) -> Bool {
  statusCode == 408 || statusCode == 429 || (500...599).contains(statusCode)
}

private func logHTTPRetry(_ error: CLIError, attempt: Int, maxRetries: Int, delay: TimeInterval) {
  let message = String(
    format: "warning: %@; retrying in %.1fs (%d/%d)\n",
    error.message,
    delay,
    attempt,
    maxRetries
  )
  FileHandle.standardError.write(Data(message.utf8))
}

private func sleepForRetry(_ seconds: TimeInterval) {
  let micros = max(0, min(seconds, 60.0)) * 1_000_000
  usleep(useconds_t(micros))
}

private func curlEscape(_ value: String) -> String {
  value.replacingOccurrences(of: "\\", with: "\\\\")
    .replacingOccurrences(of: "\"", with: "\\\"")
}
