from .game import Game
from .version import VERSION
from .migrator import Migrator
from game.logistics import LogisticsManager
self.logistics = LogisticsManager()
for cp in self.theater.control_points:
    self.logistics.ensure_warehouse(cp.id, cp.name, cp.captured_by)
