<img width="1230" height="300" alt="logo" src="https://github.com/user-attachments/assets/7649cc04-bdcd-449e-bf83-c4f980f3de74" />

A powerful Home Assistant integration to monitor and control Proxmox VE. With Easy Proxmox you can monitor nodes, VMs and containers directly in Home Assistant, start/stop/reboot guests and display detailed system metrics.

## Features

### Per Node
- CPU usage (%)
- Load Average (1 minute)
- RAM Used / Total / Free (MB)
- Swap Used / Total / Free (MB)
- Storage (RootFS):
  - Used / Total / Free (GB, 3 decimals)
- Uptime (days, hours, minutes)

### Per VM / Container
- Status (running, stopped, etc.)
- CPU usage (%)
- RAM usage (MB)
- Uptime (days, hours, minutes)
- Network In / Out (MB)
- IP address (preferred IP is configurable)
- Power Switch:
  - ON = Start
  - OFF = Shutdown (soft)
- Buttons:
  - Reboot
  - Stop (hard)

### Dynamic Behavior
- New VMs/CTs appear automatically
- Deleted VMs/CTs are fully removed (no “ghost devices”)
- Renames are applied live
- Options are applied live (no restart required)

---

## Installation

1. Create the folder:
    /config/custom_components/proxmox_pve/


2. Copy all integration files into that folder.

3. Restart Home Assistant.

4. Add the integration:
    
    Settings → Devices & Services → Add Integration → Easy Proxmox

---

## Proxmox: Create User & API Token

### 1) Create a User
In the Proxmox Web UI:

    Datacenter → Permissions → Users → Add


Example:
- Username: `homeassistant`
- Realm: `pam` or `pve`
- Set a password (only for management; the token will be used for API access)

---

### 2) Create an API Token

Datacenter → Permissions → API Tokens → Add


- User: `homeassistant@pve`
- Token ID: `easyproxmox`
- Privilege Separation: **disabled** (important!)
- Create → copy & store the Token Secret

You will get:
    
    Token Name: homeassistant@pve!easyproxmox
    Token Secret: <long secret string>


---

### 3) Assign Permissions (Admin Rights)

To ensure full functionality (monitoring + guest controls), assign admin rights:

    Datacenter → Permissions → Add
    

- Path: `/`
- User: `homeassistant@pve`
- Role: `PVEAdmin`

This allows the integration to:
- read node status
- read VM/CT status
- start/stop/shutdown/reboot guests
- query QEMU Guest Agent (for IP discovery)

---

## Set Up the Integration in Home Assistant

When adding the integration, you will be asked for:

| Field | Meaning |
|------|---------|
| Host | IP address or hostname of your Proxmox server |
| Port | Default: `8006` |
| Verify SSL | Enable only if your certificate is valid/trusted |
| Token Name | e.g. `homeassistant@pve!easyproxmox` |
| Token Secret | The generated API token secret |

After saving:
- One device is created per Proxmox node
- VM/CT devices are linked below their node device

---

## Options (Gear Icon)

After setup, open:
    Settings → Devices & Services → Easy Proxmox → Options (gear icon)
    

### Polling Interval
How often data is fetched from Proxmox.

| Value | Description |
|------|-------------|
| 5 seconds | Very fast, higher API load |
| 10–20 seconds | Recommended |
| >30 seconds | Lower API load |

Changes are applied immediately (no restart required).

---

### IP Preference Mode

Controls which IP is shown as the “primary” IP for a guest:

| Mode | Description |
|------|------------|
| prefer_192168 | Prefer 192.168.x.x |
| prefer_private | Prefer private networks (10.x, 172.16–31.x, 192.168.x) |
| any | Use the first available IP |
| custom_prefix | Use a custom prefix |

---

### Custom IP Prefix

Only relevant if `custom_prefix` is selected.

Examples:
- `10.0.`
- `192.168.178.`
- `172.20.`

This allows you to force a specific subnet to be selected as the guest’s preferred IP.

---

## Recommended Network Configuration

For reliable guest IP detection:
- Enable **QEMU Guest Agent** in VMs
- Ensure the guest receives valid IPs (DHCP/static)
- If only loopback/link-local addresses exist, no useful IP can be selected

---

## Device Structure in Home Assistant

Easy Proxmox
└── Proxmox Node pve1
├── CPU
├── RAM Used / Free / Total
├── Swap Used / Free / Total
├── Storage Used / Free / Total
├── Uptime
└── VM: HomeAssistant (VMID 100)
├── Status
├── CPU
├── RAM
├── Network In / Out
├── IP
├── Power Switch
├── Reboot Button
└── Stop (hard) Button


---

## Security Notice

The API token has admin rights. Treat it like a root password:
- never share it publicly
- store it only in Home Assistant
- revoke and regenerate it if compromised

---

## Troubleshooting

|           Issue           |                                        Fix                                             |
|---------------------------|----------------------------------------------------------------------------------------|
| Integration won’t load    | Check logs: Settings → System → Logs                                                   |
| No IP shown               | QEMU Guest Agent missing OR IP preference mode not matching your subnet                |
| Buttons don’t work        | Check Proxmox permissions (PVEAdmin role)                                              |
| Old devices remain        | Fully cleaned up automatically since version 0.4.1                                     |

---

## License / Support

For public release, add a license file (MIT / Apache 2.0 recommended).

---

**Easy Proxmox aims to provide a complete Proxmox VE experience in Home Assistant.**
