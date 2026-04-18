"""Config flow for Datron NEXT integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import DatronApiClient, DatronApiError, DatronAuthError
from .const import (
    CONF_EXTRA_SIMPL_ROOTS,
    CONF_HAS_ROTARY_AXES,
    CONF_TOKEN,
    DEFAULT_HAS_ROTARY_AXES,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


def _parse_roots(raw: str | list[str] | None) -> list[str]:
    """Split a multi-line / comma-separated root list into clean entries."""
    if not raw:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = raw.replace(",", "\n").splitlines()
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        root = item.strip()
        if root and root not in seen:
            seen.add(root)
            cleaned.append(root)
    return cleaned


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
            session = async_create_clientsession(self.hass)
            client = DatronApiClient(host=host, token=token, port=port, session=session)

            try:
                await client.validate_connection()
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return DatronOptionsFlow(config_entry)


class DatronOptionsFlow(OptionsFlow):
    """Options flow — adjust token, extra SimPL roots, rotary-axis toggle."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        current_token: str = entry.data.get(CONF_TOKEN, "")
        current_roots: list[str] = entry.options.get(CONF_EXTRA_SIMPL_ROOTS, [])
        current_rotary: bool = entry.options.get(
            CONF_HAS_ROTARY_AXES, DEFAULT_HAS_ROTARY_AXES
        )

        if user_input is not None:
            new_token = user_input.get(CONF_TOKEN, current_token).strip()
            new_roots = _parse_roots(user_input.get(CONF_EXTRA_SIMPL_ROOTS))
            new_rotary = bool(user_input.get(CONF_HAS_ROTARY_AXES, current_rotary))

            # If the token changed, validate it against the machine before saving.
            if new_token and new_token != current_token:
                session = async_create_clientsession(self.hass)
                client = DatronApiClient(
                    host=entry.data[CONF_HOST],
                    token=new_token,
                    port=entry.data.get(CONF_PORT, DEFAULT_PORT),
                    session=session,
                )
                try:
                    await client.validate_connection()
                except DatronAuthError:
                    errors["base"] = "invalid_auth"
                except DatronApiError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error validating new token")
                    errors["base"] = "unknown"

            if not errors:
                if new_token and new_token != current_token:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_TOKEN: new_token},
                    )
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_EXTRA_SIMPL_ROOTS: new_roots,
                        CONF_HAS_ROTARY_AXES: new_rotary,
                    },
                )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TOKEN,
                    default=current_token,
                ): str,
                vol.Optional(
                    CONF_EXTRA_SIMPL_ROOTS,
                    default="\n".join(current_roots),
                ): str,
                vol.Optional(
                    CONF_HAS_ROTARY_AXES,
                    default=current_rotary,
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
