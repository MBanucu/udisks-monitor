"""Event-driven pub/sub wrapper around ``udisksctl monitor``.

Provides :class:`UdisksMonitor`, an :class:`EventBus`, and typed event
dataclasses for every event that the UDisks2 daemon can emit::

    from udisks_monitor import UdisksMonitor, DevicePropertyChanged

    mon = UdisksMonitor()

    @mon.on(DevicePropertyChanged, device='loop0', property_='BackingFile')
    def on_backing(evt):
        if not evt.value:
            print(f"{evt.device_name} detached")

    mon.start()
    mon.join()
"""

from udisks_monitor._events import (
    DevicePropertyChanged,
    Event,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
)
from udisks_monitor._monitor import UdisksMonitor
from udisks_monitor._pubsub import EventBus, SubscriptionFilter

__all__ = [
    'DevicePropertyChanged',
    'Event',
    'EventBus',
    'InterfaceAdded',
    'InterfaceRemoved',
    'JobAdded',
    'JobCompleted',
    'JobProperties',
    'JobRemoved',
    'SubscriptionFilter',
    'UdisksMonitor',
]
