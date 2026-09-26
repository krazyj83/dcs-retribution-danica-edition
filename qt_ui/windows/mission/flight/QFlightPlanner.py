from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget

from game.ato.flight import Flight
from game.ato.flighttype import FlightType
from qt_ui.models import PackageModel, GameModel
from qt_ui.windows.mission.flight.payload.QFlightPayloadTab import QFlightPayloadTab
from qt_ui.windows.mission.flight.settings.QGeneralFlightSettingsTab import (
    QGeneralFlightSettingsTab,
)
from qt_ui.windows.mission.flight.waypoints.QFlightWaypointTab import QFlightWaypointTab


class QFlightPlanner(QTabWidget):
    squadron_changed = Signal(Flight)

    def __init__(self, package_model: PackageModel, flight: Flight, gm: GameModel):
        super().__init__()

        self.payload_tab = QFlightPayloadTab(flight, gm.game)

        self.waypoint_tab = QFlightWaypointTab(gm.game, package_model.package, flight)
        self.waypoint_tab.loadout_changed.connect(self.payload_tab.reload_from_flight)

        self.general_settings_tab = QGeneralFlightSettingsTab(
            gm,
            package_model,
            flight,
            self.waypoint_tab.flight_waypoint_list,
            self.payload_tab,
        )
        self.general_settings_tab.flight_size_changed.connect(
            self.payload_tab.resize_for_flight
        )
        self.general_settings_tab.squadron_changed.connect(self.squadron_changed)
        self.addTab(self.general_settings_tab, "General Flight settings")
        self.addTab(self.payload_tab, "Payload")
        self.addTab(self.waypoint_tab, "Waypoints")

        # LOGISTIC flights carry a warehouse transfer: plan the load here.
        if flight.flight_type is FlightType.LOGISTIC:
            from qt_ui.windows.mission.flight.cargo.QFlightCargoTab import (
                QFlightCargoTab,
            )

            self.cargo_tab = QFlightCargoTab(flight, gm.game)
            self.cargo_tab.fuel_changed.connect(
                lambda: self.payload_tab.fuel_selector.fuel.setValue(round(flight.fuel))
            )
            self.cargo_tab.route_changed.connect(
                self.waypoint_tab.flight_waypoint_list.update_list
            )
            self.addTab(self.cargo_tab, "Cargo")
        self.setCurrentIndex(0)
