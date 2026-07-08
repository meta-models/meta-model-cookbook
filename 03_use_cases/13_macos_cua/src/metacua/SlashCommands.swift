import Foundation

struct SlashCommandSpec {
  let name: String
  let aliases: [String]
  let arguments: String
  let description: String
  let displayName: String?

  init(
    _ name: String,
    aliases: [String] = [],
    arguments: String = "",
    description: String,
    displayName: String? = nil
  ) {
    self.name = name
    self.aliases = aliases
    self.arguments = arguments
    self.description = description
    self.displayName = displayName
  }

  var names: [String] {
    [name] + aliases
  }

  var displayCommand: String {
    let base = displayName ?? name
    return arguments.isEmpty ? base : "\(base) \(arguments)"
  }
}

let slashCommandSpecs: [SlashCommandSpec] = [
  SlashCommandSpec("/help", aliases: ["/?"], description: "show this help"),
  SlashCommandSpec("/model", arguments: "[id]", description: "show or switch the active model"),
  SlashCommandSpec(
    "/effort",
    arguments: "[level]",
    description: "show or set effort: low, medium, high, xhigh, max"
  ),
  SlashCommandSpec(
    "/coords",
    aliases: ["/coordinates"],
    arguments: "[mode]",
    description: "show or set coordinates: pixel, normalized"
  ),
  SlashCommandSpec(
    "/max-steps",
    aliases: ["/maxsteps"],
    arguments: "[n|off]",
    description: "show, set, or clear per-goal step cap"
  ),
  SlashCommandSpec(
    "/max-images",
    aliases: ["/maximages"],
    arguments: "[n]",
    description: "show or set recent image limit"
  ),
  SlashCommandSpec(
    "/batched-actions",
    aliases: ["/batch-actions", "/batching"],
    arguments: "[on|off]",
    description: "show or toggle batched action tool schema"
  ),
  SlashCommandSpec(
    "/overlay", arguments: "[on|off]", description: "show or toggle cursor overlay"),
  SlashCommandSpec(
    "/plan",
    arguments: "[on|off]",
    description: "show or skip a short plan before each goal"
  ),
  SlashCommandSpec("/status", description: "show session state and permissions"),
  SlashCommandSpec("/tools", description: "list computer-use tools"),
  SlashCommandSpec("/doctor", description: "check configuration and permissions"),
  SlashCommandSpec("/config", description: "show active model settings"),
  SlashCommandSpec(
    "/sessions",
    aliases: ["/session-history", "/history"],
    arguments: "[n|id]",
    description: "list saved LLM sessions, or show one by id"
  ),
  SlashCommandSpec(
    "/permissions",
    aliases: ["/permission"],
    arguments: "[--prompt]",
    description: "show or request macOS permissions"
  ),
  SlashCommandSpec("/clear", description: "clear the terminal"),
  SlashCommandSpec(
    "/new",
    aliases: ["/reset"],
    description: "start a fresh goal context",
    displayName: "/new, /reset"
  ),
  SlashCommandSpec("/quit", aliases: ["/exit"], description: "exit"),
]

struct SlashCommandCatalog {
  let specs: [SlashCommandSpec]

  init(specs: [SlashCommandSpec] = slashCommandSpecs) {
    self.specs = specs
  }

  func spec(named command: String) -> SlashCommandSpec? {
    specs.first { spec in
      spec.names.contains(command)
    }
  }

  func matchingNames(prefix: String) -> [String] {
    specs.flatMap(\.names)
      .filter { $0.hasPrefix(prefix) }
      .sorted()
  }

  func commonPrefix(for names: [String]) -> String {
    guard var prefix = names.first else { return "" }
    for name in names.dropFirst() {
      while !name.hasPrefix(prefix), !prefix.isEmpty {
        prefix.removeLast()
      }
    }
    return prefix
  }
}
