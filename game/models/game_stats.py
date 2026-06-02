from __future__ import annotations

from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from game import Game


class FactionTurnMetadata:
    """
    Store metadata about a faction
    """

    aircraft_count: int = 0
    vehicles_count: int = 0
    sam_count: int = 0

    def __init__(self) -> None:
        self.aircraft_count = 0
        self.vehicles_count = 0
        self.sam_count = 0


class GameTurnMetadata:
    """
    Store metadata about a game turn
    """

    allied_units: FactionTurnMetadata
    enemy_units: FactionTurnMetadata

    def __init__(self) -> None:
        self.allied_units = FactionTurnMetadata()
        self.enemy_units = FactionTurnMetadata()


class GameStats:
    """
    Store statistics for the current game
    """

    def __init__(self) -> None:
        self.data_per_turn: List[GameTurnMetadata] = []

    def update(self, game: Game) -> None:
        """
        Save data for current turn
        :param game: Game we want to save the data about
        """

        # Remove the current turn if its just an update for this turn
        if 0 < game.turn < len(self.data_per_turn):
            del self.data_per_turn[-1]

        turn_data = GameTurnMetadata()

        for cp in game.theater.controlpoints:
            if cp.captured.is_blue:
                for squadron in cp.squadrons:
                    turn_data.allied_units.aircraft_count += squadron.owned_aircraft
                turn_data.allied_units.vehicles_count += sum(cp.base.armor.values())
            else:
                for squadron in cp.squadrons:
                    turn_data.enemy_units.aircraft_count += squadron.owned_aircraft
                turn_data.enemy_units.vehicles_count += sum(cp.base.armor.values())

        self.data_per_turn.append(turn_data)


class BlueforTurnMissions:
    """Snapshot of BLUEFOR mission types planned in one turn."""
    def __init__(self, turn: int) -> None:
        self.turn = turn
        self.mission_counts: Counter = Counter()


class BlueforMissionHistory:
    """Rolling window of BLUEFOR mission type usage across recent turns.

    Stores the last WINDOW turns of BLUEFOR ATO data. Used by
    RedforAdaptivePlanner to detect player strategy patterns and
    adjust REDFOR priorities accordingly.
    """
    WINDOW: int = 3

    def __init__(self) -> None:
        self._turns: Deque[BlueforTurnMissions] = deque(maxlen=self.WINDOW)

    def record(self, ato: AirTaskingOrder, turn: int) -> None:
        """Snapshot the current BLUEFOR ATO mission type counts."""
        snapshot = BlueforTurnMissions(turn)
        for package in ato.packages:
            for flight in package.flights:
                snapshot.mission_counts[flight.flight_type] += 1
        self._turns.append(snapshot)

    def total_counts(self) -> Counter:
        """Sum of mission type counts across all stored turns."""
        total: Counter = Counter()
        for turn in self._turns:
            total += turn.mission_counts
        return total

    def count(self, flight_type) -> int:
        """Total count of a specific flight type across the window."""
        return self.total_counts().get(flight_type, 0)

    def dominant(self, threshold: int = 2) -> list:
        """Flight types that appear at least threshold times in the window."""
        return [ft for ft, n in self.total_counts().items() if n >= threshold]

    def has_turns(self) -> bool:
        return len(self._turns) > 0

    @property
    def turns_recorded(self) -> int:
        return len(self._turns)
