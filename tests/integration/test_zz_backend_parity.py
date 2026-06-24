"""Integration test verifying both backends produce equivalent events."""

import time
import unittest

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved)

from tests.integration.helpers import (_collect_events,
                                       _collect_events_with_retry,
                                       _ensure_udisks_ready,
                                       _restore_udisks,
                                       udisksctl_available)

ALL_EVENT_TYPES = (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobProperties,
    JobCompleted,
    JobRemoved,
)


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestBackendParity(unittest.TestCase):
    """Compare events from both backends against the same operation sequence.

    The D-Bus backend is tested **first** because the subprocess
    backend spawns ``udisksctl monitor`` which, when terminated,
    drops its D-Bus connection abruptly.  Running the D-Bus backend
    afterwards would inherit a destabilised UDisks2 daemon.

    UDisks2 is restarted once per test class to provide a clean
    daemon state.  Between test methods a readiness check ensures
    UDisks2 is still alive.
    """

    @classmethod
    def setUpClass(cls):
        _restore_udisks()

    def setUp(self):
        _ensure_udisks_ready()

    @staticmethod
    def _dbus_events():
        return _collect_events_with_retry('dbus')

    @staticmethod
    def _subprocess_events():
        time.sleep(1.5)
        return _collect_events('subprocess')

    def test_both_backends_emit_all_event_types(self):
        for backend_fn, label in [(self._dbus_events, 'dbus'),
                                   (self._subprocess_events, 'subprocess')]:
            events = backend_fn()
            self.assertIsNotNone(events,
                                  f'{label} backend failed to connect')
            seen = {type(e) for e in events}
            for et in ALL_EVENT_TYPES:
                self.assertIn(et, seen,
                              f'{et.__name__} missing from {label} backend '
                              f'(saw: {[t.__name__ for t in seen]})')

    def test_both_backends_produce_matching_job_completed(self):
        dbus = self._dbus_events()
        sub = self._subprocess_events()
        self.assertIsNotNone(dbus)
        self.assertIsNotNone(sub)

        dbus_jc = [e for e in dbus if isinstance(e, JobCompleted)]
        sub_jc = [e for e in sub if isinstance(e, JobCompleted)]
        self.assertTrue(dbus_jc)
        self.assertTrue(sub_jc)

        self.assertEqual(type(dbus_jc[0].success), type(sub_jc[0].success))
        dbus_success = any(j.success for j in dbus_jc)
        sub_success = any(j.success for j in sub_jc)
        self.assertEqual(dbus_success, sub_success,
                         'JobCompleted success differs between backends')

    def test_both_backends_produce_matching_device_events(self):
        dbus = self._dbus_events()
        sub = self._subprocess_events()
        self.assertIsNotNone(dbus)
        self.assertIsNotNone(sub)

        dbus_dpc = {e.property: e.value
                    for e in dbus if isinstance(e, DevicePropertyChanged)}
        sub_dpc = {e.property: e.value
                   for e in sub if isinstance(e, DevicePropertyChanged)}

        self.assertTrue(dbus_dpc)
        self.assertTrue(sub_dpc)

        common = set(dbus_dpc) & set(sub_dpc)
        self.assertTrue(common,
                        f'no common properties: dbus={set(dbus_dpc)} sub={set(sub_dpc)}')

    def test_interface_events_emitted_by_both(self):
        dbus = self._dbus_events()
        sub = self._subprocess_events()
        self.assertIsNotNone(dbus)
        self.assertIsNotNone(sub)

        dbus_added = any(isinstance(e, InterfaceAdded) for e in dbus)
        sub_added = any(isinstance(e, InterfaceAdded) for e in sub)
        dbus_removed = any(isinstance(e, InterfaceRemoved) for e in dbus)
        sub_removed = any(isinstance(e, InterfaceRemoved) for e in sub)

        self.assertTrue(dbus_added, 'D-Bus missed InterfaceAdded')
        self.assertTrue(sub_added, 'subprocess missed InterfaceAdded')
        self.assertTrue(dbus_removed, 'D-Bus missed InterfaceRemoved')
        self.assertTrue(sub_removed, 'subprocess missed InterfaceRemoved')
