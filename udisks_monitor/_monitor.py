"""UdisksMonitor — delegates to a pluggable backend in a background thread."""

from __future__ import annotations

import threading

from udisks_monitor._backends import _get_backend
from udisks_monitor._pubsub import Callback, EventBus

_COMPLEX_FILTERS = frozenset({'device', 'interface', 'operation', 'property_'})


class UdisksMonitor(threading.Thread):
    """Background thread that monitors UDisks2 events and publishes them.

    Parameters
    ----------
    bus:
        The :class:`EventBus` to publish events to.  A default bus is
        created if not provided.
    backend:
        ``'auto'`` (default) — try the D-Bus backend, fall back to
        the subprocess backend if ``dbus-fast`` is unavailable.
        ``'subprocess'`` — always spawn ``udisksctl monitor`` and
        parse its text output.
        ``'dbus'`` — subscribe directly to UDisks2 D-Bus signals
        (requires ``pip install udisks-monitor[dbus]``).
    """

    def __init__(self, bus: EventBus | None = None, backend: str = 'auto'):
        super().__init__(daemon=True)
        self.bus = bus or EventBus()
        self._backend = _get_backend(backend, self._publish)
        self.ready = self._backend.ready

    def _publish(self, event):
        self.bus.publish(event)

    def run(self):
        self._backend.run()

    def stop(self):
        """Signal the monitor loop to exit."""
        self._backend.stop()

    def subscribe(self, callback: Callback, **filters) -> Callback:
        """Shortcut: ``monitor.subscribe(fn, device='loop0')``."""
        if hasattr(self._backend, 'add_subscriber') and \
                not (_COMPLEX_FILTERS & filters.keys()):
            event_type = filters.get('event_type')
            return self._backend.add_subscriber(callback, event_type)
        return self.bus.subscribe(callback, **filters)

    def on(self, event_type=None, **filters):
        """Shortcut decorator: ``@monitor.on(…, device='loop0')``."""
        def _decorator(fn):
            return self.subscribe(fn, event_type=event_type, **filters)
        return _decorator
