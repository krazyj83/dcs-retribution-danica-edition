"""Save backups per turn (game/persistency.turn_backup)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from game import persistency
from game.settings import Settings


@pytest.fixture
def saves(tmp_path: Path, monkeypatch: Any) -> Path:
    monkeypatch.setattr(persistency, "save_dir", lambda: tmp_path)
    autosave = tmp_path / "autosave.retribution"
    monkeypatch.setattr(persistency, "_autosave_path", lambda: str(autosave))
    return tmp_path


def _game(turn: int, keep: int = 3, name: str = "Operation Danica") -> Any:
    return SimpleNamespace(
        turn=turn,
        campaign_name=name,
        savepath=None,
        settings=SimpleNamespace(turn_backups_kept=keep),
    )


def _play(saves: Path, game: Any) -> Any:
    (saves / "autosave.retribution").write_text(f"turn {game.turn}")
    return persistency.turn_backup(game)


def test_one_backup_per_turn_and_the_oldest_are_deleted(saves: Path) -> None:
    for turn in range(1, 6):
        path = _play(saves, _game(turn, keep=3))

    folder = saves / "TurnBackups" / "Operation Danica"
    assert path == folder / "turn_005.retribution"
    assert sorted(p.name for p in folder.iterdir()) == [
        "turn_003.retribution",
        "turn_004.retribution",
        "turn_005.retribution",
    ]
    assert (folder / "turn_003.retribution").read_text() == "turn 3"


def test_turns_are_sorted_by_number_not_by_name(saves: Path) -> None:
    for turn in (98, 99, 100, 101):
        _play(saves, _game(turn, keep=2))
    folder = saves / "TurnBackups" / "Operation Danica"
    assert sorted(p.name for p in folder.iterdir()) == [
        "turn_100.retribution",
        "turn_101.retribution",
    ]


def test_campaigns_keep_their_own_backups(saves: Path) -> None:
    for turn in range(1, 4):
        _play(saves, _game(turn, keep=1, name="Alpha"))
        _play(saves, _game(turn, keep=1, name="Bravo"))
    root = saves / "TurnBackups"
    assert [p.name for p in (root / "Alpha").iterdir()] == ["turn_003.retribution"]
    assert [p.name for p in (root / "Bravo").iterdir()] == ["turn_003.retribution"]


def test_other_files_in_the_folder_are_left_alone(saves: Path) -> None:
    folder = saves / "TurnBackups" / "Operation Danica"
    folder.mkdir(parents=True)
    (folder / "my notes.txt").write_text("keep me")
    for turn in range(1, 4):
        _play(saves, _game(turn, keep=1))
    assert (folder / "my notes.txt").exists()


def test_zero_turns_backups_off(saves: Path) -> None:
    assert _play(saves, _game(1, keep=0)) is None
    assert not (saves / "TurnBackups").exists()


def test_a_failed_backup_does_not_stop_the_turn(saves: Path) -> None:
    game = _game(1)
    assert persistency.turn_backup(game) is None  # no autosave file to copy


def test_campaign_name_is_made_safe_for_a_folder(saves: Path) -> None:
    path = _play(saves, _game(1, name='Op: "Red/Storm" <2>'))
    assert path is not None
    assert path.parent.name == "Op_ _Red_Storm_ _2"


def test_unnamed_campaign_uses_the_save_file_name(saves: Path) -> None:
    game = _game(1, name="")
    game.savepath = str(saves / "Week 12.retribution")
    path = _play(saves, game)
    assert path is not None and path.parent.name == "Week 12"


def test_setting_defaults_to_ten_and_old_saves_get_it() -> None:
    assert Settings().turn_backups_kept == 10
    old = Settings()
    state = dict(old.__dict__)
    state.pop("turn_backups_kept")
    restored = Settings.__new__(Settings)
    restored.__setstate__(state)
    assert restored.turn_backups_kept == 10
