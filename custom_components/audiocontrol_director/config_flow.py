"""Config flow for AudioControl Director."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import CONF_MAC, CONF_SOURCE_NAMES, DOMAIN
from .director import Director, DirectorError

_LOGGER = logging.getLogger(__name__)

HOST_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


async def probe(host: str) -> tuple[str | None, dict[str, str]]:
    """Connect and read the amplifier's name; return it or form errors."""
    director = Director(host)
    try:
        name = await director.async_get_name()
        await director.async_get_sources()
    except DirectorError as err:
        _LOGGER.warning("Could not reach an AudioControl amplifier at %s: %s", host, err)
        return None, {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected exception")
        return None, {"base": "unknown"}
    finally:
        await director.close()
    return name or f"AudioControl {host}", {}


class DirectorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AudioControl Director."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host: str | None = None
        self._mac: str | None = None
        self._name: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return DirectorOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the amplifier's address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            self._async_abort_entries_match({CONF_HOST: host})
            name, errors = await probe(host)
            if name is not None:
                return self.async_create_entry(title=name, data={CONF_HOST: host})

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(HOST_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """An amplifier (AudioControl MAC prefix) appeared on the network."""
        mac = format_mac(discovery_info.macaddress)
        host = discovery_info.ip
        for entry in self._async_current_entries(include_ignore=False):
            if mac in (entry.unique_id, entry.data.get(CONF_MAC)):
                if entry.data.get(CONF_HOST) != host:
                    _LOGGER.info("%s moved to %s", entry.title, host)
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_HOST: host}
                    )
                    if entry.state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_RETRY):
                        self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason="already_configured")
            if entry.data.get(CONF_HOST) == host and CONF_MAC not in entry.data:
                # Added by address (or by the old integration): remember the MAC
                # so an address change is followed.
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_MAC: mac}
                )
                return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        name, errors = await probe(host)
        if name is None:
            return self.async_abort(reason=errors["base"])
        self._host, self._mac, self._name = host, mac, name
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered amplifier."""
        assert self._host and self._name
        if user_input is not None:
            return self.async_create_entry(
                title=self._name, data={CONF_HOST: self._host, CONF_MAC: self._mac}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._name, "host": self._host},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the amplifier's address."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            _, errors = await probe(host)
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: host})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(HOST_SCHEMA, user_input or entry.data),
            errors=errors,
        )


class DirectorOptionsFlow(OptionsFlow):
    """Rename the inputs."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """One field per input, labelled with the amplifier's name for it."""
        entry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        sources = entry.runtime_data.sources
        current: dict[str, str] = entry.options.get(CONF_SOURCE_NAMES, {})

        if user_input is not None:
            names = {
                source.code: name
                for source in sources
                if (name := user_input.get(source.name, "").strip()) and name != source.name
            }
            return self.async_create_entry(data={**entry.options, CONF_SOURCE_NAMES: names})

        schema = vol.Schema(
            {
                vol.Optional(
                    source.name,
                    description={"suggested_value": current.get(source.code, "")},
                ): str
                for source in sources
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
