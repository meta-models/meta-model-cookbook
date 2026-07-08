import Foundation

/// Muse Spark backend (POST {base}/responses), used statelessly (`store: false`).
/// Every request resends the full conversation built up so far. Reasoning items are
/// requested with `encrypted_content` and passed back verbatim on the next turn, so
/// chain-of-thought survives multi-turn tool calls without relying on the server to
/// retain state via `previous_response_id`.
struct MuseSparkBackend: LLMBackend {
  let config: AgentConfig

  var label: String { "Muse Spark \(config.model)" }
  var coordSpace: CoordSpace { config.coords }

  private var tools: [[String: Any]] {
    agentToolSpecs(enableBatchedActions: config.batchedActions).map {
      ["type": "function", "name": $0.name, "description": $0.description, "parameters": $0.schema]
    }
  }

  private func imageBlock(_ s: Screenshot) -> [String: Any] {
    ["type": "input_image", "image_url": "data:image/png;base64," + s.pngBase64]
  }

  private var reasoningEffort: String {
    switch config.effort {
    case "minimal", "low": return "low"
    case "medium": return "medium"
    default: return "high"
    }
  }

  func initialConversation(goalText: String, screenshot: Screenshot) -> [[String: Any]] {
    [
      [
        "role": "user", "type": "message",
        "content": [["type": "input_text", "text": goalText], imageBlock(screenshot)],
      ]
    ]
  }

  func plan(system: String, conversation: [[String: Any]]) throws -> String? {
    guard let url = URL(string: config.baseURL + "/responses") else {
      throw CLIError("invalid base URL: \(config.baseURL)")
    }
    let body: [String: Any] = [
      "model": config.model,
      "instructions": system
        + "\n\nBefore acting, write a concise user-facing plan. Use 2-4 short bullets. Do not call tools.",
      "input": conversation,
      "stream": false,
      "max_output_tokens": 512,
      "reasoning": ["effort": "low"],
    ]
    let obj = try httpPostJSON(
      url: url,
      headers: ["Authorization": "Bearer \(config.apiKey)"],
      body: body
    )
    let text = extractOutputText(from: obj)
      .trimmingCharacters(in: .whitespacesAndNewlines)
    return text.isEmpty ? nil : text
  }

  func send(
    system: String,
    conversation: [[String: Any]]
  ) throws -> LLMResult {
    guard let url = URL(string: config.baseURL + "/responses") else {
      throw CLIError("invalid base URL: \(config.baseURL)")
    }
    let body: [String: Any] = [
      "model": config.model,
      "instructions": system,
      "input": conversation,
      "tools": tools,
      "parallel_tool_calls": false,
      "stream": false,
      "store": false,
      "include": ["reasoning.encrypted_content"],
      "max_output_tokens": 128000,
      "reasoning": ["effort": reasoningEffort, "summary": "auto"],
    ]
    let obj = try httpPostJSON(
      url: url,
      headers: ["Authorization": "Bearer \(config.apiKey)"],
      body: body
    )

    let output = (obj["output"] as? [[String: Any]]) ?? []
    var text = ""
    var thinking = ""
    var calls: [LLMToolCall] = []
    var refused = false
    var pendingReasoningItem: [String: Any]?
    var messageItems: [[String: Any]] = []
    var functionCallItems: [[String: Any]] = []
    for item in output {
      switch item["type"] as? String {
      case "message":
        var itemText = ""
        var itemRefused = false
        for content in (item["content"] as? [[String: Any]]) ?? [] {
          switch content["type"] as? String {
          case "output_text":
            itemText += (content["text"] as? String ?? "")
          case "refusal":
            itemRefused = true
            itemText += (content["refusal"] as? String ?? "")
          case "reasoning_text":
            thinking = appendFragments(extractReasoningFragments(from: content), to: thinking)
          default:
            break
          }
        }
        text += itemText
        if itemRefused {
          refused = true
        } else if !itemText.isEmpty {
          var messageItem: [String: Any] = ["role": "assistant", "content": itemText]
          if item["phase"] as? String == "commentary" {
            messageItem["phase"] = "commentary"
          }
          messageItems.append(messageItem)
        }
      case "reasoning":
        thinking = appendFragments(extractReasoningFragments(from: item), to: thinking)
        pendingReasoningItem = reasoningPassbackItem(from: item)
      case "function_call":
        let argsString = item["arguments"] as? String ?? "{}"
        let callId = item["call_id"] as? String ?? ""
        let name = item["name"] as? String ?? ""
        try validateFunctionCallIdentity(toolName: name, callId: callId)
        let input = try parseFunctionCallInput(argsString, toolName: name, callId: callId)
        calls.append(LLMToolCall(id: callId, name: name, input: input))
        functionCallItems.append([
          "type": "function_call",
          "call_id": callId,
          "name": name,
          "arguments": argsString,
        ])
      default:
        break
      }
    }

    var historyItems: [[String: Any]] = []
    if let pendingReasoningItem { historyItems.append(pendingReasoningItem) }
    historyItems.append(contentsOf: messageItems)
    historyItems.append(contentsOf: functionCallItems)

    let truncated =
      ((obj["incomplete_details"] as? [String: Any])?["reason"] as? String) == "max_output_tokens"
      || (obj["status"] as? String) == "incomplete"
    let finish =
      !calls.isEmpty
      ? "tool_use"
      : refused
        ? "refusal"
        : truncated ? "max_tokens" : "stop"

    return LLMResult(
      responseId: obj["id"] as? String ?? obj["response_id"] as? String,
      sessionIds: extractSessionIds(from: obj),
      assistantItems: output,
      historyItems: historyItems,
      toolCalls: calls,
      text: text,
      thinking: thinking,
      finish: finish,
      refusalReason: refused ? text : nil,
      rawResponse: obj
    )
  }

  func toolResultItems(_ runs: [ToolRun], screenshot: Screenshot?) -> [[String: Any]] {
    var items: [[String: Any]] = []
    for run in runs {
      items.append([
        "type": "function_call_output",
        "call_id": run.callId,
        "output": run.isError ? "ERROR: " + run.output : run.output,
      ])
    }
    var content: [[String: Any]] = [
      ["type": "input_text", "text": "Screen observation after the action:"]
    ]
    if let screenshot {
      content.append(imageBlock(screenshot))
    } else {
      content.append(["type": "input_text", "text": "[screenshot unavailable]"])
    }
    items.append([
      "role": "user",
      "type": "message",
      "content": content,
    ])
    return items
  }
}

private func validateFunctionCallIdentity(toolName: String, callId: String) throws {
  let trimmedName = toolName.trimmingCharacters(in: .whitespacesAndNewlines)
  let trimmedCallId = callId.trimmingCharacters(in: .whitespacesAndNewlines)
  if trimmedName.isEmpty && trimmedCallId.isEmpty {
    throw CLIError("function_call output item is missing both name and call_id")
  }
  if trimmedName.isEmpty {
    throw CLIError("function_call output item is missing name for call_id \(trimmedCallId)")
  }
  if trimmedCallId.isEmpty {
    throw CLIError("function_call output item for \(trimmedName) is missing call_id")
  }
}

private func extractOutputText(from obj: [String: Any]) -> String {
  var text = ""
  for item in (obj["output"] as? [[String: Any]]) ?? [] {
    guard item["type"] as? String == "message" else { continue }
    for content in (item["content"] as? [[String: Any]]) ?? [] {
      switch content["type"] as? String {
      case "output_text":
        text += content["text"] as? String ?? ""
      case "refusal":
        text += content["refusal"] as? String ?? ""
      default:
        break
      }
    }
  }
  return text
}

private func parseFunctionCallInput(
  _ rawArguments: String,
  toolName: String,
  callId: String
) throws -> [String: Any] {
  let source =
    rawArguments.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "{}" : rawArguments
  do {
    let value = try JSONSerialization.jsonObject(with: Data(source.utf8))
    guard let input = value as? [String: Any] else {
      throw CLIError(
        "function-call arguments for \(toolCallLabel(toolName: toolName, callId: callId)) must decode to a JSON object"
      )
    }
    return input
  } catch let error as CLIError {
    throw error
  } catch {
    throw CLIError(
      "invalid JSON arguments for \(toolCallLabel(toolName: toolName, callId: callId)): \(error.localizedDescription). Ensure text values with quotes are escaped as valid JSON. arguments=\(argumentExcerpt(source))"
    )
  }
}

private func toolCallLabel(toolName: String, callId: String) -> String {
  let name = toolName.isEmpty ? "unknown tool" : toolName
  return callId.isEmpty ? name : "\(name) (\(callId))"
}

private func argumentExcerpt(_ text: String) -> String {
  let oneLine = text.replacingOccurrences(of: "\n", with: " ")
    .trimmingCharacters(in: .whitespacesAndNewlines)
  guard oneLine.count > 240 else { return oneLine }
  return String(oneLine.prefix(237)) + "..."
}

/// Rebuilds a `reasoning` output item into the minimal input-item shape the Responses
/// API expects when replaying history: id + summary + encrypted_content, dropping any
/// other server-only fields. Returns nil when there's nothing worth passing back.
private func reasoningPassbackItem(from item: [String: Any]) -> [String: Any]? {
  guard let reasoningId = item["id"] as? String, !reasoningId.isEmpty else { return nil }
  let summaryParts = (item["summary"] as? [[String: Any]]) ?? []
  let reasoningText = summaryParts.compactMap { $0["text"] as? String }
    .filter { !$0.isEmpty }
    .joined(separator: "\n")
  let encryptedContent = item["encrypted_content"] as? String
  guard encryptedContent != nil || !reasoningText.isEmpty else { return nil }
  var passback: [String: Any] = [
    "type": "reasoning",
    "id": reasoningId,
    "summary": reasoningText.isEmpty ? [] : [["type": "summary_text", "text": reasoningText]],
  ]
  if let encryptedContent { passback["encrypted_content"] = encryptedContent }
  return passback
}

private func extractReasoningFragments(from item: [String: Any]) -> [String] {
  var fragments: [String] = []
  for summary in (item["summary"] as? [[String: Any]]) ?? [] {
    if let text = summary["text"] as? String, !text.isEmpty {
      fragments.append(text)
    }
  }
  collectReasoningFragments(from: item, into: &fragments)
  return fragments
}

private func collectReasoningFragments(from value: Any, into fragments: inout [String]) {
  if let dict = value as? [String: Any] {
    if dict["type"] as? String == "reasoning_text",
      let text = dict["text"] as? String,
      !text.isEmpty
    {
      fragments.append(text)
    }
    for child in dict.values {
      collectReasoningFragments(from: child, into: &fragments)
    }
    return
  }

  if let array = value as? [Any] {
    for child in array {
      collectReasoningFragments(from: child, into: &fragments)
    }
  }
}

private func appendFragments(_ fragments: [String], to existing: String) -> String {
  let cleaned = fragments.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
    .filter { !$0.isEmpty }
  guard !cleaned.isEmpty else { return existing }
  let suffix = cleaned.joined(separator: "\n\n")
  return existing.isEmpty ? suffix : existing + "\n\n" + suffix
}

private func extractSessionIds(from value: Any) -> [String] {
  var ids: [String] = []
  collectSessionIds(from: value, into: &ids)
  return ids
}

private func collectSessionIds(from value: Any, into ids: inout [String]) {
  if let dict = value as? [String: Any] {
    for (key, child) in dict {
      if ["session_id", "sessionId", "llm_session_id"].contains(key),
        let text = child as? String,
        !text.isEmpty,
        !ids.contains(text)
      {
        ids.append(text)
      }
      if ["session_ids", "sessionIds", "llm_session_ids"].contains(key),
        let values = child as? [String]
      {
        for value in values where !value.isEmpty && !ids.contains(value) {
          ids.append(value)
        }
      }
      collectSessionIds(from: child, into: &ids)
    }
    return
  }
  if let array = value as? [Any] {
    for child in array {
      collectSessionIds(from: child, into: &ids)
    }
  }
}
