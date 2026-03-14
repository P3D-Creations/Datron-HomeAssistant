"""Config flow for Datron NEXT integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import DatronApiClient, DatronApiError, DatronAuthError
from .const import CONF_TOKEN, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class DatronNextConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Datron NEXT."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — user enters host and token."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            token = user_input[CONF_TOKEN]
            port = user_input.get(CONF_PORT, DEFAULT_PORT)

            # Prevent duplicate entries for the same host
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            # Test the connection
            session = async_create_clientsession(self.hass, verify_ssl=False)
            client = DatronApiClient(host=host, token=token, port=port, session=session)

            try:
                user_info = await client.validate_connection()
            except DatronAuthError:
                errors["base"] = "invalid_auth"
            except DatronApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during config flow")
                errors["base"] = "unknown"
            else:
                # Build a descriptive title from machine info
                try:
                    machine_type = await client.get_machine_type()
                    machine_number = await client.get_machine_number()
                    title = (
                        f"Datron {machine_type.get('displayName', 'CNC')} "
                        f"({machine_number.get('number', host)})"
                    )
                except DatronApiError:
                    title = f"Datron NEXT ({host})"

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_TOKEN: token,
                        CONF_PORT: port,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
