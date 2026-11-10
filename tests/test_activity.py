"""Zone signal sensors from the web page's operation status."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.audiocontrol_director.activity import PATH, parse_activity
from custom_components.audiocontrol_director.const import (
    CONF_SIGNAL_INTERVAL,
    DOMAIN,
    MAX_MISSED_POLLS,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "amp98_operation.json").read_text())
URL = f"http://127.0.0.1{PATH}"


def test_parse_activity() -> None:
    status = parse_activity(FIXTURE)
    assert list(status) == [f"Z{n}" for n in range(1, 9)]  # digital outputs left out
    assert status["Z5"] == "Active"
    assert status["Z1"] == "Off"
    with pytest.raises(ValueError):
        parse_activity({"outputZones": []})


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Distributed Amp 1", data={"host": "127.0.0.1"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll(hass: HomeAssistant, seconds: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_signal_sensors(hass: HomeAssistant, amp1, aioclient_mock) -> None:
    aioclient_mock.get(URL, json=FIXTURE)
    await _setup(hass)
    state = hass.states.get("binary_sensor.distributed_amp_1_gym_signal")
    assert state.state == "on"
    assert state.attributes["device_class"] == "sound"
    assert state.attributes["status"] == "Active"
    assert hass.states.get("binary_sensor.distributed_amp_1_sauna_signal").state == "off"
    assert hass.states.get("binary_sensor.distributed_amp_1_music_room_1_signal").state == "off"
    # Digital outputs always read Active, so they get no sensor.
    assert hass.states.get("binary_sensor.distributed_amp_1_digital_out_a_signal") is None

    # The zone goes idle.
    idle = json.loads(json.dumps(FIXTURE))
    for zone in idle["outputZones"]:
        if zone["zoneNumber"] == 5:
            zone["status"] = "Off"
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, json=idle)
    await _poll(hass, 11)
    assert hass.states.get("binary_sensor.distributed_amp_1_gym_signal").state == "off"


async def test_activity_failures(hass: HomeAssistant, amp1, aioclient_mock) -> None:
    aioclient_mock.get(URL, json=FIXTURE)
    await _setup(hass)
    entity = "binary_sensor.distributed_amp_1_gym_signal"
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, status=500)
    for n in range(MAX_MISSED_POLLS):
        await _poll(hass, 11 * (n + 1))
        assert hass.states.get(entity).state == "on"  # last reading kept
    await _poll(hass, 11 * (MAX_MISSED_POLLS + 1))
    assert hass.states.get(entity).state == "unavailable"
    assert hass.states.get("media_player.distributed_amp_1_gym").state == "on"


async def test_signal_interval_option(hass: HomeAssistant, amp1, aioclient_mock) -> None:
    aioclient_mock.get(URL, json=FIXTURE)
    entry = await _setup(hass)
    activity = entry.runtime_data.activity
    assert activity.update_interval == timedelta(seconds=10)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_SIGNAL_INTERVAL in result["data_schema"].schema
    await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SIGNAL_INTERVAL: 30})
    await hass.async_block_till_done()
    assert entry.options[CONF_SIGNAL_INTERVAL] == 30
    assert activity.update_interval == timedelta(seconds=30)
