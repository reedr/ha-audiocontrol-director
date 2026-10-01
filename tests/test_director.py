"""The telnet client and its parsers."""

from __future__ import annotations

import pytest

from custom_components.audiocontrol_director.director import (
    Director,
    DirectorCommandError,
    DirectorConnectionError,
    parse_inputs,
    parse_status,
)

from .fake_director import FIXTURES


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_amp1() -> None:
    sources = parse_inputs(_load("amp98_INPUT.txt"))
    assert [s.code for s in sources] == [*(f"MX{i}" for i in range(1, 9)), "DXa", "DXb"]
    assert sources[8].name == "Digital In A"
    status = parse_status(_load("amp98_SYSTEMstat.txt"), 8)
    assert status.name == "Distributed Amp 1"
    assert (status.temperature, status.temperature_status) == (124, "Normal")
    assert (status.voltage, status.voltage_status) == (124, "Normal")
    assert status.ip_address == "10.0.1.98"
    assert list(status.outputs) == [*(f"Z{i}" for i in range(1, 9)), "DXOa", "DXOb"]
    z1 = status.outputs["Z1"]
    assert (z1.name, z1.is_on, z1.source, z1.volume, z1.group) == (
        "Music room",
        True,
        "MX1",
        100,
        1,
    )
    assert (z1.eq_name, z1.eq_preset, z1.temperature) == ("Acoustic", 1, 131)
    assert status.outputs["Z4"].eq_preset is None
    # MX9/MX10 in the status table are the digital inputs.
    assert status.outputs["DXOa"].source == "DXa"
    assert status.outputs["DXOb"].source == "DXb"
    assert status.outputs["DXOa"].temperature is None
    assert {g: [z.code for z in zs] for g, zs in status.groups().items()} == {
        1: ["Z1", "Z2", "Z3"],
        2: ["Z6", "Z7", "Z8"],
    }


def test_parse_amp5() -> None:
    sources = parse_inputs(_load("amp102_INPUT.txt"))
    assert [s.code for s in sources] == ["MX1", "MX2", "MX3", "MX4", "DXa", "DXb", "DXc", "DXd"]
    status = parse_status(_load("amp102_SYSTEMstat.txt"), 4)
    assert [z.code for z in status.zones] == ["Z1", "Z2", "Z3", "Z4"]
    assert [o.code for o in status.digital_outputs] == ["DXOa", "DXOb"]
    assert status.outputs["DXOa"].number == 5
    assert status.outputs["DXOb"].source == "DXb"


async def test_session(amp1) -> None:
    director = Director("127.0.0.1")
    try:
        assert await director.async_get_name() == "Distributed Amp 1"
        status = await director.async_get_status(loudness=True)
        assert status.shorts == (False,) * 8
        assert status.loudness == {f"Z{i}": False for i in range(1, 9)}

        await director.async_set_source("GRP1", "DXb")
        await director.async_set_volume("Z4", 140)
        status = await director.async_get_status()
        assert [status.outputs[z].source for z in ("Z1", "Z2", "Z3")] == ["DXb"] * 3
        assert status.outputs["Z4"].volume == 100
        assert "Z4setvol100" in amp1.commands

        with pytest.raises(DirectorCommandError):
            await director.request("bogus")

        # The amplifier ends the session; the next command reconnects.
        amp1.drop_sessions()
        assert await director.async_get_name() == "Distributed Amp 1"
    finally:
        await director.close()


async def test_paused_table(amp1, monkeypatch) -> None:
    """A stall between rows longer than the idle window doesn't cut the table short."""
    monkeypatch.setattr("custom_components.audiocontrol_director.director.REPLY_TIMEOUT", 5)
    amp1.row_pause = 0.06
    director = Director("127.0.0.1")
    try:
        status = await director.async_get_status()
        assert len(status.outputs) == 10
        # The session is still in step afterwards.
        assert await director.async_get_name() == "Distributed Amp 1"
    finally:
        await director.close()


async def test_no_answer(amp1) -> None:
    amp1.silent = True
    director = Director("127.0.0.1")
    with pytest.raises(DirectorConnectionError):
        await director.async_get_name()
    await director.close()
