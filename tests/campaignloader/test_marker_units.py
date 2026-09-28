"""Unit types the campaign loader recognises (game/campaignloader/markerunits.py)."""

from __future__ import annotations

from dcs.vehicles import AirDefence, Armor, MissilesSS, Unarmed

from game.campaignloader.markerunits import (
    role_for_group,
    role_for_type,
    warship_types,
)
from game.campaignloader.mizcampaignloader import MizCampaignLoader

SKIP = frozenset(
    {
        MizCampaignLoader.FRONT_LINE_UNIT_TYPE,
        MizCampaignLoader.CP_CONVOY_SPAWN_TYPE,
        MizCampaignLoader.FOB_UNIT_TYPE,
        MizCampaignLoader.INVISIBLE_FOB_UNIT_TYPE,
        MizCampaignLoader.NEUTRAL_FOB_UNIT_TYPE,
    }
)


def test_the_old_markers_still_work() -> None:
    assert role_for_type(AirDefence.Patriot_ln.id) == "long_range_sams"
    assert role_for_type(AirDefence.Hawk_ln.id) == "medium_range_sams"
    assert role_for_type(AirDefence.M1097_Avenger.id) == "short_range_sams"
    assert role_for_type(AirDefence.ZSU_23_4_Shilka.id) == "aaa"
    assert role_for_type(AirDefence.x_1L13_EWR.id) == "ewrs"
    assert role_for_type(MissilesSS.Scud_B.id) == "missile_sites"
    assert role_for_type(MissilesSS.hy_launcher.id) == "coastal_defenses"
    assert role_for_type(Armor.M_1_Abrams.id) == "armor_groups"


def test_every_part_of_a_sam_site_is_recognised() -> None:
    long_range = [
        AirDefence.S_300PS_64H6E_sr.id,
        AirDefence.S_300PS_40B6M_tr.id,
        AirDefence.Patriot_str.id,
    ]
    medium_range = [
        AirDefence.SA_11_Buk_SR_9S18M1.id,
        AirDefence.Kub_1S91_str.id,
        AirDefence.snr_s_125_tr.id,
        AirDefence.NASAMS_Radar_MPQ64F1.id,
    ]
    short_range = [
        AirDefence.Tor_9A331.id,
        AirDefence.Osa_9A33_ln.id,
        AirDefence.Roland_ADS.id,
    ]
    assert {role_for_type(t) for t in long_range} == {"long_range_sams"}
    assert {role_for_type(t) for t in medium_range} == {"medium_range_sams"}
    assert {role_for_type(t) for t in short_range} == {"short_range_sams"}
    assert role_for_type(AirDefence.Gepard.id) == "aaa"
    assert role_for_type(AirDefence.FPS_117.id) == "ewrs"


def test_mod_sams_by_name() -> None:
    assert role_for_type("S-300PMU2 5P85SE2 ln") == "long_range_sams"
    assert role_for_type("SA-17 Buk M1-2 LN 9A310M1-2") == "medium_range_sams"


def test_any_tank_ifv_or_apc_is_armour() -> None:
    for vehicle in (Armor.T_72B3, Armor.BMP_2, Armor.M_2_Bradley):
        assert role_for_type(vehicle.id) == "armor_groups"
    assert role_for_type(Unarmed.Ural_375.id) is None


def test_group_led_by_a_truck_takes_the_highest_role_inside() -> None:
    group = [Unarmed.Ural_375.id, AirDefence.SA_11_Buk_LN_9A310M1.id, Armor.BMP_2.id]
    assert role_for_group(group, SKIP) == "medium_range_sams"


def test_first_unit_decides_when_recognised() -> None:
    # An armour group with a Shilka escort stays armour.
    group = [Armor.T_72B3.id, AirDefence.ZSU_23_4_Shilka.id]
    assert role_for_group(group, SKIP) == "armor_groups"


def test_campaign_markers_are_never_matched() -> None:
    # The M113 front-line marker is an APC, but it marks the front line.
    assert role_for_group([MizCampaignLoader.FRONT_LINE_UNIT_TYPE], SKIP) is None
    assert role_for_group([MizCampaignLoader.CP_CONVOY_SPAWN_TYPE], SKIP) is None


def test_warships_are_ships_but_carriers_are_not() -> None:
    ships = warship_types()
    assert "USS_Arleigh_Burke_IIa" in ships
    assert "Stennis" not in ships and "LHA_Tarawa" not in ships
