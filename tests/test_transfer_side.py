"""A transfer's side: old saves (bool) are converted, and REDFOR transfers are
labelled as enemy transfers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from game.migrator import Migrator
from game.theater.player import Player
from game.transfers import TransferOrder


def _transfer(player: Any) -> Any:
    t: Any = TransferOrder.__new__(TransferOrder)
    t.player = player
    return t


def test_old_bool_sides_are_converted() -> None:
    pending, in_convoy, on_ship = _transfer(True), _transfer(False), _transfer(True)
    already = _transfer(Player.RED)
    transfers = SimpleNamespace(
        pending_transfers=[pending, already],
        convoys=[SimpleNamespace(transfers=[in_convoy])],
        cargo_ships=[SimpleNamespace(transfers=[on_ship])],
    )
    migrator: Any = Migrator.__new__(Migrator)
    migrator.game = SimpleNamespace(coalitions=[SimpleNamespace(transfers=transfers)])

    migrator._update_transfers()

    assert pending.player is Player.BLUE
    assert in_convoy.player is Player.RED
    assert on_ship.player is Player.BLUE
    assert already.player is Player.RED


def _order(side: Player) -> TransferOrder:
    origin: Any = SimpleNamespace(name="Kutaisi", captured=side)
    destination: Any = SimpleNamespace(name="Senaki")
    return TransferOrder(origin, destination, {})


def test_enemy_transfers_are_labelled_as_enemy() -> None:
    assert str(_order(Player.BLUE)).startswith("Transfer of 0 units from Kutaisi")
    assert str(_order(Player.RED)).startswith("Enemy transfer of 0 units")
