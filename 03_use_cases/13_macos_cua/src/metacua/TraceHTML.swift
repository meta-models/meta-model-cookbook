import Foundation

/// Renders a saved trace (`<traces>/<traceId>.jsonl` + sidecar PNGs) into a
/// self-describing HTML timeline: one card per step with the screenshot the
/// model saw, its reasoning, the action(s) it took, and click coordinates
/// (normalized 0-1000) overlaid as markers on the screenshot.
enum TraceHTML {
  // Matches the sidecar reference the SessionStore writes into the JSONL,
  // e.g. `data:image/png;base64,<saved <traceId>/<hash>.png (329394 bytes)>`.
  private static let savedPattern = try! NSRegularExpression(
    pattern: #"<saved ([^ >]+) \((\d+) bytes\)>"#)
  private static let coordMax = 1000.0

  /// Generate `<traces>/<traceId>.html`. When `inlineImages` is true the
  /// screenshots are embedded as base64 (portable but large); otherwise they
  /// are referenced by relative path (small, opens locally next to the images).
  @discardableResult
  static func render(traceId: String, inlineImages: Bool = false) throws -> URL {
    let tracesDir = SessionStore.shared.storageURL
    let jsonlURL = SessionStore.shared.traceFileURL(traceId: traceId)
    guard FileManager.default.fileExists(atPath: jsonlURL.path) else {
      throw CLIError("no trace found at \(jsonlURL.path)")
    }

    let records = try loadRecords(jsonlURL)
    guard !records.isEmpty else {
      throw CLIError("trace \(traceId) has no records")
    }

    let html = buildHTML(records: records, tracesDir: tracesDir, inlineImages: inlineImages)
    let outURL = jsonlURL.deletingPathExtension().appendingPathExtension("html")
    try html.data(using: .utf8)?.write(to: outURL, options: [.atomic])
    return outURL
  }

  // MARK: - Loading

  private static func loadRecords(_ url: URL) throws -> [[String: Any]] {
    let data = try Data(contentsOf: url)
    guard let text = String(data: data, encoding: .utf8) else {
      throw CLIError("could not read trace as UTF-8")
    }
    var records: [[String: Any]] = []
    for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
      guard
        let d = String(line).data(using: .utf8),
        let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
      else { continue }
      records.append(obj)
    }
    records.sort { (($0["step"] as? Int) ?? 0) < (($1["step"] as? Int) ?? 0) }
    return records
  }

  // MARK: - Image references

  /// All sidecar-relative image paths referenced anywhere in a JSON value, in order, de-duped.
  private static func imageRefs(_ value: Any?) -> [String] {
    var refs: [String] = []
    func walk(_ v: Any?) {
      if let dict = v as? [String: Any] {
        for child in dict.values { walk(child) }
      } else if let arr = v as? [Any] {
        for child in arr { walk(child) }
      } else if let s = v as? String {
        let ns = s as NSString
        for m in savedPattern.matches(in: s, range: NSRange(location: 0, length: ns.length)) {
          refs.append(ns.substring(with: m.range(at: 1)))
        }
      }
    }
    walk(value)
    var seen = Set<String>()
    return refs.filter { seen.insert($0).inserted }
  }

  private static func imageSource(tracesDir: URL, relpath: String, inline: Bool) -> String? {
    let path = tracesDir.appendingPathComponent(relpath)
    guard FileManager.default.fileExists(atPath: path.path) else { return nil }
    if !inline { return relpath }
    guard let bytes = try? Data(contentsOf: path) else { return nil }
    let mime = relpath.hasSuffix(".jpg") || relpath.hasSuffix(".jpeg") ? "image/jpeg" : "image/png"
    return "data:\(mime);base64,\(bytes.base64EncodedString())"
  }

  // MARK: - Click markers

  private struct Marker {
    let left: Double
    let top: Double
    let label: String
  }

  private static func markers(_ toolCalls: [[String: Any]]) -> [Marker] {
    var out: [Marker] = []
    for call in toolCalls {
      guard let input = call["input"] as? [String: Any] else { continue }
      let action = (input["action"] as? String)?.lowercased() ?? "point"
      if let pt = point(input["coordinate"]) {
        out.append(marker(pt, action))
      }
      if let start = point(input["start_coordinate"]) {
        out.append(marker(start, "drag start"))
      }
    }
    return out
  }

  private static func point(_ value: Any?) -> (Double, Double)? {
    guard let arr = value as? [Any], arr.count == 2 else { return nil }
    let x = (arr[0] as? NSNumber)?.doubleValue ?? Double("\(arr[0])")
    let y = (arr[1] as? NSNumber)?.doubleValue ?? Double("\(arr[1])")
    guard let x, let y else { return nil }
    return (x, y)
  }

  private static func marker(_ pt: (Double, Double), _ kind: String) -> Marker {
    let clamp = { (v: Double) in max(0.0, min(100.0, v / coordMax * 100.0)) }
    return Marker(
      left: clamp(pt.0), top: clamp(pt.1),
      label: "\(kind) \(Int(pt.0.rounded())),\(Int(pt.1.rounded()))")
  }

  // MARK: - HTML

  private static func buildHTML(
    records: [[String: Any]], tracesDir: URL, inlineImages: Bool
  )
    -> String
  {
    let first = records.first ?? [:]
    let goal = str(first["goal"])
    let model = str(first["model"])
    let backend = str(first["backend"])
    let traceId = str(first["trace_id"])
    let started = str(first["timestamp"])

    var totalImgs = 0
    var steps: [String] = []
    for r in records {
      let step = (r["step"] as? Int).map(String.init) ?? "?"
      let finish = str(r["finish"])
      let text = str(r["text"])
      let thinking = str(r["thinking"])
      let toolCalls = (r["tool_calls"] as? [[String: Any]]) ?? []

      let ms = markers(toolCalls)
      var shot = "<div class=\"noshot\">no screenshot saved for this step</div>"
      let refs = imageRefs(r["request"]).isEmpty ? imageRefs(r) : imageRefs(r["request"])
      if let last = refs.last, let src = imageSource(tracesDir: tracesDir, relpath: last, inline: inlineImages) {
        totalImgs += 1
        let markerHTML = ms.map {
          "<div class=\"marker\" style=\"left:\(fmt($0.left))%;top:\(fmt($0.top))%\">"
            + "<span class=\"dot\"></span><span class=\"lbl\">\(esc($0.label))</span></div>"
        }.joined()
        shot =
          "<div class=\"imgwrap\"><a href=\"\(esc(src))\" target=\"_blank\">"
          + "<img src=\"\(esc(src))\" alt=\"step \(esc(step))\" loading=\"lazy\"></a>\(markerHTML)</div>"
      }

      var actions = ""
      if !toolCalls.isEmpty {
        let items = toolCalls.map { call -> String in
          let name = esc(str(call["name"]))
          let inputJSON = jsonString(call["input"])
          return "<li><span class=\"act-name\">\(name)</span> <code>\(esc(inputJSON))</code></li>"
        }.joined()
        actions = "<div class=\"actions\"><div class=\"label\">actions</div><ul>\(items)</ul></div>"
      }

      let textHTML =
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        ? "" : "<div class=\"text\">\(esc(text))</div>"
      let thinkingHTML =
        thinking.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        ? ""
        : "<details class=\"thinking\"><summary>thinking</summary><pre>\(esc(thinking))</pre></details>"

      steps.append(
        """
          <section class="step">
            <div class="shot">\(shot)</div>
            <div class="body">
              <div class="step-head"><span class="num">step \(esc(step))</span>
                <span class="finish">\(esc(finish))</span></div>
              \(textHTML)
              \(actions)
              \(thinkingHTML)
            </div>
          </section>
        """)
    }

    let title = goal.isEmpty ? traceId : goal
    return """
      <!doctype html>
      <html lang="en"><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>\(esc(title))</title>
      <style>
        :root { color-scheme: light dark; }
        * { box-sizing: border-box; }
        body { margin: 0; font: 15px/1.5 -apple-system, system-ui, sans-serif; background: Canvas; color: CanvasText; }
        header { padding: 20px 24px; border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent);
          position: sticky; top: 0; background: color-mix(in srgb, Canvas 92%, transparent); backdrop-filter: blur(8px); z-index: 5; }
        header h1 { margin: 0 0 6px; font-size: 18px; }
        header .meta { font-size: 13px; opacity: .7; display: flex; gap: 16px; flex-wrap: wrap; }
        main { max-width: 1000px; margin: 0 auto; padding: 16px; }
        .step { display: grid; grid-template-columns: 340px 1fr; gap: 20px; padding: 20px 8px;
          border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent); align-items: start; }
        .shot img { width: 100%; border-radius: 8px; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent);
          cursor: zoom-in; display: block; }
        .imgwrap { position: relative; line-height: 0; }
        .marker { position: absolute; transform: translate(-50%, -50%); pointer-events: none; z-index: 2; }
        .marker .dot { display: block; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%;
          border: 2px solid #ff2d55; box-shadow: 0 0 0 2px rgba(255,255,255,.9), 0 0 8px 2px rgba(255,45,85,.6);
          background: rgba(255,45,85,.25); animation: pulse 1.6s ease-out infinite; }
        .marker .dot::after { content: ""; position: absolute; left: 50%; top: 50%; width: 4px; height: 4px;
          margin: -2px 0 0 -2px; border-radius: 50%; background: #ff2d55; }
        .marker .lbl { position: absolute; left: 16px; top: -6px; white-space: nowrap;
          font: 11px/1.4 ui-monospace, monospace; color: #fff; background: rgba(255,45,85,.92); padding: 1px 6px; border-radius: 5px; }
        @keyframes pulse { 0% { box-shadow: 0 0 0 2px rgba(255,255,255,.9), 0 0 0 0 rgba(255,45,85,.5); }
          100% { box-shadow: 0 0 0 2px rgba(255,255,255,.9), 0 0 0 14px rgba(255,45,85,0); } }
        .step-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
        .num { font-weight: 700; }
        .finish { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: color-mix(in srgb, CanvasText 12%, transparent); }
        .text { margin: 6px 0; white-space: pre-wrap; }
        .actions .label { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; opacity: .6; margin-top: 10px; }
        .actions ul { margin: 4px 0 0; padding-left: 18px; }
        .actions li { margin: 3px 0; }
        .act-name { font-weight: 600; }
        code { font: 12px/1.4 ui-monospace, monospace; background: color-mix(in srgb, CanvasText 8%, transparent);
          padding: 1px 6px; border-radius: 5px; word-break: break-word; }
        .thinking { margin-top: 10px; }
        .thinking summary { cursor: pointer; font-size: 12px; opacity: .6; }
        .thinking pre { white-space: pre-wrap; font: 12px/1.5 ui-monospace, monospace;
          background: color-mix(in srgb, CanvasText 6%, transparent); padding: 10px; border-radius: 6px; }
        @media (max-width: 720px) { .step { grid-template-columns: 1fr; } }
      </style></head>
      <body>
      <header>
        <h1>\(esc(title.isEmpty ? "metacua trace" : title))</h1>
        <div class="meta">
          <span>trace <code>\(esc(traceId))</code></span>
          <span>model \(esc(model))</span>
          <span>backend \(esc(backend))</span>
          <span>\(records.count) steps</span>
          <span>\(totalImgs) screenshots</span>
          <span>\(esc(started))</span>
        </div>
      </header>
      <main>
      \(steps.joined(separator: "\n"))
      </main>
      </body></html>
      """
  }

  // MARK: - Small helpers

  private static func str(_ value: Any?) -> String {
    guard let value, !(value is NSNull) else { return "" }
    return value as? String ?? "\(value)"
  }

  private static func jsonString(_ value: Any?) -> String {
    guard let value, JSONSerialization.isValidJSONObject(value) || value is [Any],
      let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
      let text = String(data: data, encoding: .utf8)
    else { return str(value) }
    return text
  }

  private static func fmt(_ v: Double) -> String { String(format: "%.3f", v) }

  private static func esc(_ s: String) -> String {
    s.replacingOccurrences(of: "&", with: "&amp;")
      .replacingOccurrences(of: "<", with: "&lt;")
      .replacingOccurrences(of: ">", with: "&gt;")
      .replacingOccurrences(of: "\"", with: "&quot;")
  }
}

/// `metacua render <trace-id> [--inline] [--open]`
func runRender(_ raw: [String]) throws {
  // The trace id is the first bare (non-flag) token; the rest are parsed as flags.
  var traceId: String? = nil
  var flagArgs: [String] = []
  for token in raw {
    if token.hasPrefix("--") {
      flagArgs.append(token)
    } else if traceId == nil {
      traceId = token
    } else {
      flagArgs.append(token)
    }
  }
  let args = try Args(flagArgs)
  guard let traceId = traceId ?? args.string("id") else {
    throw CLIError("usage: metacua render <trace-id> [--inline] [--open]", code: 2)
  }
  let out = try TraceHTML.render(traceId: traceId, inlineImages: args.flag("inline"))
  print("wrote \(out.path)")
  if args.flag("open") {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    proc.arguments = [out.path]
    try? proc.run()
  }
}
