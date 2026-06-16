"""Integration tests — real udisksctl monitor with a loop device.

Requires a working udisksctl and polkit permissions.
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from udisks_monitor import (DevicePropertyChanged, JobCompleted,
                             JobProperties, UdisksMonitor)


def udisksctl_available():
    try:
        r = subprocess.run(['udisksctl', 'dump'], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def make_image():
    """Create a small VFAT image, set up a loop device, unmount it."""
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                    'count=1'], capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    r = subprocess.run(
        ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
        capture_output=True, text=True)
    r.check_returncode()
    for line in r.stdout.splitlines():
        if '/dev/' in line and 'loop' in line:
            device = line.strip().split()[-1].rstrip('.')
            return device, path, device.split('/')[-1]
    raise RuntimeError(f'could not parse loop-setup output:\n{r.stdout}')


def cleanup(device, img_path):
    subprocess.run(['udisksctl', 'unmount', '-b', device,
                    '--no-user-interaction'], capture_output=True)
    subprocess.run(['udisksctl', 'loop-delete', '-b', device,
                    '--no-user-interaction'], capture_output=True)
    time.sleep(0.3)
    if os.path.exists(img_path):
        os.unlink(img_path)


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestIntegration(unittest.TestCase):
    """Real udisksctl monitor integration — event-driven."""

    @classmethod
    def setUpClass(cls):
        pass  # device created per test for fresh events

    def setUp(self):
        self.mon = UdisksMonitor()

    def tearDown(self):
        self.mon.stop()
        self.mon.join(timeout=5)

    def test_monitor_starts_and_is_ready(self):
        self.mon.start()
        ready = self.mon.ready.wait(timeout=10)
        self.assertTrue(ready)

    def test_event_driven_property_detection(self):
        """Use a threading.Event to wait for the first DevicePropertyChanged."""
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
                        'timed out waiting for property event')
        self.assertIsInstance(first_event[0], DevicePropertyChanged)

    def test_event_driven_job_detection(self):
        """Wait for a JobCompleted event after loop-setup."""
        received = threading.Event()
        first_job = []

        def handler(evt):
            first_job.append(evt)
            received.set()

        self.mon.subscribe(handler, event_type=JobCompleted)
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        self.assertTrue(received.wait(timeout=5),
                        'timed out waiting for job completed event')
        self.assertIsInstance(first_job[0], JobCompleted)

    def test_multiple_subscribers_both_fire(self):
        """Two subscribers both receive the same event."""
        r1 = threading.Event()
        r2 = threading.Event()

        self.mon.subscribe(lambda e: r1.set(), event_type=DevicePropertyChanged)
        self.mon.subscribe(lambda e: r2.set(), event_type=DevicePropertyChanged)
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        self.assertTrue(r1.wait(timeout=5), 'subscriber 1 did not fire')
        self.assertTrue(r2.wait(timeout=5), 'subscriber 2 did not fire')

    def test_stop_stops_monitor(self):
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))
        self.assertTrue(self.mon.is_alive())
        self.mon.stop()
        self.mon.join(timeout=5)
        self.assertFalse(self.mon.is_alive())
