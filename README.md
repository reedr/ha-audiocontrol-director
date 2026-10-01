# AudioControl Director

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration for **AudioControl Director** matrix amplifiers (M-series, 4- and
8-zone models). It uses the amplifier's telnet control protocol on port 23 and keeps one session
open per amplifier. It has no Python dependencies. Status is polled every 5 s and again straight
after each command.

## Setup

Amplifiers are discovered by their MAC address (AudioControl's `44:14:41` prefix) when Home
Assistant sees them on the network. You can also add one by IP address under
**Settings → Devices & services → Add integration → AudioControl Director**. Each amplifier is
one config entry and one device.

## Entities

| Entity | What it does |
|---|---|
| `media_player` per group | One player per zone group (GRP1–8), controlled with group commands: power, volume, mute, source. Named after the group's first zone. |
| `media_player` per ungrouped zone | Power, volume, mute, source. |
| `media_player` per digital output | Digital Out A/B: source (and power and volume, as the amplifier allows). |
| `number` *Zone* volume | Volume of each zone in a group, for balancing a group's zones (e.g. a subwoofer zone). |
| `number` *Zone* bass / treble | −10 to +10. Disabled by default. |
| `select` *Zone* EQ | Recalls EQ preset 1–6. Shows nothing while a zone has unsaved EQ changes. Disabled by default. |
| `switch` *Zone* signal sense | Turns a zone on automatically when its input has a signal. |
| `switch` *Zone* loudness | Disabled by default. Read once a minute, since each zone needs its own query. |
| `sensor` Temperature, Line voltage | Amplifier-wide readings. Diagnostic. |
| `sensor` *Zone* temperature | Output-stage temperature per zone. Disabled by default. |
| `binary_sensor` Protection, Overheating, Line voltage, Short circuit | On when the amplifier reports anything other than Normal. Attributes give its own wording and the zones involved. |
| `binary_sensor` *Zone* overheating | On when a zone's temperature status isn't Normal (e.g. `OverTemp`). |
| `button` All zones on / off | `allZon` / `allZoff`. |
| `button` Power on / Standby | Global power. Disabled by default; the amplifier doesn't report its power state. |

When two zones share a name, the zone number is added to their entity names (`music room 2`).

If groups are changed on the amplifier's web page, the entry reloads by itself: grouped zones'
players are removed, and new group players appear.

## Input names

**Configure** on the entry lets you name the inputs (e.g. `Channel 1-2` → `Sonos Kitchen`).
Players show these names in their source lists. `select_source` also accepts the amplifier's
own name (`Channel 1-2`, `Digital In B`) or the protocol code (`MX1`, `DXb`). Players report the
current input's code as the `source_id` attribute and its amplifier name as `source_input`, so
automations don't have to depend on display names:

```yaml
condition: state
entity_id: media_player.great_room_amp
attribute: source_id
state: DXb
```

## Upgrading from audiocontrol-director-hass

Entries made by the old integration keep working: same domain, same config entry, same
entity IDs for ungrouped zones and digital outputs. On first start:

* The per-zone devices are removed. Their entities move to the amplifier's device and keep the
  zone device's area.
* Zones in a group lose their players. One group player replaces them, named after the first
  zone's old player without its suffix (`media_player.music_room_amp_1` →
  `media_player.music_room_amp`), in the same area.
* The unused amplifier player (`media_player.distributed_amp_N`) is removed.
* The entry is renamed after the amplifier.

Automations, scripts and dashboards that used the grouped zones' players need to point at the
group player.

## Credits

This integration is based on Philip Flesher's
[audiocontrol-director-hass](https://github.com/philipflesher/audiocontrol-director-hass) and
[audiocontrol-director-telnet-py](https://github.com/philipflesher/audiocontrol-director-telnet-py).
It has been rewritten, with the telnet client folded in.

## License

MIT. See [LICENSE](LICENSE).
