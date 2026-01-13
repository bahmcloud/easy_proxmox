import logging
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import ProxmoxClient
from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_SCAN_INTERVAL,
    CONF_IP_MODE,
    CONF_IP_PREFIX,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_IP_MODE,
    DEFAULT_IP_PREFIX,
)
from .coordinator import ProxmoxResourcesCoordinator, ProxmoxNodesCoordinator
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)


def _opt(entry: ConfigEntry, key: str, default):
    return entry.options.get(key, default)


async def _apply_options_now(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply updated options to all coordinators without reload/restart."""
    data = hass.data[DOMAIN][entry.entry_id]

    new_scan_interval = int(_opt(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    new_ip_mode = str(_opt(entry, CONF_IP_MODE, DEFAULT_IP_MODE))
    new_ip_prefix = str(_opt(entry, CONF_IP_PREFIX, DEFAULT_IP_PREFIX))

    data["scan_interval"] = new_scan_interval
    data["ip_mode"] = new_ip_mode
    data["ip_prefix"] = new_ip_prefix

    td = timedelta(seconds=new_scan_interval)

    resources = data.get("resources")
    if resources:
        resources.update_interval = td

    nodes = data.get("nodes")
    if nodes:
        nodes.update_interval = td

    for node_coord in (data.get("node_coordinators") or {}).values():
        node_coord.update_interval = td

    for guest_coord in (data.get("guest_coordinators") or {}).values():
        guest_coord.update_interval = td
        guest_coord.ip_mode = new_ip_mode
        guest_coord.ip_prefix = new_ip_prefix

    # trigger refresh so UI updates quickly
    tasks = []
    if resources:
        tasks.append(resources.async_request_refresh())
    if nodes:
        tasks.append(nodes.async_request_refresh())

    for node_coord in (data.get("node_coordinators") or {}).values():
        tasks.append(node_coord.async_request_refresh())

    for guest_coord in (data.get("guest_coordinators") or {}).values():
        tasks.append(guest_coord.async_request_refresh())

    for t in tasks:
        hass.async_create_task(t)

    _LOGGER.debug(
        "Applied options live for %s: scan_interval=%s ip_mode=%s ip_prefix=%s",
        entry.entry_id,
        new_scan_interval,
        new_ip_mode,
        new_ip_prefix,
    )


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await _apply_options_now(hass, entry)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = aiohttp.ClientSession()

    client = ProxmoxClient(
        host=entry.data["host"],
        port=entry.data["port"],
        token_name=entry.data["token_name"],
        token_value=entry.data["token_value"],
        verify_ssl=entry.data["verify_ssl"],
        session=session,
    )

    scan_interval = int(_opt(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    ip_mode = str(_opt(entry, CONF_IP_MODE, DEFAULT_IP_MODE))
    ip_prefix = str(_opt(entry, CONF_IP_PREFIX, DEFAULT_IP_PREFIX))

    resources = ProxmoxResourcesCoordinator(hass, client, scan_interval=scan_interval)
    nodes = ProxmoxNodesCoordinator(hass, client, scan_interval=scan_interval)

    await resources.async_config_entry_first_refresh()
    await nodes.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "session": session,
        "client": client,
        "resources": resources,
        "nodes": nodes,
        "scan_interval": scan_interval,
        "ip_mode": ip_mode,
        "ip_prefix": ip_prefix,
        "guest_coordinators": {},
        "node_coordinators": {},
        "platform_cache": {},
    }

    # Register services once
    await async_register_services(hass)

    # Apply option updates live
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Set up proxmox_pve entry %s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data:
            pc = data.get("platform_cache") or {}
            for key in ("sensor_unsub", "switch_unsub", "button_unsub"):
                for unsub in pc.get(key, []):
                    try:
                        unsub()
                    except Exception:
                        pass

            if data.get("session"):
                await data["session"].close()

        # If no entries remain, unregister services
        if not hass.data.get(DOMAIN):
            await async_unregister_services(hass)

    return unload_ok
