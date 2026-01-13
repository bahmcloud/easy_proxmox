import asyncio
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ProxmoxGuestCoordinator, ProxmoxNodeCoordinator

_LOGGER = logging.getLogger(__name__)


def _bytes_to_mb(value: int | float) -> float:
    return round(float(value) / (1024.0 * 1024.0), 2)


def _bytes_to_gb_3(value: int | float) -> float:
    return round(float(value) / (1024.0 * 1024.0 * 1024.0), 3)


def _format_uptime(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    days = seconds // 86400
    rem = seconds % 86400
    hours = rem // 3600
    minutes = (rem % 3600) // 60
    return f"{days}d {hours}h {minutes:02d}m"


# -----------------------
# Node helpers
# -----------------------
def _node_id(node: str) -> str:
    return f"node:{node}"


def _node_name(node: str) -> str:
    return f"Proxmox Node {node}"


async def _get_node_coordinator(hass: HomeAssistant, entry: ConfigEntry, node: str) -> ProxmoxNodeCoordinator:
    data = hass.data[DOMAIN][entry.entry_id]
    if node in data["node_coordinators"]:
        return data["node_coordinators"][node]

    coord = ProxmoxNodeCoordinator(
        hass=hass,
        client=data["client"],
        node=node,
        scan_interval=int(data["scan_interval"]),
    )
    data["node_coordinators"][node] = coord
    hass.async_create_task(coord.async_config_entry_first_refresh())
    return coord


# -----------------------
# Guest helpers
# -----------------------
def _guest_display_name(resource: dict) -> str:
    name = resource.get("name") or f"{resource.get('type')} {resource.get('vmid')}"
    return f"{name} (VMID {resource.get('vmid')})"


def _guest_id(resource: dict) -> str:
    return f"{resource.get('node')}:{resource.get('type')}:{resource.get('vmid')}"


def _guest_key(resource: dict) -> tuple[str, str, int]:
    return (resource["node"], resource["type"], int(resource["vmid"]))


def _model_for(resource: dict) -> str:
    return "Virtual Machine" if resource.get("type") == "qemu" else "Container"


async def _get_guest_coordinator(hass: HomeAssistant, entry: ConfigEntry, resource: dict) -> ProxmoxGuestCoordinator:
    data = hass.data[DOMAIN][entry.entry_id]
    key = _guest_key(resource)

    if key in data["guest_coordinators"]:
        return data["guest_coordinators"][key]

    coord = ProxmoxGuestCoordinator(
        hass=hass,
        client=data["client"],
        node=key[0],
        vmtype=key[1],
        vmid=key[2],
        scan_interval=int(data["scan_interval"]),
        ip_mode=str(data["ip_mode"]),
        ip_prefix=str(data["ip_prefix"]),
    )
    data["guest_coordinators"][key] = coord
    hass.async_create_task(coord.async_config_entry_first_refresh())
    return coord


def _update_device_name(hass: HomeAssistant, guest_id: str, new_name: str, model: str) -> None:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, guest_id)})
    if device and (device.name != new_name or device.model != model):
        dev_reg.async_update_device(device.id, name=new_name, model=model)


async def _purge_guest_entity_registry(hass: HomeAssistant, entry: ConfigEntry, guest_id: str) -> None:
    ent_reg = er.async_get(hass)
    prefix = f"{entry.entry_id}_{guest_id}_"

    to_remove: list[str] = []
    for entity_id, ent in ent_reg.entities.items():
        if ent.config_entry_id != entry.entry_id:
            continue
        if ent.unique_id and ent.unique_id.startswith(prefix):
            to_remove.append(entity_id)

    for entity_id in to_remove:
        ent_reg.async_remove(entity_id)

    await asyncio.sleep(0)


async def _remove_device(hass: HomeAssistant, device_ident: str) -> None:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, device_ident)})
    if device:
        dev_reg.async_remove_device(device.id)


# -----------------------
# Node Entities
# -----------------------
class ProxmoxNodeBase(CoordinatorEntity):
    def __init__(self, coordinator: ProxmoxNodeCoordinator, entry: ConfigEntry, node: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._node = node

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, _node_id(self._node))},
            "name": _node_name(self._node),
            "manufacturer": "Proxmox VE",
            "model": "Node",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"node": self._node}


class ProxmoxNodeCpuSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:cpu-64-bit"
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_cpu"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} CPU"

    @property
    def native_value(self) -> float | None:
        cpu = (self.coordinator.data or {}).get("cpu")
        return None if cpu is None else round(float(cpu) * 100.0, 2)


class ProxmoxNodeUptimeSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_uptime"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} Uptime"

    @property
    def native_value(self) -> str | None:
        up = (self.coordinator.data or {}).get("uptime")
        return None if up is None else _format_uptime(int(up))


class ProxmoxNodeLoad1Sensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_load1"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} Load (1m)"

    @property
    def native_value(self) -> float | None:
        la = (self.coordinator.data or {}).get("loadavg")
        if not la:
            return None
        try:
            if isinstance(la, list) and la:
                return float(la[0])
            if isinstance(la, str):
                return float(la.split()[0])
        except Exception:
            return None
        return None


# ---- RAM (MB)
class ProxmoxNodeRamUsedSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:memory"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_ram_used_mb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} RAM Used"

    @property
    def native_value(self) -> float | None:
        mem = (self.coordinator.data or {}).get("memory", {}).get("used")
        return None if mem is None else _bytes_to_mb(int(mem))


class ProxmoxNodeRamTotalSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:memory"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_ram_total_mb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} RAM Total"

    @property
    def native_value(self) -> float | None:
        total = (self.coordinator.data or {}).get("memory", {}).get("total")
        return None if total is None else _bytes_to_mb(int(total))


class ProxmoxNodeRamFreeSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:memory"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_ram_free_mb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} RAM Free"

    @property
    def native_value(self) -> float | None:
        free = (self.coordinator.data or {}).get("memory", {}).get("free")
        return None if free is None else _bytes_to_mb(int(free))


# ---- Swap (MB)
class ProxmoxNodeSwapUsedSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:swap-horizontal"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_swap_used_mb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} Swap Used"

    @property
    def native_value(self) -> float | None:
        used = (self.coordinator.data or {}).get("swap", {}).get("used")
        return None if used is None else _bytes_to_mb(int(used))


class ProxmoxNodeSwapTotalSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:swap-horizontal"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_swap_total_mb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} Swap Total"

    @property
    def native_value(self) -> float | None:
        total = (self.coordinator.data or {}).get("swap", {}).get("total")
        return None if total is None else _bytes_to_mb(int(total))


class ProxmoxNodeSwapFreeSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:swap-horizontal"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_swap_free_mb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} Swap Free"

    @property
    def native_value(self) -> float | None:
        free = (self.coordinator.data or {}).get("swap", {}).get("free")
        return None if free is None else _bytes_to_mb(int(free))


# ---- RootFS / Node Storage (GB, 3 decimals)
class ProxmoxNodeStorageUsedSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:harddisk"
    _attr_native_unit_of_measurement = "GB"

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_storage_used_gb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} Storage Used"

    @property
    def native_value(self) -> float | None:
        used = (self.coordinator.data or {}).get("rootfs", {}).get("used")
        return None if used is None else _bytes_to_gb_3(int(used))


class ProxmoxNodeStorageTotalSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:harddisk"
    _attr_native_unit_of_measurement = "GB"

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_storage_total_gb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} Storage Total"

    @property
    def native_value(self) -> float | None:
        total = (self.coordinator.data or {}).get("rootfs", {}).get("total")
        return None if total is None else _bytes_to_gb_3(int(total))


class ProxmoxNodeStorageFreeSensor(ProxmoxNodeBase, SensorEntity):
    _attr_icon = "mdi:harddisk"
    _attr_native_unit_of_measurement = "GB"

    def __init__(self, coordinator, entry, node: str) -> None:
        super().__init__(coordinator, entry, node)
        self._attr_unique_id = f"{entry.entry_id}_{_node_id(node)}_storage_free_gb"

    @property
    def name(self) -> str:
        return f"{_node_name(self._node)} Storage Free"

    @property
    def native_value(self) -> float | None:
        free = (self.coordinator.data or {}).get("rootfs", {}).get("free")
        return None if free is None else _bytes_to_gb_3(int(free))


# -----------------------
# Guest Entities
# -----------------------
class ProxmoxBaseGuestEntity(CoordinatorEntity):
    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._resource = dict(resource)

    def update_resource(self, resource: dict) -> None:
        self._resource = dict(resource)

    @property
    def device_info(self):
        node = self._resource.get("node")
        via = (DOMAIN, _node_id(node)) if node else None

        info = {
            "identifiers": {(DOMAIN, _guest_id(self._resource))},
            "name": _guest_display_name(self._resource),
            "manufacturer": "Proxmox VE",
            "model": _model_for(self._resource),
        }
        if via:
            info["via_device"] = via
        return info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"vmid": self._resource.get("vmid"), "node": self._resource.get("node"), "type": self._resource.get("type")}


class ProxmoxGuestStatusSensor(ProxmoxBaseGuestEntity, SensorEntity):
    _attr_icon = "mdi:power"

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_status"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} Status"

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("status")


class ProxmoxGuestCpuSensor(ProxmoxBaseGuestEntity, SensorEntity):
    _attr_icon = "mdi:cpu-64-bit"
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_cpu"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} CPU"

    @property
    def native_value(self) -> float | None:
        cpu = (self.coordinator.data or {}).get("cpu")
        return None if cpu is None else round(float(cpu) * 100.0, 2)


class ProxmoxGuestRamUsedMB(ProxmoxBaseGuestEntity, SensorEntity):
    _attr_icon = "mdi:memory"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_ram_used_mb"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} RAM Used"

    @property
    def native_value(self) -> float | None:
        mem = (self.coordinator.data or {}).get("mem")
        return None if mem is None else _bytes_to_mb(int(mem))


class ProxmoxGuestUptimePretty(ProxmoxBaseGuestEntity, SensorEntity):
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_uptime_pretty"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} Uptime"

    @property
    def native_value(self) -> str | None:
        uptime = (self.coordinator.data or {}).get("uptime")
        return None if uptime is None else _format_uptime(int(uptime))


class ProxmoxGuestNetInMB(ProxmoxBaseGuestEntity, SensorEntity):
    _attr_icon = "mdi:download-network"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_netin_mb"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} Network In"

    @property
    def native_value(self) -> float | None:
        v = (self.coordinator.data or {}).get("netin")
        return None if v is None else _bytes_to_mb(int(v))


class ProxmoxGuestNetOutMB(ProxmoxBaseGuestEntity, SensorEntity):
    _attr_icon = "mdi:upload-network"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_netout_mb"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} Network Out"

    @property
    def native_value(self) -> float | None:
        v = (self.coordinator.data or {}).get("netout")
        return None if v is None else _bytes_to_mb(int(v))


class ProxmoxGuestPreferredIP(ProxmoxBaseGuestEntity, SensorEntity):
    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_ip_preferred"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} IP"

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("_preferred_ip")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        attrs["ip_addresses"] = (self.coordinator.data or {}).get("_ip_addresses", [])
        return attrs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    resources_coord = data["resources"]
    nodes_coord = data["nodes"]

    platform_cache = data.setdefault("platform_cache", {})
    guest_cache: dict[tuple[str, str, int], list[SensorEntity]] = platform_cache.setdefault("sensor_guest", {})
    node_cache: dict[str, list[SensorEntity]] = platform_cache.setdefault("sensor_node", {})

    async def _sync_nodes() -> None:
        nodes = nodes_coord.data or []
        current_nodes = {n.get("node") for n in nodes if n.get("node")}

        new_entities: list[SensorEntity] = []
        for node in sorted(current_nodes):
            if node in node_cache:
                continue

            node_c = await _get_node_coordinator(hass, entry, node)
            ents = [
                ProxmoxNodeCpuSensor(node_c, entry, node),
                ProxmoxNodeLoad1Sensor(node_c, entry, node),
                ProxmoxNodeRamUsedSensor(node_c, entry, node),
                ProxmoxNodeRamTotalSensor(node_c, entry, node),
                ProxmoxNodeRamFreeSensor(node_c, entry, node),
                ProxmoxNodeSwapUsedSensor(node_c, entry, node),
                ProxmoxNodeSwapTotalSensor(node_c, entry, node),
                ProxmoxNodeSwapFreeSensor(node_c, entry, node),
                ProxmoxNodeStorageUsedSensor(node_c, entry, node),
                ProxmoxNodeStorageTotalSensor(node_c, entry, node),
                ProxmoxNodeStorageFreeSensor(node_c, entry, node),
                ProxmoxNodeUptimeSensor(node_c, entry, node),
            ]
            node_cache[node] = ents
            new_entities.extend(ents)

        if new_entities:
            async_add_entities(new_entities, update_before_add=False)

        removed = [n for n in list(node_cache.keys()) if n not in current_nodes]
        for n in removed:
            for ent in node_cache[n]:
                await ent.async_remove()
            del node_cache[n]
            await _remove_device(hass, _node_id(n))

    async def _sync_guests() -> None:
        resources = resources_coord.data or []
        current: dict[tuple[str, str, int], dict] = {}

        for r in resources:
            if r.get("type") not in ("qemu", "lxc"):
                continue
            if r.get("node") is None or r.get("vmid") is None:
                continue
            current[_guest_key(r)] = r

        for key, r in current.items():
            if key not in guest_cache:
                continue
            gid = _guest_id(r)
            _update_device_name(hass, gid, _guest_display_name(r), _model_for(r))
            for ent in guest_cache[key]:
                ent.update_resource(r)
                ent.async_write_ha_state()

        new_entities: list[SensorEntity] = []
        for key, r in current.items():
            if key in guest_cache:
                continue
            guest_coord = await _get_guest_coordinator(hass, entry, r)
            ents = [
                ProxmoxGuestStatusSensor(guest_coord, entry, r),
                ProxmoxGuestCpuSensor(guest_coord, entry, r),
                ProxmoxGuestRamUsedMB(guest_coord, entry, r),
                ProxmoxGuestUptimePretty(guest_coord, entry, r),
                ProxmoxGuestNetInMB(guest_coord, entry, r),
                ProxmoxGuestNetOutMB(guest_coord, entry, r),
                ProxmoxGuestPreferredIP(guest_coord, entry, r),
            ]
            guest_cache[key] = ents
            new_entities.extend(ents)

        if new_entities:
            async_add_entities(new_entities, update_before_add=False)

        removed = [k for k in list(guest_cache.keys()) if k not in current]
        for k in removed:
            gid = f"{k[0]}:{k[1]}:{k[2]}"
            for ent in guest_cache[k]:
                await ent.async_remove()
            del guest_cache[k]

            data["guest_coordinators"].pop(k, None)
            await _purge_guest_entity_registry(hass, entry, gid)
            await _remove_device(hass, gid)

    await _sync_nodes()
    await _sync_guests()

    unsub_nodes = nodes_coord.async_add_listener(lambda: hass.async_create_task(_sync_nodes()))
    unsub_guests = resources_coord.async_add_listener(lambda: hass.async_create_task(_sync_guests()))
    platform_cache.setdefault("sensor_unsub", []).extend([unsub_nodes, unsub_guests])
