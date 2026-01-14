# Changelog

## 0.7.4
- Added Home Assistant Diagnostics support
  - New “Download diagnostics” feature for each Easy Proxmox config entry
  - Diagnostics include:
    - Config entry data and options (sanitized)
    - Runtime client information
    - Coordinator states (last update success, exceptions, update interval)
    - Safe previews of nodes and guests
  - Sensitive data such as API tokens and credentials are automatically redacted
  - Diagnostics are fully JSON-serializable and suitable for GitHub issue attachments

## 0.7.3
- Fixed service execution when using device targets in automations and scripts
- Services now work correctly on Home Assistant versions where `ServiceCall.target` is not available
- Improved target resolution:
  - Supports `device_id` passed via UI targets and via service data
  - Supports `entity_id` targets and automatically resolves them to the corresponding device
  - Accepts both `str` and `list[str]` formats for target identifiers
- Fixed issue where service calls were accepted but no Proxmox action was executed
- Improved compatibility with the Home Assistant automation editor and mobile UI

## 0.7.2
- Fixed service validation for device targets:
  - Home Assistant may pass `device_id` as a list (target/data wrapper)
  - Services now accept both `str` and `list[str]` for `device_id`
  - Improved device target parsing for UI and script wrappers

## 0.7.1
- Fixed Home Assistant service UI integration:
  - Services now properly expose the **Device selector** in the visual automation editor
  - Implemented correct handling of `call.target.device_id`
  - Services are now fully compatible with Home Assistant’s target system
- Fixed issue where only a YAML data field was shown instead of a device selection field
- Improved service robustness when used in multi-host environments
- This release is a bugfix release for v0.7.0

## 0.7.0
- Added full service support for automations and scripts:
  - `proxmox_pve.start`
  - `proxmox_pve.shutdown`
  - `proxmox_pve.stop_hard`
  - `proxmox_pve.reboot`
- Services are now fully multi-host capable:
  - Automatic detection of the correct Proxmox host when using `device_id`
  - Optional selection via `config_entry_id`
  - Optional selection via `host`
  - Automatic lookup by `node/vmid/type` if no host is given
  - Clear error handling for ambiguous multi-host targets
- Services can be used in:
  - Automations
  - Scripts
  - Dashboards
- Added `services.yaml` for proper UI descriptions in Home Assistant
- Easy Proxmox can now be fully controlled without any buttons or switches, purely via automations

## 0.6.1
- Fix correct autor in hacs

## 0.6.0
- Added object structure für using as repositorie in hacs

## 0.6.0-alpha
- Extended Node monitoring with additional sensors:
  - RAM Total (MB) and RAM Free (MB)
  - Swap Used/Total/Free (MB)
  - Node Storage (RootFS) Used/Total/Free in GB (3 decimals)
- Kept existing Node sensors: CPU (%), Load (1m), RAM Used (MB), Uptime (d/h/m)
- No changes to VM/CT entities, cleanup logic, or controls
- Add README.md and LICENSE

## 0.5.2-alpha
- Options are now applied live without restart or integration reload
  - Changing polling interval updates all coordinators immediately
  - Changing IP preference mode/prefix updates all existing guest coordinators immediately
- Triggered refresh after saving options so sensors update quickly
- Renamed integration to "Easy Proxmox (by René Bachmann)"

## 0.5.1-alpha
- Fixed Options Flow crash that caused:
  “Config flow could not be loaded: 500 Internal Server Error”
- Fixed incompatibility with Home Assistant’s `OptionsFlow`:
  - Removed illegal assignment to the read-only `config_entry` property
  - Now fetching the ConfigEntry safely via `self.context["entry_id"]`
- Restored Options (gear icon) in the integration UI
- Options dialog can now be opened and saved without backend errors
- Improved compatibility with newer Home Assistant core versions
- Stabilized Config Flow import and initialization


## 0.5.0-alpha
- Added Options Flow:
  - Configurable polling interval
  - Configurable IP preference mode (prefer 192.168.*, private IPs, any, or custom prefix)
- Added Proxmox Node devices:
  - One device per Proxmox node
  - Sensors for:
    - CPU usage (%)
    - RAM used (MB) and total RAM (attribute)
    - Uptime (days, hours, minutes)
    - Load average (1 minute)
- VM/CT devices are now linked to their node device (via_device)
- Existing dynamic VM handling, rename detection and hard cleanup retained

## 0.4.1
- Fixed entity and device cleanup when a VM/CT is deleted:
  - Entities are fully removed from Entity Registry
  - Devices are fully removed from Device Registry
  - No more “unavailable ghost entities”
- Guaranteed hard cleanup for removed guests

## 0.4.0
- Dynamic VM/CT discovery:
  - New guests appear automatically without reload
  - Removed guests are automatically cleaned up
- Live rename handling:
  - Device names and entity names update when VM name changes
- Improved coordinator lifecycle handling

## 0.3.0
- One Home Assistant device per VM/CT
- Power Switch:
  - ON → Start
  - OFF → Shutdown (soft)
- Buttons:
  - Reboot
  - Stop (hard)
- Sensors per VM/CT:
  - CPU usage (%)
  - RAM usage (MB)
  - Uptime (days, hours, minutes)
  - Network In/Out (MB)
  - Preferred IP address + list of all IPs
- VMID added to device and entity names
- Network and memory values converted to MB
- IP selection prioritizes LAN IPs (e.g. 192.168.*)

## 0.2.0
- Start, Stop and Reboot buttons added
- Domain renamed and integration structure stabilized
- Improved error handling and platform loading

## 0.1.0
- Initial Proxmox VE integration
- API token authentication
- Basic connectivity test via Config Flow
- First experimental entities




