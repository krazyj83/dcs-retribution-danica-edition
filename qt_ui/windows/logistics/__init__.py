"""
qt_ui/windows/logistics/__init__.py

Package marker for the logistics UI window module.

Note: an earlier draft of this file contained a duplicate, incomplete
copy of the data model classes that actually live in game/logistics/
(DropZone, Warehouse, WarehouseCategory, LogisticsManager, etc.).
QLogisticsWindow.py imports the real versions from game.logistics —
nothing in this codebase imports from here, so this file is kept
intentionally empty to avoid two competing definitions of the same
classes.
"""
