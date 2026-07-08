import Foundation

/// Resolved configuration for the Muse Spark endpoint.
struct AgentConfig {
  var apiKey: String
  var baseURL: String
  var model: String
  var coords: CoordSpace
  var effort: String
  var screenshotScale: Double
  var maxImages: Int
  var batchedActions: Bool

  static let defaultBaseURL = "https://api.meta.ai/v1"
  static let defaultModel = "muse-spark-1.1"
  static let defaultScreenshotScale = 1.0
  static let defaultMaxImages = 5
  static let defaultBatchedActions = false
}

private func configFileURL() -> URL {
  metacuaHomeURL().appendingPathComponent("config.json")
}

func metacuaHomeURL() -> URL {
  FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent(".metacua")
}

private func legacyConfigFileURLs() -> [URL] {
  let home = FileManager.default.homeDirectoryForCurrentUser
  return [
    home.appendingPathComponent(".config/metacua/config.json"),
    home.appendingPathComponent(".config/gui-agent/config.json"),
  ]
}

private func existingConfigFileURL() -> URL? {
  let primaryURL = configFileURL()
  if FileManager.default.fileExists(atPath: primaryURL.path) {
    return primaryURL
  }
  return legacyConfigFileURLs().first {
    FileManager.default.fileExists(atPath: $0.path)
  }
}

private func loadConfigFile() -> [String: String] {
  guard let url = existingConfigFileURL() else {
    return [:]
  }
  guard
    let data = try? Data(contentsOf: url),
    let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
  else {
    return [:]
  }
  var out: [String: String] = [:]
  for (key, value) in obj where value is String {
    out[key] = value as? String
  }
  return out
}

private func env(_ name: String) -> String? {
  guard let value = ProcessInfo.processInfo.environment[name], !value.isEmpty else { return nil }
  return value
}

private func normalizeBaseURL(_ url: String) -> String {
  var normalized = url.trimmingCharacters(in: .whitespacesAndNewlines)
  while normalized.hasSuffix("/") { normalized.removeLast() }
  return normalized
}

private func parseScreenshotScale(_ raw: String?) throws -> Double? {
  guard let raw else { return nil }
  guard let value = Double(raw), value.isFinite, value > 0, value <= 1 else {
    throw CLIError("screenshot scale must be > 0 and <= 1 (got '\(raw)')", code: 2)
  }
  return value
}

private func parseMaxImages(_ raw: String?) throws -> Int? {
  guard let raw else { return nil }
  guard let value = Int(raw), value >= 1 else {
    throw CLIError("max images must be >= 1 (got '\(raw)')", code: 2)
  }
  return value
}

private func parseBool(_ raw: String, label: String) throws -> Bool {
  switch raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
  case "1", "true", "yes", "on", "enabled", "enable": return true
  case "0", "false", "no", "off", "disabled", "disable": return false
  default:
    throw CLIError("\(label) must be true or false (got '\(raw)')", code: 2)
  }
}

private func parseBatchedActions(_ args: Args, file: [String: String]) throws -> Bool {
  let enabledFlag = args.flag("batched-actions") || args.flag("batch-actions")
  let disabledFlag = args.flag("no-batched-actions") || args.flag("no-batch-actions")
  if enabledFlag && disabledFlag {
    throw CLIError("pass only one of --batched-actions or --no-batched-actions", code: 2)
  }
  if disabledFlag { return false }
  if enabledFlag { return true }
  if let raw =
    args.string("batched-actions")
    ?? args.string("batch-actions")
    ?? env("METACUA_BATCHED_ACTIONS")
    ?? env("LLM_BATCHED_ACTIONS")
    ?? file["batchedActions"]
  {
    return try parseBool(raw, label: "batched actions")
  }
  return AgentConfig.defaultBatchedActions
}

/// Resolve config with precedence: CLI flags -> environment -> config file -> defaults.
func resolveAgentConfig(_ args: Args) throws -> AgentConfig {
  let file = loadConfigFile()

  let apiKey =
    args.string("api-key")
    ?? env("MODEL_API_KEY")
    ?? env("MUSE_SPARK_API_KEY")
    ?? file["apiKey"]
  guard let key = apiKey, !key.isEmpty else {
    throw CLIError(
      "No API key found. Provide one via --api-key, MODEL_API_KEY / MUSE_SPARK_API_KEY, or `metacua configure --api-key <KEY>`.",
      code: 2
    )
  }

  let baseURL =
    args.string("base-url")
    ?? env("LLM_BASE_URL")
    ?? env("MUSE_SPARK_BASE_URL")
    ?? file["baseURL"]
    ?? AgentConfig.defaultBaseURL

  let model =
    args.string("model")
    ?? env("LLM_MODEL")
    ?? env("MUSE_SPARK_MODEL")
    ?? file["model"]
    ?? AgentConfig.defaultModel

  let coords =
    (args.string("coords") ?? file["coords"]).flatMap(CoordSpace.parse) ?? .normalized1000
  let effort = args.string("effort") ?? env("LLM_EFFORT") ?? file["effort"] ?? "high"
  let screenshotScale =
    try parseScreenshotScale(
      args.string("screenshot-scale")
        ?? env("METACUA_SCREENSHOT_SCALE")
        ?? env("LLM_SCREENSHOT_SCALE")
        ?? file["screenshotScale"])
    ?? AgentConfig.defaultScreenshotScale
  let maxImages =
    try parseMaxImages(
      args.string("max-images")
        ?? env("METACUA_MAX_IMAGES")
        ?? env("LLM_MAX_IMAGES")
        ?? file["maxImages"])
    ?? AgentConfig.defaultMaxImages
  let batchedActions = try parseBatchedActions(args, file: file)

  return AgentConfig(
    apiKey: key,
    baseURL: normalizeBaseURL(baseURL),
    model: model,
    coords: coords,
    effort: effort,
    screenshotScale: screenshotScale,
    maxImages: maxImages,
    batchedActions: batchedActions
  )
}

/// `metacua configure` - persist endpoint, key, and model settings to the config file.
func runConfigure(_ raw: [String]) throws {
  let args = try Args(raw)
  var file = loadConfigFile()

  if let key = args.string("api-key") { file["apiKey"] = key }
  if let url = args.string("base-url") { file["baseURL"] = normalizeBaseURL(url) }
  if let model = args.string("model") { file["model"] = model }
  if let coords = args.string("coords") { file["coords"] = coords }
  if let effort = args.string("effort") { file["effort"] = effort }
  if let screenshotScale = try parseScreenshotScale(args.string("screenshot-scale")) {
    file["screenshotScale"] = String(screenshotScale)
  }
  if let maxImages = try parseMaxImages(args.string("max-images")) {
    file["maxImages"] = String(maxImages)
  }
  if (args.flag("batched-actions") || args.flag("batch-actions"))
    && (args.flag("no-batched-actions") || args.flag("no-batch-actions"))
  {
    throw CLIError("pass only one of --batched-actions or --no-batched-actions", code: 2)
  }
  if args.flag("batched-actions") || args.flag("batch-actions") {
    file["batchedActions"] = "true"
  }
  if args.flag("no-batched-actions") || args.flag("no-batch-actions") {
    file["batchedActions"] = "false"
  }
  if let batchedActions = args.string("batched-actions") ?? args.string("batch-actions") {
    file["batchedActions"] = String(try parseBool(batchedActions, label: "batched actions"))
  }

  if file.isEmpty {
    throw CLIError(
      "nothing to save - pass --api-key, --base-url, --model, --coords, --effort, --screenshot-scale, --max-images, and/or --batched-actions",
      code: 2)
  }

  let url = configFileURL()
  let fileManager = FileManager.default
  try fileManager.createDirectory(
    at: url.deletingLastPathComponent(),
    withIntermediateDirectories: true,
    attributes: [.posixPermissions: 0o700]
  )
  let data = try JSONSerialization.data(
    withJSONObject: file, options: [.prettyPrinted, .sortedKeys])
  guard
    fileManager.createFile(atPath: url.path, contents: data, attributes: [.posixPermissions: 0o600])
  else {
    throw CLIError("failed to write config to \(url.path)")
  }

  let shownKey = file["apiKey"].map { "set (\($0.count) chars)" } ?? "not set"
  print("Saved config to \(url.path)")
  print("  baseURL: \(file["baseURL"] ?? AgentConfig.defaultBaseURL)")
  print("  model:   \(file["model"] ?? AgentConfig.defaultModel)")
  print("  coords:  \(file["coords"] ?? "normalized")")
  print("  effort:  \(file["effort"] ?? "high")")
  print("  scale:   \(file["screenshotScale"] ?? String(AgentConfig.defaultScreenshotScale))")
  print("  images:  \(file["maxImages"] ?? String(AgentConfig.defaultMaxImages))")
  print("  batch:   \(file["batchedActions"] ?? String(AgentConfig.defaultBatchedActions))")
  print("  apiKey:  \(shownKey)")
}
