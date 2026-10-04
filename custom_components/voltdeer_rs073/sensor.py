"""Sensors exposed by all scalar fields in the Voltdeer RS073 JSON."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_EXCLUDED_SENSORS,
    CONF_INCLUDE_DIAGNOSTICS,
    CONF_INCLUDE_MEASUREMENTS,
    DOMAIN,
)
from .coordinator import VoltdeerCoordinator


def _scalar_values(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Recursively yield paths and values for every JSON scalar."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _scalar_values(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _scalar_values(child, (*path, str(index)))
    elif path and (value is None or isinstance(value, (str, int, float, bool))):
        yield path, value


def _sensor_metadata(path: tuple[str, ...], value: Any) -> tuple[str | None, str | None, str | None]:
    """Return a suitable device class, unit, and state class when known."""
    key = path[-1]
    if key.endswith("_current") or key == "total_current":
        return SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, SensorStateClass.MEASUREMENT
    if key.endswith("_voltage"):
        return SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, SensorStateClass.MEASUREMENT
    if key.endswith("_act_power") or key == "total_act_power":
        return SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT
    if key.endswith("_aprt_power") or key == "total_aprt_power":
        return SensorDeviceClass.APPARENT_POWER, UnitOfApparentPower.VOLT_AMPERE, SensorStateClass.MEASUREMENT
    if key.endswith("_pf"):
        return None, "%", SensorStateClass.MEASUREMENT
    if key.endswith("_total_act_energy") or key.endswith("_total_act_ret_energy"):
        return SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, SensorStateClass.TOTAL_INCREASING
    if key in {"tC", "tF"}:
        unit = UnitOfTemperature.CELSIUS if key == "tC" else UnitOfTemperature.FAHRENHEIT
        return SensorDeviceClass.TEMPERATURE, unit, SensorStateClass.MEASUREMENT
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None, None, SensorStateClass.MEASUREMENT
    return None, None, None


def _display_name(path: tuple[str, ...]) -> str:
    """Create a readable label while keeping JSON component names visible."""
    return " ".join(part.replace("_", " ").replace(":", " ").title() for part in path)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for all current and subsequently discovered scalar fields."""
    coordinator: VoltdeerCoordinator = hass.data[DOMAIN][entry.entry_id]
    device = DeviceInfo(
        identifiers={(DOMAIN, coordinator.host)},
        name=f"Voltdeer RS073 ({coordinator.host})",
        manufacturer="Voltdeer",
        model="RS073",
        configuration_url=f"http://{coordinator.host}/",
    )
    added_paths: set[tuple[str, ...]] = set()
    options = entry.options
    include_measurements = options.get(CONF_INCLUDE_MEASUREMENTS, True)
    include_diagnostics = options.get(CONF_INCLUDE_DIAGNOSTICS, True)
    excluded = {
        item.strip()
        for item in options.get(CONF_EXCLUDED_SENSORS, "").split(",")
        if item.strip()
    }

    def add_new_sensors() -> None:
        """Create entities for any scalar JSON paths not seen before."""
        new_entities = []
        for path, value in _scalar_values(coordinator.data):
            if path in added_paths:
                continue
            path_name = ".".join(path)
            if path_name in excluded or path[-1] in excluded:
                added_paths.add(path)
                continue

            device_class, _, _ = _sensor_metadata(path, value)
            is_measurement = device_class is not None or path[0] in {"em:0", "emdata:0"}
            if (is_measurement and not include_measurements) or (
                not is_measurement and not include_diagnostics
            ):
                added_paths.add(path)
                continue

            added_paths.add(path)
            new_entities.append(VoltdeerSensor(coordinator, path, value, device))
        if new_entities:
            async_add_entities(new_entities)

    add_new_sensors()
    coordinator.async_add_listener(add_new_sensors)

    if include_measurements:
        for key, name, phase_key in (
            ("total_import_energy", "Total Import Energy (Phase Sum)", "total_act_energy"),
            ("total_export_energy", "Total Export Energy (Phase Sum)", "total_act_ret_energy"),
        ):
            path_name = f"derived.{key}"
            if key not in excluded and path_name not in excluded:
                async_add_entities(
                    [_PhaseSumEnergySensor(coordinator, key, name, phase_key, device)]
                )


class _PhaseSumEnergySensor(CoordinatorEntity[VoltdeerCoordinator], SensorEntity):
    """Sum the three cumulative phase energy counters."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: VoltdeerCoordinator,
        key: str,
        name: str,
        phase_key: str,
        device: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._phase_key = phase_key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.host}_{key}"
        self._attr_device_info = device

    @property
    def native_value(self) -> float | None:
        """Return the sum only when all three phase counters are available."""
        energy = self.coordinator.data.get("emdata:0", {})
        if not isinstance(energy, dict):
            return None
        values = [energy.get(f"{phase}_{self._phase_key}") for phase in "abc"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            return None
        return sum(values)


class VoltdeerSensor(CoordinatorEntity[VoltdeerCoordinator], SensorEntity):
    """Represent one scalar JSON value as a Home Assistant sensor."""

    def __init__(
        self,
        coordinator: VoltdeerCoordinator,
        path: tuple[str, ...],
        initial_value: Any,
        device: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self.path = path
        self._attr_device_info = device
        self._attr_unique_id = f"{coordinator.host}_{re.sub(r'[^a-zA-Z0-9_]+', '_', '.'.join(path)).lower()}"
        self._attr_name = _display_name(path)
        self._attr_device_class, self._attr_native_unit_of_measurement, self._attr_state_class = (
            _sensor_metadata(path, initial_value)
        )

    @property
    def native_value(self) -> Any:
        """Read the latest scalar at this sensor's JSON path."""
        value: Any = self.coordinator.data
        for part in self.path:
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit():
                index = int(part)
                value = value[index] if index < len(value) else None
            else:
                return None
        return value if not isinstance(value, bool) else str(value).lower()
