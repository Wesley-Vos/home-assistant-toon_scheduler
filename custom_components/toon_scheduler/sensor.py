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

BASE_URL = "http://{0}:{1}/schedule/config_happ_thermstat.xml"
_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=10)
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
            _LOGGER.error(
                "Timeout error occurred while polling Toon using url: %s", self._url
            )
            return
        except Exception as err:
            _LOGGER.error("Unknown error occurred while polling Toon: %s", err)
            self._data = None
            return

        try:
            self._data = await response.text()
            _LOGGER.debug("Data received from Toon: %s", self._data)
            self._data = ToonSync(self._process_data())
        except Exception as err:
            _LOGGER.error("Cannot parse data received from Toon: %s", err)
            self._data = None
            return

    @property
    def latest_data(self):
        """Return the latest data object."""
        return self._data

    def _process_data(self):
        response_dict = xmltodict.parse(self._data).get('Config').get('device')
        return [r for r in response_dict if "schedule" in r][0].get('schedule').get('entry')


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
        self._total_state = None
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
        attr["start_day"] = self._total_state.ha_start_day
        attr["start_time"] = self._total_state.ha_start_time
        attr["end_day"] = self._total_state.ha_end_day
        attr["end_time"] = self._total_state.ha_end_time
        return attr

    async def async_update(self):
        """Get the latest data and use it to update our sensor state."""

        await self._data.async_update()
        data = self._data.latest_data

        self._total_state = data.get_schedule(int(self._type) - 1)
        self._state = self._total_state.state
        #self._state = 1

        _LOGGER.debug("Device: %s State: %s", self._type, self._state)


class ToonSync:
    def __init__(self, data):
        self.schedule = []
        for d in data:
            item = ToonScheduleItem(d.get('startDayOfWeek'), d.get('endDayOfWeek'), d.get('startHour'),
                                    d.get('startMin'),
                                    d.get('endHour'), d.get('endMin'), d.get('targetState'))
            self.schedule.append(item)
        self.schedule.sort()
        self.data = []
        self._store_data()

    def _current_item_idx(self):
        today = datetime.today().weekday()
        time = datetime.now(pytz.timezone('Europe/Amsterdam')).time()

        for idx, item in enumerate(self.schedule):
            # start_day and end_day both today
            if int(item.start_day) == today and int(item.end_day) == today and item.start_dt < time < item.end_dt:
                return idx
            # start_day is before today and end_day is today
            elif int(item.start_day) < today and int(item.end_day) == today and time < item.end_dt:
                return idx
            # start_day is today and end_day is after today
            elif int(item.start_day) == today and int(item.end_day) > today and time > item.start_dt:
                return idx
                # start_day is before today and end_day is after today
            elif int(item.start_day) < today < int(item.end_day):
                return idx
            # start_day is sunday (6) and end_day is monday (0)
            elif int(item.start_day) > int(item.end_day) and (
                    (int(item.start_day) == today and time > item.start_dt) or (
                    int(item.end_day) == today and time < item.end_dt)):
                return idx

    def _store_data(self):
        current_idx = self._current_item_idx()
        for _ in range(4):
            self.data.append(self.schedule[current_idx])
            current_idx = (current_idx + 1) % len(self.schedule)
    
    def get_schedule(self, i):
        return self.data[i]


def leading_zero(x):
    return x if int(x) >= 10 else "0" + x


def format_time(hour, minute):
    return leading_zero(hour) + ":" + leading_zero(minute)


@total_ordering
class ToonScheduleItem:
    def __init__(self, start_day, end_day, start_hour, start_min, end_hour, end_min, state):
        self.start_day = str((int(start_day) + 6) % 7)
        self.end_day = str((int(end_day) + 6) % 7)
        self.start_time = format_time(start_hour, start_min)
        self.end_time = format_time(end_hour, end_min)
        self.start_dt = datetime.strptime(self.start_time, "%H:%M").time()
        self.end_dt = datetime.strptime(self.end_time, "%H:%M").time()
        self.state = state
        self._toState()

    def __str__(self):
        return str(self.start_day) + " - " + str(self.end_day) + " - " + str(self.start_time) + " - " + str(
            self.end_time) + " - " + str(self.state)

    def __lt__(self, other):
        return (self.start_day < other.start_day) or (
                self.start_day == other.start_day and self.start_time < other.start_time)

    def __eq__(self, other):
        return self.start_day == other.start_day and self.end_day == other.end_day and self.start_time == other.start_time and self.end_time == other.end_time

    def _toState(self):
        states = ["comfort", "thuis", "slapen", "weg"]
        days = ["eergisteren", "gisteren", "vandaag", "morgen", "overmorgen"]
        today = datetime.now(pytz.timezone('Europe/Amsterdam')).weekday()

        try:
            self.state = states[int(self.state)]
            self.ha_start_day = days[(int(self.start_day) - today + 6) % 6 + 2]
            self.ha_end_day = days[(int(self.end_day) - today + 6) % 6 + 2]
            self.ha_start_time = self.start_time
            self.ha_end_time = self.end_time
        except IndexError:
            _LOGGER.error("Encountered index error while generating states")
            self.state = None
            self.state = None
            self.ha_start_day = None
            self.ha_end_day = None
            self.ha_start_time = None
            self.ha_end_time = None

