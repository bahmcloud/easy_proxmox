import logging
from typing import Any, Tuple

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_START = "start"
SERVICE_SHUTDOWN = "shutdown"
SERVICE_STOP_HARD = "stop_hard"
SERVICE_REBOOT = "reboot"

ATTR_DEVICE_ID = "device_id"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_HOST = "host"
ATTR_NODE = "node"
ATTR_VMID = "vmid"
ATTR_TYPE = "type"

VALID_TYPES = ("qemu", "lxc")

# IMPORTANT:
# HA may pass device_id via target (list) OR data (list) depending on UI/script wrapper.
SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): vol.Any(str, [str]),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): str,
        vol.Optional(ATTR_HOST): str,
        vol.Optional(ATTR_NODE): str,
        vol.Optional(ATTR_VMID): vol.Coerce(int),
        vol.Optional(ATTR_TYPE, default="qemu"): vol.In(VALID_TYPES),
    }
)


def _first_str(value: Any) -> str | None:
    """Return first string from str or list[str], else None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value:
        v0 = value[0]
        if isinstance(v0, str) and v0.strip():
            return v0.strip()
    return None


def _get_target_device_id(call: ServiceCall) -> str | None:
    """
    Prefer call.target.device_id (UI target).
    Fallback to call.data.device_id (some wrappers convert target to data).
    """
    if call.target and isinstance(call.target, dict):
        dev_id = _first_str(call.target.get("device_id"))
        if dev_id:
            return dev_id

    # fallback: data.device_id can be str or list[str]
    return _first_str(call.data.get(ATTR_DEVICE_ID))


def _parse_guest_identifier(identifier: str) -> Tuple[str, str, int]:
    """
    Guest device identifier format: "node:type:vmid"
    Example: "pve1:qemu:100"
    """
    parts = identifier.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid guest identifier: {identifier}")
    node, vmtype, vmid_s = parts
    vmid = int(vmid_s)
    if vmtype not in VALID_TYPES:
        raise ValueError(f"Invalid VM type: {vmtype}")
    return node, vmtype, vmid


def _resolve_target(hass: HomeAssistant, call: ServiceCall) -> Tuple[str, str, int]:
    """Resolve node/type/vmid from device target OR node+vmid (+ optional type)."""
    device_id = _get_target_device_id(call)
    node = call.data.get(ATTR_NODE)
    vmid = call.data.get(ATTR_VMID)
    vmtype = call.data.get(ATTR_TYPE, "qemu")

    if device_id:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(device_id)
        if not device:
            raise ValueError(f"Device not found: {device_id}")

        for ident_domain, ident_value in device.identifiers:
            if ident_domain != DOMAIN:
                continue
            if ident_value.startswith("node:"):
                continue
            return _parse_guest_identifier(ident_value)

        raise ValueError(f"Selected device has no Easy Proxmox guest identifier: {device_id}")

    if not node or vmid is None:
        raise ValueError("Provide a Device target OR node + vmid (+ optional type/host/config_entry_id).")

    if vmtype not in VALID_TYPES:
        raise ValueError(f"Invalid type: {vmtype} (allowed: {VALID_TYPES})")

    return str(node), str(vmtype), int(vmid)


def _get_domain_entries(hass: HomeAssistant) -> dict[str, Any]:
    domain_data: dict[str, Any] = hass.data.get(DOMAIN, {})
    if not domain_data:
        raise ValueError("Easy Proxmox is not set up.")
    return domain_data


def _pick_entry_id_for_device(hass: HomeAssistant, device_id: str) -> str:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if not device:
        raise ValueError(f"Device not found: {device_id}")

    domain_entries = _get_domain_entries(hass)
    candidates = [eid for eid in device.config_entries if eid in domain_entries]
    if not candidates:
        raise ValueError("Device is not linked to any loaded Easy Proxmox config entry.")
    if len(candidates) > 1:
        _LOGGER.warning("Device %s belongs to multiple Easy Proxmox entries, using first.", device_id)
    return candidates[0]


def _pick_entry_id_by_host(hass: HomeAssistant, host: str) -> str:
    domain_entries = _get_domain_entries(hass)
    matches = []
    for entry_id, data in domain_entries.items():
        if not isinstance(data, dict):
            continue
        client = data.get("client")
        if client and getattr(client, "host", None) == host:
            matches.append(entry_id)

    if not matches:
        raise ValueError(f"No Easy Proxmox entry found for host '{host}'.")
    if len(matches) > 1:
        raise ValueError(f"Multiple Easy Proxmox entries found for host '{host}'. Please use config_entry_id.")
    return matches[0]


def _pick_entry_id_by_guest_lookup(hass: HomeAssistant, node: str, vmtype: str, vmid: int) -> str:
    domain_entries = _get_domain_entries(hass)
    matches = []

    for entry_id, data in domain_entries.items():
        if not isinstance(data, dict):
            continue
        resources = data.get("resources")
        res_list = getattr(resources, "data", None)
        if not res_list:
            continue

        for r in res_list:
            try:
                if r.get("type") == vmtype and str(r.get("node")) == node and int(r.get("vmid")) == vmid:
                    matches.append(entry_id)
                    break
            except Exception:
                continue

    if not matches:
        raise ValueError(
            f"Could not find guest {node}/{vmtype}/{vmid} in any configured Proxmox host. "
            "Provide host or config_entry_id, or use device target."
        )
    if len(matches) > 1:
        raise ValueError(
            f"Guest {node}/{vmtype}/{vmid} exists on multiple configured hosts (ambiguous). "
            "Please provide host or config_entry_id, or use device target."
        )
    return matches[0]


def _resolve_entry_id(hass: HomeAssistant, call: ServiceCall, target: Tuple[str, str, int]) -> str:
    domain_entries = _get_domain_entries(hass)

    config_entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if config_entry_id:
        if config_entry_id not in domain_entries:
            raise ValueError(f"config_entry_id '{config_entry_id}' not found or not loaded.")
        return config_entry_id

    device_id = _get_target_device_id(call)
    if device_id:
        return _pick_entry_id_for_device(hass, device_id)

    host = call.data.get(ATTR_HOST)
    if host:
        return _pick_entry_id_by_host(hass, host)

    node, vmtype, vmid = target
    return _pick_entry_id_by_guest_lookup(hass, node, vmtype, vmid)


async def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_START):
        return

    async def _call_action(call: ServiceCall, action: str) -> None:
        node, vmtype, vmid = _resolve_target(hass, call)
        entry_id = _resolve_entry_id(hass, call, (node, vmtype, vmid))

        domain_entries = _get_domain_entries(hass)
        entry_data = domain_entries.get(entry_id)
        if not isinstance(entry_data, dict) or not entry_data.get("client"):
            raise ValueError(f"Selected config entry '{entry_id}' has no client (not loaded).")

        client = entry_data["client"]
        _LOGGER.debug("Service action=%s entry=%s target=%s/%s/%s", action, entry_id, node, vmtype, vmid)
        await client.guest_action(node=node, vmid=vmid, vmtype=vmtype, action=action)

    async def handle_start(call: ServiceCall) -> None:
        await _call_action(call, "start")

    async def handle_shutdown(call: ServiceCall) -> None:
        await _call_action(call, "shutdown")

    async def handle_stop_hard(call: ServiceCall) -> None:
        await _call_action(call, "stop")

    async def handle_reboot(call: ServiceCall) -> None:
        await _call_action(call, "reboot")

    hass.services.async_register(DOMAIN, SERVICE_START, handle_start, schema=SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SHUTDOWN, handle_shutdown, schema=SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_STOP_HARD, handle_stop_hard, schema=SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REBOOT, handle_reboot, schema=SERVICE_SCHEMA)


async def async_unregister_services(hass: HomeAssistant) -> None:
    for svc in (SERVICE_START, SERVICE_SHUTDOWN, SERVICE_STOP_HARD, SERVICE_REBOOT):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)