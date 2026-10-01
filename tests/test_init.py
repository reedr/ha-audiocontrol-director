"""Setup, entities and control."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.media_player import ATTR_INPUT_SOURCE, ATTR_MEDIA_VOLUME_LEVEL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.audiocontrol_director.const import CONF_SOURCE_NAMES, DOMAIN


async def _setup(hass: HomeAssistant, **kwargs) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Distributed Amp 1", data={"host": "127.0.0.1"}, **kwargs
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_entities(hass: HomeAssistant, amp1) -> None:
    entry = await _setup(hass, unique_id="44:14:41:00:00:01")
    ent_reg = er.async_get(hass)
    players = sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        if e.domain == "media_player"
    )
    assert players == [
        "media_player.distributed_amp_1_digital_out_a",
        "media_player.distributed_amp_1_digital_out_b",
        "media_player.distributed_amp_1_great_room",
        "media_player.distributed_amp_1_gym",
        "media_player.distributed_amp_1_music_room",
        "media_player.distributed_amp_1_sauna",
    ]
    assert ent_reg.async_get("media_player.distributed_amp_1_music_room").unique_id == (
        "44:14:41:00:00:01_group_1"
    )
    assert ent_reg.async_get("media_player.distributed_amp_1_sauna").unique_id == (
        "44:14:41:00:00:01_output_Z4"
    )
    state = hass.states.get("media_player.distributed_amp_1_music_room")
    assert state.state == "on"
    assert state.attributes[ATTR_INPUT_SOURCE] == "Channel 1-2"
    assert state.attributes["source_id"] == "MX1"
    assert state.attributes[ATTR_MEDIA_VOLUME_LEVEL] == 1.0
    assert state.attributes["zones"] == ["Z1 Music room", "Z2 music room", "Z3 music room sub"]
    assert len(state.attributes["source_list"]) == 10
    assert (
        hass.states.get("media_player.distributed_amp_1_digital_out_a").attributes[
            ATTR_INPUT_SOURCE
        ]
        == "Digital In A"
    )

    # 124 °F, shown in the test instance's metric units.
    assert float(hass.states.get("sensor.distributed_amp_1_temperature").state) == pytest.approx(
        51.1, abs=0.1
    )
    assert hass.states.get("sensor.distributed_amp_1_line_voltage").state == "124"
    assert hass.states.get("binary_sensor.distributed_amp_1_protection").state == "off"
    assert hass.states.get("binary_sensor.distributed_amp_1_overheating").state == "off"
    assert hass.states.get("binary_sensor.distributed_amp_1_short_circuit").state == "off"
    assert hass.states.get("binary_sensor.distributed_amp_1_gym_overheating").state == "off"
    assert hass.states.get("switch.distributed_amp_1_gym_signal_sense").state == "off"
    # Grouped zones get their own volume; ungrouped ones use the player.
    assert hass.states.get("number.distributed_amp_1_music_room_sub_volume").state == "100"
    assert ent_reg.async_get_entity_id("number", DOMAIN, "44:14:41:00:00:01_Z4_volume") is None
    # Disabled by default.
    for entity_id in (
        "sensor.distributed_amp_1_gym_temperature",
        "switch.distributed_amp_1_gym_loudness",
        "number.distributed_amp_1_gym_bass",
        "select.distributed_amp_1_gym_eq",
        "button.distributed_amp_1_standby",
    ):
        assert ent_reg.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "Distributed Amp 1"


async def test_control(hass: HomeAssistant, amp1) -> None:
    await _setup(hass)
    group = "media_player.distributed_amp_1_great_room"

    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": group, ATTR_MEDIA_VOLUME_LEVEL: 0.42},
        blocking=True,
    )
    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": group, ATTR_INPUT_SOURCE: "Digital In B"},
        blocking=True,
    )
    await hass.services.async_call(
        "media_player",
        "turn_off",
        {"entity_id": "media_player.distributed_amp_1_gym"},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.distributed_amp_1_great_room_sub_volume", "value": 60},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.distributed_amp_1_gym_signal_sense"},
        blocking=True,
    )
    assert amp1.commands[-5:] == [
        "GRP2setvol42",
        "GRP2sourceDXb",
        "Z5off",
        "Z8setvol60",
        "Z5signalsense1",
    ]
    await _poll(hass)
    state = hass.states.get(group)
    assert state.attributes[ATTR_INPUT_SOURCE] == "Digital In B"
    assert state.attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.42
    assert hass.states.get("number.distributed_amp_1_great_room_sub_volume").state == "60"
    assert hass.states.get("media_player.distributed_amp_1_gym").state == "off"
    assert hass.states.get("switch.distributed_amp_1_gym_signal_sense").state == "on"

    # Mute is volume 0; unmute restores the volume.
    for mute in (True, False):
        await hass.services.async_call(
            "media_player",
            "volume_mute",
            {"entity_id": group, "is_volume_muted": mute},
            blocking=True,
        )
        await _poll(hass)
    assert amp1.commands.count("GRP2setvol0") == 1
    assert hass.states.get(group).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.42

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "media_player",
            "select_source",
            {"entity_id": group, ATTR_INPUT_SOURCE: "Nope"},
            blocking=True,
        )


async def test_source_names(hass: HomeAssistant, amp1) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "Channel 1-2" in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"Channel 1-2": "Sonos Music Room", "Digital In B": " Theater "}
    )
    assert entry.options[CONF_SOURCE_NAMES] == {"MX1": "Sonos Music Room", "DXb": "Theater"}
    await hass.async_block_till_done()

    player = "media_player.distributed_amp_1_music_room"
    state = hass.states.get(player)
    assert state.attributes[ATTR_INPUT_SOURCE] == "Sonos Music Room"
    assert "Theater" in state.attributes["source_list"]
    assert "Digital In B" not in state.attributes["source_list"]
    # Display name, amplifier name and code all select an input.
    for source, code in (("Theater", "DXb"), ("Channel 5-6", "MX3"), ("MX2", "MX2")):
        await hass.services.async_call(
            "media_player",
            "select_source",
            {"entity_id": player, ATTR_INPUT_SOURCE: source},
            blocking=True,
        )
        assert amp1.commands[-1] == f"GRP1source{code}"


async def test_regroup_reloads(hass: HomeAssistant, amp1) -> None:
    entry = await _setup(hass)
    ent_reg = er.async_get(hass)
    assert hass.states.get("media_player.distributed_amp_1_gym")
    # Gym joins the music room group on the amplifier's web page.
    amp1.outputs[4]["group"] = 1
    await _poll(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert ent_reg.async_get("media_player.distributed_amp_1_gym")
    await _poll(hass)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert ent_reg.async_get("media_player.distributed_amp_1_gym") is None
    assert hass.states.get("number.distributed_amp_1_gym_volume").state == "100"
    assert (
        "Z5 Gym" in hass.states.get("media_player.distributed_amp_1_music_room").attributes["zones"]
    )


async def test_unavailable_and_retry(hass: HomeAssistant, amp1) -> None:
    await _setup(hass)
    amp1.silent = True
    await _poll(hass)
    assert hass.states.get("media_player.distributed_amp_1_gym").state == "unavailable"
    amp1.silent = False
    await _poll(hass)
    assert hass.states.get("media_player.distributed_amp_1_gym").state == "on"


async def test_not_ready(hass: HomeAssistant, amp1) -> None:
    amp1.silent = True
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "127.0.0.1"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_amp5(hass: HomeAssistant, amp5) -> None:
    await _setup(hass)
    state = hass.states.get("media_player.distributed_amp_5_patio")
    assert state.attributes["zones"] == ["Z1 patio", "Z2 patio sub"]
    assert state.attributes["source_list"][-4:] == [
        "Digital In A",
        "Digital In B",
        "Digital In C",
        "Digital In D",
    ]
    assert (
        hass.states.get("media_player.distributed_amp_5_digital_out_b").attributes["source_id"]
        == "DXb"
    )
    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": "media_player.distributed_amp_5_balcony", ATTR_INPUT_SOURCE: "Digital In C"},
        blocking=True,
    )
    await _poll(hass)
    state = hass.states.get("media_player.distributed_amp_5_balcony")
    assert state.attributes["source_id"] == "DXc"
