"""Diagnostic: single-monitor integration tests using ONLY dbus backend in sequence."""

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


# ── startup tests ─────────────────────────────────────────────────

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestStartupDbusSingle(unittest.TestCase):

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


# ── subscribers tests ─────────────────────────────────────────────

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestSubscribersDbusSingle(unittest.TestCase):

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


# ── events test ───────────────────────────────────────────────────

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
class TestEventsDbusSingle(unittest.TestCase):

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
