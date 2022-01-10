"""
Support for reading Toon Scheduling data
Only works for rooted Toon.

configuration.yaml

sensor:
    - platform: toon_scheduler
    host: IP_ADDRESS
    port: 80
    scan_interval: 10
"""
import asyncio
import json
import logging
from datetime import timedelta
from typing import Final

import xmltodict
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
from datetime import datetime, timedelta
from functools import total_ordering

import pytz as pytz

BASE_URL = "http://{0}:{1}/happ_thermstat?action=getWeeklyList"
_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=1)
DEFAULT_NAME = "Toon "

SENSOR_LIST = {
    "toon_scheduler_1",
    "toon_scheduler_2",
    "toon_scheduler_3",
    "toon_scheduler_4"
}

SENSOR_TYPES: Final[tuple[SensorEntityDescription, ...]] = (
    SensorEntityDescription(
        key="1",
        name="Huidig programma",
        icon="mdi:calendar-clock"
    ),
    SensorEntityDescription(
        key="2",
        name="Volgend programma",
        icon="mdi:calendar-clock"
    ),
    SensorEntityDescription(
        key="3",
        name="Volgend volgend programma",
        icon="mdi:calendar-clock"
    ),
    SensorEntityDescription(
        key="4",
        name="Volgend volgend volgend programma",
        icon="mdi:calendar-clock"
    ),
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=80): cv.positive_int,
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
            _LOGGER.error("Timeout error occurred while polling Toon using url: %s", self._url)
            return
        except Exception as err:
            _LOGGER.error("Unknown error occurred while polling Toon: %s", err)
            self._data = None
            return

        try:
            self._data = await response.text()
            _LOGGER.debug("Data received from Toon: %s", self._data)

            self._data = self._data \
                .replace("targetState", '"targetState"') \
                .replace("weekDay", '"weekDay"') \
                .replace("startTimeT", '"startTimeT"') \
                .replace("endTimeT", '"endTimeT"') \
                .replace("'", '"') \
                .replace("result", '"result"') \
                .replace("programs", '"programs"')
            self._data = json.loads(self._data)
            self._data = Schedule(self._data["programs"])
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
        self._attr_name = "toon_scheduler_" + self._type
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
        return self._data.latest_data.get_schedule(int(self._type)).get_ha_attrs()

    async def async_update(self):
        """Get the latest data and use it to update our sensor state."""

        await self._data.async_update()
        self._state = self._data.latest_data.get_schedule(int(self._type)).get_ha_state()
        _LOGGER.debug("Device: %s State: %s", self._type, self._state)


class Schedule:
    STATES = {"Sleep": "slapen", "Active": "thuis", "Relax": "comfort", "Away": "weg"}

    WEEKDAYS = ["zondag", "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag"]
    RELATIVE_DAYS = ["vandaag", "morgen", "overmorgen"]

    def __init__(self, data):
        self._schedule = list(map(self.ScheduleItem, data))
        self._schedule.sort()

    def get_schedule(self, i):
        return self._schedule[i]

    def __str__(self):
        return "\n".join(map(str, self._schedule))

    class ScheduleItem:
        def __init__(self, data):
            self.state = Schedule.STATES[data["targetState"]]
            self.start_time = datetime.fromtimestamp(int(data["startTimeT"]), pytz.timezone('Europe/Amsterdam'))
            self.end_time = datetime.fromtimestamp(int(data["endTimeT"]), pytz.timezone('Europe/Amsterdam'))
            relative_day = (self.start_time.weekday() - datetime.now(
                pytz.timezone("Europe/Amsterdam")).weekday() + 6) % 6
            self.day = Schedule.RELATIVE_DAYS[relative_day] if 0 <= relative_day < 3 else Schedule.WEEKDAYS[
                int(data["weekDay"])]

        def __lt__(self, other):
            return self.start_time < other.start_time

        def __eq__(self, other):
            return self.start_time == other.start_time

        def __str__(self):
            return f"{self.state} | op {self.day} vanaf {self.start_time.strftime('%H:%M:%S')}"

        def get_ha_attrs(self):
            return {"start_day": self.day, "start_time": self.start_time.strftime("%H:%M")}

        def get_ha_state(self):
            return self.state
