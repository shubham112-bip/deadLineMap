"""Conservative parser for a practical subset of NGINX configuration."""
from __future__ import annotations
import glob
from dataclasses import dataclass
from pathlib import Path
from deadlinemap.model import NginxDirective, ParseIssue

@dataclass(frozen=True)
class Token:
    value: str
    line: int

def tokenize(text: str) -> list[Token]:
    out: list[Token] = []
    i = 0
    line = 1
    while i < len(text):
        c = text[i]
        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "#":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if c in "{};":
            out.append(Token(c, line))
            i += 1
            continue
        if c in ("'", '"'):
            q, start = c, line
            i += 1
            value = []
            while i < len(text):
                c = text[i]
                if c == "\\" and i + 1 < len(text):
                    if text[i + 1] == "\n":
                        line += 1
                    value.append(text[i + 1])
                    i += 2
                    continue
                if c == q:
                    i += 1
                    break
                if c == "\n":
                    line += 1
                value.append(c)
                i += 1
            else:
                raise ValueError(f"unterminated quoted string on line {start}")
            out.append(Token("".join(value), start))
            continue
        start_i, start_line = i, line
        while i < len(text) and text[i] not in " \t\r\n{};#'\\"":
            i += 1
        if i == start_i:
            i += 1
        out.append(Token(text[start_i:i], start_line))
    return out

class NginxParser:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.directives: list[NginxDirective] = []
        self.issues: list[ParseIssue] = []
        self.active: set[Path] = set()
        self.parsed: set[tuple[Path, tuple[str, ...]]] = set()

    def parse(self, path: Path):
        self._file(path.resolve(), ())
        return self.directives, self.issues

    def _inside(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

    def _file(self, path: Path, context: tuple[str, ...]):
        path = path.resolve()
        if not self._inside(path):
            self.issues.append(ParseIssue("DM005", "Include is outside scan root", path, 1))
            return
        key = (path, context)
        if path in self.active:
            self.issues.append(ParseIssue("DM005", "Cyclic include detected", path, 1))
            return
        if key in self.parsed:
            return
        self.parsed.add(key)
        try:
            text = path.read_text(encoding="utf-8")
            tokens = tokenize(text)
        except (OSError, UnicodeError, ValueError) as exc:
            self.issues.append(ParseIssue("DM005", "Could not parse NGINX file", path, 1, str(exc)))
            return
        self.active.add(path)
        try:
            self._block(tokens, 0, path, context, False)
        except ValueError as exc:
            self.issues.append(ParseIssue("DM005", "Malformed NGINX syntax", path, 1, str(exc)))
        finally:
            self.active.remove(path)

    def _block(self, tokens, index, source, context, close):
        while index < len(tokens):
            tok = tokens[index]
            if tok.value == "}":
                if not close:
                    raise ValueError(f"unexpected }} on line {tok.line}")
                return index + 1
            if tok.value in {"{", ";"}:
                raise ValueError(f"unexpected {tok.value!r} on line {tok.line}")
            name, line = tok.value, tok.line
            index += 1
            args = []
            while index < len(tokens) and tokens[index].value not in {";", "{", "}"}:
                args.append(tokens[index].value)
                index += 1
            if index >= len(tokens) or tokens[index].value == "}":
                raise ValueError(f"directive {name!r} on line {line} is missing a terminator")
            delimiter = tokens[index].value
            if delimiter == "{":
                label = name + ((" " + " ".join(args)) if args else "")
                index = self._block(tokens, index + 1, source, context + (label,), True)
            else:
                if name == "include":
                    self._include(args, source, context, line)
                else:
                    self.directives.append(NginxDirective(name, tuple(args), context, source, line))
                index += 1
        if close:
            raise ValueError("unclosed block")
        return index

    def _include(self, args, source, context, line):
        if len(args) != 1 or "$" in args[0]:
            self.issues.append(ParseIssue("DM005", "Dynamic or unsupported include", source, line, "Only one static path is followed."))
            return
        target = Path(args[0])
        if not target.is_absolute():
            target = source.parent / target
        matches = sorted(Path(p).resolve() for p in glob.glob(str(target)))
        if not matches:
            self.issues.append(ParseIssue("DM005", "Include matched no files", source, line, args[0]))
            return
        for path in matches:
            if self._inside(path):
                self._file(path, context)
            else:
                self.issues.append(ParseIssue("DM005", "Include escapes scan root", source, line, str(path)))

def parse_nginx(path: Path, root: Path):
    return NginxParser(root).parse(path)
