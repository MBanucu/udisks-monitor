"""Event dataclasses emitted by the udisksctl monitor parser."""

from dataclasses import dataclass
from typing import Any


class Event:
    """Base class for all monitor events."""


@dataclass(slots=True)
class DevicePropertyChanged(Event):
    """A single property on a device interface changed value."""
    object_path: str
    device_name: str
    interface: str
    property: str
    value: Any


@dataclass(slots=True)
class InterfaceAdded(Event):
    """A new D-Bus interface was added to a device."""
    object_path: str
    device_name: str
    interface: str
    properties: dict[str, Any]


@dataclass(slots=True)
class InterfaceRemoved(Event):
    """A D-Bus interface was removed from a device."""
    object_path: str
    device_name: str
    interface: str


@dataclass(slots=True)
class JobAdded(Event):
    """A new UDisks2 job was created."""
    job_path: str
    job_id: int


@dataclass(slots=True)
class JobProperties(Event):
    """Job metadata (operation and target objects)."""
    job_path: str
    job_id: int
    operation: str
    objects: str


@dataclass(slots=True)
class JobCompleted(Event):
    """A job finished (success or failure)."""
    job_path: str
    job_id: int
    success: bool
    message: str


@dataclass(slots=True)
class JobRemoved(Event):
    """A job object was removed from the UDisks2 tree."""
    job_path: str
    job_id: int
