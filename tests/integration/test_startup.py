"""Integration tests for UdisksMonitor startup and shutdown lifecycle."""

import threading
import unittest

from udisks_monitor import (DevicePropertyChanged, UdisksMonitor)

from tests.integration.helpers import (_backend, _ensure_udisks_ready,
                                       _restart_udisks, cleanup, make_image,
                                       udisksctl_available)


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestStartupLifecycle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _restart_udisks()

    def setUp(self):
        _ensure_udisks_ready()
        self.mon = UdisksMonitor(backend=_backend())

    def tearDown(self):
        self.mon.stop()
        self.mon.join(timeout=5)

    def test_starts_and_signals_ready(self):
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=15))

    def test_stop_stops_monitor(self):
        self.mon.start()
        self.assertTrue(self.mon.ready.wait(timeout=15))
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
        self.assertTrue(self.mon.ready.wait(timeout=15))

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        self.assertTrue(received.wait(timeout=5),
                        'subscriber registered before start() did not fire')
        self.assertIsInstance(first_event[0], DevicePropertyChanged)
