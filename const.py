DOMAIN = "proxmox_pve"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_VERIFY_SSL = "verify_ssl"
CONF_TOKEN_NAME = "token_name"
CONF_TOKEN_VALUE = "token_value"

# Options
CONF_SCAN_INTERVAL = "scan_interval"
CONF_IP_MODE = "ip_mode"
CONF_IP_PREFIX = "ip_prefix"

DEFAULT_PORT = 8006
DEFAULT_VERIFY_SSL = True

DEFAULT_SCAN_INTERVAL = 20

IP_MODE_PREFER_192168 = "prefer_192168"
IP_MODE_PREFER_PRIVATE = "prefer_private"
IP_MODE_ANY = "any"
IP_MODE_CUSTOM_PREFIX = "custom_prefix"

DEFAULT_IP_MODE = IP_MODE_PREFER_192168
DEFAULT_IP_PREFIX = "192.168."

PLATFORMS = ["sensor", "switch", "button"]
