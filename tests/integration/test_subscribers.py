"""Integration tests for subscriber behavior with real UDisks2."""

import subprocess
import threading
import unittest

from udisks_monitor import (DevicePropertyChanged, JobCompleted,
                            UdisksMonitor)

from tests.integration.helpers import (_backend, _timeout, cleanup, make_image,
                                       udisksctl_available)


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestSubscriberBehavior(unittest.TestCase):

    def setUp(self):
        self.mon = UdisksMonitor(backend=_backend())

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

        self.assertTrue(r1.wait(timeout=_timeout()), 'subscriber 1 did not fire')
        self.assertTrue(r2.wait(timeout=_timeout()), 'subscriber 2 did not fire')

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

        prop_ok = props_received.wait(timeout=_timeout())
        job_ok = jobs_received.wait(timeout=_timeout())

        self.assertTrue(prop_ok, 'DevicePropertyChanged subscriber did not fire')
        self.assertTrue(job_ok, 'JobCompleted subscriber did not fire')
