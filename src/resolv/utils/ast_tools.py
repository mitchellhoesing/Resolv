"""Tree-sitter helpers for extracting Python top-level definitions."""

from __future__ import annotations

import tree_sitter_python
from tree_sitter import Language, Parser

_PY_LANGUAGE = Language(tree_sitter_python.language())
_PARSER = Parser(_PY_LANGUAGE)


def extract_definitions(source: bytes) -> list[tuple[str, str]]:
    """Return (symbol_name, snippet) pairs for top-level functions and classes.

    Snippets are the raw source text spanning the definition node.
    Malformed Python that tree-sitter cannot parse yields an empty list.
    """
    if not source:
        return []
    tree = _PARSER.parse(source)
    root = tree.root_node
    if root.has_error and not root.children:
        return []

    results: list[tuple[str, str]] = []
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
        results.append((name, snippet))
    return results
