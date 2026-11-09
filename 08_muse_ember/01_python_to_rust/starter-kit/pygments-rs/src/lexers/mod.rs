//! Registry of ported lexers. It is intentionally empty in this step.
//!
//! Each ported lexer lives in its own file in this directory, defines
//! `pub static LEXER: LexerDef`, and adds exactly one line to the
//! `lexers!` invocation below, e.g. `python,`.

use crate::lexer::LexerDef;

macro_rules! lexers {
    ($($name:ident),* $(,)?) => {
        $(pub mod $name;)*
        pub static LEXERS: &[&LexerDef] = &[$($name::LEXER),*];
    };
}

lexers! {}

/// Look up a lexer definition by alias (exact match, as in the CLI).
pub fn find(alias: &str) -> Option<&'static LexerDef> {
    LEXERS.iter().copied().find(|def| def.aliases.contains(&alias))
}

/// All registered aliases, in registry order.
pub fn aliases() -> Vec<&'static str> {
    LEXERS.iter().flat_map(|def| def.aliases.iter().copied()).collect()
}
