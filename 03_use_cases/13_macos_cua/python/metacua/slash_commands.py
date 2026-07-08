"""Interactive slash-command registry shared by help and completion."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SlashCommandSpec:
    name: str
    aliases: List[str] = field(default_factory=list)
    arguments: str = ""
    description: str = ""
    display_name: Optional[str] = None

    @property
    def names(self) -> List[str]:
        return [self.name] + list(self.aliases)

    @property
    def display_command(self) -> str:
        base = self.display_name or self.name
        return base if not self.arguments else f"{base} {self.arguments}"


SLASH_COMMAND_SPECS: List[SlashCommandSpec] = [
    SlashCommandSpec("/help", aliases=["/?"], description="show this help"),
    SlashCommandSpec("/model", arguments="[id]", description="show or switch the active model"),
    SlashCommandSpec(
        "/syntax",
        arguments="[mode]",
        description="show or set action syntax: function, pyautogui",
    ),
    SlashCommandSpec(
        "/effort",
        arguments="[level]",
        description="show or set effort: low, medium, high, xhigh, max",
    ),
    SlashCommandSpec(
        "/coords",
        aliases=["/coordinates"],
        arguments="[mode]",
        description="show or set coordinates: pixel, normalized",
    ),
    SlashCommandSpec(
        "/max-steps",
        aliases=["/maxsteps"],
        arguments="[n|off]",
        description="show, set, or clear per-goal step cap",
    ),
    SlashCommandSpec(
        "/max-images",
        aliases=["/maximages"],
        arguments="[n]",
        description="show or set retained image count",
    ),
    SlashCommandSpec(
        "/batched-actions",
        aliases=["/batch-actions", "/batching"],
        arguments="[on|off]",
        description="show or toggle batched action tool schema",
    ),
    SlashCommandSpec("/overlay", arguments="[on|off]", description="show or toggle cursor overlay"),
    SlashCommandSpec(
        "/debug",
        arguments="[on|off]",
        description="show or hide backend reasoning text during execution",
    ),
    SlashCommandSpec("/status", description="show session state and permissions"),
    SlashCommandSpec("/tools", description="list computer-use tools"),
    SlashCommandSpec("/doctor", description="check configuration and permissions"),
    SlashCommandSpec("/config", description="show active model settings"),
    SlashCommandSpec(
        "/sessions",
        aliases=["/session-history", "/history"],
        arguments="[n|id]",
        description="list saved LLM sessions, or show one by id",
    ),
    SlashCommandSpec(
        "/permissions",
        aliases=["/permission"],
        arguments="[--prompt]",
        description="show or request macOS permissions",
    ),
    SlashCommandSpec("/clear", description="clear the terminal"),
    SlashCommandSpec(
        "/new",
        aliases=["/reset"],
        description="start a fresh goal context",
        display_name="/new, /reset",
    ),
    SlashCommandSpec("/quit", aliases=["/exit"], description="exit"),
]


class SlashCommandCatalog:
    def __init__(self, specs: Optional[List[SlashCommandSpec]] = None):
        self.specs = specs if specs is not None else SLASH_COMMAND_SPECS

    def spec(self, command: str) -> Optional[SlashCommandSpec]:
        for spec in self.specs:
            if command in spec.names:
                return spec
        return None

    def matching_names(self, prefix: str) -> List[str]:
        names = [name for spec in self.specs for name in spec.names if name.startswith(prefix)]
        return sorted(names)

    def common_prefix(self, names: List[str]) -> str:
        if not names:
            return ""
        prefix = names[0]
        for name in names[1:]:
            while prefix and not name.startswith(prefix):
                prefix = prefix[:-1]
        return prefix
