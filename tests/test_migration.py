"""Collapse of the old integration's per-zone devices and players."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiocontrol_director.const import DOMAIN

UID = "audiocontrol_1"
# zone code -> (zone device name, area, old entity object ID, registry name)
ZONES = {
    "Z1": ("Music room", "music_room", "music_room_amp_1", "music room amp 1"),
    "Z2": ("music room", "music_room", "music_room_amp_2", "music room amp 2"),
    "Z3": ("music room sub", "music_room", "music_room_amp_sub", "music room amp sub"),
    "Z4": ("sauna", "pool", "sauna_amp", "sauna amp"),
    "Z5": ("Gym", "gym", "gym_amp", "gym amp"),
    "Z6": ("great room", "great_room", "great_room_amp_1", "great room amp 1"),
    "Z7": ("great room", "great_room", "great_room_amp_2", "great room amp 2"),
    "Z8": ("great room sub", "great_room", "great_room_amp_sub", "great room amp sub"),
    "DXOa": ("Digital Out A", "av_closet", "digital_out_a", None),
    "DXOb": ("Digital Out B", "av_closet", "digital_out_b", None),
}


def _legacy(hass: HomeAssistant) -> MockConfigEntry:
    """What the old integration left in the registries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=UID,
        unique_id=UID,
        data={"host": "127.0.0.1", "unique_id": UID, "name": UID},
    )
    entry.add_to_hass(hass)
    area_reg = ar.async_get(hass)
    for area in ("music_room", "pool", "gym", "great_room", "av_closet"):
        area_reg.async_create(area)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    amp = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, UID)}, name="Distributed Amp 1"
    )
    dev_reg.async_update_device(amp.id, area_id="av_closet")
    ent_reg.async_get_or_create(
        "media_player",
        DOMAIN,
        UID,
        config_entry=entry,
        device_id=amp.id,
        suggested_object_id="distributed_amp_1",
    )
    for code, (name, area, object_id, reg_name) in ZONES.items():
        unique_id = f"{UID}_output_{code}"
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, unique_id)},
            name=name,
            via_device_id=amp.id,
        )
        dev_reg.async_update_device(device.id, area_id=area)
        ent = ent_reg.async_get_or_create(
            "media_player",
            DOMAIN,
            unique_id,
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=object_id,
        )
        ent_reg.async_update_entity(ent.entity_id, name=reg_name)
    # A stale device from an old layout, with no entities.
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{UID}_output_9")},
        name="Digital Out",
    )
    ent_reg.async_update_entity("media_player.great_room_amp_2", labels={"music"})
    ent_reg.async_update_entity_options(
        "media_player.music_room_amp_1", "conversation", {"should_expose": False}
    )
    return entry


async def test_collapse(hass: HomeAssistant, amp1) -> None:
    entry = _legacy(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.title == "Distributed Amp 1"
    dev_reg = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    assert [d.name for d in devices] == ["Distributed Amp 1"]
    assert devices[0].area_id == "av_closet"
    amp_id = devices[0].id

    ent_reg = er.async_get(hass)
    # Groups replace their zones' players, in their area and named after them.
    music = ent_reg.async_get("media_player.music_room_amp")
    assert music.unique_id == f"{UID}_group_1"
    assert (music.name, music.area_id, music.device_id) == ("music room amp", "music_room", amp_id)
    great = ent_reg.async_get("media_player.great_room_amp")
    assert (great.name, great.area_id, great.labels) == ("great room amp", "great_room", {"music"})
    for gone in (
        "media_player.music_room_amp_1",
        "media_player.music_room_amp_sub",
        "media_player.great_room_amp_2",
        "media_player.distributed_amp_1",
    ):
        assert ent_reg.async_get(gone) is None, gone
    assert hass.states.get("media_player.music_room_amp").state == "on"
    assert music.options["conversation"] == {"should_expose": False}

    # Ungrouped zones keep their entity, name and (now entity-level) area.
    sauna = ent_reg.async_get("media_player.sauna_amp")
    assert (sauna.name, sauna.area_id, sauna.device_id) == ("sauna amp", "pool", amp_id)
    assert hass.states.get("media_player.sauna_amp").attributes["friendly_name"] == "sauna amp"
    assert ent_reg.async_get("media_player.digital_out_a").area_id == "av_closet"
    assert hass.states.get("media_player.digital_out_b").attributes["source"] == "Digital In B"

    # A second start changes nothing.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ent_reg.async_get("media_player.music_room_amp").unique_id == f"{UID}_group_1"
    assert ent_reg.async_get("media_player.music_room_amp_2") is None
    assert len(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)) == 1


async def test_zone_devices_without_players(hass: HomeAssistant, amp5) -> None:
    """Amp 5's old entry had zone devices but its players were never created."""
    uid = "audiocontrol_5"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=uid,
        unique_id=uid,
        data={"host": "127.0.0.1", "unique_id": uid, "name": uid},
    )
    entry.add_to_hass(hass)
    area_reg = ar.async_get(hass)
    dev_reg = dr.async_get(hass)
    for area in ("spa_patio", "balcony", "master_patio"):
        area_reg.async_create(area)
    amp = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, uid)}, name="Distributed Amp 5"
    )
    for code, name, area in (
        ("Z1", "patio amp", "spa_patio"),
        ("Z2", "patio amp sub", "spa_patio"),
        ("Z3", "deck amp", "balcony"),
        ("Z4", "master porch amp", "master_patio"),
    ):
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{uid}_output_{code}")},
            name=name.removesuffix(" amp"),
            via_device_id=amp.id,
        )
        dev_reg.async_update_device(device.id, area_id=area, name_by_user=name)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    for entity_id, unique_id, name, area in (
        ("media_player.patio_amp", f"{uid}_group_1", "patio amp", "spa_patio"),
        ("media_player.deck_amp", f"{uid}_output_Z3", "deck amp", "balcony"),
        ("media_player.master_porch_amp", f"{uid}_output_Z4", "master porch amp", "master_patio"),
    ):
        reg = ent_reg.async_get(entity_id)
        assert (reg.unique_id, reg.name, reg.area_id) == (unique_id, name, area), entity_id
        assert hass.states.get(entity_id).state == "on"
    assert len(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)) == 1


async def test_bad_reply_prunes_nothing(hass: HomeAssistant, amp1) -> None:
    """A stalled status reply at setup doesn't lose anyone's players."""
    amp1.row_pause = 0.06
    entry = _legacy(hass)
    with patch("custom_components.audiocontrol_director.director.REPLY_TIMEOUT", 5):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    ent_reg = er.async_get(hass)
    for entity_id in (
        "media_player.sauna_amp",
        "media_player.gym_amp",
        "media_player.digital_out_a",
    ):
        assert ent_reg.async_get(entity_id), entity_id
    assert ent_reg.async_get("media_player.great_room_amp")
