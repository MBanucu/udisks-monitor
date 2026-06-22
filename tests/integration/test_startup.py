"""Integration tests for UdisksMonitor startup and shutdown lifecycle."""

import subprocess
import threading
import time
import unittest

from udisks_monitor import (DevicePropertyChanged, UdisksMonitor)

from tests.integration.helpers import (_backend, cleanup, make_image,
                                       udisksctl_available)


def _restart_udisks():
    subprocess.run(
        ['sudo', 'systemctl', 'restart', 'udisks2'],
        capture_output=True, timeout=15)
    for _ in range(20):
        r = subprocess.run(
            ['busctl', '--system', 'call',
             'org.freedesktop.DBus', '/org/freedesktop/DBus',
             'org.freedesktop.DBus', 'NameHasOwner',
             's', 'org.freedesktop.UDisks2'],
            capture_output=True, text=True, timeout=5)
        if 'true' in r.stdout:
            time.sleep(0.3)
            return
        time.sleep(0.5)
    raise RuntimeError('UDisks2 did not become ready after restart')


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestStartupLifecycle(unittest.TestCase):

    def setUp(self):
        _restart_udisks()
        self.mon = UdisksMonitor(backend=_backend())

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
