from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QInputDialog

from game.server.settings import ServerSettings
from qt_ui.liberation_install import server_port
from qt_ui.models import GameModel

#: Disk cache for downloaded map tiles.
MAX_CACHE_BYTES = 100 * 1024 * 1024


class LoggingWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line_number: int,
        source: str,
    ) -> None:
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logging.error(message)
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
            logging.warning(message)
        else:
            logging.info(message)

    def javaScriptPrompt(self, *args):  # type: ignore[no-untyped-def]
        """Handle window.prompt() calls from the map JavaScript."""
        message = args[1] if len(args) > 1 else "Input"
        default_value = args[2] if len(args) > 2 else ""
        result = args[3] if len(args) > 3 else None
        text, ok = QInputDialog.getText(
            None,
            "Input",
            message,
            text=default_value,
        )
        if ok:
            if result is not None:
                result.append(text)
                return True
            return True, text
        if result is not None:
            return False
        return False, ""


def map_profile_dir() -> Path:
    """Where the map keeps its tile cache and saved layer choices."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "DCSRetribution" / "map_web_profile"
    return Path.home() / ".config" / "DCSRetribution" / "map_web_profile"


class QLiberationMap(QWebEngineView):
    def __init__(self, game_model: GameModel, dev: bool, parent) -> None:
        super().__init__(parent)
        self.game_model = game_model
        self.setMinimumSize(800, 600)

        # A named, on-disk profile: map tiles are cached between sessions and the
        # map's localStorage (chosen base map and overlays) persists.
        storage_dir = map_profile_dir()
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = str(storage_dir.resolve())
        self.profile = QWebEngineProfile("LiberationMapProfile", self)
        self.profile.setPersistentStoragePath(storage_path)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self.profile.setHttpCacheMaximumSize(MAX_CACHE_BYTES)
        self.profile.setCachePath(storage_path)

        self.page_instance: LoggingWebPage | None = LoggingWebPage(self.profile, self)

        # The page must go before its profile does, or Qt warns about a profile
        # released while a page still uses it.
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._cleanup)
        self.destroyed.connect(self._cleanup)

        settings = self.page_instance.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        # Required to allow "cross-origin" access from file:// scoped canvas.html to the
        # localhost HTTP backend.
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

        if dev:
            url = QUrl("http://localhost:3000")
        else:
            url = QUrl.fromLocalFile(str(Path("client/build/index.html").resolve()))

        server_settings = ServerSettings.get(server_port())
        host = server_settings.server_bind_address
        if host.startswith("::"):
            host = f"[{host}]"
        port = server_settings.server_port
        url.setQuery(f"server={host}:{port}")

        self.page_instance.load(url)
        self.setPage(self.page_instance)

    def _cleanup(self) -> None:
        """Detach and delete the page before the profile is torn down."""
        if getattr(self, "page_instance", None) is not None:
            self.setPage(None)  # type: ignore[arg-type]
            assert self.page_instance is not None
            self.page_instance.deleteLater()
            self.page_instance = None
