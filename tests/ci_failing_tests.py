"""Only the integration tests that fail in CI — extracted for isolation testing."""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved, UdisksMonitor)

# ── helpers (copied from tests/integration/helpers.py) ──────────

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

# ── failing startup test ─────────────────────────────────────────

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestFailingStartup(unittest.TestCase):

    def setUp(self):
        self.mon = UdisksMonitor()

    def tearDown(self):
        self.mon.stop()
        self.mon.join(timeout=5)

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

# ── failing subscribers test ─────────────────────────────────────

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestFailingSubscribers(unittest.TestCase):

    def setUp(self):
        self.mon = UdisksMonitor()

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

# ── failing events test ──────────────────────────────────────────

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
class TestFailingEvents(unittest.TestCase):

    def test_full_lifecycle_emits_all_event_types(self):
        mon = UdisksMonitor()
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

# ── failing parity tests ─────────────────────────────────────────

ALL_PARITY_TYPES = (
    DevicePropertyChanged, InterfaceAdded, InterfaceRemoved,
    JobAdded, JobProperties, JobCompleted, JobRemoved,
)

def _wait_for(cls, events, since, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for i in range(since, len(events)):
            if isinstance(events[i], cls):
                return i
        time.sleep(0.05)
    return None

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
class TestFailingParity(unittest.TestCase):

    def test_both_backends_emit_all_event_types(self):
        for backend, label in [('subprocess', 'subprocess'),
                               ('dbus', 'D-Bus')]:
            events = _collect_events(backend)
            self.assertIsNotNone(events,
                                 f'{label} backend failed to connect')
            seen = {type(e) for e in events}
            for et in ALL_PARITY_TYPES:
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
