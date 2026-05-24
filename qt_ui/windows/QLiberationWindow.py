import logging
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QCloseEvent, QIcon, QAction, QGuiApplication, QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import qt_ui.uiconstants as CONST
from game import Game, VERSION, persistency, Migrator
from game.debriefing import Debriefing
from game.game import TurnState
from game.layout import LAYOUTS
from game.persistency import pre_pretense_backups_dir
from game.pretense.pretensemissiongenerator import PretenseMissionGenerator
from game.server import EventStream, GameContext
from game.server.dependencies import QtCallbacks, QtContext
from game.theater import ControlPoint, MissionTarget, TheaterGroundObject
from qt_ui import liberation_install
from qt_ui.dialogs import Dialog
from qt_ui.models import GameModel
from qt_ui.simcontroller import SimController
from qt_ui.uiconstants import URLS
from qt_ui.uiflags import UiFlags
from qt_ui.uncaughtexceptionhandler import UncaughtExceptionHandler
from qt_ui.widgets.QTopPanel import QTopPanel
from qt_ui.widgets.ato import QAirTaskingOrderPanel
from qt_ui.widgets.map.QLiberationMap import QLiberationMap
from qt_ui.windows.GameUpdateSignal import GameUpdateSignal
from qt_ui.windows.QDebriefingWindow import QDebriefingWindow
from qt_ui.windows.basemenu.QBaseMenu2 import QBaseMenu2
from qt_ui.windows.groundobject.QGroundObjectMenu import QGroundObjectMenu
from qt_ui.windows.infos.QInfoPanel import QInfoPanel
from qt_ui.windows.logs.QLogsWindow import QLogsWindow
from qt_ui.windows.newgame.QNewGameWizard import NewGameWizard
from qt_ui.windows.notes.QNotesWindow import QNotesWindow
from qt_ui.windows.preferences.QLiberationPreferencesWindow import (
    QLiberationPreferencesWindow,
)
from qt_ui.windows.settings.QSettingsWindow import QSettingsWindow
from qt_ui.windows.stats.QStatsWindow import QStatsWindow
from qt_ui.windows.logistics.QLogisticsWindow import QLogisticsWindow


class QLiberationWindow(QMainWindow):
    new_package_signal = Signal(MissionTarget)
    tgo_info_signal = Signal(TheaterGroundObject)
    control_point_info_signal = Signal(ControlPoint)
    open_drop_zone_dialog_signal = Signal(float, float)

    def __init__(self, game: Game | None, ui_flags: UiFlags) -> None:
        super().__init__()

        self._uncaught_exception_handler = UncaughtExceptionHandler(self)

        self.game = game
        self._logistics_window: Optional[QLogisticsWindow] = None
        self.sim_controller = SimController(self.game)
        self.sim_controller.sim_update.connect(EventStream.put_nowait)
        self.game_model = GameModel(game, self.sim_controller)
        GameContext.set_model(self.game_model)
        self.new_package_signal.connect(
            lambda target: Dialog.open_new_package_dialog(target, self)
        )
        self.tgo_info_signal.connect(self.open_tgo_info_dialog)
        self.control_point_info_signal.connect(self.open_control_point_info_dialog)
        self.open_drop_zone_dialog_signal.connect(self._open_drop_zone_at)
        QtContext.set_callbacks(
            QtCallbacks(
                lambda target: self.new_package_signal.emit(target),
                lambda tgo: self.tgo_info_signal.emit(tgo),
                lambda cp: self.control_point_info_signal.emit(cp),
                lambda lat, lng: self.open_drop_zone_dialog_signal.emit(lat, lng),
            )
        )
        Dialog.set_game(self.game_model)
        self.ato_panel = QAirTaskingOrderPanel(self.game_model)
        self.info_panel = QInfoPanel(self.game)
        self.liberation_map = QLiberationMap(
            self.game_model, ui_flags.dev_ui_webserver, self
        )

        self.setGeometry(300, 100, 270, 100)
        self.updateWindowTitle()
        self.setWindowIcon(QIcon("./resources/icon.png"))
        self.statusBar().showMessage("Ready")

        self.initUi(ui_flags)
        self.initActions()
        self.initToolbar()
        self.initMenuBar()
        self.connectSignals()

        # Default to maximized on the main display if we don't have any persistent
        # configuration.
        screen = QGuiApplication.primaryScreen().availableSize()
        self.setGeometry(0, 0, screen.width(), screen.height())
        self.setWindowState(Qt.WindowState.WindowMaximized)

        # But override it with the saved configuration if it exists.
        self._restore_window_geometry()

        if self.game is None:
            last_save_file = liberation_install.get_last_save_file()
            if last_save_file:
                logging.info("Loading last saved game : " + str(last_save_file))
                game = persistency.load_game(last_save_file)
                game = self.migrate_game(game, last_save_file)
                self.onGameGenerated(game)
                self.updateWindowTitle(last_save_file if game else None)
            else:
                logging.info("No existing save game")
        else:
            self.onGameGenerated(self.game)

    def _open_drop_zone_at(self, lat: float, lng: float) -> None:
        """Open the logistics window and immediately show the drop zone dialog
        pre-filled with the map coordinates from the right-click."""
        if self._logistics_window is None or not self._logistics_window.isVisible():
            self._logistics_window = QLogisticsWindow(self.game)
        self._logistics_window.show()
        self._logistics_window.raise_()
        self._logistics_window.open_add_drop_zone_at(lat, lng)

    def initUi(self, ui_flags: UiFlags) -> None:
        hbox = QSplitter(Qt.Orientation.Horizontal)
        vbox = QSplitter(Qt.Orientation.Vertical)
        hbox.addWidget(self.ato_panel)
        hbox.addWidget(vbox)
        vbox.addWidget(self.liberation_map)
        vbox.addWidget(self.info_panel)

        # Will make the ATO sidebar as small as necessary to fit the content. In
        # practice this means it is sized by the hints in the panel.
        hbox.setSizes([1, 10000000])
        vbox.setSizes([600, 100])

        self.top_panel = QTopPanel(self.game_model, self.sim_controller, ui_flags)
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(self.top_panel)
        vbox.addWidget(hbox)

        central_widget = QWidget()
        central_widget.setLayout(vbox)
        self.setCentralWidget(central_widget)

    def connectSignals(self):
        GameUpdateSignal.get_instance().gameupdated.connect(self.setGame)
        GameUpdateSignal.get_instance().debriefingReceived.connect(self.onDebriefing)
        GameUpdateSignal.get_instance().game_state_changed.connect(self.onEndGame)

    def initActions(self):
        self.newGameAction = QAction("&New Game", self)
        self.newGameAction.setIcon(QIcon(CONST.ICONS["New"]))
        self.newGameAction.triggered.connect(self.newGame)
        self.newGameAction.setShortcut("CTRL+N")

        self.openAction = QAction("&Open", self)
        self.openAction.setIcon(QIcon(CONST.ICONS["Open"]))
        self.openAction.triggered.connect(self.openFile)
        self.openAction.setShortcut("CTRL+O")

        self.saveGameAction = QAction("&Save", self)
        self.saveGameAction.setIcon(QIcon(CONST.ICONS["Save"]))
        self.saveGameAction.triggered.connect(self.saveGame)
        self.saveGameAction.setShortcut("CTRL+S")

        self.saveAsAction = QAction("Save &As", self)
        self.saveAsAction.setIcon(QIcon(CONST.ICONS["Save"]))
        self.saveAsAction.triggered.connect(self.saveGameAs)
        self.saveAsAction.setShortcut("CTRL+A")

        self.showAboutDialogAction = QAction("&About DCS Retribution", self)
        self.showAboutDialogAction.setIcon(QIcon.fromTheme("help-about"))
        self.showAboutDialogAction.triggered.connect(self.showAboutDialog)

        self.showLiberationPrefDialogAction =
