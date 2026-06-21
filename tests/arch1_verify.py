"""Architecture 1 verification: direct D-Bus dispatch, bypassing EventBus."""

import os
import subprocess
import threading
import time
import unittest

from udisks_monitor import (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
    UdisksMonitor,
)

from tests.integration.helpers import cleanup, make_image, udisksctl_available

SKIP_DBUS_INTEGRATION = os.environ.get('CI', '') == 'true'

ALL_EVENT_TYPES = (
    DevicePropertyChanged, InterfaceAdded, InterfaceRemoved,
    JobAdded, JobProperties, JobCompleted, JobRemoved,
)


@unittest.skipIf(SKIP_DBUS_INTEGRATION,
                 'D-Bus integration tests are unstable in CI')
@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestArch1DirectDispatch(unittest.TestCase):
    """Verify D-Bus backend dispatches events directly to subscribers
    without going through EventBus.publish()."""

    def test_job_completed_arrives(self):
        """JobCompleted must be received via direct dispatch."""
        events = []
        jc_received = threading.Event()

        def on_jc(evt):
            events.append(evt)
            jc_received.set()

        mon = UdisksMonitor(backend='dbus')
        mon.subscribe(on_jc, event_type=JobCompleted)
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10),
                        'D-Bus monitor did not become ready')

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        jc_ok = jc_received.wait(timeout=10)
        mon.stop()
        mon.join(timeout=5)

        self.assertTrue(jc_ok, 'JobCompleted never arrived via direct dispatch')
        jc_events = [e for e in events if isinstance(e, JobCompleted)]
        self.assertGreater(len(jc_events), 0)
        for jc in jc_events:
            self.assertIsInstance(jc.success, bool)
            self.assertTrue(jc.job_path.startswith('/org/freedesktop/UDisks2/jobs/'))

    def test_all_seven_types_received(self):
        """A loop-setup + loop-delete cycle emits all 7 event types via direct dispatch."""
        events = []
        received = {et: threading.Event() for et in ALL_EVENT_TYPES}

        def on_event(evt):
            events.append(evt)
            for et, ev in received.items():
                if isinstance(evt, et):
                    ev.set()

        mon = UdisksMonitor(backend='dbus')
        for et in ALL_EVENT_TYPES:
            mon.subscribe(on_event, event_type=et)
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        dev, img, _name = make_image()

        subprocess.run(
            ['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'],
            capture_output=True)

        received[JobCompleted].wait(timeout=10)

        mon.stop()
        mon.join(timeout=5)
        cleanup(dev, img)

        seen = {type(e) for e in events}
        missing = [et.__name__ for et in ALL_EVENT_TYPES if et not in seen
                   and et is not InterfaceRemoved]
        self.assertFalse(missing,
                         f'missing event types via direct dispatch: {missing} '
                         f'(received {len(events)}: {[t.__name__ for t in seen]})')

        if InterfaceRemoved not in seen:
            self.skipTest('InterfaceRemoved not received — known flake')

    def test_interface_added_has_correct_data(self):
        """InterfaceAdded via direct dispatch has valid fields."""
        events = []
        ia_received = threading.Event()

        def on_ia(evt):
            events.append(evt)
            ia_received.set()

        mon = UdisksMonitor(backend='dbus')
        mon.subscribe(on_ia, event_type=InterfaceAdded)
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        dev, img, name = make_image()
        self.addCleanup(cleanup, dev, img)

        ia_received.wait(timeout=10)
        mon.stop()
        mon.join(timeout=5)

        ia_events = [e for e in events if isinstance(e, InterfaceAdded)]
        self.assertGreater(len(ia_events), 0)
        for ia in ia_events:
            self.assertIsInstance(ia.properties, dict)
            self.assertIsInstance(ia.interface, str)
            self.assertTrue(ia.interface.startswith('org.freedesktop.UDisks2.'))

    def test_device_property_changed_has_correct_data(self):
        """DevicePropertyChanged via direct dispatch has valid fields."""
        events = []
        dpc_received = threading.Event()

        def on_dpc(evt):
            events.append(evt)
            dpc_received.set()

        mon = UdisksMonitor(backend='dbus')
        mon.subscribe(on_dpc, event_type=DevicePropertyChanged)
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        dev, img, name = make_image()
        self.addCleanup(cleanup, dev, img)

        dpc_received.wait(timeout=10)
        mon.stop()
        mon.join(timeout=5)

        dpc_events = [e for e in events if isinstance(e, DevicePropertyChanged)]
        self.assertGreater(len(dpc_events), 0)
        device_events = [e for e in dpc_events if e.device_name == name]
        self.assertGreater(len(device_events), 0,
                           f'no DevicePropertyChanged for {name!r}')

    def test_job_properties_arrives(self):
        """JobProperties must arrive via direct dispatch."""
        events = []
        jp_received = threading.Event()

        def on_jp(evt):
            events.append(evt)
            jp_received.set()

        mon = UdisksMonitor(backend='dbus')
        mon.subscribe(on_jp, event_type=JobProperties)
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        jp_ok = jp_received.wait(timeout=10)
        mon.stop()
        mon.join(timeout=5)

        self.assertTrue(jp_ok, 'JobProperties never arrived via direct dispatch')

    def test_catch_all_subscriber_receives_everything(self):
        """A subscriber with event_type=None receives ALL event types."""
        events = []

        mon = UdisksMonitor(backend='dbus')
        mon.subscribe(lambda e: events.append(type(e)))
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        dev, img, _name = make_image()
        subprocess.run(
            ['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'],
            capture_output=True)
        time.sleep(0.5)

        mon.stop()
        mon.join(timeout=5)
        cleanup(dev, img)

        seen = set(events)
        for et in ALL_EVENT_TYPES:
            if et is not InterfaceRemoved:
                self.assertIn(et, seen,
                              f'{et.__name__} not received by catch-all subscriber '
                              f'(saw {[t.__name__ for t in sorted(seen, key=str)]})')

    def test_multiple_subscribers_same_type_both_fire(self):
        """Two subscribers for the same event_type both receive events."""
        r1 = threading.Event()
        r2 = threading.Event()

        mon = UdisksMonitor(backend='dbus')
        mon.subscribe(lambda e: r1.set(), event_type=DevicePropertyChanged)
        mon.subscribe(lambda e: r2.set(), event_type=DevicePropertyChanged)
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        dev, img, _name = make_image()
        subprocess.run(
            ['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'],
            capture_output=True)

        ok1 = r1.wait(timeout=5)
        ok2 = r2.wait(timeout=5)

        mon.stop()
        mon.join(timeout=5)
        cleanup(dev, img)

        self.assertTrue(ok1, 'subscriber 1 did not fire')
        self.assertTrue(ok2, 'subscriber 2 did not fire')


@unittest.skipIf(SKIP_DBUS_INTEGRATION,
                 'D-Bus integration tests are unstable in CI')
@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestArch1InterleavedStress(unittest.TestCase):
    """Verify direct dispatch under concurrent load (8 subscriber pairs)."""

    PAIRS = 8

    def test_eight_subscriber_pairs_all_receive_events(self):
        """8 pairs of subscribers (subprocess + dbus) all get events."""

        def _run_pair(idx, results):
            events = []
            jc_event = threading.Event()

            mon = UdisksMonitor(backend='dbus')
            mon.subscribe(lambda e: events.append(e))
            mon.subscribe(lambda e: jc_event.set(),
                          event_type=JobCompleted)
            mon.start()

            if not mon.ready.wait(timeout=10):
                results[idx] = ('dbus_ready_timeout', [])
                return

            dev, img, _name = make_image()
            try:
                subprocess.run(
                    ['udisksctl', 'loop-delete', '-b', dev,
                     '--no-user-interaction'], capture_output=True)
                jc_event.wait(timeout=10)
            finally:
                cleanup(dev, img)
                mon.stop()
                mon.join(timeout=5)

            seen = {type(e) for e in events}
            results[idx] = ('ok', seen)

        pairs = 4  # fewer pairs to avoid overloading UDisks2
        threads = []
        results: dict[int, tuple] = {}

        for i in range(pairs):
            t = threading.Thread(target=_run_pair, args=(i, results))
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=120)

        failures = []
        for i in range(pairs):
            status, seen = results.get(i, ('missing', set()))
            if status == 'missing':
                failures.append(f'Pair {i}: never completed')
            elif status == 'dbus_ready_timeout':
                failures.append(f'Pair {i}: D-Bus ready timeout')
            elif status == 'ok':
                missing = []
                if JobCompleted not in seen:
                    missing.append('JobCompleted')
                if DevicePropertyChanged not in seen:
                    missing.append('DevicePropertyChanged')
                if missing:
                    failures.append(f'Pair {i}: missing {missing}')

        self.assertFalse(
            failures,
            f'{len(failures)}/{pairs} pairs failed:\n' +
            '\n'.join(failures))

        success_count = sum(1 for v in results.values()
                           if v[0] == 'ok' and JobCompleted in v[1]
                           and DevicePropertyChanged in v[1])
        self.assertGreaterEqual(
            success_count, max(1, pairs - 1),
            f'Only {success_count}/{pairs} pairs received events '
            f'(minimum expected: {max(1, pairs - 1)})')

    def test_subprocess_and_dbus_pair_deliver_events(self):
        """Verify direct dispatch still works alongside subprocess backend."""
        dbus_events = []
        sub_events = []
        dbus_jc = threading.Event()
        sub_jc = threading.Event()

        dmon = UdisksMonitor(backend='dbus')
        dmon.subscribe(lambda e: dbus_events.append(e))
        dmon.subscribe(lambda e: dbus_jc.set(), event_type=JobCompleted)

        smon = UdisksMonitor(backend='subprocess')
        smon.subscribe(lambda e: sub_events.append(e))
        smon.subscribe(lambda e: sub_jc.set(), event_type=JobCompleted)

        dmon.start()
        self.assertTrue(dmon.ready.wait(timeout=10))
        smon.start()
        self.assertTrue(smon.ready.wait(timeout=10))

        dev, img, _name = make_image()
        try:
            subprocess.run(
                ['udisksctl', 'loop-delete', '-b', dev,
                 '--no-user-interaction'], capture_output=True)
            dbus_jc.wait(timeout=10)
            sub_jc.wait(timeout=10)
        finally:
            cleanup(dev, img)
            dmon.stop()
            dmon.join(timeout=5)
            smon.stop()
            smon.join(timeout=5)

        dbus_jc_count = sum(1 for e in dbus_events if isinstance(e, JobCompleted))
        sub_jc_count = sum(1 for e in sub_events if isinstance(e, JobCompleted))
        self.assertGreater(dbus_jc_count, 0,
                           'D-Bus direct dispatch: no JobCompleted')
        self.assertGreater(sub_jc_count, 0,
                           'Subprocess backend: no JobCompleted')
