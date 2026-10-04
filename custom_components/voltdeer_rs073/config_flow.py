"""Config flow for Voltdeer RS073."""

from __future__ import annotations

import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_EXCLUDED_SENSORS,
    CONF_INCLUDE_DIAGNOSTICS,
    CONF_INCLUDE_MEASUREMENTS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


class VoltdeerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the meter by its local IP address or hostname."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Create the options flow for this config entry."""
        return VoltdeerOptionsFlow()

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        """Handle an HTTP service discovered through mDNS."""
        host = str(discovery_info.ip_address)
        await self.async_set_unique_id(host.lower())
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": "Voltdeer RS073"}

        try:
            session = async_get_clientsession(self.hass)
            async with session.get(f"http://{host}/", timeout=10) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError):
            return self.async_abort(reason="cannot_connect")

        if not isinstance(data, dict) or not isinstance(data.get("em:0"), dict):
            return self.async_abort(reason="not_supported")

        return self.async_create_entry(
            title=f"Voltdeer RS073 ({host})",
            data={CONF_HOST: host},
        )

    async def async_step_user(self, user_input=None):
        """Ask for the host and verify its root status endpoint."""
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().rstrip("/")
            if host.startswith("http://"):
                host = host[7:]
            elif host.startswith("https://"):
                host = host[8:]
            host = host.split("/", 1)[0]

            if not host:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(host.lower())
                self._abort_if_unique_id_configured()
                try:
                    session = async_get_clientsession(self.hass)
                    async with session.get(f"http://{host}/", timeout=10) as response:
                        response.raise_for_status()
                        data = await response.json(content_type=None)
                    if not isinstance(data, dict) or not isinstance(data.get("em:0"), dict):
                        errors["base"] = "invalid_response"
                except (ClientError, TimeoutError, ValueError):
                    errors["base"] = "cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title=f"Voltdeer RS073 ({host})",
                    data={CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )


class VoltdeerOptionsFlow(OptionsFlowWithReload):
    """Configure the meter polling interval."""

    async def async_step_init(self, user_input=None):
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=3600)), 
                vol.Required(
                    CONF_INCLUDE_MEASUREMENTS,
                    default=options.get(CONF_INCLUDE_MEASUREMENTS, True),
                ): bool,
                vol.Required(
                    CONF_INCLUDE_DIAGNOSTICS,
                    default=options.get(CONF_INCLUDE_DIAGNOSTICS, True),
                ): bool,
                vol.Optional(
                    CONF_EXCLUDED_SENSORS,
                    default=options.get(CONF_EXCLUDED_SENSORS, ""),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
