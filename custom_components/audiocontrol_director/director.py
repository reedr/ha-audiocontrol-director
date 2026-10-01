"""Telnet client for AudioControl Director M-series matrix amplifiers.

Command and response formats follow AudioControl's "Director Series Comm,
Control and Query protocol". Every reply starts with an echo of the command
and a CR; errors come back as ``xx<command>xx``. Based on Philip Flesher's
audiocontrol-director-telnet-py, rewritten for the larger amplifiers and for a
single long-lived session.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field, replace

_LOGGER = logging.getLogger(__name__)

PORT = 23
CONNECT_TIMEOUT = 5.0
REPLY_TIMEOUT = 5.0
# A reply's body ends with CRLF; once one has arrived, a short silence means
# it is complete. AMP? has no terminator, so allow a longer silence for it.
IDLE_AFTER_LINE = 0.25
IDLE_NO_LINE = 0.4
# AudioControl recommends at most 20 commands a second.
MIN_COMMAND_GAP = 0.05

_IAC = 255


class DirectorError(Exception):
    """Base error."""


class DirectorConnectionError(DirectorError):
    """The amplifier could not be reached or stopped answering."""


class DirectorCommandError(DirectorError):
    """The amplifier answered ``xx<command>xx`` (unknown or invalid command)."""


def _strip_telnet(data: bytes) -> bytes:
    """Drop any telnet option negotiation; the amplifiers normally send none."""
    if _IAC not in data:
        return data
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == _IAC and i + 1 < len(data):
            cmd = data[i + 1]
            if cmd in (251, 252, 253, 254):  # WILL, WONT, DO, DONT + option
                i += 3
            elif cmd == 250:  # subnegotiation, up to IAC SE
                end = data.find(bytes([_IAC, 240]), i)
                i = end + 2 if end >= 0 else len(data)
            else:
                i += 2
            continue
        out.append(data[i])
        i += 1
    return bytes(out)


# ─── parsed status ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Source:
    """An input: ``MX<n>`` (analog pair) or ``DX<a..d>`` (digital)."""

    code: str  # protocol name, e.g. MX3 or DXb
    name: str  # the amplifier's name, e.g. "Channel 5-6" or "Digital In B"


@dataclass(frozen=True)
class Output:
    """A zone (``Z<n>``) or digital output (``DXO<a|b>``) from SYSTEMstat?."""

    code: str
    number: int  # position in the status table
    name: str
    is_on: bool
    source: str | None  # Source.code
    volume: int
    bass: int
    treble: int
    eq_name: str
    eq_preset: int | None  # 1-6, None for "unsaved values"
    group: int  # 0 = not grouped
    temperature: int | None
    temperature_status: str | None
    signal_sense: bool

    @property
    def is_digital(self) -> bool:
        """Whether this is a digital (unamplified) output."""
        return self.code.startswith("DXO")


@dataclass(frozen=True)
class Status:
    """One poll of an amplifier."""

    name: str
    temperature: int | None
    temperature_status: str | None
    voltage: int | None
    voltage_status: str | None
    protection: str
    thermal_protection: str
    zone_protect: str
    ip_address: str | None
    outputs: dict[str, Output] = field(default_factory=dict)  # by code
    shorts: tuple[bool, ...] = ()
    loudness: dict[str, bool] = field(default_factory=dict)  # by zone code

    @property
    def zones(self) -> list[Output]:
        """Amplified zones, in order."""
        return [o for o in self.outputs.values() if not o.is_digital]

    @property
    def digital_outputs(self) -> list[Output]:
        """Digital outputs, in order."""
        return [o for o in self.outputs.values() if o.is_digital]

    def groups(self) -> dict[int, list[Output]]:
        """Zones by group number (grouped zones only)."""
        out: dict[int, list[Output]] = {}
        for zone in self.zones:
            if zone.group:
                out.setdefault(zone.group, []).append(zone)
        return out


def parse_inputs(body: str) -> list[Source]:
    """Parse INPUT?: ``Channel 1-2: 1 2 3`` ... ``Digital In A: 9`` ... ``Pink noise:``.

    Analog pairs are MX1.. in order, digital inputs DXa.. in order. Pink noise
    is a test signal, not a source.
    """
    sources: list[Source] = []
    analog = digital = 0
    for line in body.splitlines():
        name = line.split(":", 1)[0].strip()
        if name.startswith("Channel "):
            analog += 1
            sources.append(Source(f"MX{analog}", name))
        elif name.startswith("Digital In "):
            digital += 1
            sources.append(Source(f"DX{chr(ord('a') + digital - 1)}", name))
    return sources


def _status_source(raw: str, analog_count: int) -> str | None:
    """``MX5 & 5`` in SYSTEMstat? numbers analog pairs first, then digital inputs."""
    match = re.match(r"MX(\d+)", raw.strip())
    if not match:
        return None
    index = int(match.group(1))
    if index <= analog_count:
        return f"MX{index}"
    return f"DX{chr(ord('a') + index - analog_count - 1)}"


def _int(text: str) -> int | None:
    match = re.search(r"-?\d+", text)
    return int(match.group()) if match else None


def _value_and_status(text: str) -> tuple[int | None, str | None]:
    """``124 F & Normal`` / ``124 & Normal`` / ``131 F/Normal``."""
    value = _int(text)
    parts = re.split(r"[&/]", text, maxsplit=1)
    status = parts[1].strip() if len(parts) > 1 else None
    return value, status or None


def parse_status(body: str, analog_count: int) -> Status:
    """Parse SYSTEMstat?."""
    header: dict[str, str] = {}
    outputs: dict[str, Output] = {}
    digital = 0
    in_table = False
    for line in body.splitlines():
        if not line.strip():
            continue
        if line.startswith("ZONES,"):
            in_table = True
            continue
        if not in_table:
            key, _, value = line.partition(":")
            header[key.strip().upper()] = value.strip()
            continue
        fields = [f.strip() for f in line.split(",")]
        if len(fields) < 11:
            continue
        name = fields[0]
        number = _int(fields[1]) or 0
        if name.lower().startswith("digital out"):
            digital += 1
            code = f"DXO{chr(ord('a') + digital - 1)}"
        else:
            code = f"Z{number}"
        eq_name, _, eq_index = fields[7].rpartition(" and ")
        eq_idx = _int(eq_index)
        temp, temp_status = _value_and_status(fields[9])
        outputs[code] = Output(
            code=code,
            number=number,
            name=name,
            is_on=fields[2].lower() == "on",
            source=_status_source(fields[3], analog_count),
            volume=_int(fields[4]) or 0,
            bass=_int(fields[5]) or 0,
            treble=_int(fields[6]) or 0,
            eq_name=eq_name or fields[7],
            eq_preset=eq_idx + 1 if eq_idx is not None and eq_idx >= 0 else None,
            group=_int(fields[8]) or 0,
            temperature=temp if temp else None,
            temperature_status=temp_status,
            signal_sense=fields[10].lower() == "on",
        )
    temp, temp_status = _value_and_status(header.get("GLOBAL TEMP", ""))
    volt, volt_status = _value_and_status(header.get("GLOBAL VOLTAGE", ""))
    return Status(
        name=header.get("AMPLIFIER NAME", ""),
        temperature=temp,
        temperature_status=temp_status,
        voltage=volt,
        voltage_status=volt_status,
        protection=header.get("GLOBAL PROTECTION", ""),
        thermal_protection=header.get("THERMAL PROTECTION", ""),
        zone_protect=header.get("ZONE OUTPUT PROTECT", ""),
        ip_address=header.get("IP ADDRESS") or None,
        outputs=outputs,
    )


def parse_shorts(body: str) -> tuple[bool, ...]:
    """SHORT?: ``0 0 0 1`` (one flag per zone)."""
    return tuple(part == "1" for part in body.split())


# ─── client ───────────────────────────────────────────────────────────────────


class Director:
    """One amplifier over a single telnet session, one command at a time."""

    def __init__(self, host: str, port: int | None = None) -> None:
        """Set up the client; nothing connects until the first command."""
        self.host = host
        self._port = PORT if port is None else port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._last_command = 0.0
        self._closed = False
        self.sources: list[Source] = []

    @property
    def analog_count(self) -> int:
        """Number of analog input pairs."""
        return sum(1 for s in self.sources if s.code.startswith("MX"))

    async def _connect(self) -> None:
        if self._closed:
            raise DirectorConnectionError(f"{self.host}: client closed")
        if self._writer is not None:
            assert self._reader is not None
            if not self._writer.is_closing() and not self._reader.at_eof():
                return
            await self._drop()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self._port), CONNECT_TIMEOUT
            )
        except (OSError, TimeoutError) as err:
            self._reader = self._writer = None
            raise DirectorConnectionError(f"cannot connect to {self.host}: {err!r}") from err

    async def _drop(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            except (OSError, TimeoutError):
                pass

    async def close(self) -> None:
        """Close the session; the client can't be used afterwards."""
        self._closed = True
        async with self._lock:
            await self._drop()

    async def _read_reply(self, command: str) -> str:
        assert self._reader is not None
        buf = b""
        deadline = time.monotonic() + REPLY_TIMEOUT
        while True:
            echoed = f"{command}\r".encode() in buf
            idle = IDLE_AFTER_LINE if echoed and b"\n" in buf else IDLE_NO_LINE
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                chunk = await asyncio.wait_for(self._reader.read(4096), min(idle, remaining))
            except TimeoutError:
                if echoed:
                    break
                continue
            if not chunk:
                raise DirectorConnectionError(f"{self.host} closed the connection")
            buf += _strip_telnet(chunk)
        text = buf.decode("ascii", errors="replace")
        echo = f"{command}\r"
        if echo not in text:
            raise DirectorConnectionError(f"{self.host} did not answer {command!r}")
        body = text.split(echo, 1)[1]
        if body.strip() == f"xx{command}xx":
            raise DirectorCommandError(f"{self.host} rejected {command!r}")
        return body

    async def request(self, command: str) -> str:
        """Send a command or query and return the reply body (after the echo).

        The amplifier ends idle sessions after a while; a reused connection that
        turns out to be dead is replaced and the command sent once more.
        """
        async with self._lock:
            reused = self._writer is not None
            try:
                return await self._send(command)
            except DirectorConnectionError:
                if not reused or self._closed:
                    raise
                _LOGGER.debug("%s: session dropped, reconnecting", self.host)
                return await self._send(command)

    async def _send(self, command: str) -> str:
        gap = MIN_COMMAND_GAP - (time.monotonic() - self._last_command)
        if gap > 0:
            await asyncio.sleep(gap)
        await self._connect()
        assert self._writer is not None
        _LOGGER.debug("%s -> %s", self.host, command)
        try:
            self._writer.write(command.encode("ascii") + b"\r")
            await self._writer.drain()
            body = await self._read_reply(command)
        except DirectorCommandError:
            raise
        except (OSError, DirectorConnectionError) as err:
            await self._drop()
            if isinstance(err, DirectorConnectionError):
                raise
            raise DirectorConnectionError(f"{self.host}: {err!r}") from err
        finally:
            self._last_command = time.monotonic()
        _LOGGER.debug("%s <- %r", self.host, body)
        return body

    # ─── queries ──

    async def async_get_name(self) -> str:
        """The amplifier's name (AMP?)."""
        return (await self.request("AMP?")).strip()

    async def async_get_sources(self) -> list[Source]:
        """Inputs from INPUT?, kept for decoding SYSTEMstat?."""
        self.sources = parse_inputs(await self.request("INPUT?"))
        return self.sources

    async def async_get_status(self, *, loudness: bool = False) -> Status:
        """SYSTEMstat? plus SHORT?, and per-zone loudness when asked."""
        if not self.sources:
            await self.async_get_sources()
        status = parse_status(await self.request("SYSTEMstat?"), self.analog_count)
        try:
            shorts = parse_shorts(await self.request("SHORT?"))
        except DirectorCommandError:
            shorts = ()
        louds: dict[str, bool] = {}
        if loudness:
            for zone in status.zones:
                try:
                    reply = await self.request(f"{zone.code}loudness?")
                except DirectorCommandError:
                    continue
                louds[zone.code] = reply.strip().lower() in ("on", "1")
        return replace(status, shorts=shorts, loudness=louds)

    # ─── commands ──
    # `target` is a zone (Z3), a group (GRP2) or a digital output (DXOa).

    async def async_set_power(self, target: str, on: bool) -> None:
        """Turn a zone, group or digital output on or off."""
        await self.request(f"{target}{'on' if on else 'off'}")

    async def async_set_source(self, target: str, source: str) -> None:
        """Route an input (MXn / DXa) to a zone, group or digital output."""
        await self.request(f"{target}source{source}")

    async def async_set_volume(self, target: str, volume: int) -> None:
        """Set volume 0-100."""
        await self.request(f"{target}setvol{max(0, min(100, int(volume)))}")

    async def async_set_bass(self, zone: str, value: int) -> None:
        """Set bass -10..10."""
        await self.request(f"{zone}setbass{max(-10, min(10, int(value)))}")

    async def async_set_treble(self, zone: str, value: int) -> None:
        """Set treble -10..10."""
        await self.request(f"{zone}settreble{max(-10, min(10, int(value)))}")

    async def async_set_eq(self, zone: str, preset: int) -> None:
        """Recall EQ preset 1-6."""
        await self.request(f"{zone}eq{max(1, min(6, int(preset)))}")

    async def async_set_loudness(self, zone: str, on: bool) -> None:
        """Turn loudness on or off."""
        await self.request(f"{zone}loudness{1 if on else 0}")

    async def async_set_signal_sense(self, zone: str, on: bool) -> None:
        """Turn signal sense (auto-on with signal) on or off."""
        await self.request(f"{zone}signalsense{1 if on else 0}")

    async def async_amp_power(self, on: bool) -> None:
        """Global power (power1 / power0)."""
        await self.request(f"power{1 if on else 0}")

    async def async_all_zones(self, on: bool) -> None:
        """All zones and digital outputs on or off (allZon / allZoff)."""
        await self.request("allZon" if on else "allZoff")
