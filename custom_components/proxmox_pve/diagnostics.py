from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


# ---------------------------
# Masking helpers
# ---------------------------

_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")


def _mask_ipv4(ip: str) -> str:
    """Mask IPv4 addresses (keep first two octets). Example: 192.168.178.101 -> 192.168.xxx.xxx"""
    parts = ip.split(".")
    if len(parts) != 4:
        return ip
    return f"{parts[0]}.{parts[1]}.xxx.xxx"


def _mask_ipv4_in_text(text: str) -> str:
    """Replace any IPv4 occurrences inside a string."""
    return _IPV4_RE.sub(lambda m: _mask_ipv4(m.group(0)), text)


def _mask_token_name(value: Any) -> Any:
    """Show only first 2 and last 2 chars of token_name."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if len(s) <= 4:
        return "*" * len(s) if s else s
    return f"{s[:2]}***{s[-2:]}"


def _redact_secret(value: Any) -> Any:
    """Redact secrets while keeping structure intact."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return value
        if len(s) <= 6:
            return "***"
        return s[:3] + "***" + s[-3:]
    if isinstance(value, dict):
        return {k: _redact_secret(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secret(v) for v in value]
    return value


def _sanitize_public(value: Any) -> Any:
    """
    Public-safe sanitization:
    - Mask all IPv4 strings anywhere
    - Keep structure
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _mask_ipv4_in_text(value)
    if isinstance(value, dict):
        return {str(k): _sanitize_public(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_public(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize_public(v) for v in value]
    return value


# ---------------------------
# Coordinator helpers
# ---------------------------

def _safe_coordinator_state(coord: Any) -> dict[str, Any]:
    if not coord:
        return {}
    data = getattr(coord, "data", None)
    preview = None
    if isinstance(data, list):
        preview = data[:3]
    return {
        "name": getattr(coord, "name", None),
        "update_interval": str(getattr(coord, "update_interval", None)),
        "last_update_success": getattr(coord, "last_update_success", None),
        "last_exception": repr(getattr(coord, "last_exception", None)),
        "data_type": type(data).__name__,
        "data_preview": preview,
    }


def _stringify_key(key: Any) -> str:
    if isinstance(key, tuple):
        return ":".join(str(x) for x in key)
    return str(key)


def _safe_coord_map(coord_map: Any) -> dict[str, Any]:
    if not isinstance(coord_map, dict):
        return {}
    return {_stringify_key(k): _safe_coordinator_state(v) for k, v in coord_map.items()}


# ---------------------------
# Proxmox client access
# ---------------------------

async def _try_call(func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
    return await func(*args, **kwargs)


async def _client_get_json(client: Any, path: str) -> Any:
    """
    Best-effort JSON GET against the Proxmox client.
    Tries multiple method names to stay compatible with different client styles.
    """
    if client is None:
        return None

    if not path.startswith("/"):
        path = "/" + path

    candidates = []
    for name in (
        "get",
        "api_get",
        "request",
        "api_request",
        "_request",
        "_api_request",
        "get_json",
        "async_get",
    ):
        fn = getattr(client, name, None)
        if callable(fn):
            candidates.append((name, fn))

    last_err: Exception | None = None

    for name, fn in candidates:
        try:
            if name in ("request", "api_request", "_request", "_api_request"):
                data = await _try_call(fn, "GET", path)
            else:
                data = await _try_call(fn, path)

            # Unwrap {"data": ...} responses
            if isinstance(data, dict) and "data" in data and len(data) == 1:
                return data["data"]

            return data
        except Exception as err:  # noqa: BLE001
            last_err = err
            continue

    if last_err:
        return {
            "error": f"Could not query {path} via client "
                     f"({type(last_err).__name__}: {last_err})"
        }

    return {"error": f"Could not query {path} via client (no compatible method found)"}


# ---------------------------
# Proxmox data processing
# ---------------------------

def _count_resources(resources_data: Any) -> dict[str, int]:
    counts = {
        "nodes": 0,
        "vms": 0,
        "containers": 0,
        "total_guests": 0,
    }
    if not isinstance(resources_data, list):
        return counts

    for r in resources_data:
        if not isinstance(r, dict):
            continue
        r_type = r.get("type")
        if r_type == "node":
            counts["nodes"] += 1
        elif r_type == "qemu":
            counts["vms"] += 1
            counts["total_guests"] += 1
        elif r_type == "lxc":
            counts["containers"] += 1
            counts["total_guests"] += 1

    return counts


def _extract_cluster_info(cluster_status: Any) -> dict[str, Any] | None:
    if not isinstance(cluster_status, list):
        return None

    cluster_name = None
    node_count = 0

    for item in cluster_status:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "cluster":
            cluster_name = item.get("name") or cluster_name
        if item.get("type") == "node":
            node_count += 1

    return {
        "name": cluster_name,
        "nodes": node_count,
        "raw_preview": cluster_status[:5],
    }


# ---------------------------
# Main diagnostics entrypoint
# ---------------------------

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (public-safe, JSON serializable)."""
    domain_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}) or {}

    client = domain_data.get("client")
    resources = domain_data.get("resources")
    nodes = domain_data.get("nodes")
    guest_coordinators = domain_data.get("guest_coordinators", {}) or {}
    node_coordinators = domain_data.get("node_coordinators", {}) or {}

    # ---- Entry data/options with focused redaction ----
    entry_data = dict(entry.data)
    # Mask secrets
    for key in ("token_value", "password", "api_key", "secret"):
        if key in entry_data:
            entry_data[key] = _redact_secret(entry_data[key])
    # Mask token_name per requirement
    if "token_name" in entry_data:
        entry_data["token_name"] = _mask_token_name(entry_data["token_name"])
    # Host/IP should be masked
    if "host" in entry_data and isinstance(entry_data["host"], str):
        entry_data["host"] = _mask_ipv4_in_text(entry_data["host"])

    options = dict(entry.options)
    # ip_prefix may reveal network; mask if it looks like an IP-ish prefix
    if "ip_prefix" in options and isinstance(options["ip_prefix"], str):
        options["ip_prefix"] = _mask_ipv4_in_text(options["ip_prefix"])

    # ---- Resource previews & counts ----
    res_preview = None
    res_counts = {"nodes": 0, "vms": 0, "containers": 0, "total_guests": 0}
    try:
        if resources and isinstance(resources.data, list):
            res_counts = _count_resources(resources.data)
            res_preview = [
                {
                    "type": r.get("type"),
                    "node": r.get("node"),
                    "vmid": r.get("vmid"),
                    "name": r.get("name"),
                    "status": r.get("status"),
                }
                for r in resources.data[:25]
                if isinstance(r, dict)
            ]
    except Exception:  # noqa: BLE001
        res_preview = None

    node_preview = None
    try:
        if nodes and isinstance(nodes.data, list):
            node_preview = [
                {
                    "node": n.get("node"),
                    "status": n.get("status"),
                    "uptime": n.get("uptime"),
                    "cpu": n.get("cpu"),
                    "mem": n.get("mem"),
                    "maxmem": n.get("maxmem"),
                }
                for n in nodes.data[:15]
                if isinstance(n, dict)
            ]
    except Exception:  # noqa: BLE001
        node_preview = None

    # ---- Proxmox meta information ----
    version_info = await _client_get_json(client, "/version")
    cluster_status = await _client_get_json(client, "/cluster/status")
    cluster_info = _extract_cluster_info(cluster_status)

    proxmox_meta = {
        "version": version_info,
        "cluster": cluster_info,
        "counts": res_counts,
    }

    result = {
        "entry": {
            "entry_id": entry.entry_id,
            # Title can contain IPs (like "Proxmox 192.168.x.x") -> mask it
            "title": _mask_ipv4_in_text(entry.title),
            "data": entry_data,
            "options": options,
        },
        "runtime": {
            "client": {
                "host": _mask_ipv4_in_text(str(getattr(client, "host", ""))) if client else None,
                "port": getattr(client, "port", None) if client else None,
                "verify_ssl": getattr(client, "verify_ssl", None) if client else None,
            },
            "scan_interval": domain_data.get("scan_interval"),
            "ip_mode": domain_data.get("ip_mode"),
            "ip_prefix": _mask_ipv4_in_text(str(domain_data.get("ip_prefix"))) if domain_data.get("ip_prefix") else None,
        },
        "proxmox": proxmox_meta,
        "coordinators": {
            "resources": _safe_coordinator_state(resources),
            "nodes": _safe_coordinator_state(nodes),
            "node_coordinators": _safe_coord_map(node_coordinators),
            "guest_coordinators": _safe_coord_map(guest_coordinators),
        },
        "data_preview": {
            "resources_preview": res_preview,
            "nodes_preview": node_preview,
        },
    }

    # FINAL PASS: mask any IPv4 that still appears anywhere (including cluster raw_preview "ip")
    return _sanitize_public(result)
