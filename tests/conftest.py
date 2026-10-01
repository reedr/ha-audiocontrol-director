"""Fixtures for AudioControl Director tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from .fake_director import FakeDirector

pytest_plugins = ("pytest_homeassistant_custom_component",)


@pytest.fixture(autouse=True)
def enable_integration(enable_custom_integrations):
    """Allow Home Assistant to load the custom integration under test."""


@pytest.fixture(autouse=True)
def fast_timing():
    """Shrink the client's timeouts."""
    module = "custom_components.audiocontrol_director.director"
    with (
        patch(f"{module}.REPLY_TIMEOUT", 0.5),
        patch(f"{module}.IDLE_AFTER_LINE", 0.03),
        patch(f"{module}.IDLE_NO_LINE", 0.1),
        patch(f"{module}.MIN_COMMAND_GAP", 0),
    ):
        yield


async def _serve(amp: str):
    server = FakeDirector(amp)
    await server.start()
    with patch("custom_components.audiocontrol_director.director.PORT", server.port):
        yield server
    await server.stop()


@pytest.fixture
async def amp1(socket_enabled):
    """An 8-zone amplifier with two groups (captured from Distributed Amp 1)."""
    async for server in _serve("amp98"):
        yield server


@pytest.fixture
async def amp5(socket_enabled):
    """A 4-zone amplifier with four digital inputs (Distributed Amp 5)."""
    async for server in _serve("amp102"):
        yield server
