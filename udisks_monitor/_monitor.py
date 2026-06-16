"""UdisksMonitor — spawns udisksctl monitor in a background thread."""

from __future__ import annotations

import subprocess
import threading

from udisks_monitor._events import Event
from udisks_monitor._parser import MonitorParser
from udisks_monitor._pubsub import Callback, EventBus


class UdisksMonitor(threading.Thread):
    """Background thread that runs ``udisksctl monitor`` and publishes events.

    Parameters
    ----------
    bus:
        The :class:`EventBus` to publish events to.  A default bus is
        created if not provided.
    """

    def __init__(self, bus: EventBus | None = None):
        super().__init__(daemon=True)
        self.bus = bus or EventBus()
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._parser = MonitorParser()
        self._proc = None

    def stop(self):
        """Signal the monitor loop to exit and terminate the subprocess."""
        self._stop.set()
        if self._proc is not None:
            self._proc.terminate()

    def run(self):
        try:
            proc = subprocess.Popen(
                ['udisksctl', 'monitor'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            self._proc = proc
        except Exception:
            self.ready.set()
            return

        try:
            first = proc.stdout.readline()
        except Exception:
            proc.terminate()
            proc.wait()
            self.ready.set()
            return

        self.ready.set()
        self._feed(first)

        try:
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                self._feed(line)
        finally:
            proc.stdout.close()
            proc.terminate()
            proc.wait()

    def _feed(self, line: str):
        event = self._parser.feed(line)
        if event is not None:
            self.bus.publish(event)

    def subscribe(self, callback: Callback, **filters) -> Callback:
        """Shortcut: ``monitor.subscribe(fn, device='loop0')``."""
        return self.bus.subscribe(callback, **filters)

    def on(self, event_type=None, **filters):
        """Shortcut decorator: ``@monitor.on(…, device='loop0')``."""
        return self.bus.on(event_type, **filters)
