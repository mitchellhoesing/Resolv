"""Unit tests for the tree-sitter AST helpers."""

from __future__ import annotations

from resolv.utils.ast_tools import extract_definitions


def test_extract_top_level_function_and_class() -> None:
    source = (
        b"def alpha(x):\n"
        b"    return x + 1\n"
        b"\n"
        b"class Beta:\n"
        b"    def method(self):\n"
        b"        return 2\n"
    )
    defs = extract_definitions(source)
    names = [name for name, _ in defs]
    assert names == ["alpha", "Beta"]
    alpha_snippet = defs[0][1]
    beta_snippet = defs[1][1]
    assert "return x + 1" in alpha_snippet
    assert "class Beta" in beta_snippet
    assert "def method(self):" in beta_snippet


def test_extract_handles_decorated_definition() -> None:
    source = (
        b"@staticmethod\n"
        b"def decorated():\n"
        b"    return 1\n"
    )
    defs = extract_definitions(source)
    assert [name for name, _ in defs] == ["decorated"]
    assert "@staticmethod" in defs[0][1]


def test_extract_ignores_nested_definitions() -> None:
    source = (
        b"def outer():\n"
        b"    def inner():\n"
        b"        return 1\n"
        b"    return inner\n"
    )
    defs = extract_definitions(source)
    assert [name for name, _ in defs] == ["outer"]


def test_extract_empty_source_returns_empty_list() -> None:
    assert extract_definitions(b"") == []
