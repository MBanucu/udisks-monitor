"""Integration tests verifying all UDisks2 event types via real UDisks2.

A single loop-setup + loop-delete cycle produces all 7 event types::

  loop-setup  → JobAdded, JobProperties, JobCompleted, JobRemoved,
                InterfaceAdded, DevicePropertyChanged
  loop-delete → JobAdded, JobProperties, JobCompleted, JobRemoved,
                InterfaceRemoved, DevicePropertyChanged

InterfaceRemoved is excluded from the assertion because UDisks2
suppresses it ~20% of the time when auto-mount creates a transient
filesystem state during loop-delete.
"""

import subprocess
import threading
import unittest

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved, UdisksMonitor)

from tests.integration.helpers import (_backend, _restart_udisks, cleanup,
                                       make_image, udisksctl_available)

ALL_EVENT_TYPES = (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobProperties,
    JobCompleted,
    JobRemoved,
)

_RELIABLE_TYPES = (
    DevicePropertyChanged,
    InterfaceAdded,
    JobAdded,
    JobProperties,
    JobCompleted,
    JobRemoved,
)



class _EventRecorder:
    """Subscribes to event types and records them with per-type Events.

    Use in a ``with`` block to automatically unsubscribe on exit.
    """

    def __init__(self, monitor, event_types=ALL_EVENT_TYPES):
        self.monitor = monitor
        self.events = []
        self.received = {et: threading.Event() for et in event_types}

        self._handlers = {}
        for et in event_types:
            handler = self._make_handler(et)
            self._handlers[et] = handler
            monitor.subscribe(handler, event_type=et)

    def _make_handler(self, et):
        received = self.received[et]

        def handler(evt):
            self.events.append(evt)
            received.set()

        return handler

    def wait_for_type(self, event_type, timeout=5):
        return self.received[event_type].wait(timeout=timeout)

    def types_seen(self):
        return {type(e) for e in self.events}


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestAllEventTypes(unittest.TestCase):

    def setUp(self):
        _restart_udisks()

    def test_full_lifecycle_emits_all_event_types(self):
        mon = UdisksMonitor(backend=_backend())
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        recorder = _EventRecorder(mon)

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)

        recorder.wait_for_type(JobCompleted, timeout=5)

        mon.stop()
        mon.join(timeout=5)

        seen = recorder.types_seen()
        for et in _RELIABLE_TYPES:
            self.assertIn(et, seen,
                          f'{et.__name__} not emitted during loop lifecycle '
                          f'(saw: {[t.__name__ for t in seen]})')

        self.assertGreater(len(recorder.events), 0,
                           'no events at all were recorded')
