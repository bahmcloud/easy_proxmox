import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp


class ProxmoxApiError(Exception):
    """Raised for Proxmox API errors."""


@dataclass
class ProxmoxClient:
    host: str
    port: int
    token_name: str   # "USER@REALM!TOKENID"
    token_value: str
    verify_ssl: bool
    session: aiohttp.ClientSession

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}/api2/json"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"PVEAPIToken={self.token_name}={self.token_value}"}

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("headers", {})
        kwargs["headers"].update(self._headers())

        ssl = None if self.verify_ssl else False

        try:
            async with self.session.request(method, url, ssl=ssl, **kwargs) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise ProxmoxApiError(f"HTTP {resp.status} calling {path}: {text}")
                payload = await resp.json()
                return payload.get("data")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise ProxmoxApiError(str(e)) from e

    async def test_connection(self) -> None:
        await self._request("GET", "/version")

    async def list_cluster_resources(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/cluster/resources", params={"type": "vm"})

    async def list_nodes(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/nodes")

    async def get_node_status(self, node: str) -> dict[str, Any]:
        return await self._request("GET", f"/nodes/{node}/status")

    async def guest_action(self, node: str, vmid: int, vmtype: str, action: str) -> Any:
        return await self._request("POST", f"/nodes/{node}/{vmtype}/{vmid}/status/{action}")

    async def get_guest_status_current(self, node: str, vmid: int, vmtype: str) -> dict[str, Any]:
        return await self._request("GET", f"/nodes/{node}/{vmtype}/{vmid}/status/current")

    async def get_qemu_agent_network_ifaces(self, node: str, vmid: int) -> dict[str, Any]:
        return await self._request("GET", f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
