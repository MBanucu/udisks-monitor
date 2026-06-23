"""D-Bus backend — subscribes directly to UDisks2 signals via dbus-fast.

Architecture — thread-safe queued dispatch:
  * Each subscriber gets its own ``queue.Queue`` and daemon thread.
  * The D-Bus handler pushes event objects to matching subscriber
    queues (non-blocking ``put``).
  * Subscribers drain their own queues in dedicated threads.
  * No subscriber callbacks run in the asyncio event-loop thread.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import traceback
from datetime import datetime

from dbus_fast.aio import MessageBus as _AioMessageBus
from dbus_fast import BusType as _BusType
from dbus_fast import Message as _Message
from dbus_fast import MessageType as _MessageType
from dbus_fast.signature import Variant as _Variant

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

# Match only UDisks2 signals by path namespace so the D-Bus daemon
# filters out systemd1 and other service signals before delivery.
# Using 'type=signal' alone or interface-based rules still floods
# the receive buffer (all services share org.freedesktop.DBus.Properties
# and org.freedesktop.DBus.ObjectManager interfaces), causing
# JobCompleted to be dropped.
_ADD_MATCH_RULES = [
    'type=signal,path_namespace=/org/freedesktop/UDisks2',
]


def _device_from_path(path: str) -> str:
    idx = path.find(_BLOCK_DEVICES)
    if idx == -1:
        return ''
    return path[idx + len(_BLOCK_DEVICES):]


def _unwrap(value):
    if isinstance(value, _Variant):
        return value.value
    return value


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
        self._subs: list[tuple] = []

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

        for rule in _ADD_MATCH_RULES:
            reply = await bus.call(_Message(
                destination='org.freedesktop.DBus',
                path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus',
                member='AddMatch',
                signature='s',
                body=[rule],
            ))
            if reply.message_type == _MessageType.ERROR:
                raise RuntimeError(
                    f'AddMatch failed for rule {rule!r}: '
                    f'{reply.body[0] if reply.body else "unknown"}')
            print(f'  [MATCH] rule={rule!r} ok')

        self._stop_signal = asyncio.Event()
        self.ready.set()
        print(f'  [READY] subs={len(self._subs)}')
        await self._stop_signal.wait()
        bus.disconnect()
        print(f'  [STOP]')
        # Drain subscribers after disconnect — no more signals can
        # arrive, so any queued events are already dispatched.
        for _, _, q in self._subs:
            q.put(None)

    def stop(self):
        if self._stop_signal is not None and \
                self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop_signal.set)
            return
        # Monitor never started or already stopped — drain threads
        # need to exit, but _listen() won't inject sentinels.
        for _, _, q in self._subs:
            q.put(None)

    # ── subscriber management ────────────────────────────────────

    def add_subscriber(self, callback, event_type=None):
        q = queue.Queue()
        self._subs.append((callback, event_type, q))
        t = threading.Thread(target=self._drain, args=(q, callback),
                             daemon=True)
        t.start()
        return callback

    @staticmethod
    def _drain(q, callback):
        while True:
            evt = q.get()
            if evt is None:
                break
            try:
                callback(evt)
            except Exception:
                traceback.print_exc()

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

    def _dispatch(self, event):
        for _, event_type, q in self._subs:
            if event_type is None or isinstance(event, event_type):
                q.put(event)
        self._publish(event)

    def _on_interfaces_added(self, object_path, ifaces):
        ts = _timestamp()
        for iface_name, props in ifaces.items():
            if not iface_name.startswith('org.freedesktop.UDisks2.'):
                continue
            if iface_name == 'org.freedesktop.UDisks2.Job':
                job_id = int(object_path.rsplit('/', 1)[1])
                self._dispatch(JobAdded(
                    job_path=object_path, job_id=job_id, timestamp=ts))
                operation = _unwrap(props.get('Operation', ''))
                objects_list = _unwrap(props.get('Objects', []))
                objects = ' '.join(objects_list) if isinstance(objects_list, list) else str(objects_list)
                self._dispatch(JobProperties(
                    job_path=object_path, job_id=job_id,
                    operation=operation, objects=objects, timestamp=ts))
            elif _BLOCK_DEVICES in object_path:
                device = _device_from_path(object_path)
                self._dispatch(InterfaceAdded(
                    object_path=object_path, device_name=device,
                    interface=iface_name,
                    properties={k: _unwrap(v) for k, v in props.items()},
                    timestamp=ts))

    def _on_interfaces_removed(self, object_path, interfaces):
        ts = _timestamp()
        for iface_name in interfaces:
            if not iface_name.startswith('org.freedesktop.UDisks2.'):
                continue
            if iface_name == 'org.freedesktop.UDisks2.Job':
                job_id = int(object_path.rsplit('/', 1)[1])
                self._dispatch(JobRemoved(
                    job_path=object_path, job_id=job_id, timestamp=ts))
            elif _BLOCK_DEVICES in object_path:
                device = _device_from_path(object_path)
                self._dispatch(InterfaceRemoved(
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
            self._dispatch(DevicePropertyChanged(
                object_path=object_path, device_name=device,
                interface=iface_name, property=prop_name,
                value=_unwrap(value), timestamp=ts))

    def _on_job_completed(self, object_path, success, message):
        ts = _timestamp()
        job_id = int(object_path.rsplit('/', 1)[1])
        event = JobCompleted(
            job_path=object_path, job_id=job_id,
            success=success, message=message, timestamp=ts)
        print(f'  [JC] dispatcher subs={len(self._subs)} event={event}')
        self._dispatch(event)
