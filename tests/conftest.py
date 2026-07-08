"""Shared pytest fixtures."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest import mock as _um

import pytest

from resolv.core.state import BlackboardState, IssueRef


# ---------------------------------------------------------------------------
# pytest_mock shim
# ---------------------------------------------------------------------------
# The test suite imports ``from pytest_mock import MockerFixture`` in several
# modules. When the real pytest-mock package is not installed (e.g. minimal
# CI sandboxes), those imports abort test collection. We install a minimal
# shim into ``sys.modules`` covering the subset the tests actually rely on.
_USING_PYTEST_MOCK_SHIM = False
try:  # pragma: no cover - simple import guard
    import pytest_mock  # noqa: F401
except ImportError:  # pragma: no cover - shim exercised only in the fallback
    _USING_PYTEST_MOCK_SHIM = True
    class _PatchProxy:
        def __init__(self, fixture: "_MockerFixture") -> None:
            self._fixture = fixture

        def __call__(self, target: Any, *args: Any, **kwargs: Any) -> Any:
            patcher = _um.patch(target, *args, **kwargs)
            return self._fixture._start(patcher)

        def object(self, target: Any, attribute: str, *args: Any, **kwargs: Any) -> Any:
            patcher = _um.patch.object(target, attribute, *args, **kwargs)
            return self._fixture._start(patcher)

        def dict(
            self,
            in_dict: Any,
            values: Any = (),
            clear: bool = False,
            **kwargs: Any,
        ) -> Any:
            patcher = _um.patch.dict(in_dict, values, clear=clear, **kwargs)
            return self._fixture._start(patcher)

        def multiple(self, target: Any, **kwargs: Any) -> Any:
            patcher = _um.patch.multiple(target, **kwargs)
            return self._fixture._start(patcher)

    class _MockerFixture:
        Mock = _um.Mock
        MagicMock = _um.MagicMock
        PropertyMock = _um.PropertyMock
        AsyncMock = _um.AsyncMock
        ANY = _um.ANY
        call = _um.call
        sentinel = _um.sentinel

        def __init__(self) -> None:
            self._patchers: list[Any] = []
            self.patch = _PatchProxy(self)

        def _start(self, patcher: Any) -> Any:
            started = patcher.start()
            self._patchers.append(patcher)
            return started

        def stopall(self) -> None:
            while self._patchers:
                patcher = self._patchers.pop()
                patcher.stop()

    _shim = types.ModuleType("pytest_mock")
    _shim.MockerFixture = _MockerFixture  # type: ignore[attr-defined]
    sys.modules["pytest_mock"] = _shim


if _USING_PYTEST_MOCK_SHIM:

    @pytest.fixture
    def mocker() -> Any:
        """Fallback ``mocker`` fixture used when pytest-mock is not installed."""
        import pytest_mock as _pm

        fixture = _pm.MockerFixture()  # type: ignore[attr-defined]
        try:
            yield fixture
        finally:
            fixture.stopall()


@pytest.fixture
def sample_issue() -> IssueRef:
    return IssueRef(
        owner="acme",
        repo="widgets",
        number=42,
        title="Crash on empty input",
        body="Reproduces by calling process('')",
        labels=("bug",),
    )


@pytest.fixture
def sample_state(sample_issue: IssueRef, tmp_path: Path) -> BlackboardState:
    return BlackboardState(issue=sample_issue, workspace_path=tmp_path)
