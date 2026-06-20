"""Integration test verifying both backends produce equivalent events."""

import os
import subprocess
import threading
import unittest

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved, UdisksMonitor)

from tests.integration.helpers import (cleanup, make_image,
                                       udisksctl_available)

SKIP_PARITY = os.environ.get('CI', '') == 'true'

ALL_EVENT_TYPES = (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobProperties,
    JobCompleted,
    JobRemoved,
)


def _collect_events(backend):
    events = []
    interface_added = threading.Event()
    job_completed = threading.Event()

    mon = UdisksMonitor(backend=backend)
    mon.subscribe(lambda _: interface_added.set(), event_type=InterfaceAdded)
    mon.subscribe(lambda _: job_completed.set(), event_type=JobCompleted)
    mon.subscribe(lambda e: events.append(e))
    mon.start()

    if not mon.ready.wait(timeout=10):
        mon.stop()
        mon.join(timeout=5)
        return None

    dev, img, _name = make_image()
    try:
        if not interface_added.wait(timeout=5):
            return None
        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)
        if not job_completed.wait(timeout=5):
            return None
    finally:
        cleanup(dev, img)
        mon.stop()
        mon.join(timeout=5)

    return events


@unittest.skipIf(SKIP_PARITY, 'D-Bus backend overloads UDisks2 daemon in CI')
@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestBackendParity(unittest.TestCase):

    def test_both_backends_emit_all_event_types(self):
        for backend, label in [('subprocess', 'subprocess'),
                               ('dbus', 'D-Bus')]:
            events = _collect_events(backend)
            self.assertIsNotNone(events,
                                 f'{label} backend failed to connect')
            seen = {type(e) for e in events}
            for et in ALL_EVENT_TYPES:
                self.assertIn(et, seen,
                              f'{et.__name__} missing from {label} backend '
                              f'(saw: {[t.__name__ for t in seen]})')

    def test_both_backends_produce_matching_job_completed(self):
        sub = _collect_events('subprocess')
        dbus = _collect_events('dbus')
        self.assertIsNotNone(sub)
        self.assertIsNotNone(dbus)

        sub_jc = [e for e in sub if isinstance(e, JobCompleted)]
        dbus_jc = [e for e in dbus if isinstance(e, JobCompleted)]
        self.assertTrue(sub_jc)
        self.assertTrue(dbus_jc)

        self.assertEqual(type(sub_jc[0].success), type(dbus_jc[0].success))
        sub_success = any(j.success for j in sub_jc)
        dbus_success = any(j.success for j in dbus_jc)
        self.assertEqual(sub_success, dbus_success,
                         'JobCompleted success differs between backends')

    def test_both_backends_produce_matching_device_events(self):
        sub = _collect_events('subprocess')
        dbus = _collect_events('dbus')
        self.assertIsNotNone(sub)
        self.assertIsNotNone(dbus)

        sub_dpc = {e.property: e.value
                   for e in sub if isinstance(e, DevicePropertyChanged)}
        dbus_dpc = {e.property: e.value
                    for e in dbus if isinstance(e, DevicePropertyChanged)}

        self.assertTrue(sub_dpc)
        self.assertTrue(dbus_dpc)

        common = set(sub_dpc) & set(dbus_dpc)
        self.assertTrue(common,
                        f'no common properties: sub={set(sub_dpc)} dbus={set(dbus_dpc)}')

    def test_interface_events_emitted_by_both(self):
        sub = _collect_events('subprocess')
        dbus = _collect_events('dbus')
        self.assertIsNotNone(sub)
        self.assertIsNotNone(dbus)

        sub_added = any(isinstance(e, InterfaceAdded) for e in sub)
        dbus_added = any(isinstance(e, InterfaceAdded) for e in dbus)
        sub_removed = any(isinstance(e, InterfaceRemoved) for e in sub)
        dbus_removed = any(isinstance(e, InterfaceRemoved) for e in dbus)

        self.assertTrue(sub_added, 'subprocess missed InterfaceAdded')
        self.assertTrue(dbus_added, 'D-Bus missed InterfaceAdded')
        self.assertTrue(sub_removed, 'subprocess missed InterfaceRemoved')
        self.assertTrue(dbus_removed, 'D-Bus missed InterfaceRemoved')
