"""Shared entity helpers for the Datron NEXT integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_MODEL,
    CONNECTION_LIVE,
    CONNECTION_NEXT,
    DEFAULT_MODEL,
    DOMAIN,
)


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the single DeviceInfo block shared by every Datron entity.

    This centralises what used to be seven duplicated blocks. The result is
    deterministic (it depends only on ``entry.data``, never on runtime
    coordinator state) and kept behaviourally identical to the old NEXT block:

    * ``manufacturer`` stays "Datron".
    * ``model`` comes from ``entry.data[CONF_MODEL]`` when present (captured at
      config time for Live entries); NEXT and legacy entries have no such key
      and fall back to the historical hard-coded "M8Cube", so their device
      registry model is unchanged.
    * ``sw_version`` is "Live" for Datron Live entries and "NEXT" otherwise.
    * ``configuration_url`` uses ``https://`` for Live (self-signed web UI)
      and ``http://`` for NEXT (unchanged).
    """
    connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_NEXT)
    host = entry.data[CONF_HOST]

    if connection_type == CONNECTION_LIVE:
        sw_version = "Live"
        configuration_url = f"https://{host}"
    else:
        sw_version = "NEXT"
        configuration_url = f"http://{host}"

    model = entry.data.get(CONF_MODEL) or DEFAULT_MODEL

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Datron",
        model=model,
        sw_version=sw_version,
        configuration_url=configuration_url,
    )
