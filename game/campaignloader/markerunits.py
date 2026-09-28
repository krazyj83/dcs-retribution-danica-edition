"""Unit types the campaign loader recognises when reading a campaign .miz.

A vehicle or ship group placed in the campaign .miz becomes a ground object
(SAM site, EWR, armour group, ship...) according to its units:

1. A group-name prefix (SAM-LR-, EWR-, ...) always wins
   (MizCampaignLoader.NAME_PREFIX_ROUTES).
2. Otherwise the first unit's type decides, using the lists below.
3. If the first unit isn't in any list (e.g. a supply truck placed first),
   the highest-ranking role among the group's other units decides:
   long-range SAM > medium > short > AAA > EWR > missile > coastal > armour.
4. Anything else becomes a custom group (spawned as armour).

The lists cover every DCS air defence, missile and coastal unit (plus the
common mod SAMs by name prefix); armour and ships are every tank, IFV, APC,
ATGM, recon and artillery vehicle and every warship Retribution has unit data
for. Types used as campaign markers for other things (front line M113, convoy
spawn HMMWV, FOB trucks, carriers, shipping lanes) are never matched.

Add a type by adding its DCS type name to the right set.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Optional

#: Preset list names on ControlPoint.preset_locations, in rank order (step 3).
ROLE_ORDER = (
    "long_range_sams",
    "medium_range_sams",
    "short_range_sams",
    "aaa",
    "ewrs",
    "missile_sites",
    "coastal_defenses",
    "armor_groups",
)

LONG_RANGE_SAM_TYPES = frozenset(
    {
        # MIM-104 Patriot
        "Patriot ln",
        "Patriot str",
        "Patriot cp",
        "Patriot ECS",
        "Patriot AMG",
        "Patriot EPP",
        # S-300PS (SA-10)
        "S-300PS 5P85C ln",
        "S-300PS 5P85D ln",
        "S-300PS 40B6M tr",
        "S-300PS 40B6MD sr",
        "S-300PS 40B6MD sr_19J6",
        "S-300PS 64H6E sr",
        "S-300PS 54K6 cp",
        "S-300PS 5H63C 30H6_tr",
        # S-200 (SA-5)
        "S-200_Launcher",
        "RPC_5N62V",
        "RLS_19J6",
    }
)
#: Mod SAMs (High Digit SAMs, Currenthill...) recognised by name.
LONG_RANGE_SAM_PREFIXES = ("S-300", "S-400", "MIM104", "SA-10", "SA-12", "SA-20")

MEDIUM_RANGE_SAM_TYPES = frozenset(
    {
        # MIM-23 Hawk
        "Hawk ln",
        "Hawk sr",
        "Hawk tr",
        "Hawk pcp",
        "Hawk cwar",
        # S-75 (SA-2)
        "S_75M_Volhov",
        "SNR_75V",
        "RD_75",
        # S-125 (SA-3)
        "5p73 s-125 ln",
        "snr s-125 tr",
        "p-19 s-125 sr",
        "5p73 V-601P ln",
        # 2K12 Kub (SA-6)
        "Kub 2P25 ln",
        "Kub 1S91 str",
        # Buk (SA-11, SA-17)
        "SA-11 Buk LN 9A310M1",
        "SA-11 Buk SR 9S18M1",
        "SA-11 Buk CC 9S470M1",
        "polyana-d4m1 cp",
        # NASAMS
        "NASAMS_LN_B",
        "NASAMS_LN_C",
        "NASAMS_Radar_MPQ64F1",
        "NASAMS_Command_Post",
        # IRIS-T SLM (Currenthill)
        "CHAP_IRISTSLM_LN",
        "CHAP_IRISTSLM_STR",
        "CHAP_IRISTSLM_CP",
    }
)
MEDIUM_RANGE_SAM_PREFIXES = ("SA-17", "SA-2 ", "SA-3 ", "SA-6 ", "HQ-2")

SHORT_RANGE_SAM_TYPES = frozenset(
    {
        "M1097 Avenger",
        "M48 Chaparral",
        "M6 Linebacker",
        "rapier_fsa_launcher",
        "rapier_fsa_optical_tracker_unit",
        "rapier_fsa_blindfire_radar",
        "Roland ADS",
        "Roland Radar",
        "2S6 Tunguska",
        "Strela-1 9P31",
        "Strela-10M3",
        "Osa 9A33 ln",
        "SA-8 Osa LD 9T217",
        "Tor 9A331",
        "CHAP_TorM2",
        "CHAP_PantsirS1",
        "HQ-7_LN_SP",
        "HQ-7_LN_P",
        "HQ-7_STR_SP",
        # MANPADS teams
        "Soldier stinger",
        "Stinger comm",
        "Stinger comm dsr",
        "SA-18 Igla manpad",
        "SA-18 Igla comm",
        "SA-18 Igla-S manpad",
        "SA-18 Igla-S comm",
        "Igla manpad INS",
        "SA-24 Igla-S manpad",
        "SA-14 Strela-3 manpad",
    }
)
SHORT_RANGE_SAM_PREFIXES = ("SA-8", "SA-13", "SA-15", "SA-19", "SA-22")

AAA_TYPES = frozenset(
    {
        "flak18",
        "flak30",
        "flak36",
        "flak37",
        "flak38",
        "flak41",
        "bofors40",
        "Vulcan",
        "ZSU-23-4 Shilka",
        "ZSU_57_2",
        "ZU-23 Emplacement",
        "ZU-23 Emplacement Closed",
        "ZU-23 Insurgent",
        "ZU-23 Closed Insurgent",
        "HL_ZU-23",
        "tt_ZU-23",
        "Ural-375 ZU-23",
        "Ural-375 ZU-23 Insurgent",
        "Gepard",
        "KS-19",
        "S-60_Type59_Artillery",
        "M45_Quadmount",
        "M1_37mm",
        "QF_37_AA",
        "Type_3_80mm_AA",
        "Type_88_75mm_AA",
        "Type_94_25mm_AA_Truck",
        "Type_96_25mm_AA",
        "HEMTT_C-RAM_Phalanx",
        # WW2 flak battery parts
        "KDO_Mod40",
        "Allies_Director",
        "SON_9",
        "Flakscheinwerfer_37",
    }
)

EWR_TYPES = frozenset(
    {
        "1L13 EWR",
        "55G6 EWR",
        "FPS-117",
        "FPS-117 Dome",
        "FPS-117 ECS",
        "FuMG-401",
        "FuSe-65",
        "P14_SR",
        "Dog Ear radar",
    }
)

MISSILE_SITE_TYPES = frozenset(
    {"Scud_B", "CHAP_9K720_Cluster", "CHAP_9K720_HE", "v1_launcher"}
)

COASTAL_DEFENSE_TYPES = frozenset({"hy_launcher", "Silkworm_SR"})

#: Retribution unit classes that make an armour group.
ARMOR_CLASSES = ("Tank", "IFV", "APC", "ATGM", "Recon", "Artillery")
#: Retribution ship classes that make a ship group (not carriers or cargo).
WARSHIP_CLASSES = ("Destroyer", "Cruiser", "Frigate", "Boat", "Submarine")


def _match(type_id: str, types: frozenset[str], prefixes: tuple[str, ...]) -> bool:
    return type_id in types or type_id.startswith(prefixes)


@lru_cache(maxsize=1)
def armor_types() -> frozenset[str]:
    """DCS types of every tank, IFV, APC, ATGM, recon and artillery vehicle."""
    from game.dcs.groundunittype import GroundUnitType

    names = set()
    for dcs_type in GroundUnitType.each_dcs_type():
        for unit_type in GroundUnitType.for_dcs_type(dcs_type):
            if unit_type.unit_class.value in ARMOR_CLASSES:
                names.add(dcs_type.id)
    return frozenset(names)


@lru_cache(maxsize=1)
def warship_types() -> frozenset[str]:
    """DCS types of every warship Retribution has data for."""
    from game.dcs.shipunittype import ShipUnitType

    names = set()
    for dcs_type in ShipUnitType.each_dcs_type():
        for unit_type in ShipUnitType.for_dcs_type(dcs_type):
            if unit_type.unit_class.value in WARSHIP_CLASSES:
                names.add(dcs_type.id)
    return frozenset(names)


def role_for_type(type_id: str) -> Optional[str]:
    """The preset list a vehicle of this type makes, or None."""
    if _match(type_id, LONG_RANGE_SAM_TYPES, LONG_RANGE_SAM_PREFIXES):
        return "long_range_sams"
    if _match(type_id, MEDIUM_RANGE_SAM_TYPES, MEDIUM_RANGE_SAM_PREFIXES):
        return "medium_range_sams"
    if _match(type_id, SHORT_RANGE_SAM_TYPES, SHORT_RANGE_SAM_PREFIXES):
        return "short_range_sams"
    if type_id in AAA_TYPES:
        return "aaa"
    if type_id in EWR_TYPES:
        return "ewrs"
    if type_id in MISSILE_SITE_TYPES:
        return "missile_sites"
    if type_id in COASTAL_DEFENSE_TYPES:
        return "coastal_defenses"
    if type_id in armor_types():
        return "armor_groups"
    return None


def role_for_group(type_ids: Iterable[str], skip: frozenset[str]) -> Optional[str]:
    """The role of a vehicle group from its units' types (steps 2 and 3).

    ``skip`` are marker types that mean something else (front line, FOB...):
    a group starting with one is never matched.
    """
    ids = [t for t in type_ids]
    if not ids or ids[0] in skip:
        return None
    first = role_for_type(ids[0])
    if first is not None:
        return first
    roles = {role_for_type(t) for t in ids[1:] if t not in skip}
    for role in ROLE_ORDER:
        if role in roles:
            return role
    return None
