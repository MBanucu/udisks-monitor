"""D-Bus backend — subscribes directly to UDisks2 signals via dbus-fast."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime

from dbus_fast.aio import MessageBus as _AioMessageBus
from dbus_fast import BusType as _BusType
from dbus_fast import Message as _Message
from dbus_fast import MessageType as _MessageType

from udisks_monitor._backends._base import _Backend
from udisks_monitor._events import (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
)

_BLOCK_DEVICES = '/block_devices/'


def _device_from_path(path: str) -> str:
    idx = path.find(_BLOCK_DEVICES)
    if idx == -1:
        return ''
    return path[idx + len(_BLOCK_DEVICES):]


def _timestamp() -> str:
    return datetime.now().strftime('%H:%M:%S.%f')[:-3]


class _DBusBackend(_Backend):
    """Monitors UDisks2 events via direct D-Bus signal subscription.

    An asyncio event loop is run in the calling thread (which is
    expected to be a dedicated monitor thread).
    """

    def __init__(self, publish):
        super().__init__(publish)
        self._loop = None
        self._stop_signal = None

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._listen())
        except Exception:
            self.ready.set()
        finally:
            loop.close()

    async def _listen(self):
        bus = await _AioMessageBus(bus_type=_BusType.SYSTEM).connect()
        bus.add_message_handler(self._on_message)

        reply = await bus.call(_Message(
            destination='org.freedesktop.DBus',
            path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus',
            member='AddMatch',
            signature='s',
            body=['type=signal'],
        ))
        if reply.message_type == _MessageType.ERROR:
            raise RuntimeError(
                f'AddMatch failed: {reply.body[0] if reply.body else "unknown"}')

        self._stop_signal = asyncio.Event()
        self.ready.set()
        await self._stop_signal.wait()
        bus.disconnect()

    def stop(self):
        if self._stop_signal is not None and \
                self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop_signal.set)

    # ── message routing ──────────────────────────────────────────

    def _on_message(self, msg):
        if msg.message_type != _MessageType.SIGNAL:
            return
        if msg.interface == 'org.freedesktop.DBus.ObjectManager':
            if msg.member == 'InterfacesAdded':
                self._on_interfaces_added(*msg.body)
            elif msg.member == 'InterfacesRemoved':
                self._on_interfaces_removed(*msg.body)
        elif msg.interface == 'org.freedesktop.DBus.Properties':
            if msg.member == 'PropertiesChanged':
                self._on_properties_changed(msg.path, *msg.body)
        elif msg.interface == 'org.freedesktop.UDisks2.Job':
            if msg.member == 'Completed':
                self._on_job_completed(msg.path, *msg.body)

    # ── signal handlers ──────────────────────────────────────────

    def _on_interfaces_added(self, object_path, ifaces):
        ts = _timestamp()
        for iface_name, props in ifaces.items():
            if not iface_name.startswith('org.freedesktop.UDisks2.'):
                continue
            if iface_name == 'org.freedesktop.UDisks2.Job':
                job_id = int(object_path.rsplit('/', 1)[1])
                self._publish(JobAdded(
                    job_path=object_path, job_id=job_id, timestamp=ts))
                operation = props.get('Operation', '')
                objects_list = props.get('Objects', [])
                objects = ' '.join(objects_list) if isinstance(objects_list, list) else str(objects_list)
                self._publish(JobProperties(
                    job_path=object_path, job_id=job_id,
                    operation=operation, objects=objects, timestamp=ts))
            elif _BLOCK_DEVICES in object_path:
                device = _device_from_path(object_path)
                self._publish(InterfaceAdded(
                    object_path=object_path, device_name=device,
                    interface=iface_name, properties=dict(props),
                    timestamp=ts))

    def _on_interfaces_removed(self, object_path, interfaces):
        ts = _timestamp()
        for iface_name in interfaces:
            if not iface_name.startswith('org.freedesktop.UDisks2.'):
                continue
            if iface_name == 'org.freedesktop.UDisks2.Job':
                job_id = int(object_path.rsplit('/', 1)[1])
                self._publish(JobRemoved(
                    job_path=object_path, job_id=job_id, timestamp=ts))
            elif _BLOCK_DEVICES in object_path:
                device = _device_from_path(object_path)
                self._publish(InterfaceRemoved(
                    object_path=object_path, device_name=device,
                    interface=iface_name, timestamp=ts))

    def _on_properties_changed(self, object_path, iface_name, changed, invalidated):
        if _BLOCK_DEVICES not in object_path:
            return
        if not iface_name.startswith('org.freedesktop.UDisks2.'):
            return
        device = _device_from_path(object_path)
        ts = _timestamp()
        for prop_name, value in changed.items():
            self._publish(DevicePropertyChanged(
                object_path=object_path, device_name=device,
                interface=iface_name, property=prop_name, value=value,
                timestamp=ts))

    def _on_job_completed(self, object_path, success, message):
        ts = _timestamp()
        job_id = int(object_path.rsplit('/', 1)[1])
        self._publish(JobCompleted(
            job_path=object_path, job_id=job_id,
            success=success, message=message, timestamp=ts))
