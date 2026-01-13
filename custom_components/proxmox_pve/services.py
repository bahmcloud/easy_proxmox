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
ATTR_NODE = "node"
ATTR_VMID = "vmid"
ATTR_TYPE = "type"

VALID_TYPES = ("qemu", "lxc")

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): str,
        vol.Optional(ATTR_NODE): str,
        vol.Optional(ATTR_VMID): vol.Coerce(int),
        vol.Optional(ATTR_TYPE, default="qemu"): vol.In(VALID_TYPES),
    }
)


def _parse_guest_identifier(identifier: str) -> Tuple[str, str, int]:
    """
    Our device identifier for guests is: "node:type:vmid"
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
    """Resolve node/type/vmid from either device_id or node+vmid."""
    device_id = call.data.get(ATTR_DEVICE_ID)
    node = call.data.get(ATTR_NODE)
    vmid = call.data.get(ATTR_VMID)
    vmtype = call.data.get(ATTR_TYPE, "qemu")

    if device_id:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(device_id)
        if not device:
            raise ValueError(f"Device not found: {device_id}")

        # Find our identifiers
        for ident_domain, ident_value in device.identifiers:
            if ident_domain != DOMAIN:
                continue
            # Node devices are "node:<name>" — we need guest identifiers only
            if ident_value.startswith("node:"):
                continue
            # Guest devices are "node:type:vmid"
            return _parse_guest_identifier(ident_value)

        raise ValueError(f"Selected device has no Easy Proxmox guest identifier: {device_id}")

    # Fallback: manual node/vmid
    if not node or vmid is None:
        raise ValueError("Provide either device_id OR node + vmid (+ optional type).")

    if vmtype not in VALID_TYPES:
        raise ValueError(f"Invalid type: {vmtype} (allowed: {VALID_TYPES})")

    return str(node), str(vmtype), int(vmid)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register domain services once."""
    if hass.services.has_service(DOMAIN, SERVICE_START):
        return

    async def _call_action(call: ServiceCall, action: str) -> None:
        node, vmtype, vmid = _resolve_target(hass, call)

        # Find the corresponding config entry client
        # If multiple entries exist, we just use the first one that is loaded.
        domain_data: dict[str, Any] = hass.data.get(DOMAIN, {})
        if not domain_data:
            raise ValueError("Easy Proxmox is not set up.")

        client = None
        for entry_id, entry_data in domain_data.items():
            if isinstance(entry_data, dict) and entry_data.get("client"):
                client = entry_data["client"]
                break

        if client is None:
            raise ValueError("No Proxmox client available (integration not loaded).")

        _LOGGER.debug("Service action=%s target=%s/%s/%s", action, node, vmtype, vmid)
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
    """Unregister services (optional, usually not required, but clean)."""
    for svc in (SERVICE_START, SERVICE_SHUTDOWN, SERVICE_STOP_HARD, SERVICE_REBOOT):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
