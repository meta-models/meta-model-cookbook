//! Static lexer definitions, transcribed as data from Python `RegexLexer`
//! subclasses. A ported lexer is one `LexerDef` static: name, aliases, flags
//! and a `states` table of rules.
//!
//! Patterns use Python `re` syntax and are matched at the current position
//! only. In addition to Python syntax, a pattern may contain unistring
//! placeholders expanded by the engine before compilation: `${Ll}`,
//! `${xid_start}`, `${combine:Ll,Lu}` and `${allexcept:Cc,Cf}` stand for the
//! matching `pygments.unistring` character-class strings.
//!
//! Example (mirrors the Python tokens table):
//!
//! ```ignore
//! pub static LEXER: LexerDef = LexerDef {
//!     name: "Example",
//!     aliases: &["example"],
//!     flags: Flags::MULTILINE,
//!     parent: None,
//!     states: &[
//!         ("root", &[
//!             Rule::new(Pattern::Re(r"\s+"), Action::Token(token::WHITESPACE), Transition::Stay),
//!             Rule::new(words(&["if", "else"]), Action::Token(token::KEYWORD), Transition::Stay),
//!         ]),
//!     ],
//! };
//! ```

use std::ops::BitOr;

use crate::token::TokenType;

/// Regex compilation flags, mirroring the Python `re` flags a lexer class
/// sets in its `flags` attribute. `RegexLexer`'s Python default is
/// `Flags::MULTILINE`; a definition supplies its full flag set.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Flags(pub u32);

impl Flags {
    pub const NONE: Flags = Flags(0);
    pub const IGNORECASE: Flags = Flags(1 << 0);
    pub const MULTILINE: Flags = Flags(1 << 1);
    pub const DOTALL: Flags = Flags(1 << 2);
    pub const VERBOSE: Flags = Flags(1 << 3);
    pub const UNICODE: Flags = Flags(1 << 4);
    pub const ASCII: Flags = Flags(1 << 5);

    pub const fn contains(self, other: Flags) -> bool {
        self.0 & other.0 == other.0
    }
    pub const fn union(self, other: Flags) -> Flags {
        Flags(self.0 | other.0)
    }
}

impl BitOr for Flags {
    type Output = Flags;
    fn bitor(self, rhs: Flags) -> Flags {
        Flags(self.0 | rhs.0)
    }
}

#[derive(Clone, Copy, Debug)]
pub enum Pattern {
    /// A Python `re` pattern.
    Re(&'static str),
    /// `words(...)` from `pygments.lexer`: literal words with an optional
    /// regex prefix and suffix.
    Words {
        words: &'static [&'static str],
        prefix: &'static str,
        suffix: &'static str,
    },
}

pub const fn words(list: &'static [&'static str]) -> Pattern {
    Pattern::Words { words: list, prefix: "", suffix: "" }
}

pub const fn words_affix(list: &'static [&'static str], prefix: &'static str, suffix: &'static str) -> Pattern {
    Pattern::Words { words: list, prefix, suffix }
}

/// What a matched rule emits.
#[derive(Clone, Copy, Debug)]
pub enum Action {
    /// Python `None`: emit nothing.
    None,
    Token(TokenType),
    /// `bygroups(...)`: one entry per capture group (group 1 first).
    ByGroups(&'static [ByGroupAction]),
    Using(Using),
}

#[derive(Clone, Copy, Debug)]
pub enum ByGroupAction {
    /// Python `None` in `bygroups(...)`: skip this group.
    Skip,
    Token(TokenType),
    Using(Using),
    /// A nested `bygroups(...)`.
    ByGroups(&'static [ByGroupAction]),
}

/// `using(...)` from `pygments.lexer`.
#[derive(Clone, Copy, Debug)]
pub struct Using {
    pub target: UsingTarget,
    pub state: Option<UsingState>,
}

#[derive(Clone, Copy, Debug)]
pub enum UsingTarget {
    /// `this`: the same lexer definition.
    This,
    /// `using(SomeOtherLexer)`: another static definition.
    Other(&'static LexerDef),
}

#[derive(Clone, Copy, Debug)]
pub enum UsingState {
    /// `state='name'`: start in `('root', 'name')`.
    Single(&'static str),
    /// `state=('a', 'b', ...)`: the given initial stack.
    Stack(&'static [&'static str]),
}

pub const fn using_this() -> Action {
    Action::Using(Using { target: UsingTarget::This, state: None })
}

pub const fn using_this_state(state: &'static str) -> Action {
    Action::Using(Using { target: UsingTarget::This, state: Some(UsingState::Single(state)) })
}

pub const fn using_this_stack(stack: &'static [&'static str]) -> Action {
    Action::Using(Using { target: UsingTarget::This, state: Some(UsingState::Stack(stack)) })
}

pub const fn using_other(other: &'static LexerDef) -> Action {
    Action::Using(Using { target: UsingTarget::Other(other), state: None })
}

pub const fn using_other_state(other: &'static LexerDef, state: &'static str) -> Action {
    Action::Using(Using { target: UsingTarget::Other(other), state: Some(UsingState::Single(state)) })
}

pub const fn this_using() -> Using {
    Using { target: UsingTarget::This, state: None }
}

pub const fn this_using_state(state: &'static str) -> Using {
    Using { target: UsingTarget::This, state: Some(UsingState::Single(state)) }
}

pub const fn this_using_stack(stack: &'static [&'static str]) -> Using {
    Using { target: UsingTarget::This, state: Some(UsingState::Stack(stack)) }
}

pub const fn other_using(other: &'static LexerDef) -> Using {
    Using { target: UsingTarget::Other(other), state: None }
}

pub const fn other_using_state(other: &'static LexerDef, state: &'static str) -> Using {
    Using { target: UsingTarget::Other(other), state: Some(UsingState::Single(state)) }
}

pub const fn bygroups(actions: &'static [ByGroupAction]) -> Action {
    Action::ByGroups(actions)
}

/// A state transition, mirroring the third element of a Python rule tuple.
#[derive(Clone, Copy, Debug)]
pub enum Transition {
    /// No transition.
    Stay,
    /// Push the named state (a plain string state name in Python).
    State(&'static str),
    /// `#push`
    Push,
    /// `#pop` (standalone; pops one, keeping at least the root state)
    Pop,
    /// `#pop:n`
    PopN(u32),
    /// A tuple of transitions, applied left to right.
    Tuple(&'static [TupleItem]),
    /// `combined('a', 'b', ...)`: push an anonymous combined state.
    Combined(&'static [&'static str]),
}

#[derive(Clone, Copy, Debug)]
pub enum TupleItem {
    State(&'static str),
    /// `#push` inside a tuple.
    Push,
    /// `#pop` inside a tuple (pops one only if more than one state is stacked).
    Pop,
}

#[derive(Clone, Copy, Debug)]
pub enum Rule {
    /// `(pattern, action, transition)`
    Matched { pattern: Pattern, action: Action, transition: Transition },
    /// `include('state')`
    Include(&'static str),
    /// `inherit`
    Inherit,
    /// `default(state)`: an empty match that only applies a transition.
    Default(Transition),
}

impl Rule {
    pub const fn new(pattern: Pattern, action: Action, transition: Transition) -> Rule {
        Rule::Matched { pattern, action, transition }
    }
    /// `(pattern, token)` with no transition.
    pub const fn token(pattern: &'static str, token: TokenType) -> Rule {
        Rule::Matched { pattern: Pattern::Re(pattern), action: Action::Token(token), transition: Transition::Stay }
    }
    /// `(pattern, token, 'state')`
    pub const fn token_to(pattern: &'static str, token: TokenType, state: &'static str) -> Rule {
        Rule::Matched { pattern: Pattern::Re(pattern), action: Action::Token(token), transition: Transition::State(state) }
    }
}

pub type StateDef = (&'static str, &'static [Rule]);

#[derive(Clone, Copy, Debug)]
pub struct LexerDef {
    pub name: &'static str,
    pub aliases: &'static [&'static str],
    pub flags: Flags,
    /// The superclass definition for `inherit` and for states this lexer does
    /// not define, mirroring Python class inheritance. `None` for a lexer
    /// directly subclassing `RegexLexer`.
    pub parent: Option<&'static LexerDef>,
    pub states: &'static [StateDef],
}
