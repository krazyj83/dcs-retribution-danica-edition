"""window.prompt() from the map (drop zone and convoy route names)."""

from __future__ import annotations

from typing import Any

import pytest

from qt_ui.widgets.map import QLiberationMap as map_module
from qt_ui.widgets.map.QLiberationMap import LoggingWebPage

#: The handler does not use self; call it unbound without a web engine.
prompt: Any = LoggingWebPage.javaScriptPrompt


@pytest.fixture
def answer(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    reply: dict[str, Any] = {"text": "DZ Alpha", "ok": True, "asked": None}

    def get_text(parent: Any, title: str, label: str, text: str = "") -> Any:
        reply["asked"] = (label, text)
        return reply["text"], reply["ok"]

    monkeypatch.setattr(map_module.QInputDialog, "getText", get_text)
    return reply


@pytest.mark.parametrize(
    "extra",
    [(), ("",)],  # some PySide versions also pass Qt's output argument as a str
)
def test_prompt_returns_the_typed_name(answer: dict[str, Any], extra: Any) -> None:
    result = prompt(None, "file:///map", "Drop zone name:", "Drop Zone", *extra)

    assert result == (True, "DZ Alpha")
    assert answer["asked"] == ("Drop zone name:", "Drop Zone")


def test_cancelled_prompt(answer: dict[str, Any]) -> None:
    answer["ok"] = False

    assert prompt(None, "u", "Name:", "x", "") == (False, "")
