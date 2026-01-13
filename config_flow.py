import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .api import ProxmoxClient, ProxmoxApiError
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_VERIFY_SSL,
    CONF_TOKEN_NAME,
    CONF_TOKEN_VALUE,
    DEFAULT_PORT,
    DEFAULT_VERIFY_SSL,
    # options
    CONF_SCAN_INTERVAL,
    CONF_IP_MODE,
    CONF_IP_PREFIX,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_IP_MODE,
    DEFAULT_IP_PREFIX,
    IP_MODE_PREFER_192168,
    IP_MODE_PREFER_PRIVATE,
    IP_MODE_ANY,
    IP_MODE_CUSTOM_PREFIX,
)


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
        vol.Required(CONF_TOKEN_NAME): str,
        vol.Required(CONF_TOKEN_VALUE): str,
    }
)


async def _validate_input(data: dict) -> None:
    async with aiohttp.ClientSession() as session:
        client = ProxmoxClient(
            host=data[CONF_HOST],
            port=int(data[CONF_PORT]),
            token_name=data[CONF_TOKEN_NAME],
            token_value=data[CONF_TOKEN_VALUE],
            verify_ssl=bool(data[CONF_VERIFY_SSL]),
            session=session,
        )
        await client.test_connection()


def _options_schema(current: dict) -> vol.Schema:
    ip_modes = [IP_MODE_PREFER_192168, IP_MODE_PREFER_PRIVATE, IP_MODE_ANY, IP_MODE_CUSTOM_PREFIX]
    return vol.Schema(
        {
            vol.Required(CONF_SCAN_INTERVAL, default=int(current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))): vol.All(
                vol.Coerce(int), vol.Range(min=5, max=3600)
            ),
            vol.Required(CONF_IP_MODE, default=current.get(CONF_IP_MODE, DEFAULT_IP_MODE)): vol.In(ip_modes),
            vol.Required(CONF_IP_PREFIX, default=current.get(CONF_IP_PREFIX, DEFAULT_IP_PREFIX)): str,
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}

        if user_input is not None:
            unique = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_TOKEN_NAME]}"
            await self.async_set_unique_id(unique)
            self._abort_if_unique_id_configured()

            try:
                await _validate_input(user_input)
            except ProxmoxApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                title = f"Proxmox {user_input[CONF_HOST]}"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        # IMPORTANT: Do not store config_entry on OptionsFlowHandler as attribute named config_entry.
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None) -> FlowResult:
        # Fetch the config entry safely (works across HA versions)
        entry_id = self.context.get("entry_id")
        config_entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None

        current = dict(config_entry.options) if config_entry else {}

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=_options_schema(current))
