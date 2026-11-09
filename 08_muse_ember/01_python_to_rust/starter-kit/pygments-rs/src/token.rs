//! Token types. The stored value is the dotted path after `Token`, so the
//! empty path is `Token` itself, matching Python's `repr` for token types.

use std::fmt;

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, PartialOrd, Ord)]
pub struct TokenType(pub &'static str);

impl TokenType {
    pub const fn new(path: &'static str) -> Self {
        TokenType(path)
    }
}

impl fmt::Display for TokenType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.0.is_empty() {
            write!(f, "Token")
        } else {
            write!(f, "Token.{}", self.0)
        }
    }
}

macro_rules! tokens {
    ($($name:ident = $path:expr;)*) => {
        $(pub const $name: TokenType = TokenType::new($path);)*
    };
}

tokens! {
    TOKEN = "";
    TEXT = "Text";
    WHITESPACE = "Text.Whitespace";
    ESCAPE = "Escape";
    ERROR = "Error";
    OTHER = "Other";
    KEYWORD = "Keyword";
    KEYWORD_CONSTANT = "Keyword.Constant";
    KEYWORD_DECLARATION = "Keyword.Declaration";
    KEYWORD_NAMESPACE = "Keyword.Namespace";
    KEYWORD_PSEUDO = "Keyword.Pseudo";
    KEYWORD_RESERVED = "Keyword.Reserved";
    KEYWORD_TYPE = "Keyword.Type";
    NAME = "Name";
    NAME_ATTRIBUTE = "Name.Attribute";
    NAME_BUILTIN = "Name.Builtin";
    NAME_BUILTIN_PSEUDO = "Name.Builtin.Pseudo";
    NAME_CLASS = "Name.Class";
    NAME_CONSTANT = "Name.Constant";
    NAME_DECORATOR = "Name.Decorator";
    NAME_ENTITY = "Name.Entity";
    NAME_EXCEPTION = "Name.Exception";
    NAME_FUNCTION = "Name.Function";
    NAME_FUNCTION_MAGIC = "Name.Function.Magic";
    NAME_PROPERTY = "Name.Property";
    NAME_LABEL = "Name.Label";
    NAME_NAMESPACE = "Name.Namespace";
    NAME_OTHER = "Name.Other";
    NAME_TAG = "Name.Tag";
    NAME_VARIABLE = "Name.Variable";
    NAME_VARIABLE_CLASS = "Name.Variable.Class";
    NAME_VARIABLE_GLOBAL = "Name.Variable.Global";
    NAME_VARIABLE_INSTANCE = "Name.Variable.Instance";
    NAME_VARIABLE_MAGIC = "Name.Variable.Magic";
    LITERAL = "Literal";
    LITERAL_DATE = "Literal.Date";
    STRING = "Literal.String";
    STRING_AFFIX = "Literal.String.Affix";
    STRING_BACKTICK = "Literal.String.Backtick";
    STRING_CHAR = "Literal.String.Char";
    STRING_DELIMITER = "Literal.String.Delimiter";
    STRING_DOC = "Literal.String.Doc";
    STRING_DOUBLE = "Literal.String.Double";
    STRING_ESCAPE = "Literal.String.Escape";
    STRING_HEREDOC = "Literal.String.Heredoc";
    STRING_INTERPOL = "Literal.String.Interpol";
    STRING_OTHER = "Literal.String.Other";
    STRING_REGEX = "Literal.String.Regex";
    STRING_SINGLE = "Literal.String.Single";
    STRING_SYMBOL = "Literal.String.Symbol";
    NUMBER = "Literal.Number";
    NUMBER_BIN = "Literal.Number.Bin";
    NUMBER_FLOAT = "Literal.Number.Float";
    NUMBER_HEX = "Literal.Number.Hex";
    NUMBER_INTEGER = "Literal.Number.Integer";
    NUMBER_INTEGER_LONG = "Literal.Number.Integer.Long";
    NUMBER_OCT = "Literal.Number.Oct";
    PUNCTUATION = "Punctuation";
    PUNCTUATION_MARKER = "Punctuation.Marker";
    OPERATOR = "Operator";
    OPERATOR_WORD = "Operator.Word";
    COMMENT = "Comment";
    COMMENT_HASHBANG = "Comment.Hashbang";
    COMMENT_MULTILINE = "Comment.Multiline";
    COMMENT_PREPROC = "Comment.Preproc";
    COMMENT_PREPROCFILE = "Comment.PreprocFile";
    COMMENT_SINGLE = "Comment.Single";
    COMMENT_SPECIAL = "Comment.Special";
    GENERIC = "Generic";
    GENERIC_DELETED = "Generic.Deleted";
    GENERIC_EMPH = "Generic.Emph";
    GENERIC_ERROR = "Generic.Error";
    GENERIC_HEADING = "Generic.Heading";
    GENERIC_INSERTED = "Generic.Inserted";
    GENERIC_OUTPUT = "Generic.Output";
    GENERIC_PROMPT = "Generic.Prompt";
    GENERIC_STRONG = "Generic.Strong";
    GENERIC_SUBHEADING = "Generic.Subheading";
    GENERIC_EMPHSTRONG = "Generic.EmphStrong";
    GENERIC_TRACEBACK = "Generic.Traceback";
}
