"""Fetch local status JSON from the Voltdeer RS073."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class VoltdeerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the meter's local web status page."""

    def __init__(
        self, hass: HomeAssistant, host: str, scan_interval: float = DEFAULT_SCAN_INTERVAL
    ) -> None:
        self.host = host
        self.session = async_get_clientsession(hass)
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """GET the device root and validate its meter data."""
        try:
            async with self.session.get(f"http://{self.host}/", timeout=10) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Error fetching Voltdeer RS073 data: {err}") from err

        if not isinstance(data, dict) or not isinstance(data.get("em:0"), dict):
            raise UpdateFailed("Response does not contain valid em:0 meter data")
        return data
