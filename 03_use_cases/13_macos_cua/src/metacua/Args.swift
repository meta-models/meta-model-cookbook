import Foundation

/// A typed CLI error carrying an exit code.
struct CLIError: Error {
  let message: String
  let code: Int32
  init(_ message: String, code: Int32 = 1) {
    self.message = message
    self.code = code
  }
}

/// Minimal, dependency-free `--flag value` / `--flag=value` parser.
struct Args {
  private var values: [String: String] = [:]
  private var flags: Set<String> = []

  init(_ raw: [String]) throws {
    var i = 0
    while i < raw.count {
      let token = raw[i]
      guard token.hasPrefix("--") else {
        throw CLIError("unexpected argument '\(token)' (flags must start with --)", code: 2)
      }
      let body = String(token.dropFirst(2))
      if let eq = body.firstIndex(of: "=") {
        let key = String(body[..<eq])
        let value = String(body[body.index(after: eq)...])
        values[key] = value
        i += 1
        continue
      }
      if i + 1 < raw.count && !raw[i + 1].hasPrefix("--") {
        values[body] = raw[i + 1]
        i += 2
      } else {
        flags.insert(body)
        i += 1
      }
    }
  }

  func string(_ name: String) -> String? { values[name] }

  func string(_ names: [String]) -> String? {
    for name in names where values[name] != nil { return values[name] }
    return nil
  }

  func requiredString(_ name: String) throws -> String {
    guard let value = values[name] else {
      throw CLIError("missing required option --\(name)", code: 2)
    }
    return value
  }

  func int(_ name: String) throws -> Int? {
    guard let value = values[name] else { return nil }
    guard let number = Int(value) else {
      throw CLIError("--\(name) must be an integer (got '\(value)')", code: 2)
    }
    return number
  }

  func double(_ name: String) throws -> Double? {
    guard let value = values[name] else { return nil }
    guard let number = Double(value), number.isFinite else {
      throw CLIError("--\(name) must be a finite number (got '\(value)')", code: 2)
    }
    return number
  }

  func requiredDouble(_ name: String) throws -> Double {
    guard let value = try double(name) else {
      throw CLIError("missing required option --\(name)", code: 2)
    }
    return value
  }

  func flag(_ name: String) -> Bool { flags.contains(name) }
}

func printUsage(toStderr: Bool = false) {
  let text = """
    metacua - terminal-first macOS computer-use agent

    USAGE:
      metacua                  Start the interactive agent session
      metacua <command> [options]

    AGENT:
      agent       Run the agent: it screenshots the screen, sends it to Muse Spark, prints model output and tool calls, and executes GUI tool calls.
      sessions    View saved LLM session ids and sanitized per-trajectory message history.
      render      Render a saved trace into an HTML timeline (screenshots + actions + click markers).
      configure   Save endpoint, API key, model, coordinates, effort, and tool settings to a config file.

    MANUAL TOOLS:
      click       Click at pixel coordinates
      moveto      Move the pointer to pixel coordinates without clicking
      pointer     Control the pointer with arrow keys in the terminal
      screenshot  Capture a screenshot to PNG
      scroll      Scroll in a direction by N pages
      drag        Drag between two pixel coordinates
      press-key   Press a key or key-combination
      type-text   Insert literal text into the focused field
      permissions Show or request Accessibility and Screen Recording permission
      help        Show this help

    COMMON:
      --app <name|bundle-id>   Application to bring to front first. Use "current" or "frontmost" to skip activation.

    click     --app A --x N --y N [--click-count N] [--mouse-button left|right|center]
    moveto    --app A --x N --y N
    pointer   [--app A] [--step N]
    screenshot [--out PATH] [--scale 0.5]
    scroll    --app A --direction up|down|left|right [--pages N] [--lines-per-page N] [--x N --y N]
    drag      --app A --from-x N --from-y N --to-x N --to-y N [--mouse-button left|right|center]
    press-key --app A --key "cmd+shift+a"
    type-text --app A --text "hello world"

    AGENT OPTIONS:
      metacua agent [--goal "..."] [--model NAME] [--base-url URL] [--api-key KEY] [--coords pixel|normalized] [--effort low|medium|high|xhigh|max] [--screenshot-scale 1.0] [--max-images N] [--batched-actions] [--max-steps N] [--no-overlay] [--no-plan]
      metacua sessions [--limit N] [--id ID] [--json] [--history] [--path]
      metacua render <trace-id> [--inline] [--open]

      Default base URL: https://api.meta.ai/v1
      Default model:    muse-spark-1.1
      Default coords:   normalized (0-1000)
      Default screenshot scale: 1.0
      Default recent image limit: 5
      Default batched actions: off
      Default overlay: on
      Resolution order: flags -> env (MODEL_API_KEY / MUSE_SPARK_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_EFFORT, METACUA_SCREENSHOT_SCALE, METACUA_MAX_IMAGES, METACUA_BATCHED_ACTIONS) -> config file -> defaults.
      Without --goal, the agent starts an interactive terminal session.
      The agent prints a short plan before acting; pass --no-plan to skip the extra planning call.
      The overlay opens by default; pass --no-overlay to keep the terminal visible during goals.
      There is no default step cap; set --max-steps N when you want one.

    INTERACTIVE SLASH COMMANDS:
      /help                    show command help
      /model [name]            show or switch the active model
      /effort [level]          show or set effort: low, medium, high, xhigh, max
      /coords [mode]           show or set coordinates: pixel, normalized
      /max-steps [n|off]       show, set, or clear per-goal step cap
      /max-images [n]          show or set recent image limit
      /batched-actions [on|off] show or toggle batched action tool schema
      /overlay [on|off]        show or toggle cursor overlay
      /plan [on|off]           show or skip a short plan before each goal
      /status                  show session state and permissions
      /tools                   list computer-use tools
      /doctor                  check configuration and permissions
      /config                  show active model settings
      /sessions [n|id]         list saved LLM sessions, or show one by id
      /permissions [--prompt]  show or request macOS permissions
      /clear                   clear the terminal
      /new, /reset             start a fresh goal context
      /quit                    exit

      Slash command input supports inline hints and Tab completion in interactive terminals.

    CONFIGURE:
      metacua configure --api-key KEY [--base-url URL] [--model NAME] [--coords pixel|normalized] [--effort E] [--screenshot-scale 1.0] [--max-images N] [--batched-actions|--no-batched-actions]

    EXAMPLES:
      metacua configure --api-key LLM_...
      metacua agent --goal "Open Safari and search for the weather in Tokyo"
      metacua click --app Finder --x 120 --y 90 --click-count 2
      metacua scroll --app Safari --direction down --pages 3
      metacua press-key --app Safari --key cmd+t

    NOTE: Native macOS control needs Accessibility and Screen Recording permission. Run `metacua permissions --prompt` to open the system dialogs.
    """
  if toStderr {
    FileHandle.standardError.write(Data((text + "\n").utf8))
  } else {
    print(text)
  }
}
