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
        char = text[i]
        if char in (" ", "\t", "\r"):
            i += 1
            continue
        if char == "\n":
            line += 1
            i += 1
            continue
        if char == "#":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if char in ("{", "}", ";"):
            out.append(Token(char, line))
            i += 1
            continue
        if char in ("'", '"'):
            quote, start_line = char, line
            i += 1
            value: list[str] = []
            while i < len(text):
                current = text[i]
                if current == "\\" and i + 1 < len(text):
                    if text[i + 1] == "\n":
                        line += 1
                    value.append(text[i + 1])
                    i += 2
                    continue
                if current == quote:
                    i += 1
                    break
                if current == "\n":
                    line += 1
                value.append(current)
                i += 1
            else:
                raise ValueError(f"unterminated quoted string on line {start_line}")
            out.append(Token("".join(value), start_line))
            continue

        start_i, start_line = i, line
        delimiters = (" ", "\t", "\r", "\n", "{", "}", ";", "#", "'", '"')
        while i < len(text) and text[i] not in delimiters:
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
        self._next_scope_id = 0

    def parse(self, path: Path):
        resolved = path.resolve()
        # Prefix every scope with its entry-point path so multiple nginx.conf
        # trees scanned together cannot accidentally inherit from each other.
        self._file(resolved, (), (str(resolved),))
        return self.directives, self.issues

    def _inside(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

    def _file(self, path: Path, context: tuple[str, ...], scope: tuple[str, ...]):
        path = path.resolve()
        if not self._inside(path):
            self.issues.append(ParseIssue("DM005", "Include is outside scan root", path, 1))
            return
        key = (path, scope)
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
            self.issues.append(
                ParseIssue("DM005", "Could not parse NGINX file", path, 1, str(exc))
            )
            return

        self.active.add(path)
        try:
            self._block(tokens, 0, path, context, scope, False)
        except ValueError as exc:
            self.issues.append(
                ParseIssue("DM005", "Malformed NGINX syntax", path, 1, str(exc))
            )
        finally:
            self.active.remove(path)

    def _block(self, tokens, index, source, context, scope, close):
        while index < len(tokens):
            token = tokens[index]
            if token.value == "}":
                if not close:
                    raise ValueError(f"unexpected }} on line {token.line}")
                return index + 1
            if token.value in {"{", ";"}:
                raise ValueError(f"unexpected {token.value!r} on line {token.line}")

            name, line = token.value, token.line
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
                block_id = str(self._next_scope_id)
                self._next_scope_id += 1
                index = self._block(
                    tokens, index + 1, source, context + (label,),
                    scope + (block_id,), True
                )
            else:
                if name == "include":
                    self._include(args, source, context, scope, line)
                else:
                    self.directives.append(
                        NginxDirective(name, tuple(args), context, source, line, scope)
                    )
                index += 1

        if close:
            raise ValueError("unclosed block")
        return index

    def _include(self, args, source, context, scope, line):
        if len(args) != 1 or "$" in args[0]:
            self.issues.append(
                ParseIssue(
                    "DM005", "Dynamic or unsupported include", source, line,
                    "Only one static path is followed.",
                )
            )
            return

        target = Path(args[0])
        if not target.is_absolute():
            target = source.parent / target
        matches = sorted(Path(item).resolve() for item in glob.glob(str(target)))
        if not matches:
            self.issues.append(
                ParseIssue("DM005", "Include matched no files", source, line, args[0])
            )
            return

        for path in matches:
            if self._inside(path):
                self._file(path, context, scope)
            else:
                self.issues.append(
                    ParseIssue("DM005", "Include escapes scan root", source, line, str(path))
                )


def parse_nginx(path: Path, root: Path):
    return NginxParser(root).parse(path)
