"""Tree-sitter helpers for extracting Python top-level definitions."""

from __future__ import annotations

from typing import NamedTuple

import tree_sitter_python
from tree_sitter import Language, Parser

_PY_LANGUAGE = Language(tree_sitter_python.language())
_PARSER = Parser(_PY_LANGUAGE)


class Definition(NamedTuple):
    name: str
    snippet: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive


def extract_definitions(source: bytes) -> list[Definition]:
    """Return Definitions for top-level functions and classes.

    Snippets are the raw source text spanning the definition node; start_line/
    end_line are 1-based source line numbers for that span (used for git blame).
    Malformed Python that tree-sitter cannot parse yields an empty list.
    """
    if not source:
        return []
    tree = _PARSER.parse(source)
    root = tree.root_node
    if root.has_error and not root.children:
        return []

    results: list[Definition] = []
    for child in root.children:
        if child.type not in ("function_definition", "class_definition", "decorated_definition"):
            continue
        target = child
        if child.type == "decorated_definition":
            target = next(
                (c for c in child.children if c.type in ("function_definition", "class_definition")),
                child,
            )
        name_node = target.child_by_field_name("name")
        if name_node is None:
            continue
        name = source[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")
        snippet = source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
        results.append(
            Definition(name, snippet, child.start_point[0] + 1, child.end_point[0] + 1)
        )
    return results
