import asyncio
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ProxmoxGuestCoordinator

_LOGGER = logging.getLogger(__name__)


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


async def _remove_device(hass: HomeAssistant, guest_id: str) -> None:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, guest_id)})
    if device:
        dev_reg.async_remove_device(device.id)


class _BaseGuestButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._resource = dict(resource)

    def update_resource(self, resource: dict) -> None:
        self._resource = dict(resource)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, _guest_id(self._resource))},
            "name": _guest_display_name(self._resource),
            "manufacturer": "Proxmox VE",
            "model": _model_for(self._resource),
        }

    @property
    def extra_state_attributes(self):
        return {"vmid": self._resource.get("vmid"), "node": self._resource.get("node"), "type": self._resource.get("type")}


class ProxmoxGuestRebootButton(_BaseGuestButton):
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_reboot"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} Reboot"

    async def async_press(self) -> None:
        client = self.hass.data[DOMAIN][self._entry.entry_id]["client"]
        await client.guest_action(self._resource["node"], int(self._resource["vmid"]), self._resource["type"], "reboot")
        await self.coordinator.async_request_refresh()


class ProxmoxGuestHardStopButton(_BaseGuestButton):
    _attr_icon = "mdi:stop-circle"

    def __init__(self, coordinator, entry: ConfigEntry, resource: dict) -> None:
        super().__init__(coordinator, entry, resource)
        self._attr_unique_id = f"{entry.entry_id}_{_guest_id(resource)}_stop_hard"

    @property
    def name(self) -> str:
        return f"{_guest_display_name(self._resource)} Stop (hard)"

    async def async_press(self) -> None:
        client = self.hass.data[DOMAIN][self._entry.entry_id]["client"]
        await client.guest_action(self._resource["node"], int(self._resource["vmid"]), self._resource["type"], "stop")
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    resources_coord = data["resources"]

    platform_cache = data.setdefault("platform_cache", {})
    cache: dict[tuple[str, str, int], list[ButtonEntity]] = platform_cache.setdefault("button", {})

    async def _sync() -> None:
        resources = resources_coord.data or []
        current: dict[tuple[str, str, int], dict] = {}

        for r in resources:
            if r.get("type") not in ("qemu", "lxc"):
                continue
            if r.get("node") is None or r.get("vmid") is None:
                continue
            current[_guest_key(r)] = r

        # update
        for key, r in current.items():
            if key not in cache:
                continue
            gid = _guest_id(r)
            _update_device_name(hass, gid, _guest_display_name(r), _model_for(r))
            for ent in cache[key]:
                ent.update_resource(r)
                ent.async_write_ha_state()

        # add
        new_entities: list[ButtonEntity] = []
        for key, r in current.items():
            if key in cache:
                continue
            guest_coord = await _get_guest_coordinator(hass, entry, r)
            ents = [ProxmoxGuestRebootButton(guest_coord, entry, r), ProxmoxGuestHardStopButton(guest_coord, entry, r)]
            cache[key] = ents
            new_entities.extend(ents)

        if new_entities:
            async_add_entities(new_entities, update_before_add=False)

        # remove (hard cleanup)
        removed = [k for k in list(cache.keys()) if k not in current]
        for k in removed:
            gid = f"{k[0]}:{k[1]}:{k[2]}"

            for ent in cache[k]:
                await ent.async_remove()
            del cache[k]

            data["guest_coordinators"].pop(k, None)
            await _purge_guest_entity_registry(hass, entry, gid)
            await _remove_device(hass, gid)

    await _sync()
    unsub = resources_coord.async_add_listener(lambda: hass.async_create_task(_sync()))
    platform_cache.setdefault("button_unsub", []).append(unsub)
