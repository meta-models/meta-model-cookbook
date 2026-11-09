//! The `RegexLexer` engine: compiles a static `LexerDef` and lexes text with
//! the semantics of `pygments.lexer.RegexLexer.get_tokens` (with default
//! options) and `get_tokens_unprocessed`.

use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

use crate::lexer::{
    Action, ByGroupAction, LexerDef, Rule, Transition, TupleItem, Using, UsingState, UsingTarget,
};
use crate::token::{TokenType, ERROR, WHITESPACE};

#[derive(Clone, Debug)]
enum CTransition {
    Stay,
    Push(usize),
    PushSelf,
    Pop(usize),
    Tuple(Vec<CTupleItem>),
}

#[derive(Clone, Debug)]
enum CTupleItem {
    Push(usize),
    PushSelf,
    Pop,
}

struct CompiledRule {
    regex: Option<crate::regex_compile::CompiledPattern>,
    action: Action,
    transition: CTransition,
}

struct CompiledState {
    rules: Vec<CompiledRule>,
}

pub struct CompiledLexer {
    def: &'static LexerDef,
    states: Vec<CompiledState>,
    index: HashMap<String, usize>,
    using_cache: RefCell<HashMap<usize, Rc<CompiledLexer>>>,
}

fn processed_states(def: &LexerDef) -> Vec<(String, Vec<Rule>)> {
    let parent: Option<Vec<(String, Vec<Rule>)>> = def.parent.map(processed_states);
    // The parent's already-processed (include/inherit-expanded) rules.
    let parent_processed: HashMap<String, Vec<Rule>> = match &parent {
        Some(p) => p.iter().map(|(n, r)| (n.clone(), r.clone())).collect(),
        None => HashMap::new(),
    };

    let mut expanded: HashMap<String, Vec<Rule>> = HashMap::new();
    let mut visiting: HashSet<String> = HashSet::new();

    fn expand(
        def: &LexerDef,
        parent_processed: &HashMap<String, Vec<Rule>>,
        name: &str,
        expanded: &mut HashMap<String, Vec<Rule>>,
        visiting: &mut HashSet<String>,
    ) -> Vec<Rule> {
        if let Some(r) = expanded.get(name) {
            return r.clone();
        }
        assert!(visiting.insert(name.to_string()), "circular state reference {name:?}");
        let raw = def
            .states
            .iter()
            .find(|(n, _)| *n == name)
            .unwrap_or_else(|| panic!("unknown state {name:?} in lexer {:?}", def.name));
        let mut out: Vec<Rule> = Vec::new();
        for rule in raw.1.iter() {
            match rule {
                Rule::Include(target) => {
                    assert!(*target != name, "circular state reference {name:?}");
                    if def.states.iter().any(|(n, _)| n == target) {
                        out.extend(expand(def, parent_processed, target, expanded, visiting));
                    } else if let Some(r) = parent_processed.get(*target) {
                        out.extend(r.iter().copied());
                    } else {
                        panic!("unknown state {target:?} in lexer {:?}", def.name);
                    }
                }
                Rule::Inherit => {
                    if let Some(r) = parent_processed.get(name) {
                        out.extend(r.iter().copied());
                    }
                }
                other => out.push(*other),
            }
        }
        visiting.remove(name);
        expanded.insert(name.to_string(), out.clone());
        out
    }

    let mut result: Vec<(String, Vec<Rule>)> = Vec::new();
    if let Some(p) = &parent {
        for (name, _) in p {
            if !def.states.iter().any(|(n, _)| n == name) {
                result.push((name.clone(), parent_processed[name].clone()));
            }
        }
    }
    for (name, _) in def.states {
        let rules = expand(def, &parent_processed, name, &mut expanded, &mut visiting);
        result.push((name.to_string(), rules));
    }
    result
}

impl CompiledLexer {
    pub fn new(def: &'static LexerDef) -> CompiledLexer {
        let skeleton = processed_states(def);
        let mut index: HashMap<String, usize> = HashMap::new();
        let mut names: Vec<String> = Vec::new();
        for (name, _) in &skeleton {
            index.insert(name.clone(), names.len());
            names.push(name.clone());
        }
        let mut skeletons: Vec<Vec<Rule>> = skeleton.into_iter().map(|(_, r)| r).collect();

        let mut compiled: Vec<CompiledState> = Vec::new();
        let mut i = 0;
        while i < skeletons.len() {
            let rules = skeletons[i].clone();
            let mut out: Vec<CompiledRule> = Vec::with_capacity(rules.len());
            for rule in &rules {
                match rule {
                    Rule::Default(t) => out.push(CompiledRule {
                        regex: None,
                        action: Action::None,
                        transition: resolve_transition(
                            t, &mut names, &mut index, &mut skeletons, def,
                        ),
                    }),
                    Rule::Matched { pattern, action, transition } => {
                        out.push(CompiledRule {
                            regex: Some(crate::regex_compile::compile(pattern, def.flags)),
                            action: *action,
                            transition: resolve_transition(
                                transition, &mut names, &mut index, &mut skeletons, def,
                            ),
                        })
                    }
                    Rule::Include(_) | Rule::Inherit => {
                        unreachable!("include/inherit are expanded before compilation")
                    }
                }
            }
            compiled.push(CompiledState { rules: out });
            i += 1;
        }
        assert!(index.contains_key("root"), "lexer {:?} has no 'root' state", def.name);
        CompiledLexer { def, states: compiled, index, using_cache: RefCell::new(HashMap::new()) }
    }

    pub fn def(&self) -> &'static LexerDef {
        self.def
    }

    fn state_index(&self, name: &str) -> usize {
        *self
            .index
            .get(name)
            .unwrap_or_else(|| panic!("unknown state {name:?} in lexer {:?}", self.def.name))
    }

    fn using_stack(&self, using: &Using) -> Vec<usize> {
        match &using.state {
            None => vec![self.state_index("root")],
            Some(UsingState::Single(s)) => vec![self.state_index("root"), self.state_index(s)],
            Some(UsingState::Stack(names)) => {
                assert!(!names.is_empty(), "using() with an empty state stack");
                names.iter().map(|n| self.state_index(n)).collect()
            }
        }
    }

    fn other_lexer(&self, def: &'static LexerDef) -> Rc<CompiledLexer> {
        let key = def as *const LexerDef as usize;
        if let Some(l) = self.using_cache.borrow().get(&key) {
            return l.clone();
        }
        let compiled = Rc::new(CompiledLexer::new(def));
        self.using_cache.borrow_mut().insert(key, compiled.clone());
        compiled
    }

    /// Lex `text` with default-option preprocessing, as `Lexer.get_tokens`.
    pub fn get_tokens(&self, text: &str) -> Vec<(TokenType, String)> {
        let mut out = Vec::new();
        self.get_tokens_with(text, |t, v| out.push((t, v.to_string())));
        out
    }

    /// Streaming form of `get_tokens`: tokens are slices of the preprocessed
    /// text, so no per-token allocation happens.
    pub fn get_tokens_with<F: FnMut(TokenType, &str)>(&self, text: &str, mut f: F) {
        let text = preprocess(text);
        let root = self.state_index("root");
        self.run(&text, vec![root], &mut f);
    }

    /// As Python `get_tokens_unprocessed`, without preprocessing. Panics on
    /// an unknown state name, like Python's `KeyError`.
    pub fn get_tokens_unprocessed_with<F: FnMut(TokenType, &str)>(
        &self,
        text: &str,
        stack: &[&str],
        mut f: F,
    ) {
        assert!(!stack.is_empty(), "empty initial state stack");
        let stack: Vec<usize> = stack.iter().map(|n| self.state_index(n)).collect();
        self.run(text, stack, &mut f);
    }

    fn emit_using<F: FnMut(TokenType, &str)>(&self, using: &Using, text: &str, f: &mut F) {
        match using.target {
            UsingTarget::This => {
                let stack = self.using_stack(using);
                self.run(text, stack, f);
            }
            UsingTarget::Other(def) => {
                let other = self.other_lexer(def);
                let stack = other.using_stack(using);
                other.run(text, stack, f);
            }
        }
    }

    fn run<F: FnMut(TokenType, &str)>(&self, text: &str, mut stack: Vec<usize>, f: &mut F) {
        let root = self.state_index("root");
        let mut pos = 0usize;
        'outer: loop {
            let state = *stack.last().expect("empty state stack");
            for rule in &self.states[state].rules {
                let caps: Option<crate::regex_compile::MatchData> = match &rule.regex {
                    None => {
                        // default(): an empty match at the current position.
                        self.apply_transition(&rule.transition, &mut stack);
                        continue 'outer;
                    }
                    Some(re) => re.try_match(text, pos),
                };
                let caps = match caps {
                    Some(c) => c,
                    None => continue,
                };
                let (whole_start, end) = caps.group_span(0).expect("group 0");
                let whole = &text[whole_start..end];
                match &rule.action {
                    Action::None => {}
                    Action::Token(t) => f(*t, whole),
                    Action::ByGroups(actions) => {
                        emit_bygroups(self, actions, &MatchView::Real { data: &caps, text }, f)
                    }
                    Action::Using(u) => {
                        let u = *u;
                        self.emit_using(&u, whole, f);
                    }
                }
                pos = end;
                self.apply_transition(&rule.transition, &mut stack);
                continue 'outer;
            }
            // No rule matched.
            if pos >= text.len() {
                break;
            }
            let ch_len = text[pos..].chars().next().expect("char boundary").len_utf8();
            if text[pos..].starts_with('\n') {
                stack = vec![root];
                f(WHITESPACE, "\n");
                pos += 1;
            } else {
                f(ERROR, &text[pos..pos + ch_len]);
                pos += ch_len;
            }
        }
    }

    fn apply_transition(&self, t: &CTransition, stack: &mut Vec<usize>) {
        match t {
            CTransition::Stay => {}
            CTransition::Push(idx) => stack.push(*idx),
            CTransition::PushSelf => {
                let cur = *stack.last().expect("empty state stack");
                stack.push(cur);
            }
            CTransition::Pop(n) => {
                if *n >= stack.len() {
                    stack.truncate(1);
                } else {
                    let new_len = stack.len() - n;
                    stack.truncate(new_len);
                }
            }
            CTransition::Tuple(items) => {
                for item in items {
                    match item {
                        CTupleItem::Push(idx) => stack.push(*idx),
                        CTupleItem::PushSelf => {
                            let cur = *stack.last().expect("empty state stack");
                            stack.push(cur);
                        }
                        CTupleItem::Pop => {
                            if stack.len() > 1 {
                                stack.pop();
                            }
                        }
                    }
                }
            }
        }
    }
}

fn resolve_transition(
    t: &Transition,
    names: &mut Vec<String>,
    index: &mut HashMap<String, usize>,
    skeletons: &mut Vec<Vec<Rule>>,
    def: &LexerDef,
) -> CTransition {
    fn state_idx(
        name: &str,
        _names: &[String],
        index: &HashMap<String, usize>,
        def: &LexerDef,
    ) -> usize {
        *index
            .get(name)
            .unwrap_or_else(|| panic!("unknown new state {name:?} in lexer {:?}", def.name))
    }
    match t {
        Transition::Stay => CTransition::Stay,
        Transition::State(name) => CTransition::Push(state_idx(name, names, index, def)),
        Transition::Push => CTransition::PushSelf,
        Transition::Pop => CTransition::Pop(1),
        Transition::PopN(n) => CTransition::Pop(*n as usize),
        Transition::Tuple(items) => CTransition::Tuple(
            items
                .iter()
                .map(|item| match item {
                    TupleItem::State(name) => CTupleItem::Push(state_idx(name, names, index, def)),
                    TupleItem::Push => CTupleItem::PushSelf,
                    TupleItem::Pop => CTupleItem::Pop,
                })
                .collect(),
        ),
        Transition::Combined(parts) => {
            let tmp = format!("_tmp_{}", names.len());
            let mut rules: Vec<Rule> = Vec::new();
            for part in *parts {
                let idx = state_idx(part, names, index, def);
                rules.extend(skeletons[idx].iter().copied());
            }
            index.insert(tmp.clone(), names.len());
            names.push(tmp);
            skeletons.push(rules);
            CTransition::Push(index[names.last().unwrap().as_str()])
        }
    }
}

enum MatchView<'a> {
    Real { data: &'a crate::regex_compile::MatchData, text: &'a str },
    Pseudo(&'a str),
}

impl<'a> MatchView<'a> {
    fn group(&self, i: usize) -> Option<&'a str> {
        match self {
            MatchView::Real { data, text } => data.group(text, i),
            MatchView::Pseudo(text) => {
                if i == 0 {
                    Some(text)
                } else {
                    panic!("no such group {i}");
                }
            }
        }
    }
}

fn emit_bygroups<F: FnMut(TokenType, &str)>(
    lexer: &CompiledLexer,
    actions: &[ByGroupAction],
    view: &MatchView<'_>,
    f: &mut F,
) {
    for (i, action) in actions.iter().enumerate() {
        match action {
            ByGroupAction::Skip => {}
            ByGroupAction::Token(t) => {
                if let Some(data) = view.group(i + 1) {
                    if !data.is_empty() {
                        f(*t, data);
                    }
                }
            }
            ByGroupAction::Using(u) => {
                if let Some(data) = view.group(i + 1) {
                    lexer.emit_using(u, data, f);
                }
            }
            ByGroupAction::ByGroups(inner) => {
                if let Some(data) = view.group(i + 1) {
                    emit_bygroups(lexer, inner, &MatchView::Pseudo(data), f);
                }
            }
        }
    }
}

/// Input preprocessing of `Lexer.get_tokens` with default options
/// (`stripnl=True`, `stripall=False`, `ensurenl=True`, `tabsize=0`) for
/// text that is already a Unicode string.
pub fn preprocess(text: &str) -> String {
    let text = text.strip_prefix('\u{feff}').unwrap_or(text);
    let mut text = text.replace("\r\n", "\n").replace('\r', "\n");
    text = text.trim_matches('\n').to_string();
    if !text.ends_with('\n') {
        text.push('\n');
    }
    text
}
