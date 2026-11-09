//! Engine tests with small hand-written test lexers (no ported lexers).

use pygments_rs::engine::{preprocess, CompiledLexer};
use pygments_rs::lexer::{
    bygroups, this_using_state, using_other, using_this_state, words, words_affix, Action,
    ByGroupAction,
    Flags, LexerDef, Pattern, Rule, Transition, TupleItem,
};
use pygments_rs::token;
use pygments_rs::TokenType;

type Toks = Vec<(String, String)>;

fn lex(def: &'static LexerDef, text: &str) -> Toks {
    CompiledLexer::new(def)
        .get_tokens(text)
        .into_iter()
        .map(|(t, v)| (t.to_string(), v))
        .collect()
}

fn lex_unprocessed(def: &'static LexerDef, text: &str) -> Toks {
    let lexer = CompiledLexer::new(def);
    let mut out = Vec::new();
    lexer.get_tokens_unprocessed_with(text, &["root"], |t, v| {
        out.push((t.to_string(), v.to_string()))
    });
    out
}

fn expected(pairs: &[(&str, &str)]) -> Toks {
    pairs.iter().map(|(t, v)| (t.to_string(), v.to_string())).collect()
}

// ---------------------------------------------------------------- basics

static BASIC: LexerDef = LexerDef {
    name: "Basic",
    aliases: &["basic-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r"\s+", token::WHITESPACE),
        Rule::new(words_affix(&["if", "else"], "", r"\b"), Action::Token(token::KEYWORD), Transition::Stay),
        Rule::token(r"\d+", token::NUMBER_INTEGER),
        Rule::token(r"[A-Za-z_]\w*", token::NAME),
        Rule::token(r"[+\-*/=;()]", token::OPERATOR),
    ])],
};

#[test]
fn basic_tokens_and_rule_order() {
    assert_eq!(
        lex(&BASIC, "if x1 = 42; else"),
        expected(&[
            ("Token.Keyword", "if"),
            ("Token.Text.Whitespace", " "),
            ("Token.Name", "x1"),
            ("Token.Text.Whitespace", " "),
            ("Token.Operator", "="),
            ("Token.Text.Whitespace", " "),
            ("Token.Literal.Number.Integer", "42"),
            ("Token.Operator", ";"),
            ("Token.Text.Whitespace", " "),
            ("Token.Keyword", "else"),
            ("Token.Text.Whitespace", "\n"),
        ])
    );
}

#[test]
fn token_repr() {
    assert_eq!(TokenType::new("Literal.String.Double").to_string(), "Token.Literal.String.Double");
    assert_eq!(token::TOKEN.to_string(), "Token");
    assert_eq!(token::STRING_DOUBLE.to_string(), "Token.Literal.String.Double");
    assert_eq!(token::ERROR.to_string(), "Token.Error");
}

static ERR_LEXER: LexerDef = LexerDef {
    name: "Err",
    aliases: &["err-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[
        ("root", &[Rule::token_to(r"a", token::TEXT, "inner")]),
        ("inner", &[Rule::token(r"b", token::NAME)]),
    ],
};

#[test]
fn error_token_and_newline_resets_to_root() {
    assert_eq!(
        lex_unprocessed(&ERR_LEXER, "aZb\nb"),
        expected(&[
            ("Token.Text", "a"),
            ("Token.Error", "Z"),
            ("Token.Name", "b"),
            ("Token.Text.Whitespace", "\n"),
            ("Token.Error", "b"),
        ])
    );
    // An unmatched non-ASCII character is a single Error token.
    assert_eq!(
        lex_unprocessed(&ERR_LEXER, "é"),
        expected(&[("Token.Error", "é")])
    );
}

// ------------------------------------------- tuple transitions, default, pops

static TUPLE_LEXER: LexerDef = LexerDef {
    name: "Tuple",
    aliases: &["tuple-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[
        ("root", &[
            Rule::token_to("a", TokenType::new("Text.Root"), "rag"),
            Rule::token("e", TokenType::new("Text.Root")),
            Rule::new(Pattern::Re("#"), Action::Token(TokenType::new("Text.Root")), Transition::Pop),
            Rule::new(
                Pattern::Re("@"),
                Action::Token(TokenType::new("Text.Root")),
                Transition::Tuple(&[TupleItem::Pop, TupleItem::Pop]),
            ),
            Rule::Default(Transition::Tuple(&[TupleItem::State("beer"), TupleItem::State("beer")])),
        ]),
        ("beer", &[Rule::new(
            Pattern::Re("d"),
            Action::Token(TokenType::new("Text.Beer")),
            Transition::Tuple(&[TupleItem::Pop, TupleItem::Pop]),
        )]),
        ("rag", &[
            Rule::new(Pattern::Re("b"), Action::Token(TokenType::new("Text.Rag")), Transition::Push),
            Rule::new(
                Pattern::Re("c"),
                Action::Token(TokenType::new("Text.Rag")),
                Transition::Tuple(&[TupleItem::Pop, TupleItem::State("beer")]),
            ),
        ]),
    ],
};

#[test]
fn tuple_transitions_and_push() {
    assert_eq!(
        lex_unprocessed(&TUPLE_LEXER, "abcde"),
        expected(&[
            ("Token.Text.Root", "a"),
            ("Token.Text.Rag", "b"),
            ("Token.Text.Rag", "c"),
            ("Token.Text.Beer", "d"),
            ("Token.Text.Root", "e"),
        ])
    );
}

#[test]
fn default_transition() {
    assert_eq!(
        lex_unprocessed(&TUPLE_LEXER, "d"),
        expected(&[("Token.Text.Beer", "d")])
    );
}

#[test]
fn pop_on_empty_stack_keeps_root() {
    assert_eq!(
        lex_unprocessed(&TUPLE_LEXER, "#e"),
        expected(&[("Token.Text.Root", "#"), ("Token.Text.Root", "e")])
    );
    assert_eq!(
        lex_unprocessed(&TUPLE_LEXER, "@e"),
        expected(&[("Token.Text.Root", "@"), ("Token.Text.Root", "e")])
    );
}

static POPN_LEXER: LexerDef = LexerDef {
    name: "PopN",
    aliases: &["popn-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[
        ("root", &[
            Rule::token_to("a", token::TEXT, "s1"),
            Rule::token("d", token::KEYWORD),
        ]),
        ("s1", &[Rule::token_to("b", token::TEXT, "s2")]),
        ("s2", &[Rule::new(Pattern::Re("c"), Action::Token(token::TEXT), Transition::PopN(2))]),
    ],
};

#[test]
fn pop_n() {
    assert_eq!(
        lex_unprocessed(&POPN_LEXER, "abcd"),
        expected(&[
            ("Token.Text", "a"),
            ("Token.Text", "b"),
            ("Token.Text", "c"),
            ("Token.Keyword", "d"),
        ])
    );
}

// ------------------------------------------------------- include and inherit

static INCLUDE_LEXER: LexerDef = LexerDef {
    name: "Include",
    aliases: &["include-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[
        ("root", &[Rule::Include("helpers"), Rule::token("z", token::KEYWORD)]),
        ("helpers", &[Rule::token("h", token::NAME)]),
    ],
};

#[test]
fn include_state() {
    assert_eq!(
        lex_unprocessed(&INCLUDE_LEXER, "hz"),
        expected(&[("Token.Name", "h"), ("Token.Keyword", "z")])
    );
}

static PARENT_LEXER: LexerDef = LexerDef {
    name: "Parent",
    aliases: &["parent-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[
        ("root", &[Rule::token("a", token::TEXT), Rule::token("b", token::TEXT)]),
        ("inner", &[Rule::token("x", token::NAME)]),
    ],
};

static CHILD_LEXER: LexerDef = LexerDef {
    name: "Child",
    aliases: &["child-test"],
    flags: Flags::MULTILINE,
    parent: Some(&PARENT_LEXER),
    states: &[("root", &[
        Rule::token("p", token::KEYWORD),
        Rule::Inherit,
        Rule::token("q", token::KEYWORD),
        Rule::token_to("s", token::OPERATOR, "inner"),
    ])],
};

#[test]
fn inherit_position_and_inherited_state() {
    assert_eq!(
        lex_unprocessed(&CHILD_LEXER, "pabqsx"),
        expected(&[
            ("Token.Keyword", "p"),
            ("Token.Text", "a"),
            ("Token.Text", "b"),
            ("Token.Keyword", "q"),
            ("Token.Operator", "s"),
            ("Token.Name", "x"),
        ])
    );
}

// ---------------------------------------------------------------- combined

static COMBINED_LEXER: LexerDef = LexerDef {
    name: "Combined",
    aliases: &["combined-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[
        ("root", &[Rule::new(
            Pattern::Re(r"\("),
            Action::Token(token::PUNCTUATION),
            Transition::Combined(&["sa", "sb"]),
        )]),
        ("sa", &[Rule::token("a", token::NAME)]),
        ("sb", &[
            Rule::token("b", token::KEYWORD),
            Rule::new(Pattern::Re(r"\)"), Action::Token(token::PUNCTUATION), Transition::Pop),
        ]),
    ],
};

#[test]
fn combined_state() {
    assert_eq!(
        lex_unprocessed(&COMBINED_LEXER, "(ab)"),
        expected(&[
            ("Token.Punctuation", "("),
            ("Token.Name", "a"),
            ("Token.Keyword", "b"),
            ("Token.Punctuation", ")"),
        ])
    );
}

// ------------------------------------------------------------ bygroups/using

static USING_LEXER: LexerDef = LexerDef {
    name: "Using",
    aliases: &["using-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[
        ("root", &[
            Rule::new(
                Pattern::Re(r#"(")(.+?)(")"#),
                bygroups(&[
                    ByGroupAction::Token(token::STRING),
                    ByGroupAction::Using(this_using_state("string")),
                    ByGroupAction::Token(token::STRING),
                ]),
                Transition::Stay,
            ),
            Rule::token(r#"[^"]+"#, token::TEXT),
        ]),
        ("string", &[Rule::token(r".+", token::KEYWORD)]),
    ],
};

#[test]
fn bygroups_with_using_this() {
    assert_eq!(
        lex(&USING_LEXER, "a\"bcd\"e"),
        expected(&[
            ("Token.Text", "a"),
            ("Token.Literal.String", "\""),
            ("Token.Keyword", "bcd"),
            ("Token.Literal.String", "\""),
            ("Token.Text", "e\n"),
        ])
    );
}

static BYGROUPS_LEXER: LexerDef = LexerDef {
    name: "ByGroups",
    aliases: &["bygroups-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::new(
            Pattern::Re(r"(a)(b)?(c)"),
            bygroups(&[
                ByGroupAction::Token(token::KEYWORD),
                ByGroupAction::Skip,
                ByGroupAction::Token(token::NAME),
            ]),
            Transition::Stay,
        ),
        Rule::token(r"\n", token::TEXT),
    ])],
};

#[test]
fn bygroups_skips_none_and_missing_groups() {
    // Group 2 participates in "abc" but is skipped; in "ac" it is absent.
    assert_eq!(
        lex_unprocessed(&BYGROUPS_LEXER, "abcac"),
        expected(&[
            ("Token.Keyword", "a"),
            ("Token.Name", "c"),
            ("Token.Keyword", "a"),
            ("Token.Name", "c"),
        ])
    );
}

static OTHER_LEXER: LexerDef = LexerDef {
    name: "Other",
    aliases: &["other-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r"<", token::PUNCTUATION),
        Rule::token(r"\d+", token::NUMBER_INTEGER),
        Rule::token(r">", token::PUNCTUATION),
    ])],
};

static USING_OTHER_LEXER: LexerDef = LexerDef {
    name: "UsingOther",
    aliases: &["using-other-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::new(Pattern::Re(r"<\d+>"), using_other(&OTHER_LEXER), Transition::Stay),
        Rule::new(
            Pattern::Re(r"(\{)(\w+)(\})"),
            bygroups(&[
                ByGroupAction::Token(token::PUNCTUATION),
                ByGroupAction::Using(pygments_rs::lexer::this_using()),
                ByGroupAction::Token(token::PUNCTUATION),
            ]),
            Transition::Stay,
        ),
        Rule::token(r"\w+", token::NAME),
    ])],
};

#[test]
fn using_other_and_using_this_without_state() {
    assert_eq!(
        lex_unprocessed(&USING_OTHER_LEXER, "<42>{abc}"),
        expected(&[
            ("Token.Punctuation", "<"),
            ("Token.Literal.Number.Integer", "42"),
            ("Token.Punctuation", ">"),
            ("Token.Punctuation", "{"),
            ("Token.Name", "abc"),
            ("Token.Punctuation", "}"),
        ])
    );
}

static USING_INVALID_LEXER: LexerDef = LexerDef {
    name: "UsingInvalid",
    aliases: &["using-invalid-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[Rule::new(
        Pattern::Re(r"#.*"),
        using_this_state("invalid"),
        Transition::Stay,
    )])],
};

#[test]
#[should_panic(expected = "unknown state")]
fn using_invalid_state_panics() {
    let _ = lex(&USING_INVALID_LEXER, "#a");
}

// ------------------------------------------------------------------- words()

static WORDS_LEXER: LexerDef = LexerDef {
    name: "Words",
    aliases: &["words-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::new(
            words(&["a-word", "another-word", "[", "]", "^", "\\", "(", ")", "(?:", "-", "|", r"\w"]),
            Action::Token(token::NAME),
            Transition::Stay,
        ),
        Rule::new(words_affix(&["space-allowed-before-this"], " ?", ""), Action::Token(token::NAME), Transition::Stay),
        Rule::token(r"\n", token::TEXT),
        Rule::token(r" ", token::TEXT),
    ])],
};

#[test]
fn words_match_literals_and_affixes() {
    assert_eq!(
        lex(&WORDS_LEXER, "a-word another-word [ \\ (?: \\w"),
        expected(&[
            ("Token.Name", "a-word"),
            ("Token.Text", " "),
            ("Token.Name", "another-word"),
            ("Token.Text", " "),
            ("Token.Name", "["),
            ("Token.Text", " "),
            ("Token.Name", "\\"),
            ("Token.Text", " "),
            ("Token.Name", "(?:"),
            ("Token.Text", " "),
            ("Token.Name", "\\w"),
            ("Token.Text", "\n"),
        ])
    );
    assert_eq!(
        lex(&WORDS_LEXER, " space-allowed-before-this"),
        expected(&[("Token.Name", " space-allowed-before-this"), ("Token.Text", "\n")])
    );
}

// --------------------------------------------------------------- unistring

static UNI_LEXER: LexerDef = LexerDef {
    name: "Uni",
    aliases: &["uni-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r"[${Lu}]+", token::NAME_CLASS),
        Rule::token(r"[${Ll}]+", token::NAME),
        Rule::token(r"[${xid_start}][${xid_continue}]*", token::NAME_FUNCTION),
        Rule::token(r"\s+", token::WHITESPACE),
    ])],
};

#[test]
fn unistring_classes() {
    assert_eq!(
        lex(&UNI_LEXER, "abc XYZ _x9 café"),
        expected(&[
            ("Token.Name", "abc"),
            ("Token.Text.Whitespace", " "),
            ("Token.Name.Class", "XYZ"),
            ("Token.Text.Whitespace", " "),
            ("Token.Name.Function", "_x9"),
            ("Token.Text.Whitespace", " "),
            ("Token.Name", "café"),
            ("Token.Text.Whitespace", "\n"),
        ])
    );
}

static UNI_COMBINE_LEXER: LexerDef = LexerDef {
    name: "UniCombine",
    aliases: &["uni-combine-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r"[${combine:Ll,Lu}]+", token::NAME),
        Rule::token(r"[${allexcept:Nd}]+", token::STRING),
        Rule::token(r"[0-9]+", token::NUMBER_INTEGER),
    ])],
};

#[test]
fn unistring_combine_and_allexcept() {
    assert_eq!(
        lex_unprocessed(&UNI_COMBINE_LEXER, "aZ 12"),
        expected(&[
            ("Token.Name", "aZ"),
            ("Token.Literal.String", " "),
            ("Token.Literal.Number.Integer", "12"),
        ])
    );
}

// -------------------------------------------------------------------- flags

static FLAGS_LEXER: LexerDef = LexerDef {
    name: "Flags",
    aliases: &["flags-test"],
    flags: Flags::IGNORECASE.union(Flags::MULTILINE).union(Flags::DOTALL),
    parent: None,
    states: &[("root", &[
        Rule::token(r"^abc", token::KEYWORD),
        Rule::token(r"a.c", token::STRING),
        Rule::token(r"\n", token::TEXT),
    ])],
};

#[test]
fn lexer_flags_ignorecase_multiline_dotall() {
    assert_eq!(
        lex_unprocessed(&FLAGS_LEXER, "ABC a\nc"),
        expected(&[("Token.Keyword", "ABC"), ("Token.Error", " "), ("Token.Literal.String", "a\nc")])
    );
}

static VERBOSE_LEXER: LexerDef = LexerDef {
    name: "Verbose",
    aliases: &["verbose-test"],
    flags: Flags::VERBOSE.union(Flags::MULTILINE),
    parent: None,
    states: &[("root", &[Rule::token("a b  # comment\n c", token::KEYWORD)])],
};

#[test]
fn verbose_flag() {
    assert_eq!(
        lex_unprocessed(&VERBOSE_LEXER, "abc"),
        expected(&[("Token.Keyword", "abc")])
    );
}

static ASCII_LEXER: LexerDef = LexerDef {
    name: "Ascii",
    aliases: &["ascii-test"],
    flags: Flags::ASCII.union(Flags::MULTILINE),
    parent: None,
    states: &[("root", &[Rule::token(r"\w+", token::NAME)])],
};

#[test]
fn ascii_flag() {
    assert_eq!(
        lex_unprocessed(&ASCII_LEXER, "abc é"),
        expected(&[
            ("Token.Name", "abc"),
            ("Token.Error", " "),
            ("Token.Error", "é"),
        ])
    );
}

static INLINE_FLAG_LEXER: LexerDef = LexerDef {
    name: "InlineFlag",
    aliases: &["inline-flag-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r"(?i)abc", token::KEYWORD),
        Rule::token(r"(?s:.)", token::TEXT),
    ])],
};

#[test]
fn inline_flags() {
    assert_eq!(
        lex_unprocessed(&INLINE_FLAG_LEXER, "ABCx"),
        expected(&[("Token.Keyword", "ABC"), ("Token.Text", "x")])
    );
}

// ------------------------------------------- lookaround, backrefs, Python re

static LOOK_LEXER: LexerDef = LexerDef {
    name: "Look",
    aliases: &["look-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r#"(['"])(\w*)\1"#, token::STRING_DOUBLE),
        Rule::token(r"@", token::PUNCTUATION),
        Rule::token(r"(?<=@)\w+", token::NAME_ATTRIBUTE),
        Rule::token(r"\w+(?=\()", token::NAME_FUNCTION),
        Rule::token(r"(?<!\w)\d+", token::NUMBER_INTEGER),
        Rule::token(r"\w+", token::NAME),
        Rule::token(r"[()\s]", token::TEXT),
    ])],
};

#[test]
fn lookahead_lookbehind_backreference() {
    assert_eq!(
        lex_unprocessed(&LOOK_LEXER, "'hi' @user foo( 42"),
        expected(&[
            ("Token.Literal.String.Double", "'hi'"),
            ("Token.Text", " "),
            ("Token.Punctuation", "@"),
            ("Token.Name.Attribute", "user"),
            ("Token.Text", " "),
            ("Token.Name.Function", "foo"),
            ("Token.Text", "("),
            ("Token.Text", " "),
            ("Token.Literal.Number.Integer", "42"),
        ])
    );
}

static PYRE_LEXER: LexerDef = LexerDef {
    name: "PyRe",
    aliases: &["pyre-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r#"(?P<q>['"]).*?(?P=q)"#, token::STRING_SINGLE),
        Rule::token(r"ba{,3}", token::KEYWORD),
        Rule::token(r"zzz\Z", token::NAME),
    ])],
};

#[test]
fn python_pattern_syntax() {
    assert_eq!(
        lex_unprocessed(&PYRE_LEXER, "\"x\" baa zzz"),
        expected(&[
            ("Token.Literal.String.Single", "\"x\""),
            ("Token.Error", " "),
            ("Token.Keyword", "baa"),
            ("Token.Error", " "),
            ("Token.Name", "zzz"),
        ])
    );
}

// -------------------------------------------------------------- preprocessing

#[test]
fn preprocessing_matches_get_tokens_defaults() {
    assert_eq!(preprocess("abc"), "abc\n");
    assert_eq!(preprocess("abc\n"), "abc\n");
    assert_eq!(preprocess("\n\nabc\n\n\n"), "abc\n");
    assert_eq!(preprocess(""), "\n");
    assert_eq!(preprocess("\u{feff}abc"), "abc\n");
    assert_eq!(preprocess("a\r\nb\rc"), "a\nb\nc\n");
    assert_eq!(preprocess("a\n\n"), "a\n");
}

static PRE_LEXER: LexerDef = LexerDef {
    name: "Pre",
    aliases: &["pre-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r"[^\n]+", token::TEXT),
        Rule::token(r"\n", token::WHITESPACE),
    ])],
};

#[test]
fn preprocessing_applied_by_get_tokens() {
    assert_eq!(
        lex(&PRE_LEXER, "\u{feff}ab\r\ncd"),
        expected(&[
            ("Token.Text", "ab"),
            ("Token.Text.Whitespace", "\n"),
            ("Token.Text", "cd"),
            ("Token.Text.Whitespace", "\n"),
        ])
    );
    assert_eq!(lex(&PRE_LEXER, ""), expected(&[("Token.Text.Whitespace", "\n")]));
}

// ------------------------------------------------------------------ registry

#[test]
fn registry_is_empty() {
    assert!(pygments_rs::lexers::LEXERS.is_empty());
    assert!(pygments_rs::lexers::aliases().is_empty());
    assert!(pygments_rs::lexers::find("python").is_none());
}

// ---------------------------------------------------------------------- perf

static PERF_LEXER: LexerDef = LexerDef {
    name: "Perf",
    aliases: &["perf-test"],
    flags: Flags::MULTILINE,
    parent: None,
    states: &[("root", &[
        Rule::token(r"\s+", token::WHITESPACE),
        Rule::token(r"#[^\n]*", token::COMMENT_SINGLE),
        Rule::token(r#"(["'])(?:\\.|(?!\1).)*\1"#, token::STRING_DOUBLE),
        Rule::token(r"(?<![\w$])(?:if|else|while|return)(?![\w$])", token::KEYWORD),
        Rule::token(r"\d+(?:\.\d+)?", token::NUMBER_FLOAT),
        Rule::token(r"[A-Za-z_]\w*(?=\()", token::NAME_FUNCTION),
        Rule::token(r"[A-Za-z_]\w*", token::NAME),
        Rule::token(r"[+\-*/=<>!&|;:,.(){}[\]]", token::OPERATOR),
    ])],
};

#[test]
fn lexes_one_megabyte_well_under_a_second() {
    let snippet = "if value_1 == 42 and name('str') { return foo(bar, 3.14); } # comment\n\
                   while x_2 != 'it\\'s' { y = call(z, 100) + 2.5; }\n";
    let mut input = String::new();
    while input.len() < 1_000_000 {
        input.push_str(snippet);
    }
    assert!(input.len() >= 1_000_000);
    let lexer = CompiledLexer::new(&PERF_LEXER);
    let start = std::time::Instant::now();
    let mut bytes = 0usize;
    let mut count = 0usize;
    let mut joined = String::with_capacity(input.len());
    lexer.get_tokens_with(&input, |_, v| {
        bytes += v.len();
        count += 1;
        joined.push_str(v);
    });
    let elapsed = start.elapsed();
    assert_eq!(joined, input);
    assert!(count > 10_000, "suspiciously few tokens: {count}");
    assert_eq!(bytes, input.len());
    assert!(
        elapsed < std::time::Duration::from_secs(1),
        "lexing {} bytes took {elapsed:?}",
        input.len()
    );
}
