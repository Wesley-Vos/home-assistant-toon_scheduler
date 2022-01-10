[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)  [![made-with-python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)](https://www.python.org/) 

# Toon Scheduler Sensor Component
This is a Custom Component for Home-Assistant (https://home-assistant.io) that reads the weekly schedule of a rooted Toon Thermostat

NOTE: This component only works with rooted Toon devices.
Toon thermostats are available in The Netherlands and Belgium.

More information about rooting your Toon can be found here:
[Eneco Toon as Domotica controller](http://www.domoticaforum.eu/viewforum.php?f=87)

## Installation

### HACS - Recommended
- Have [HACS](https://hacs.xyz) installed, this will allow you to easily manage and track updates.
- Search for 'Toon Boiler Status'.
- Click Install below the found integration.
- Configure using the configuration instructions below.
- Restart Home-Assistant.

### Manual
- Copy directory `custom_components/toon_scheduler` to your `<config dir>/custom_components` directory.
- Configure with config below.
- Restart Home-Assistant.

## Usage
To use this component in your installation, add the following to your `configuration.yaml` file:

```yaml
# Example configuration.yaml entry

sensor:
  - platform: toon_scheduler
    name: Toon
    host: IP_ADDRESS
    port: 80
```

Configuration variables:

- **name** (*Optional*): Prefix name of the sensors. (default = 'Toon')
- **host** (*Required*): The IP address on which the Toon can be reached.
- **port** (*Optional*): Port used by your Toon. (default = 80)

## Example card
An example card to display the information can be this
```yaml
{% if is_state('climate.<toon thermostaat>', 'heat') %}
 **Let op!** Het programma is **uitgeschakeld**.
{% else %} 
Thermostaat schakelt volgens programma {% endif %}

*** 

#### Volgende programma's
**{{ states('sensor.toon_scheduler_2') | capitalize}}** |  {{ state_attr('sensor.toon_scheduler_2', 'start_day')}} om {{ state_attr('sensor.toon_scheduler_2', 'start_time') }}
**{{ states('sensor.toon_scheduler_3') | capitalize}}** |  {{ state_attr('sensor.toon_scheduler_3', 'start_day')}} om {{ state_attr('sensor.toon_scheduler_3', 'start_time') }}
**{{ states('sensor.toon_scheduler_4') | capitalize}}** |  {{ state_attr('sensor.toon_scheduler_4', 'start_day')}} om {{ state_attr('sensor.toon_scheduler_4', 'start_time') }}
```

## Debugging

Add the relevant lines below to the `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.toon_scheduler: debug
```
