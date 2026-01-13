import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ProxmoxApiError, ProxmoxClient
from .const import (
    DEFAULT_SCAN_INTERVAL,
    IP_MODE_ANY,
    IP_MODE_CUSTOM_PREFIX,
    IP_MODE_PREFER_192168,
    IP_MODE_PREFER_PRIVATE,
)

_LOGGER = logging.getLogger(__name__)


def _is_private_ipv4(addr: str) -> bool:
    if addr.startswith("10."):
        return True
    if addr.startswith("192.168."):
        return True
    if addr.startswith("172."):
        try:
            second = int(addr.split(".")[1])
            return 16 <= second <= 31
        except Exception:
            return False
    return False


def _pick_preferred_ip(ips: list[str], mode: str, prefix: str | None) -> str | None:
    if not ips:
        return None

    # normalize
    prefix = (prefix or "").strip()

    if mode == IP_MODE_CUSTOM_PREFIX and prefix:
        for ip in ips:
            if ip.startswith(prefix):
                return ip

    if mode == IP_MODE_PREFER_192168:
        for ip in ips:
            if ip.startswith("192.168."):
                return ip
        for ip in ips:
            if _is_private_ipv4(ip):
                return ip
        for ip in ips:
            if "." in ip:
                return ip
        return ips[0]

    if mode == IP_MODE_PREFER_PRIVATE:
        for ip in ips:
            if _is_private_ipv4(ip):
                return ip
        for ip in ips:
            if "." in ip:
                return ip
        return ips[0]

    # IP_MODE_ANY (or fallback)
    for ip in ips:
        if "." in ip:
            return ip
    return ips[0]


class ProxmoxResourcesCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinator for /cluster/resources?type=vm"""

    def __init__(self, hass: HomeAssistant, client: ProxmoxClient, scan_interval: int = DEFAULT_SCAN_INTERVAL) -> None:
        self.client = client
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="proxmox_pve_resources",
            update_method=self._async_update_data,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            return await self.client.list_cluster_resources()
        except ProxmoxApiError as err:
            raise UpdateFailed(str(err)) from err


class ProxmoxNodesCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinator for /nodes"""

    def __init__(self, hass: HomeAssistant, client: ProxmoxClient, scan_interval: int = DEFAULT_SCAN_INTERVAL) -> None:
        self.client = client
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="proxmox_pve_nodes",
            update_method=self._async_update_data,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            return await self.client.list_nodes()
        except ProxmoxApiError as err:
            raise UpdateFailed(str(err)) from err


class ProxmoxNodeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator per node: /nodes/{node}/status"""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ProxmoxClient,
        node: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self.client = client
        self.node = node
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"proxmox_pve_node_{node}",
            update_method=self._async_update_data,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.get_node_status(self.node)
        except ProxmoxApiError as err:
            raise UpdateFailed(str(err)) from err


class ProxmoxGuestCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator per guest: /status/current (+ best-effort IPs)."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ProxmoxClient,
        node: str,
        vmid: int,
        vmtype: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        ip_mode: str = IP_MODE_PREFER_192168,
        ip_prefix: str | None = None,
    ) -> None:
        self.client = client
        self.node = node
        self.vmid = vmid
        self.vmtype = vmtype
        self.ip_mode = ip_mode
        self.ip_prefix = ip_prefix

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"proxmox_pve_guest_{node}_{vmtype}_{vmid}",
            update_method=self._async_update_data,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.client.get_guest_status_current(self.node, self.vmid, self.vmtype)
        except ProxmoxApiError as err:
            raise UpdateFailed(str(err)) from err

        ip_list: list[str] = []

        if self.vmtype == "qemu":
            try:
                agent = await self.client.get_qemu_agent_network_ifaces(self.node, self.vmid)
                for iface in agent.get("result", []):
                    for ip in iface.get("ip-addresses", []):
                        addr = ip.get("ip-address")
                        if not addr:
                            continue
                        if addr.startswith("127.") or addr.startswith("fe80:") or addr == "::1":
                            continue
                        ip_list.append(addr)
            except ProxmoxApiError:
                pass
            except Exception:
                pass

        ip_list = sorted(set(ip_list))
        status["_ip_addresses"] = ip_list
        status["_preferred_ip"] = _pick_preferred_ip(ip_list, self.ip_mode, self.ip_prefix)
        return status
