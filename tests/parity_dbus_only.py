"""Diagnostic: all integration tests using ONLY the D-Bus (dbus-fast) backend."""

import threading
import subprocess
import time
import unittest
import os
import tempfile

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved, UdisksMonitor)


def udisksctl_available():
    try:
        r = subprocess.run(['udisksctl', 'dump'], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def make_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                    'count=1'], capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    try:
        r = subprocess.run(
            ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
            capture_output=True, text=True)
        r.check_returncode()
    except subprocess.CalledProcessError:
        os.unlink(path)
        raise RuntimeError(
            f'loop-setup failed (rc={r.returncode}):\n'
            f'stdout: {r.stdout}\n'
            f'stderr: {r.stderr}') from None
    for line in r.stdout.splitlines():
        if '/dev/' in line and 'loop' in line:
            device = line.strip().split()[-1].rstrip('.')
            return device, path, device.split('/')[-1]
    os.unlink(path)
    raise RuntimeError(f'could not parse loop-setup output:\n{r.stdout}')


def cleanup(device, img_path):
    for _ in range(3):
        r = subprocess.run(
            ['udisksctl', 'unmount', '-b', device, '--no-user-interaction'],
            capture_output=True, text=True)
        r2 = subprocess.run(
            ['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
            capture_output=True, text=True)
        if r2.returncode == 0:
            break
        time.sleep(0.1)
    if os.path.exists(img_path):
        os.unlink(img_path)


# ── startup tests (dbus only) ─────────────────────────────────────

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestStartupDbus(unittest.TestCase):

    def setUp(self):
        self.mon = UdisksMonitor(backend='dbus')

    def tearDown(self):
        self.mon.stop()
        self.mon.join(timeout=5)

    def test_starts_and_signals_ready(self):
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))

    def test_stop_stops_monitor(self):
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))
        self.assertTrue(self.mon.is_alive())
        self.mon.stop()
        self.mon.join(timeout=5)
        self.assertFalse(self.mon.is_alive())

    def test_subscribers_before_start_receive_events(self):
        received = threading.Event()
        first_event = []

        def handler(evt):
            first_event.append(evt)
            received.set()

        self.mon.subscribe(handler, event_type=DevicePropertyChanged)
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        self.assertTrue(received.wait(timeout=5),
                        'subscriber registered before start() did not fire')
        self.assertIsInstance(first_event[0], DevicePropertyChanged)


# ── subscribers tests (dbus only) ─────────────────────────────────

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestSubscribersDbus(unittest.TestCase):

    def setUp(self):
        self.mon = UdisksMonitor(backend='dbus')

    def tearDown(self):
        self.mon.stop()
        self.mon.join(timeout=5)

    def test_multiple_subscribers_both_fire(self):
        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        r1 = threading.Event()
        r2 = threading.Event()

        self.mon.subscribe(lambda e: r1.set(),
                           event_type=DevicePropertyChanged)
        self.mon.subscribe(lambda e: r2.set(),
                           event_type=DevicePropertyChanged)
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))

        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)

        self.assertTrue(r1.wait(timeout=5), 'subscriber 1 did not fire')
        self.assertTrue(r2.wait(timeout=5), 'subscriber 2 did not fire')

    def test_filtered_subscriber_only_receives_matching_events(self):
        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        props_received = threading.Event()
        jobs_received = threading.Event()

        self.mon.subscribe(lambda e: props_received.set(),
                           event_type=DevicePropertyChanged)
        self.mon.subscribe(lambda e: jobs_received.set(),
                           event_type=JobCompleted)
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))

        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)

        prop_ok = props_received.wait(timeout=5)
        job_ok = jobs_received.wait(timeout=5)

        self.assertTrue(prop_ok, 'DevicePropertyChanged subscriber did not fire')
        self.assertTrue(job_ok, 'JobCompleted subscriber did not fire')


# ── events test (dbus only) ───────────────────────────────────────

ALL_EVENT_TYPES = (
    DevicePropertyChanged, InterfaceAdded, InterfaceRemoved,
    JobAdded, JobProperties, JobCompleted, JobRemoved,
)

_RELIABLE_TYPES = (
    DevicePropertyChanged, InterfaceAdded,
    JobAdded, JobProperties, JobCompleted, JobRemoved,
)


class _EventRecorder:
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
class TestEventsDbus(unittest.TestCase):

    def test_full_lifecycle_emits_all_event_types(self):
        mon = UdisksMonitor(backend='dbus')
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


# ── parity tests (dbus only, two runs compared) ───────────────────

ALL_PARITY_TYPES = (
    DevicePropertyChanged, InterfaceAdded, InterfaceRemoved,
    JobAdded, JobProperties, JobCompleted, JobRemoved,
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


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestParityDbusOnly(unittest.TestCase):

    BACKEND = 'dbus'

    def test_emits_all_event_types(self):
        events = _collect_events(self.BACKEND)
        self.assertIsNotNone(events, 'dbus backend failed to connect')
        seen = {type(e) for e in events}
        for et in ALL_PARITY_TYPES:
            self.assertIn(et, seen,
                          f'{et.__name__} missing from dbus backend '
                          f'(saw: {[t.__name__ for t in seen[::-1][:20]]})')

    def test_job_completed_events(self):
        run1 = _collect_events(self.BACKEND)
        run2 = _collect_events(self.BACKEND)
        self.assertIsNotNone(run1)
        self.assertIsNotNone(run2)

        run1_jc = [e for e in run1 if isinstance(e, JobCompleted)]
        run2_jc = [e for e in run2 if isinstance(e, JobCompleted)]
        self.assertTrue(run1_jc, 'run1 did not produce JobCompleted')
        self.assertTrue(run2_jc, 'run2 did not produce JobCompleted')

        self.assertEqual(type(run1_jc[0].success), type(run2_jc[0].success))

    def test_device_property_changed_events(self):
        run1 = _collect_events(self.BACKEND)
        run2 = _collect_events(self.BACKEND)
        self.assertIsNotNone(run1)
        self.assertIsNotNone(run2)

        run1_dpc = {e.property: e.value
                    for e in run1 if isinstance(e, DevicePropertyChanged)}
        run2_dpc = {e.property: e.value
                    for e in run2 if isinstance(e, DevicePropertyChanged)}

        self.assertTrue(run1_dpc, 'run1 produced no DevicePropertyChanged')
        self.assertTrue(run2_dpc, 'run2 produced no DevicePropertyChanged')

        common = set(run1_dpc) & set(run2_dpc)
        self.assertTrue(common,
                        f'no common properties: run1={set(run1_dpc)} run2={set(run2_dpc)}')

    def test_interface_events(self):
        run1 = _collect_events(self.BACKEND)
        run2 = _collect_events(self.BACKEND)
        self.assertIsNotNone(run1)
        self.assertIsNotNone(run2)

        r1_added = any(isinstance(e, InterfaceAdded) for e in run1)
        r2_added = any(isinstance(e, InterfaceAdded) for e in run2)
        r1_removed = any(isinstance(e, InterfaceRemoved) for e in run1)
        r2_removed = any(isinstance(e, InterfaceRemoved) for e in run2)

        self.assertTrue(r1_added, 'run1 missed InterfaceAdded')
        self.assertTrue(r2_added, 'run2 missed InterfaceAdded')
        self.assertTrue(r1_removed, 'run1 missed InterfaceRemoved')
        self.assertTrue(r2_removed, 'run2 missed InterfaceRemoved')
