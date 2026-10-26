"""Config flow for Voltdeer RS073."""

from __future__ import annotations

import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
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

# Stable identifier taken from the mDNS instance name: only the serial part,
# e.g. "ShellyPro3EM-SMS62R0878._http._tcp.local." -> "sms62r0878".
CONF_DEVICE_ID = "device_id"
NEW_METER = "new"


class InvalidResponse(Exception):
    """The host answered, but not like a Voltdeer RS073."""


def _clean_host(raw: str) -> str:
    """Strip scheme, path and whitespace from a user-entered host."""
    host = raw.strip().rstrip("/")
    if host.startswith("http://"):
        host = host[7:]
    elif host.startswith("https://"):
        host = host[8:]
    return host.split("/", 1)[0]


def _device_id_from_discovery(info: ZeroconfServiceInfo) -> str | None:
    """Return only the serial part of the mDNS name.

    "ShellyPro3EM-SMS62R0878._http._tcp.local." -> "sms62r0878"
    """
    name = (info.name or "").split("._", 1)[0].strip()
    serial = name.rsplit("-", 1)[-1].strip()
    return serial.lower() or None


async def _async_fetch(hass: HomeAssistant, host: str) -> dict:
    """Fetch and validate the meter's root JSON."""
    session = async_get_clientsession(hass)
    async with session.get(f"http://{host}/", timeout=10) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    if not isinstance(data, dict) or not isinstance(data.get("em:0"), dict):
        raise InvalidResponse
    return data


class VoltdeerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the meter by its local IP address or hostname."""

    VERSION = 1

    _host: str | None = None
    _device_id: str | None = None

    @staticmethod
    def async_get_options_flow(config_entry):
        """Create the options flow for this config entry."""
        return VoltdeerOptionsFlow()

    def _update_entry(self, entry, **changes) -> None:
        """Update an entry's data and reload it if anything changed."""
        new_data = {**entry.data, **changes}
        if new_data != dict(entry.data):
            self.hass.config_entries.async_update_entry(entry, data=new_data)
            self.hass.config_entries.async_schedule_reload(entry.entry_id)

    # ------------------------------------------------------------------ zeroconf
    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        """Handle an HTTP service discovered through mDNS."""
        host = str(discovery_info.ip_address)
        device_id = _device_id_from_discovery(discovery_info)
        entries = self._async_current_entries()

        # 1. Known device (same mDNS name): just follow it to its new IP.
        if device_id:
            for entry in entries:
                if entry.data.get(CONF_DEVICE_ID) == device_id:
                    self._update_entry(entry, **{CONF_HOST: host})
                    return self.async_abort(reason="already_configured")

        # 2. Older entry already pointing at this IP: remember its device id.
        for entry in entries:
            if entry.data.get(CONF_HOST, "").lower() == host.lower():
                if device_id and not entry.data.get(CONF_DEVICE_ID):
                    self._update_entry(entry, **{CONF_DEVICE_ID: device_id})
                return self.async_abort(reason="already_configured")

        # 3. Something new: make sure it really is a Voltdeer RS073.
        try:
            await _async_fetch(self.hass, host)
        except InvalidResponse:
            return self.async_abort(reason="not_supported")
        except (ClientError, TimeoutError, ValueError):
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(device_id or host.lower())
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._host = host
        self._device_id = device_id
        self.context["title_placeholders"] = {"name": f"Voltdeer RS073 ({host})"}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input=None):
        """Confirm a discovered meter, or attach it to an existing entry."""
        # Entries created before device ids existed: offer to adopt this meter.
        legacy = {
            entry.entry_id: entry.title
            for entry in self._async_current_entries()
            if not entry.data.get(CONF_DEVICE_ID)
        }

        if user_input is not None:
            target = user_input.get("target", NEW_METER) if legacy else NEW_METER
            if target != NEW_METER:
                entry = self.hass.config_entries.async_get_entry(target)
                if entry is not None:
                    changes = {CONF_HOST: self._host}
                    if self._device_id:
                        changes[CONF_DEVICE_ID] = self._device_id
                    self._update_entry(entry, **changes)
                    return self.async_abort(reason="reconfigure_successful")

            data = {CONF_HOST: self._host}
            if self._device_id:
                data[CONF_DEVICE_ID] = self._device_id
            return self.async_create_entry(
                title=f"Voltdeer RS073 ({self._host})", data=data
            )

        placeholders = {"host": self._host or ""}
        if legacy:
            options = {NEW_METER: "Add as a new meter", **legacy}
            return self.async_show_form(
                step_id="discovery_confirm",
                data_schema=vol.Schema(
                    {vol.Required("target", default=NEW_METER): vol.In(options)}
                ),
                description_placeholders=placeholders,
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm", description_placeholders=placeholders
        )

    # ---------------------------------------------------------------------- user
    async def async_step_user(self, user_input=None):
        """Ask for the host and verify its root status endpoint."""
        errors = {}
        if user_input is not None:
            host = _clean_host(user_input[CONF_HOST])
            if not host:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(host.lower())
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                try:
                    await _async_fetch(self.hass, host)
                except InvalidResponse:
                    errors["base"] = "invalid_response"
                except (ClientError, TimeoutError, ValueError):
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=f"Voltdeer RS073 ({host})",
                        data={CONF_HOST: host},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    # --------------------------------------------------------------- reconfigure
    async def async_step_reconfigure(self, user_input=None):
        """Change the meter's IP/hostname without touching entities or history."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            host = _clean_host(user_input[CONF_HOST])
            if not host:
                errors["base"] = "cannot_connect"
            else:
                try:
                    await _async_fetch(self.hass, host)
                except InvalidResponse:
                    errors["base"] = "invalid_response"
                except (ClientError, TimeoutError, ValueError):
                    errors["base"] = "cannot_connect"
                else:
                    # unique_id is intentionally unchanged: entities and
                    # history stay attached to this entry.
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_HOST: host}
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str}
            ),
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