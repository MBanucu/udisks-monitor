"""Diagnostic: all integration tests using ONLY the subprocess backend.

Every UdisksMonitor uses ``backend='subprocess'`` — no D-Bus connections.
Tests are copies of the integration tests from tests/integration/,
with parity tests adapted to run subprocess twice back-to-back.
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved, UdisksMonitor)


# ---------------------------------------------------------------------------
# Inline helpers (copied from tests/integration/helpers.py)
# ---------------------------------------------------------------------------

def _udisksctl_available():
    try:
        r = subprocess.run(['udisksctl', 'dump'], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _make_image():
    """Create a small VFAT image, set up a loop device, unmount it."""
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


def _cleanup(device, img_path):
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


# ---------------------------------------------------------------------------
# Event type helpers (from test_events.py)
# ---------------------------------------------------------------------------

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
    """Subscribes to event types and records them with per-type Events."""

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


# ---------------------------------------------------------------------------
# Parity helper (from test_backend_parity.py) — ALWAYS subprocess
# ---------------------------------------------------------------------------

def _collect_events(backend='subprocess'):
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

    dev, img, _name = _make_image()
    try:
        if not interface_added.wait(timeout=5):
            return None
        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)
        if not job_completed.wait(timeout=5):
            return None
    finally:
        _cleanup(dev, img)
        mon.stop()
        mon.join(timeout=5)

    return events


# ===================================================================
# Startup Lifecycle tests (from test_startup.py)
# ===================================================================

@unittest.skipUnless(_udisksctl_available(), 'udisksctl not available')
class TestStartupLifecycle(unittest.TestCase):

    def setUp(self):
        self.mon = UdisksMonitor(backend='subprocess')

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

        dev, img, _name = _make_image()
        self.addCleanup(_cleanup, dev, img)

        self.assertTrue(received.wait(timeout=5),
                        'subscriber registered before start() did not fire')
        self.assertIsInstance(first_event[0], DevicePropertyChanged)


# ===================================================================
# Subscriber Behavior tests (from test_subscribers.py)
# ===================================================================

@unittest.skipUnless(_udisksctl_available(), 'udisksctl not available')
class TestSubscriberBehavior(unittest.TestCase):

    def setUp(self):
        self.mon = UdisksMonitor(backend='subprocess')

    def tearDown(self):
        self.mon.stop()
        self.mon.join(timeout=5)

    def test_multiple_subscribers_both_fire(self):
        dev, img, _name = _make_image()
        self.addCleanup(_cleanup, dev, img)

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
        dev, img, _name = _make_image()
        self.addCleanup(_cleanup, dev, img)

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


# ===================================================================
# All Event Types test (from test_events.py)
# ===================================================================

@unittest.skipUnless(_udisksctl_available(), 'udisksctl not available')
class TestAllEventTypes(unittest.TestCase):

    def test_full_lifecycle_emits_all_event_types(self):
        mon = UdisksMonitor(backend='subprocess')
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        recorder = _EventRecorder(mon)

        dev, img, _name = _make_image()
        self.addCleanup(_cleanup, dev, img)

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


# ===================================================================
# Parity tests (from test_backend_parity.py) — subprocess vs subprocess
# ===================================================================

@unittest.skipUnless(_udisksctl_available(), 'udisksctl not available')
class TestSubprocessParity(unittest.TestCase):

    def test_two_subprocess_runs_both_emit_all_event_types(self):
        for backend, label in [('subprocess', 'run 1'),
                                ('subprocess', 'run 2')]:
            events = _collect_events(backend)
            self.assertIsNotNone(events,
                                 f'{label} failed to connect')
            seen = {type(e) for e in events}
            for et in ALL_EVENT_TYPES:
                self.assertIn(et, seen,
                              f'{et.__name__} missing from {label} '
                              f'(saw: {[t.__name__ for t in seen]})')

    def test_two_subprocess_runs_produce_matching_job_completed(self):
        sub1 = _collect_events('subprocess')
        sub2 = _collect_events('subprocess')
        self.assertIsNotNone(sub1)
        self.assertIsNotNone(sub2)

        sub1_jc = [e for e in sub1 if isinstance(e, JobCompleted)]
        sub2_jc = [e for e in sub2 if isinstance(e, JobCompleted)]
        self.assertTrue(sub1_jc)
        self.assertTrue(sub2_jc)

        self.assertEqual(type(sub1_jc[0].success), type(sub2_jc[0].success))
        sub1_success = any(j.success for j in sub1_jc)
        sub2_success = any(j.success for j in sub2_jc)
        self.assertEqual(sub1_success, sub2_success,
                         'JobCompleted success differs between runs')

    def test_two_subprocess_runs_produce_matching_device_events(self):
        sub1 = _collect_events('subprocess')
        sub2 = _collect_events('subprocess')
        self.assertIsNotNone(sub1)
        self.assertIsNotNone(sub2)

        sub1_dpc = {e.property: e.value
                    for e in sub1 if isinstance(e, DevicePropertyChanged)}
        sub2_dpc = {e.property: e.value
                    for e in sub2 if isinstance(e, DevicePropertyChanged)}

        self.assertTrue(sub1_dpc)
        self.assertTrue(sub2_dpc)

        common = set(sub1_dpc) & set(sub2_dpc)
        self.assertTrue(common,
                        f'no common properties: run1={set(sub1_dpc)} run2={set(sub2_dpc)}')

    def test_interface_events_emitted_by_both_runs(self):
        sub1 = _collect_events('subprocess')
        sub2 = _collect_events('subprocess')
        self.assertIsNotNone(sub1)
        self.assertIsNotNone(sub2)

        sub1_added = any(isinstance(e, InterfaceAdded) for e in sub1)
        sub2_added = any(isinstance(e, InterfaceAdded) for e in sub2)
        sub1_removed = any(isinstance(e, InterfaceRemoved) for e in sub1)
        sub2_removed = any(isinstance(e, InterfaceRemoved) for e in sub2)

        self.assertTrue(sub1_added, 'run 1 missed InterfaceAdded')
        self.assertTrue(sub2_added, 'run 2 missed InterfaceAdded')
        self.assertTrue(sub1_removed, 'run 1 missed InterfaceRemoved')
        self.assertTrue(sub2_removed, 'run 2 missed InterfaceRemoved')
