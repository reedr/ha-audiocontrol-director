"""Config, discovery, reconfigure and options flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiocontrol_director.const import DOMAIN

DHCP = DhcpServiceInfo(ip="127.0.0.1", hostname="director", macaddress="441441aabbcc")
MAC = "44:14:41:aa:bb:cc"


async def test_user(hass: HomeAssistant, amp1) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": " 127.0.0.1 "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Distributed Amp 1"
    assert result["data"] == {"host": "127.0.0.1"}

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1"}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_user_cannot_connect(hass: HomeAssistant, amp1) -> None:
    amp1.silent = True
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_dhcp_new(hass: HomeAssistant, amp5) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP
    )
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"]["name"] == "Distributed Amp 5"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MAC
    assert result["data"] == {"host": "127.0.0.1", "mac": MAC}


async def test_dhcp_known_host_learns_mac(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="audiocontrol_1",
        data={"host": "127.0.0.1", "unique_id": "audiocontrol_1", "name": "audiocontrol_1"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP
    )
    assert result["reason"] == "already_configured"
    assert entry.data["mac"] == MAC

    # Later the amplifier moves; the entry follows its MAC.
    moved = DhcpServiceInfo(ip="10.0.0.9", hostname="director", macaddress="441441aabbcc")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=moved
    )
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "10.0.0.9"


async def test_reconfigure(hass: HomeAssistant, amp1) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "10.9.9.9"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "127.0.0.1"


async def test_options_need_loaded_entry(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "127.0.0.1"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["reason"] == "not_loaded"
