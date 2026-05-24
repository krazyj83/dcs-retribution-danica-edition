from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import dcs.lua
from dcs import Mission, Point
from dcs.coalition import Coalition
from dcs.countries import country_dict
from dcs.point import MovingPoint
from dcs.task import OptReactOnThreat
from dcs.terrain import Airport
from dcs.unit import Static

from game.atcdata import AtcData
from game.ato.flighttype import FlightType
from game.dcs.beacons import Beacons
from game.dcs.helpers import unit_type_from_name
from game.missiongenerator.aircraft.aircraftgenerator import (
    AircraftGenerator,
)
from game.missiongenerator.logisticsmissiongenerator import (
    LogisticsMissionGenerator,
)
from game.naming import namegen
from game.radio.radios import RadioFrequency, RadioRegistry, MHz
from game.radio.tacan import TacanRegistry
from game.theater import Airfield
from game.theater.bullseye import Bullseye
from game.unitmap import UnitMap
from .briefinggenerator import BriefingGenerator, MissionInfoGenerator
from .cargoshipgenerator import CargoShipGenerator
from .convoygenerator import ConvoyGenerator
from .drawingsgenerator import DrawingsGenerator
from .environmentgenerator import EnvironmentGenerator
from .flotgenerator import FlotGenerator
from .forcedoptionsgenerator import ForcedOptionsGenerator
from .frontlineconflictdescription import FrontLineConflictDescription
from .kneeboard import KneeboardGenerator
from .luagenerator import LuaGenerator
from .missiondata import MissionData
from .playerconvoygenerator import PlayerConvoyGenerator
from .rebelliongenerator import RebellionGenerator
from .tgogenerator import TgoGenerator
from .triggergenerator import TriggerGenerator
from .visualsgenerator import VisualsGenerator
from ..radio.TacanContainer import TacanContainer
from ..radio.datalink import DataLinkRegistry

if TYPE_CHECKING:
    from game import Game


class MissionGenerator:
    def __init__(self, game: Game, time: datetime) -> None:
        self.game = game
        self.time = time
        self.mission = Mission(game.theater.terrain)
        self.unit_map = UnitMap()

        self.mission_data = MissionData()

        self.radio_registry = RadioRegistry()
        self.tacan_registry = TacanRegistry()
        self.datalink_registry = DataLinkRegistry()

        self.generation_started = False

        self.p_country = country_dict[self.game.blue.faction.country.id]()
        self.e_country = country_dict[self.game.red.faction.country.id]()

        with open("resources/default_options.lua", "r", encoding="utf-8") as f:
            options = dcs.lua.loads(f.read())["options"]
            ext_view = game.settings.external_views_allowed
            options["miscellaneous"]["f11_free_camera"] = ext_view
            options["miscellaneous"]["f5_nearest_ac"] = ext_view
            options["difficulty"]["spectatorExternalViews"] = ext_view
            sc_deck_crew = game.settings.supercarrier_deck_crew
            options["plugins"]["Supercarrier"]["deck_crew"] = sc_deck_crew
            self.mission.options.load_from_dict(options)

    def generate_miz(self, output: Path) -> UnitMap:
        if self.generation_started:
            raise RuntimeError(
                "Mission has already begun generating. To reset, create a new "
                "MissionSimulation."
            )
        self.generation_started = True

        self.setup_mission_coalitions()
        self.add_airfields_to_unit_map()
        self.initialize_registries()

        auto_fog = self.game.settings.use_auto_fog
        EnvironmentGenerator(
            self.mission, self.game.conditions, self.time, auto_fog
        ).generate()

        tgo_generator = TgoGenerator(
            self.mission,
            self.game,
            self.radio_registry,
            self.tacan_registry,
            self.unit_map,
            self.mission_data,
        )
        tgo_generator.generate()

        ConvoyGenerator(self.mission, self.game, self.unit_map).generate()
        CargoShipGenerator(self.mission, self.game, self.unit_map).generate()
        PlayerConvoyGenerator(self.mission, self.game).generate()

        self.generate_destroyed_units()

        # Generate ground conflicts first so the JTACs get the first laser code (1688)
        # rather than the first player flight with a TGP.
        self.generate_ground_conflicts()
        self.generate_air_units(tgo_generator)

        # ----------------------------------------------------------------
        # Logistics hook — inject drop zone trigger zones and generate
        # logistics flight groups for any IN_FLIGHT transfers.
        # Must run AFTER generate_air_units so the airspace is set up,
        # and BEFORE the Lua/trigger generators so the zones exist when
        # scripts reference them.
        # ----------------------------------------------------------------
        self.generate_logistics(tgo_generator)

        RebellionGenerator(self.mission, self.game).generate()
        TriggerGenerator(self.mission, self.game).generate()
        ForcedOptionsGenerator(self.mission, self.game).generate()
        VisualsGenerator(self.mission, self.game).generate()
        LuaGenerator(self.game, self.mission, self.mission_data).generate()
        DrawingsGenerator(self.mission, self.game).generate()

        self.setup_combined_arms()

        self.notify_info_generators()

        namegen.reset_numbers()
        self.generate_warehouses()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.mission.save(output)

        return self.unit_map

    def generate_logistics(self, tgo_generator: TgoGenerator) -> None:
        """
        Inject logistics content into the mission:
          1. Drop zone trigger zones (orange = troop, blue = cargo)
          2. LOGISTICS flight groups for IN_FLIGHT transfers planned
             via the ATO logistics mission type

        This is safe to call even if game.logistics does not exist —
        the check is inside LogisticsManager.inject_into_mission().
        """
        if not hasattr(self.game, "logistics"):
            return

        try:
            # Inject drop zone trigger zones into the .miz
            self.game.logistics.inject_into_mission(self.mission)
            logging.info("MissionGenerator: logistics drop zones injected")
        except Exception:
            logging.exception(
                "MissionGenerator: logistics drop zone injection failed — "
                "continuing mission generation without drop zones"
            )

        # Generate LOGISTICS flight groups from the blue ATO
        self._generate_logistics_flights()

    def _generate_logistics_flights(self) -> None:
        """
        Find all LOGISTICS-typed flights in the blue ATO and generate
        their pydcs flight groups via LogisticsMissionGenerator.

        Concept — why we handle this separately from generate_air_units():
          The AircraftGenerator handles all standard flight types through
          its generate_flights() dispatch. LOGISTICS flights are special
          because they need to read from game.logistics to get transfer
          details, and they need the drop zone trigger zones to already
          exist in the mission (which inject_into_mission() just created).
          Separating this into its own pass keeps the AircraftGenerator
          clean and avoids coupling it to the logistics module.
        """
        logistics_flights_generated = 0
        logistics_flights_skipped   = 0

        for package in self.game.blue.ato.packages:
            for flight in package.flights:
                if flight.flight_type is not FlightType.LOGISTICS:
                    continue

                transfer_id = getattr(flight, "transfer_id", None)
                if not transfer_id:
                    logging.warning(
                        "MissionGenerator: LOGISTICS flight in package '%s' "
                        "has no transfer_id — skipped. "
                        "Was schedule_transfer() called when planning?",
                        package.target.name if package.target else "unknown",
                    )
                    logistics_flights_skipped += 1
                    continue

                try:
                    gen = LogisticsMissionGenerator(
                        flight, self.game, self.mission
                    )
                    success = gen.generate()
                    if success:
                        logistics_flights_generated += 1
                        logging.info(
                            "MissionGenerator: LOGISTICS flight generated "
                            "(transfer %s)", transfer_id[:8],
                        )
                    else:
                        logistics_flights_skipped += 1
                except Exception:
                    logging.exception(
                        "MissionGenerator: LOGISTICS flight generation failed "
