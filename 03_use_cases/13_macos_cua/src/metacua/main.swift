import Foundation

// Entry point. Dispatches the first argument to a subcommand.
// Pure-GUI automation: every action is driven by pixel coordinates and
// synthetic keyboard/mouse events (CGEvent). `--app` is used only to bring
// the target application to the front before the action is performed.

let argv = Array(CommandLine.arguments.dropFirst())

do {
  guard let command = argv.first else {
    try runAgent([])
    exit(0)
  }
  let rest = Array(argv.dropFirst())

  switch command {
  case "click":
    try runClick(rest)
  case "moveto", "move":
    try runMove(rest)
  case "pointer", "cursor":
    try runPointerControl(rest)
  case "shot", "screenshot":
    try runShot(rest)
  case "demo", "overlay-demo":
    try runDemo(rest)
  case "scroll":
    try runScroll(rest)
  case "drag":
    try runDrag(rest)
  case "press-key", "press_key", "key":
    try runPressKey(rest)
  case "type-text", "type_text", "type":
    try runTypeText(rest)
  case "agent":
    try runAgent(rest)
  case "sessions", "session-history", "history":
    try runSessions(rest)
  case "render", "render-html", "html":
    try runRender(rest)
  case "configure", "config":
    try runConfigure(rest)
  case "permissions", "perm", "check":
    try runPermissions(rest)
  case "-h", "--help", "help":
    printUsage()
  case "-v", "--version", "version":
    print("metacua 1.0.0")
  default:
    FileHandle.standardError.write(Data("error: unknown command '\(command)'\n\n".utf8))
    printUsage(toStderr: true)
    exit(2)
  }
} catch let error as CLIError {
  FileHandle.standardError.write(Data("error: \(error.message)\n".utf8))
  exit(error.code)
} catch {
  FileHandle.standardError.write(Data("error: \(error)\n".utf8))
  exit(1)
}
