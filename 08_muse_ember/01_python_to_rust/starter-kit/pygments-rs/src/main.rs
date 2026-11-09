use std::io::{Read, Write};
use std::process::ExitCode;

use pygments_rs::engine::CompiledLexer;
use pygments_rs::lexers;
use pygments_rs::token::TokenType;

fn json_escape_into(out: &mut String, s: &str) {
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
}

fn print_usage() {
    eprintln!("usage: pygments-rs --lexer <alias> [--input <file>]");
    eprintln!("       pygments-rs --list");
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut lexer_alias: Option<String> = None;
    let mut input: Option<String> = None;
    let mut list = false;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--lexer" => {
                i += 1;
                if i >= args.len() {
                    print_usage();
                    return ExitCode::from(2);
                }
                lexer_alias = Some(args[i].clone());
            }
            "--input" => {
                i += 1;
                if i >= args.len() {
                    print_usage();
                    return ExitCode::from(2);
                }
                input = Some(args[i].clone());
            }
            "--list" => list = true,
            "-h" | "--help" => {
                print_usage();
                return ExitCode::SUCCESS;
            }
            other => {
                eprintln!("unknown argument: {other}");
                print_usage();
                return ExitCode::from(2);
            }
        }
        i += 1;
    }

    if list {
        let stdout = std::io::stdout();
        let mut out = std::io::BufWriter::new(stdout.lock());
        for alias in lexers::aliases() {
            writeln!(out, "{alias}").expect("write to stdout");
        }
        return ExitCode::SUCCESS;
    }

    let alias = match lexer_alias {
        Some(a) => a,
        None => {
            print_usage();
            return ExitCode::from(2);
        }
    };
    let def = match lexers::find(&alias) {
        Some(d) => d,
        None => {
            eprintln!("unknown lexer alias: {alias}");
            return ExitCode::from(2);
        }
    };

    let bytes: Vec<u8> = match &input {
        Some(path) => match std::fs::read(path) {
            Ok(b) => b,
            Err(e) => {
                eprintln!("cannot read {path}: {e}");
                return ExitCode::from(1);
            }
        },
        None => {
            let mut b = Vec::new();
            if let Err(e) = std::io::stdin().lock().read_to_end(&mut b) {
                eprintln!("cannot read stdin: {e}");
                return ExitCode::from(1);
            }
            b
        }
    };
    let text = String::from_utf8_lossy(&bytes);

    let lexer = CompiledLexer::new(def);
    let stdout = std::io::stdout();
    let mut out = std::io::BufWriter::with_capacity(1 << 16, stdout.lock());
    let mut line = String::new();
    lexer.get_tokens_with(&text, |t: TokenType, v: &str| {
        line.clear();
        line.push_str("{\"t\": \"");
        line.push_str(&t.to_string());
        line.push_str("\", \"v\": \"");
        json_escape_into(&mut line, v);
        line.push_str("\"}");
        out.write_all(line.as_bytes()).expect("write to stdout");
        out.write_all(b"\n").expect("write to stdout");
    });
    out.flush().expect("write to stdout");
    ExitCode::SUCCESS
}
