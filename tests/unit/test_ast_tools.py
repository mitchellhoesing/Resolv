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
    names = [definition.name for definition in defs]
    assert names == ["alpha", "Beta"]
    alpha_snippet = defs[0].snippet
    beta_snippet = defs[1].snippet
    assert "return x + 1" in alpha_snippet
    assert "class Beta" in beta_snippet
    assert "def method(self):" in beta_snippet
    # alpha spans lines 1-2; Beta starts at line 4 and spans its body
    assert (defs[0].start_line, defs[0].end_line) == (1, 2)
    assert defs[1].start_line == 4 and defs[1].end_line >= 6


def test_extract_handles_decorated_definition() -> None:
    source = (
        b"@staticmethod\n"
        b"def decorated():\n"
        b"    return 1\n"
    )
    defs = extract_definitions(source)
    assert [definition.name for definition in defs] == ["decorated"]
    assert "@staticmethod" in defs[0].snippet
    assert defs[0].start_line == 1  # span includes the decorator


def test_extract_ignores_nested_definitions() -> None:
    source = (
        b"def outer():\n"
        b"    def inner():\n"
        b"        return 1\n"
        b"    return inner\n"
    )
    defs = extract_definitions(source)
    assert [definition.name for definition in defs] == ["outer"]


def test_extract_empty_source_returns_empty_list() -> None:
    assert extract_definitions(b"") == []
