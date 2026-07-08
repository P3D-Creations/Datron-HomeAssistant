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
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import DatronApiClient, DatronApiError, DatronAuthError
from .const import (
    CONF_CONNECTION_TYPE,
    CONF_EXTRA_SIMPL_ROOTS,
    CONF_HAS_ROTARY_AXES,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    CONNECTION_LIVE,
    CONNECTION_NEXT,
    DEFAULT_HAS_ROTARY_AXES,
    DEFAULT_LIVE_PORT,
    DEFAULT_PORT,
    DOMAIN,
)
from .live_api import DatronLiveClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)

STEP_LIVE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_PORT, default=DEFAULT_LIVE_PORT): int,
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
        """Initial step — pick the connection type."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["connection_next", "connection_live"],
        )

    async def async_step_connection_next(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """NEXT connection — user enters host and token."""
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
                        CONF_CONNECTION_TYPE: CONNECTION_NEXT,
                        CONF_HOST: host,
                        CONF_TOKEN: token,
                        CONF_PORT: port,
                    },
                )

        return self.async_show_form(
            step_id="connection_next",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_connection_live(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Datron Live connection — host + username/password + optional port."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            port = user_input.get(CONF_PORT, DEFAULT_LIVE_PORT)

            # Prevent duplicate entries for the same host
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = DatronLiveClient(
                host=host,
                username=username,
                password=password,
                port=port,
                session=session,
            )

            try:
                await client.login()
                await client.validate_connection()
            except DatronAuthError:
                errors["base"] = "invalid_auth"
            except DatronApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Live config flow")
                errors["base"] = "unknown"
            else:
                model: str | None = None
                try:
                    machine_type = await client.get_machine_type()
                    machine_number = await client.get_machine_number()
                    model = machine_type.get("displayName") or machine_type.get("type")
                    title = (
                        f"Datron {machine_type.get('displayName', 'CNC')} "
                        f"({machine_number.get('number', host)})"
                    )
                except DatronApiError:
                    title = f"Datron Live ({host})"

                entry_data = {
                    CONF_CONNECTION_TYPE: CONNECTION_LIVE,
                    CONF_HOST: host,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_PORT: port,
                }
                if model:
                    # Captured once so device_info is deterministic and never
                    # depends on runtime coordinator state.
                    entry_data[CONF_MODEL] = model
                return self.async_create_entry(title=title, data=entry_data)

        return self.async_show_form(
            step_id="connection_live",
            data_schema=STEP_LIVE_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return DatronOptionsFlow()


class DatronOptionsFlow(OptionsFlow):
    """Options flow — adjust token, extra SimPL roots, rotary-axis toggle.

    ``config_entry`` is provided by the ``OptionsFlow`` base class as a
    read-only property (Home Assistant injects it), so we must NOT define an
    ``__init__`` that assigns to it — doing so raises
    ``AttributeError: property 'config_entry' ... has no setter`` on current HA.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Route to the NEXT or Live options step based on connection type."""
        entry = self.config_entry
        connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_NEXT)
        if connection_type == CONNECTION_LIVE:
            return await self.async_step_live_options(user_input)
        return await self.async_step_next_options(user_input)

    async def async_step_live_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Options for a Datron Live entry — change username/password."""
        errors: dict[str, str] = {}
        entry = self.config_entry
        current_username: str = entry.data.get(CONF_USERNAME, "")
        current_password: str = entry.data.get(CONF_PASSWORD, "")

        if user_input is not None:
            new_username = user_input.get(CONF_USERNAME, current_username).strip()
            new_password = user_input.get(CONF_PASSWORD, current_password)

            changed = (
                new_username != current_username or new_password != current_password
            )
            if changed:
                session = async_get_clientsession(self.hass)
                client = DatronLiveClient(
                    host=entry.data[CONF_HOST],
                    username=new_username,
                    password=new_password,
                    port=entry.data.get(CONF_PORT, DEFAULT_LIVE_PORT),
                    session=session,
                )
                try:
                    await client.login()
                    await client.validate_connection()
                except DatronAuthError:
                    errors["base"] = "invalid_auth"
                except DatronApiError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error validating Live credentials")
                    errors["base"] = "unknown"

            if not errors:
                if changed:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={
                            **entry.data,
                            CONF_USERNAME: new_username,
                            CONF_PASSWORD: new_password,
                        },
                    )
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Optional(CONF_USERNAME, default=current_username): str,
                vol.Optional(CONF_PASSWORD, default=current_password): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="live_options",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_next_options(
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
            step_id="next_options",
            data_schema=schema,
            errors=errors,
        )
