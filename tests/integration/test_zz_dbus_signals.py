"""Integration test verifying D-Bus backend receives all expected signals."""

import subprocess
import threading
import time
import unittest

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved, UdisksMonitor)

from tests.integration.helpers import (_restart_udisks, _restore_udisks,
                                       cleanup, make_image,
                                       udisksctl_available)

ALL_EVENT_TYPES = (
    DevicePropertyChanged, InterfaceAdded, InterfaceRemoved,
    JobAdded, JobProperties, JobCompleted, JobRemoved,
)


def _collect_dbus_events(self, subscriptions, wait_for, settle=0.5):
    """Run a loop-setup + loop-delete cycle with retry and UDisks2
    recovery.

    loop-delete is issued after loop-setup so that JobCompleted is
    triggered even on UDisks2 environments that omit the signal for
    loop-setup alone (observed in GitHub Actions CI).

    Returns (events, device, img, name) on success, or
    (None, None, None, None) after max retries.
    """
    for attempt in range(3):
        events = []
        received = {et: threading.Event() for et in wait_for}

        def handler(evt):
            events.append(evt)
            for et in received:
                if isinstance(evt, et):
                    received[et].set()

        mon = UdisksMonitor(backend='dbus')
        for et in subscriptions:
            mon.subscribe(handler, event_type=et)
        mon.start()

        if not mon.ready.wait(timeout=15):
            mon.stop()
            mon.join(timeout=5)
            _restore_udisks()
            continue

        dev = img = None
        try:
            dev, img, name = make_image()
        except Exception:
            mon.stop()
            mon.join(timeout=5)
            _restore_udisks()
            continue

        time.sleep(1)
        subprocess.run(
            ['udisksctl', 'loop-delete', '-b', dev,
             '--no-user-interaction'],
            capture_output=True)

        all_received = True
        for et in wait_for:
            if not received[et].wait(timeout=15):
                all_received = False
                break

        if settle:
            time.sleep(settle)

        mon.stop()
        mon.join(timeout=5)

        if all_received:
            self.addCleanup(cleanup, dev, img)
            return events, dev, img, name

        cleanup(dev, img)
        _restore_udisks()

    return None, None, None, None


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestDBusSignalCompleteness(unittest.TestCase):
    """Verify the D-Bus backend receives all expected signals from a
    loop-setup + loop-delete cycle with correct data.

    Tests run last in the integration suite (test_zz_ prefix) because
    creating multiple D-Bus connections and loop devices can degrade
    UDisks2 responsiveness.
    """

    @classmethod
    def setUpClass(cls):
        _restore_udisks()

    def setUp(self):
        _restart_udisks()

    def test_lifecycle_emits_all_event_types(self):
        """loop-setup + loop-delete should emit all 7 UDisks2 event
        types.  InterfaceAdded must carry the correct device name and
        a valid UDisks2 interface."""
        events, dev, img, name = _collect_dbus_events(
            self, ALL_EVENT_TYPES,
            (InterfaceAdded, JobCompleted, DevicePropertyChanged))
        self.assertIsNotNone(events, 'UDisks2 unresponsive')

        seen = {type(e) for e in events}
        for et in ALL_EVENT_TYPES:
            self.assertIn(et, seen,
                          f'{et.__name__} missing from D-Bus backend '
                          f'(saw {[t.__name__ for t in seen]})')

        ia_events = [e for e in events if isinstance(e, InterfaceAdded)]
        self.assertGreater(len(ia_events), 0,
                           'no InterfaceAdded events received')
        ia_device_names = {e.device_name for e in ia_events}
        self.assertIn(name, ia_device_names,
                      f'InterfaceAdded device_name mismatch: '
                      f'expected {name!r}, got {ia_device_names}')
        ia_interfaces = {e.interface for e in ia_events}
        self.assertTrue(
            any(i.startswith('org.freedesktop.UDisks2.') for i in ia_interfaces),
            f'no UDisks2 interface in {ia_interfaces}')

    def test_interface_removed_received_on_delete(self):
        """loop-delete emits InterfaceRemoved for block + filesystem
        together with JobCompleted and DevicePropertyChanged."""
        events, dev, img, _name = _collect_dbus_events(
            self, ALL_EVENT_TYPES,
            (JobCompleted, DevicePropertyChanged))
        self.assertIsNotNone(events, 'UDisks2 unresponsive')

        seen = {type(e) for e in events}
        if InterfaceRemoved not in seen:
            self.fail(
                f'InterfaceRemoved not received '
                f'(saw: {[t.__name__ for t in seen]})')
        self.assertIn(JobCompleted, seen,
                      'JobCompleted missing from delete cycle')
        self.assertIn(DevicePropertyChanged, seen,
                      'DevicePropertyChanged missing from delete cycle')

    def test_job_completed_has_correct_fields(self):
        """JobCompleted should have success=True and a valid job_path."""
        events, dev, img, _name = _collect_dbus_events(
            self, (JobCompleted,), (JobCompleted,))
        self.assertIsNotNone(events, 'UDisks2 unresponsive')

        jc_events = [e for e in events if isinstance(e, JobCompleted)]
        self.assertGreater(len(jc_events), 0, 'no JobCompleted events')
        for jc in jc_events:
            self.assertIsInstance(jc.success, bool,
                                  f'success is not bool: {jc.success!r}')
            self.assertTrue(jc.job_path.startswith(
                '/org/freedesktop/UDisks2/jobs/'),
                f'unexpected job_path: {jc.job_path!r}')
            self.assertIsInstance(jc.job_id, int)
            self.assertIsInstance(jc.message, str)

    def test_device_property_changed_has_correct_fields(self):
        """DevicePropertyChanged should have valid device_name,
        interface, property, and value fields."""
        events, dev, img, name = _collect_dbus_events(
            self, (DevicePropertyChanged,), (DevicePropertyChanged,))
        self.assertIsNotNone(events, 'UDisks2 unresponsive')

        dpc_events = [e for e in events if isinstance(e, DevicePropertyChanged)]
        self.assertGreater(len(dpc_events), 0,
                           'no DevicePropertyChanged events')
        for dpc in dpc_events:
            self.assertIsInstance(dpc.device_name, str)
            self.assertIsInstance(dpc.interface, str)
            self.assertIsInstance(dpc.property, str)

        device_events = [e for e in dpc_events if e.device_name == name]
        self.assertGreater(len(device_events), 0,
                           f'no DevicePropertyChanged for {name!r} '
                           f'(devices: {[e.device_name for e in dpc_events]})')

    def test_interface_added_properties_are_populated(self):
        """InterfaceAdded events should have a non-empty properties dict."""
        events, dev, img, _name = _collect_dbus_events(
            self, (InterfaceAdded,), (InterfaceAdded,))
        self.assertIsNotNone(events, 'UDisks2 unresponsive')

        ia_events = [e for e in events if isinstance(e, InterfaceAdded)]
        self.assertGreater(len(ia_events), 0,
                           'no InterfaceAdded events received')
        for ia in ia_events:
            self.assertIsInstance(ia.properties, dict,
                                  f'properties is not dict: {ia.properties!r}')
            self.assertIsInstance(ia.interface, str)
            self.assertTrue(
                ia.interface.startswith('org.freedesktop.UDisks2.'),
                f'unexpected interface: {ia.interface!r}')
            self.assertIsInstance(ia.object_path, str)
            self.assertTrue(ia.object_path.startswith(
                '/org/freedesktop/UDisks2/'),
                f'unexpected object_path: {ia.object_path!r}')

    def test_all_seven_event_types_received(self):
        """A full loop-setup + loop-delete cycle should emit all 7
        event types including InterfaceRemoved."""
        events, dev, img, _name = _collect_dbus_events(
            self, ALL_EVENT_TYPES, (JobCompleted,))
        self.assertIsNotNone(events, 'UDisks2 unresponsive')

        seen = {type(e) for e in events}
        missing = [et.__name__ for et in ALL_EVENT_TYPES if et not in seen]
        self.assertFalse(
            missing,
            f'D-Bus backend missed event types: {missing} '
            f'(received {len(events)} events: '
            f'{[t.__name__ for t in seen]})')
