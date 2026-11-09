//! Compiling Python `re` patterns (as used in Pygments lexer definitions) to
//! `fancy-regex`, which provides lookaround and backreferences on top of the
//! `regex` crate. Matching is anchored at the current position, giving
//! Python `Pattern.match(text, pos)` semantics while the full text stays
//! visible to lookbehind, `\b`, `^` and `$`: plain patterns run on
//! regex-automata with an anchored input, and patterns using lookaround or
//! backreferences run on a fancy-regex VM program compiled without its
//! leftmost-search prefix.

use crate::lexer::{Flags, Pattern};
use crate::unistring;

/// Port of `pygments.regexopt.regex_opt`, used for `words(...)`. The result
/// intentionally keeps the capturing group the Python version opens, so
/// capture-group numbering is identical.
pub fn regex_opt(words: &[&str], prefix: &str, suffix: &str) -> String {
    let mut uniq: Vec<Vec<char>> = words.iter().map(|w| w.chars().collect()).collect();
    uniq.sort();
    uniq.dedup();
    format!("{}{}{}", prefix, regex_opt_inner(&uniq, "("), suffix)
}

fn escape_char(c: char, out: &mut String) {
    match c {
        '\\' | '.' | '+' | '*' | '?' | '(' | ')' | '|' | '[' | ']' | '{' | '}' | '^' | '$'
        | '#' | '&' | '-' | '~' => {
            out.push('\\');
            out.push(c);
        }
        ' ' => out.push_str("\\x20"),
        '\t' => out.push_str("\\t"),
        '\n' => out.push_str("\\n"),
        '\r' => out.push_str("\\r"),
        '\x0b' => out.push_str("\\x0B"),
        '\x0c' => out.push_str("\\f"),
        c if (c as u32) < 0x20 || (c as u32) == 0x7f => out.push_str(&format!("\\x{:02X}", c as u32)),
        c => out.push(c),
    }
}

fn escape_str(s: &[char]) -> String {
    let mut out = String::new();
    for &c in s {
        escape_char(c, &mut out);
    }
    out
}

fn make_charset(letters: &[Vec<char>]) -> String {
    let mut out = String::from("[");
    for l in letters {
        assert_eq!(l.len(), 1);
        let c = l[0];
        match c {
            '[' | ']' | '^' | '\\' | '-' => {
                out.push('\\');
                out.push(c);
            }
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\x{:02X}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(']');
    out
}

fn common_prefix(strings: &[Vec<char>]) -> Vec<char> {
    if strings.is_empty() {
        return Vec::new();
    }
    let s1 = strings.iter().min().unwrap();
    let s2 = strings.iter().max().unwrap();
    let mut out = Vec::new();
    for (a, b) in s1.iter().zip(s2.iter()) {
        if a != b {
            break;
        }
        out.push(*a);
    }
    out
}

fn regex_opt_inner(strings: &[Vec<char>], open_paren: &str) -> String {
    let close = if open_paren.is_empty() { "" } else { ")" };
    if strings.is_empty() {
        return String::new();
    }
    let first = &strings[0];
    if strings.len() == 1 {
        return format!("{}{}{}", open_paren, escape_str(first), close);
    }
    if first.is_empty() {
        return format!("{}{}?{}", open_paren, regex_opt_inner(&strings[1..], "(?:"), close);
    }
    if first.len() == 1 {
        let mut oneletter: Vec<Vec<char>> = Vec::new();
        let mut rest: Vec<Vec<char>> = Vec::new();
        for s in strings {
            if s.len() == 1 {
                oneletter.push(s.clone());
            } else {
                rest.push(s.clone());
            }
        }
        if oneletter.len() > 1 {
            if !rest.is_empty() {
                return format!(
                    "{}{}|{}{}",
                    open_paren,
                    regex_opt_inner(&rest, ""),
                    make_charset(&oneletter),
                    close
                );
            }
            return format!("{}{}{}", open_paren, make_charset(&oneletter), close);
        }
    }
    let prefix = common_prefix(strings);
    if !prefix.is_empty() {
        let plen = prefix.len();
        let rest: Vec<Vec<char>> = strings.iter().map(|s| s[plen..].to_vec()).collect();
        return format!(
            "{}{}{}{}",
            open_paren,
            escape_str(&prefix),
            regex_opt_inner(&rest, "(?:"),
            close
        );
    }
    let rev: Vec<Vec<char>> = strings.iter().map(|s| s.iter().rev().copied().collect()).collect();
    let suffix = common_prefix(&rev);
    if !suffix.is_empty() {
        let slen = suffix.len();
        let mut rest: Vec<Vec<char>> =
            strings.iter().map(|s| s[..s.len() - slen].to_vec()).collect();
        rest.sort();
        let suffix_str: Vec<char> = suffix.iter().rev().copied().collect();
        return format!(
            "{}{}{}{}",
            open_paren,
            regex_opt_inner(&rest, "(?:"),
            escape_str(&suffix_str),
            close
        );
    }
    // Group consecutive strings by whether they start with first's first char.
    let mut parts: Vec<String> = Vec::new();
    let mut i = 0;
    while i < strings.len() {
        let key = strings[i][0] == first[0];
        let mut j = i;
        while j < strings.len() && (strings[j][0] == first[0]) == key {
            j += 1;
        }
        parts.push(regex_opt_inner(&strings[i..j], ""));
        i = j;
    }
    format!("{}{}{}", open_paren, parts.join("|"), close)
}

fn expand_unistring(pattern: &str) -> String {
    if !pattern.contains("${") {
        return pattern.to_string();
    }
    let mut out = String::with_capacity(pattern.len());
    let mut rest = pattern;
    while let Some(idx) = rest.find("${") {
        out.push_str(&rest[..idx]);
        let after = &rest[idx + 2..];
        let end = after.find('}').unwrap_or_else(|| panic!("unterminated unistring placeholder in pattern {pattern:?}"));
        let name = &after[..end];
        if let Some(list) = name.strip_prefix("combine:") {
            let names: Vec<&str> = list.split(',').collect();
            out.push_str(&unistring::combine(&names));
        } else if let Some(list) = name.strip_prefix("allexcept:") {
            let names: Vec<&str> = list.split(',').collect();
            out.push_str(&unistring::allexcept(&names));
        } else {
            out.push_str(
                unistring::lookup(name)
                    .unwrap_or_else(|| panic!("unknown unistring category {name:?} in pattern {pattern:?}")),
            );
        }
        rest = &after[end + 1..];
    }
    out.push_str(rest);
    out
}

fn translate_flags(spec: &str, pattern: &str) -> (String, Option<bool>) {
    let (pos, neg) = match spec.split_once('-') {
        Some((p, n)) => (p, n),
        None => (spec, ""),
    };
    let mut out_pos = String::new();
    let mut out_neg = String::new();
    let mut ascii: Option<bool> = None;
    for c in pos.chars() {
        match c {
            'i' | 'm' | 's' | 'x' => out_pos.push(c),
            'u' => ascii = Some(false),
            'a' => ascii = Some(true),
            'L' => panic!("locale regex flag is not supported (pattern {pattern:?})"),
            _ => panic!("unsupported regex flag {c:?} in pattern {pattern:?}"),
        }
    }
    for c in neg.chars() {
        match c {
            'i' | 'm' | 's' | 'x' => out_neg.push(c),
            'u' => ascii = Some(true),
            'a' => ascii = Some(false),
            'L' => panic!("locale regex flag is not supported (pattern {pattern:?})"),
            _ => panic!("unsupported regex flag {c:?} in pattern {pattern:?}"),
        }
    }
    let flags = if out_neg.is_empty() {
        out_pos
    } else if out_pos.is_empty() {
        format!("-{out_neg}")
    } else {
        format!("{out_pos}-{out_neg}")
    };
    (flags, ascii)
}

const ASCII_WORD: &str = "A-Za-z0-9_";

/// Translate a Python `re` pattern to an equivalent fancy-regex pattern,
/// without the anchoring wrapper or lexer-level flags.
pub fn translate(pattern: &str) -> String {
    translate_with_ascii(pattern, false)
}

fn translate_with_ascii(pattern: &str, initial_ascii: bool) -> String {
    let pattern = expand_unistring(pattern);
    let chars: Vec<char> = pattern.chars().collect();
    let mut out = String::with_capacity(pattern.len() + 8);
    let mut i = 0;
    let mut in_class = false;
    let mut class_fresh = false; // next ']' would be a literal
    let mut ascii = initial_ascii;
    let mut group_stack: Vec<bool> = Vec::new();
    while i < chars.len() {
        let c = chars[i];
        if c == '\\' && i + 1 < chars.len() {
            let n = chars[i + 1];
            if ascii {
                match (n, in_class) {
                    ('w', false) => { out.push_str(&format!("[{ASCII_WORD}]")); i += 2; class_fresh = false; continue; }
                    ('W', false) => { out.push_str(&format!("[^{ASCII_WORD}]")); i += 2; class_fresh = false; continue; }
                    ('d', false) => { out.push_str("[0-9]"); i += 2; class_fresh = false; continue; }
                    ('D', false) => { out.push_str("[^0-9]"); i += 2; class_fresh = false; continue; }
                    ('s', false) => { out.push_str("[ \\t\\n\\r\\x0B\\x0C]"); i += 2; class_fresh = false; continue; }
                    ('S', false) => { out.push_str("[^ \\t\\n\\r\\x0B\\x0C]"); i += 2; class_fresh = false; continue; }
                    ('b', false) => { out.push_str(&format!("(?:(?<![{ASCII_WORD}])(?=[{ASCII_WORD}])|(?<=[{ASCII_WORD}])(?![{ASCII_WORD}]))")); i += 2; class_fresh = false; continue; }
                    ('B', false) => { out.push_str(&format!("(?:(?<=[{ASCII_WORD}])(?=[{ASCII_WORD}])|(?<![{ASCII_WORD}])(?![{ASCII_WORD}]))")); i += 2; class_fresh = false; continue; }
                    ('w', true) => { out.push_str(ASCII_WORD); i += 2; class_fresh = false; continue; }
                    ('d', true) => { out.push_str("0-9"); i += 2; class_fresh = false; continue; }
                    ('s', true) => { out.push_str(" \\t\\n\\r\\x0B\\x0C"); i += 2; class_fresh = false; continue; }
                    ('W' | 'D' | 'S', true) => panic!("negated shorthand class in a character class is not supported with the ASCII flag (pattern {pattern:?})"),
                    ('b', true) => { out.push_str("\\x08"); i += 2; class_fresh = false; continue; }
                    _ => {}
                }
            }
            match n {
                'Z' => out.push_str("\\z"),
                '0' => out.push_str("\\x00"),
                'N' => panic!("\\N escapes are not supported (pattern {pattern:?})"),
                ' ' => out.push_str("\\x20"),
                c if c.is_ascii_alphanumeric() => {
                    out.push('\\');
                    out.push(c);
                }
                c if c.is_ascii() => {
                    out.push('\\');
                    out.push(c);
                }
                c => out.push(c),
            }
            i += 2;
            class_fresh = false;
            continue;
        }
        if in_class {
            // Python has no nested classes or `&&` intersection: literalize.
            if c == '[' || c == '&' {
                out.push('\\');
            }
            out.push(c);
            if c == ']' && !class_fresh {
                in_class = false;
            }
            class_fresh = false;
            i += 1;
            continue;
        }
        match c {
            '[' => {
                in_class = true;
                class_fresh = true;
                out.push(c);
                i += 1;
                if i < chars.len() && chars[i] == '^' {
                    out.push('^');
                    i += 1;
                }
                continue;
            }
            '(' if i + 2 < chars.len() && chars[i + 1] == '?' && chars[i + 2] == '#' => {
                while i < chars.len() && chars[i] != ')' {
                    i += 1;
                }
                i += 1;
                continue;
            }
            '(' if i + 1 < chars.len() && chars[i + 1] == '?' => {
                let mut j = i + 2;
                let mut spec = String::new();
                let mut valid = true;
                while j < chars.len() && chars[j] != ')' && chars[j] != ':' {
                    if !"imsxuUaAL-".contains(chars[j]) {
                        valid = false;
                        break;
                    }
                    spec.push(chars[j]);
                    j += 1;
                }
                if valid && !spec.is_empty() && j < chars.len() {
                    let (flags, ascii_change) = translate_flags(&spec, &pattern);
                    if chars[j] == ':' {
                        group_stack.push(ascii);
                        if flags.is_empty() {
                            out.push_str("(?:");
                        } else {
                            out.push_str("(?");
                            out.push_str(&flags);
                            out.push(':');
                        }
                    } else if flags.is_empty() {
                        // (?a) / (?u) only: nothing to emit.
                    } else {
                        out.push_str("(?");
                        out.push_str(&flags);
                        out.push(')');
                    }
                    if let Some(a) = ascii_change {
                        ascii = a;
                    }
                    i = j + 1;
                    continue;
                }
                group_stack.push(ascii);
                out.push(c);
                i += 1;
                continue;
            }
            '(' => {
                group_stack.push(ascii);
                out.push(c);
                i += 1;
                continue;
            }
            ')' => {
                if let Some(prev) = group_stack.pop() {
                    ascii = prev;
                }
                out.push(c);
                i += 1;
                continue;
            }
            '{' if i + 1 < chars.len() && chars[i + 1] == ',' => {
                out.push_str("{0,");
                i += 2;
                continue;
            }
            _ => {
                out.push(c);
                i += 1;
            }
        }
    }
    out
}

fn flag_prefix(flags: Flags) -> String {
    let mut pos = String::new();
    if flags.contains(Flags::IGNORECASE) {
        pos.push('i');
    }
    if flags.contains(Flags::MULTILINE) {
        pos.push('m');
    }
    if flags.contains(Flags::DOTALL) {
        pos.push('s');
    }
    if flags.contains(Flags::VERBOSE) {
        pos.push('x');
    }
    if flags.contains(Flags::UNICODE) {
        pos.push('u');
    }
    if pos.is_empty() {
        String::new()
    } else {
        format!("(?{pos})")
    }
}

/// The regex source for one lexer rule, before anchoring.
pub fn compile_source(pattern: &Pattern, flags: Flags) -> String {
    let ascii = flags.contains(Flags::ASCII) && !flags.contains(Flags::UNICODE);
    let translated = match pattern {
        Pattern::Re(p) => translate_with_ascii(p, ascii),
        Pattern::Words { words, prefix, suffix } => {
            translate_with_ascii(&regex_opt(words, prefix, suffix), ascii)
        }
    };
    format!("{}{}", flag_prefix(flags), translated)
}

/// Does the translated pattern need fancy-regex features (lookaround,
/// backreferences, conditionals, atomic groups)?
fn is_fancy(source: &str) -> bool {
    let chars: Vec<char> = source.chars().collect();
    let mut in_class = false;
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '\\' && i + 1 < chars.len() {
            let n = chars[i + 1];
            if !in_class && (('1'..='9').contains(&n) || n == 'K' || n == 'G') {
                return true;
            }
            if !in_class && (n == 'k' || n == 'g') && i + 2 < chars.len() && (chars[i + 2] == '<' || chars[i + 2] == '\'') {
                return true;
            }
            i += 2;
            continue;
        }
        if in_class {
            if c == ']' {
                in_class = false;
            }
            i += 1;
            continue;
        }
        match c {
            '[' => in_class = true,
            '(' => {
                let rest: String = chars[i..].iter().collect();
                if rest.starts_with("(?=")
                    || rest.starts_with("(?!")
                    || rest.starts_with("(?<=")
                    || rest.starts_with("(?<!")
                    || rest.starts_with("(?>")
                    || rest.starts_with("(?(")
                    || rest.starts_with("(?P=")
                {
                    return true;
                }
            }
            _ => {}
        }
        i += 1;
    }
    false
}

fn count_groups(source: &str) -> usize {
    let chars: Vec<char> = source.chars().collect();
    let mut in_class = false;
    let mut count = 0;
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '\\' {
            i += 2;
            continue;
        }
        if in_class {
            if c == ']' {
                in_class = false;
            }
            i += 1;
            continue;
        }
        match c {
            '[' => in_class = true,
            '(' => {
                let rest: String = chars[i..].iter().collect();
                if rest.starts_with("(?P<") || rest.starts_with("(?'") {
                    count += 1;
                } else if rest.starts_with("(?<") && !rest.starts_with("(?<=") && !rest.starts_with("(?<!") {
                    count += 1;
                } else if !rest.starts_with("(?") {
                    count += 1;
                }
            }
            _ => {}
        }
        i += 1;
    }
    count
}

/// The capture spans of one successful anchored match.
pub struct MatchData {
    groups: Vec<Option<(usize, usize)>>,
}

impl MatchData {
    pub fn len(&self) -> usize {
        self.groups.len()
    }
    pub fn is_empty(&self) -> bool {
        self.groups.is_empty()
    }
    /// Span of group `i` (0 is the whole match), or `None` if it did not
    /// participate. Panics if there is no such group, like Python.
    pub fn group_span(&self, i: usize) -> Option<(usize, usize)> {
        if i >= self.groups.len() {
            panic!("no such group {i}");
        }
        self.groups[i]
    }
    pub fn group<'a>(&self, text: &'a str, i: usize) -> Option<&'a str> {
        self.group_span(i).map(|(s, e)| &text[s..e])
    }
}

enum Matcher {
    Easy(regex_automata::meta::Regex),
    Fancy(fancy_regex::internal::Prog),
}

/// A compiled rule pattern, anchored at the match position.
pub struct CompiledPattern {
    source: String,
    matcher: Matcher,
    n_groups: usize,
}

impl CompiledPattern {
    pub fn source(&self) -> &str {
        &self.source
    }

    /// Match at exactly `pos` in `text` (Python `Pattern.match(text, pos)`).
    pub fn try_match(&self, text: &str, pos: usize) -> Option<MatchData> {
        match &self.matcher {
            Matcher::Easy(re) => {
                use regex_automata::{Anchored, Input};
                let input = Input::new(text).span(pos..text.len()).anchored(Anchored::Yes);
                let mut caps = re.create_captures();
                re.captures(input, &mut caps);
                if !caps.is_match() {
                    return None;
                }
                let groups = (0..=self.n_groups)
                    .map(|i| caps.get_group(i).map(|s| (s.start, s.end)))
                    .collect();
                Some(MatchData { groups })
            }
            Matcher::Fancy(prog) => match fancy_regex::internal::run_default(prog, text, pos) {
                Ok(Some(saves)) => {
                    let groups = (0..self.n_groups)
                        .map(|i| {
                            let (a, b) = (saves[2 * i], saves[2 * i + 1]);
                            if a == usize::MAX || b == usize::MAX {
                                None
                            } else {
                                Some((a, b))
                            }
                        })
                        .collect();
                    Some(MatchData { groups })
                }
                Ok(None) => None,
                Err(e) => panic!("regex error at {pos} in pattern {:?}: {e}", self.source),
            },
        }
    }
}

pub fn compile(pattern: &Pattern, flags: Flags) -> CompiledPattern {
    let source = compile_source(pattern, flags);
    if is_fancy(&source) {
        let tree = fancy_regex::Expr::parse_tree(&source)
            .unwrap_or_else(|e| panic!("uncompilable regex {source:?}: {e}"));
        let info = fancy_regex::internal::analyze(&tree, false)
            .unwrap_or_else(|e| panic!("uncompilable regex {source:?}: {e}"));
        let n_groups = count_groups(&source) + 1;
        let prog = fancy_regex::internal::compile(&info, true)
            .unwrap_or_else(|e| panic!("uncompilable regex {source:?}: {e}"));
        CompiledPattern { source, matcher: Matcher::Fancy(prog), n_groups }
    } else {
        let n_groups = count_groups(&source) + 1;
        let re = regex_automata::meta::Regex::new(&source)
            .unwrap_or_else(|e| panic!("uncompilable regex {source:?}: {e}"));
        CompiledPattern { source, matcher: Matcher::Easy(re), n_groups }
    }
}
