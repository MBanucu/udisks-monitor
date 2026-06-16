"""Integration tests — real udisksctl monitor with a loop device.

Requires a working udisksctl and polkit permissions.
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from udisks_monitor import DevicePropertyChanged, JobProperties, UdisksMonitor


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
    time.sleep(0.5)
    if os.path.exists(img_path):
        os.unlink(img_path)


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestIntegration(unittest.TestCase):
    """Real udisksctl monitor — start monitor, attach a loop device,
    then verify that property and job events are received."""

    @classmethod
    def setUpClass(cls):
        pass  # device created per test to ensure fresh events

    def setUp(self):
        self.mon = UdisksMonitor()
        self.received = []
        self.mon.subscribe(lambda e: self.received.append(e))

    def tearDown(self):
        self.mon.stop()
        self.mon.join(timeout=5)

    def test_monitor_starts_and_is_ready(self):
        self.mon.start()
        ready = self.mon.ready.wait(timeout=10)
        self.assertTrue(ready)

    def test_receives_events_on_loop_setup(self):
        """Verify the monitor receives events when a loop device is created."""
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))
        time.sleep(0.2)
        self.received.clear()
        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)
        time.sleep(1.5)
        self.assertGreaterEqual(
            len(self.received), 1,
            f'no events received during loop-setup')

    def test_multiple_subscribers(self):
        r1, r2 = [], []
        self.mon.subscribe(lambda e: r1.append(e),
                           event_type=DevicePropertyChanged)
        self.mon.subscribe(lambda e: r2.append(e),
                           event_type=DevicePropertyChanged)
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))
        time.sleep(0.2)
        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)
        time.sleep(1.5)
        self.assertGreaterEqual(len(r1), 1, f'r1={len(r1)}')
        self.assertGreaterEqual(len(r2), 1, f'r2={len(r2)}')

    def test_stop_stops_monitor(self):
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=10))
        self.assertTrue(self.mon.is_alive())
        self.mon.stop()
        self.mon.join(timeout=5)
        self.assertFalse(self.mon.is_alive())
