"""
Support for reading Opentherm boiler status data using Toon thermostat's ketelmodule.
Only works for rooted Toon.

configuration.yaml

sensor:
    - platform: toon_boilerstatus
    host: IP_ADDRESS
    port: 80
    scan_interval: 10
"""
import asyncio
import logging
from datetime import timedelta
from typing import Final

import aiohttp
import async_timeout
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (
    DEVICE_CLASS_POWER_FACTOR,
    DEVICE_CLASS_PRESSURE,
    DEVICE_CLASS_TEMPERATURE,
    PLATFORM_SCHEMA,
    STATE_CLASS_MEASUREMENT,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_RESOURCES,
    PERCENTAGE,
    PRESSURE_BAR,
    TEMP_CELSIUS,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle

BASE_URL = "http://{0}:{1}/schedule/config_happ_thermstat.xml"
_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=10)
DEFAULT_NAME = "Toon "

SENSOR_LIST = {
    "toon_huidig_programma",
    "toon_volgend_programma",
    "toon_volgend_volgend_programma",
    "toon_volgend_volgend_volgend_programma"
}

SENSOR_TYPES: Final[tuple[SensorEntityDescription, ...]] = (
    SensorEntityDescription(
        key="huidig_programma",
        name="Huidig programma",
        icon="mdi:calendar",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    SensorEntityDescription(
        key="volgend_programma",
        name="Volgend programma",
        icon="mdi:thermometer",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    SensorEntityDescription(
        key="volgend_volgend_programma",
        name="Volgend volgend programma",
        icon="mdi:flash",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    SensorEntityDescription(
        key="volgend_volgend_volgend_programma",
        name="Volgend volgend volgend programma",
        icon="mdi:gauge",
        native_unit_of_measurement=PRESSURE_BAR,
        device_class=DEVICE_CLASS_PRESSURE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=80): cv.positive_int
        ),
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Setup the Toon Scheduler sensors."""

    session = async_get_clientsession(hass)
    data = ToonSchedulerData(session, config.get(CONF_HOST), config.get(CONF_PORT))
    prefix = config.get(CONF_NAME)
    await data.async_update()

    entities = []
    for description in SENSOR_TYPES:
        _LOGGER.debug("Adding Toon Scheduler sensor: %s", description.name)
        sensor = ToonSchedulerSensor(prefix, description, data)
        entities.append(sensor)
    async_add_entities(entities, True)


# pylint: disable=abstract-method
class ToonSchedulerData:
    """Handle Toon object and limit updates."""

    def __init__(self, session, host, port):
        """Initialize the data object."""

        self._session = session
        self._url = BASE_URL.format(host, port)
        self._data = None
        
    def _process_data(self):
        self._data = None

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Download and update data from Toon."""

        try:
            with async_timeout.timeout(5):
                response = await self._session.get(
                    self._url, headers={"Accept-Encoding": "identity"}
                )
        except aiohttp.ClientError:
            _LOGGER.error("Cannot poll Toon using url: %s", self._url)
            return
        except asyncio.TimeoutError:
            _LOGGER.error(
                "Timeout error occurred while polling Toon using url: %s", self._url
            )
            return
        except Exception as err:
            _LOGGER.error("Unknown error occurred while polling Toon: %s", err)
            self._data = None
            return

        try:
            self._data = await response.json(content_type="text/plain")
            _LOGGER.debug("Data received from Toon: %s", self._data)
            self._process_data()
        except Exception as err:
            _LOGGER.error("Cannot parse data received from Toon: %s", err)
            self._data = None
            return

    @property
    def latest_data(self):
        """Return the latest data object."""
        return self._data


class ToonSchedulerSensor(SensorEntity):
    """Representation of a Toon Scheduler sensor."""

    def __init__(self, prefix, description: SensorEntityDescription, data):
        """Initialize the sensor."""
        self.entity_description = description
        self._data = data
        self._prefix = prefix
        self._type = self.entity_description.key
        self._attr_icon = self.entity_description.icon
        self._attr_name = self._prefix + self.entity_description.name
        self._attr_state_class = self.entity_description.state_class
        self._attr_native_unit_of_measurement = (
            self.entity_description.native_unit_of_measurement
        )
        self._attr_device_class = self.entity_description.device_class
        self._attr_unique_id = f"{self._prefix}_{self._type}"

        self._state = None
        self._last_updated = None

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes of this device."""
        attr = {}
        attr["Last Updated"] = None
        return attr

    async def async_update(self):
        """Get the latest data and use it to update our sensor state."""

        await self._data.async_update()
        data = self._data.latest_data

        self._last_updated = None
        self._state = None

        _LOGGER.debug("Device: %s State: %s", self._type, self._state)
