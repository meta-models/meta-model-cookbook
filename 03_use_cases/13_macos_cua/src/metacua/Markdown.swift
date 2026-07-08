import Foundation

/// Minimal Markdown -> ANSI renderer used to display the agent's final answer
/// nicely in the terminal. Handles headers, bold/italic, inline + fenced code,
/// bullet/numbered lists, blockquotes, links, and horizontal rules. When color
/// is disabled it strips the markup and returns clean plain text.
enum TerminalMarkdown {
  private static let reset = "\u{001B}[0m"

  static func render(_ markdown: String, useColor: Bool) -> String {
    var out: [String] = []
    var inFence = false
    let lines = markdown.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)

    for line in lines {
      let trimmed = line.trimmingCharacters(in: .whitespaces)

      // Fenced code block: ``` toggles; contents are shown dim, verbatim.
      if trimmed.hasPrefix("```") {
        inFence.toggle()
        continue
      }
      if inFence {
        out.append(sgr(line, "2", useColor))
        continue
      }

      // Horizontal rule.
      if trimmed == "---" || trimmed == "***" || trimmed == "___" {
        out.append(sgr(String(repeating: "─", count: 24), "2", useColor))
        continue
      }

      // ATX headers (#, ##, ###...).
      if let (level, rest) = header(trimmed) {
        let text = inline(rest, useColor: useColor)
        out.append(sgr(text, level == 1 ? "1;4" : "1", useColor))
        continue
      }

      // Blockquote.
      if trimmed.hasPrefix(">") {
        let body = String(trimmed.drop(while: { $0 == ">" })).trimmingCharacters(in: .whitespaces)
        out.append(sgr("▏", "2", useColor) + " " + inline(body, useColor: useColor))
        continue
      }

      // List item (-, *, + or "1." style).
      if let (indent, marker, body) = listItem(line) {
        let bullet = marker == "•" ? sgr("•", "36", useColor) : sgr(marker, "36", useColor)
        out.append("\(indent)\(bullet) \(inline(body, useColor: useColor))")
        continue
      }

      out.append(inline(line, useColor: useColor))
    }

    return out.joined(separator: "\n")
  }

  // MARK: - Block helpers

  private static func header(_ line: String) -> (Int, String)? {
    guard line.hasPrefix("#") else { return nil }
    var level = 0
    var idx = line.startIndex
    while idx < line.endIndex && line[idx] == "#" && level < 6 {
      level += 1
      idx = line.index(after: idx)
    }
    guard idx < line.endIndex, line[idx] == " " else { return nil }
    return (level, String(line[line.index(after: idx)...]))
  }

  private static func listItem(_ line: String) -> (String, String, String)? {
    let leading = line.prefix(while: { $0 == " " })
    let indent = String(leading)
    let rest = line[line.index(line.startIndex, offsetBy: leading.count)...]
    // Unordered.
    for m in ["- ", "* ", "+ "] where rest.hasPrefix(m) {
      return (indent, "•", String(rest.dropFirst(2)))
    }
    // Ordered: "12. text"
    let digits = rest.prefix(while: { $0.isNumber })
    if !digits.isEmpty {
      let afterDigits = rest[rest.index(rest.startIndex, offsetBy: digits.count)...]
      if afterDigits.hasPrefix(". ") {
        return (indent, "\(digits).", String(afterDigits.dropFirst(2)))
      }
    }
    return nil
  }

  // MARK: - Inline helpers

  private static func inline(_ text: String, useColor: Bool) -> String {
    var s = text
    // Order matters: code first so its contents are not reinterpreted.
    s = replace(s, #"`([^`]+)`"#) { g in sgr(g[1], "36", useColor) }
    s = replace(s, #"\[([^\]]+)\]\(([^)]+)\)"#) { g in
      useColor ? "\(sgr(g[1], "4", useColor)) \(sgr("(\(g[2]))", "2", useColor))" : "\(g[1]) (\(g[2]))"
    }
    s = replace(s, #"\*\*([^*]+)\*\*"#) { g in sgr(g[1], "1", useColor) }
    s = replace(s, #"__([^_]+)__"#) { g in sgr(g[1], "1", useColor) }
    s = replace(s, #"(?<![*\w])\*([^*\n]+)\*(?![*\w])"#) { g in sgr(g[1], "3", useColor) }
    return s
  }

  private static func replace(
    _ text: String, _ pattern: String, _ transform: ([String]) -> String
  ) -> String {
    guard let re = try? NSRegularExpression(pattern: pattern) else { return text }
    let ns = text as NSString
    var result = ""
    var last = 0
    for m in re.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
      result += ns.substring(with: NSRange(location: last, length: m.range.location - last))
      var groups: [String] = []
      for i in 0..<m.numberOfRanges {
        let r = m.range(at: i)
        groups.append(r.location == NSNotFound ? "" : ns.substring(with: r))
      }
      result += transform(groups)
      last = m.range.location + m.range.length
    }
    result += ns.substring(from: last)
    return result
  }

  private static func sgr(_ text: String, _ code: String, _ useColor: Bool) -> String {
    useColor ? "\u{001B}[\(code)m\(text)\(reset)" : text
  }
}
