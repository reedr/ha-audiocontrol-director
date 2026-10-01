"""Registry clean-up: one device per amplifier, players per group.

The old integration made a device per zone and a player per zone. Here every
entity belongs to the amplifier's device, and zones in a group share one
player. Each setup:

* records, per output, what the user set up: the old player's entity ID, name,
  area, labels and voice exposure, or, when the old player is missing, the zone
  device's name and area;
* moves entities off other devices of the entry onto the amplifier's (keeping
  the zone device's area) and removes those devices;
* removes grouped zones' players, then creates each missing group player named
  after its first zone's (``music_room_amp_1`` -> ``media_player.music_room_amp``),
  and missing ungrouped zone players named after their zone device;
* after the platforms are set up, removes entities made obsolete by a change of
  groups (and the old amplifier player). Nothing else is ever removed, so a bad
  reply can't cost entity IDs or settings.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import CONF_LEGACY_UNIQUE_ID, DOMAIN
from .coordinator import DirectorConfigEntry, DirectorCoordinator
from .entity import amp_device_info

_LOGGER = logging.getLogger(__name__)

_MEMBER_ID_SUFFIX = re.compile(r"_(?:\d+|sub(?:_\d+)?)$")
_MEMBER_NAME_SUFFIX = re.compile(r" (?:\d+|sub(?: \d+)?)$", re.IGNORECASE)
_EXPOSURE_KEYS = ("conversation", "cloud.alexa", "cloud.google_assistant")


@dataclass
class _Legacy:
    """What the user had set up for one output."""

    object_id: str
    name: str | None
    area_id: str | None
    labels: set[str] = field(default_factory=set)
    options: dict[str, Any] = field(default_factory=dict)


def _player_uid(base: str, code: str) -> str:
    return f"{base}_output_{code}"


@callback
def async_prepare_registry(
    hass: HomeAssistant, entry: DirectorConfigEntry, coord: DirectorCoordinator
) -> None:
    """Collapse zone devices and seed players (see module docstring)."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    base = coord.base_id
    status = coord.data
    amp = dev_reg.async_get_or_create(config_entry_id=entry.entry_id, **amp_device_info(coord))
    legacy: dict[str, _Legacy] = {}

    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if device.id == amp.id:
            continue
        for entity in er.async_entries_for_device(
            ent_reg, device.id, include_disabled_entities=True
        ):
            if entity.config_entry_id == entry.entry_id:
                ent_reg.async_update_entity(
                    entity.entity_id, device_id=amp.id, area_id=entity.area_id or device.area_id
                )
        # A zone device whose player never got created still holds its name and area.
        for domain, ident in device.identifiers:
            code = ident.removeprefix(f"{base}_output_")
            if domain == DOMAIN and code != ident and code in status.outputs:
                name = device.name_by_user or device.name
                if name and not ent_reg.async_get_entity_id(
                    Platform.MEDIA_PLAYER, DOMAIN, _player_uid(base, code)
                ):
                    legacy[code] = _Legacy(slugify(name), name, device.area_id)
        _LOGGER.info("Removing per-zone device %s; its entities are on %s", device.name, amp.name)
        dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)

    for code in status.outputs:
        entity_id = ent_reg.async_get_entity_id(
            Platform.MEDIA_PLAYER, DOMAIN, _player_uid(base, code)
        )
        if entity_id and (reg := ent_reg.async_get(entity_id)):
            legacy[code] = _Legacy(
                entity_id.split(".", 1)[1],
                reg.name,
                reg.area_id,
                set(reg.labels),
                {k: dict(v) for k, v in reg.options.items() if k in _EXPOSURE_KEYS},
            )

    groups = status.groups()
    # Grouped zones' players go first, so a group can take over their entity IDs.
    for zones in groups.values():
        for zone in zones:
            if entity_id := ent_reg.async_get_entity_id(
                Platform.MEDIA_PLAYER, DOMAIN, _player_uid(base, zone.code)
            ):
                _LOGGER.info("Removing %s: %s is now in a group", entity_id, zone.name)
                ent_reg.async_remove(entity_id)

    for group, zones in groups.items():
        members = [legacy[z.code] for z in zones if z.code in legacy]
        if members:
            first = members[0]
            _seed(
                ent_reg,
                entry,
                amp.id,
                f"{base}_group_{group}",
                _Legacy(
                    _MEMBER_ID_SUFFIX.sub("", first.object_id),
                    _MEMBER_NAME_SUFFIX.sub("", first.name) if first.name else None,
                    first.area_id,
                    set().union(*(m.labels for m in members)),
                    first.options,
                ),
            )
    for code, out in status.outputs.items():
        if not out.group and code in legacy:
            _seed(ent_reg, entry, amp.id, _player_uid(base, code), legacy[code])

    if entry.title == entry.data.get(CONF_LEGACY_UNIQUE_ID) and status.name:
        hass.config_entries.async_update_entry(entry, title=status.name)


def _seed(
    ent_reg: er.EntityRegistry,
    entry: DirectorConfigEntry,
    device_id: str,
    unique_id: str,
    info: _Legacy,
) -> None:
    """Create a player's registry entry with the user's ID, name, area and exposure."""
    if ent_reg.async_get_entity_id(Platform.MEDIA_PLAYER, DOMAIN, unique_id):
        return
    created = ent_reg.async_get_or_create(
        Platform.MEDIA_PLAYER,
        DOMAIN,
        unique_id,
        config_entry=entry,
        device_id=device_id,
        suggested_object_id=info.object_id,
    )
    ent_reg.async_update_entity(
        created.entity_id, name=info.name, area_id=info.area_id, labels=info.labels
    )
    for key, options in info.options.items():
        ent_reg.async_update_entity_options(created.entity_id, key, options)
    _LOGGER.info("Created %s for %s", created.entity_id, unique_id)


@callback
def async_prune_entities(
    hass: HomeAssistant, entry: DirectorConfigEntry, coord: DirectorCoordinator
) -> None:
    """Remove entities made obsolete by group changes, and the old amplifier player."""
    ent_reg = er.async_get(hass)
    base = coord.base_id
    status = coord.data
    groups = status.groups()
    obsolete = {(Platform.MEDIA_PLAYER, base)}
    for code, out in status.outputs.items():
        if out.group:
            obsolete.add((Platform.MEDIA_PLAYER, _player_uid(base, code)))
        elif not out.is_digital:
            obsolete.add((Platform.NUMBER, f"{base}_{code}_volume"))
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        group = entity.unique_id.removeprefix(f"{base}_group_")
        stale_group = (
            entity.domain == Platform.MEDIA_PLAYER
            and group != entity.unique_id
            and group.isdigit()
            and int(group) not in groups
        )
        if stale_group or (entity.domain, entity.unique_id) in obsolete:
            _LOGGER.info("Removing %s, which %s no longer has", entity.entity_id, entry.title)
            ent_reg.async_remove(entity.entity_id)
