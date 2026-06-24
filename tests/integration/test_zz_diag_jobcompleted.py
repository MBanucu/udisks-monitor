"""Diagnostic tests to determine why JobCompleted is not received via D-Bus
backend on CI runners.

These tests use independent observers (busctl monitor, dbus-fast directly)
to verify whether UDisks2 actually emits JobCompleted signals on the
system D-Bus after a loop-setup operation.
"""

import signal
import subprocess
import threading
import time
import unittest

from tests.integration.helpers import (_restore_udisks,
                                       cleanup, make_image,
                                       udisksctl_available)


######################################################################
# Test 1 — busctl monitor: independent observer of D-Bus traffic
######################################################################

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestBusctlMonitorSeesJobCompleted(unittest.TestCase):
    """Verify that busctl monitor captures a JobCompleted signal
    when a loop-setup runs.  This completely bypasses the Python
    D-Bus backend and observes raw bus traffic."""

    @classmethod
    def setUpClass(cls):
        _restore_udisks()

    def setUp(self):
        _restore_udisks()

    def test_busctl_monitor_captures_job_completed_on_loop_setup(self):
        finished = threading.Event()
        lines = []

        def run_monitor():
            proc = subprocess.Popen(
                ['busctl', 'monitor', '--system',
                 '--match',
                 "type='signal',interface='org.freedesktop.UDisks2.Job',"
                 "member='Completed',path_namespace='/org/freedesktop/UDisks2'"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True)
            try:
                for raw in proc.stdout:
                    line = raw.rstrip('\n')
                    lines.append(line)
                    if 'Job' in line and 'Completed' in line:
                        finished.set()
            finally:
                try:
                    proc.send_signal(signal.SIGTERM)
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()

        t = threading.Thread(target=run_monitor, daemon=True)
        t.start()
        time.sleep(2)

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        received = finished.wait(timeout=15)
        self.assertTrue(
            received,
            f'busctl monitor did NOT see JobCompleted signal from UDisks2\n'
            f'busctl monitor captured {len(lines)} lines:\n'
            + '\n'.join(lines[-20:]))


######################################################################
# Test 2 — dbus-fast direct: bypasses UdisksMonitor entirely
######################################################################

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestDbusFastDirectSeesJobCompleted(unittest.TestCase):
    """Use dbus-fast directly (no UdisksMonitor) to verify a raw
    D-Bus connection receives JobCompleted."""

    @classmethod
    def setUpClass(cls):
        _restore_udisks()

    def setUp(self):
        _restore_udisks()

    def test_dbus_fast_direct_receives_job_completed(self):
        import asyncio

        from dbus_fast.aio import MessageBus
        from dbus_fast import BusType, Message, MessageType

        events = []
        errors = []
        ready = threading.Event()
        stop = threading.Event()

        async def listen():
            try:
                bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

                def handler(msg):
                    if (msg.message_type == MessageType.SIGNAL
                            and msg.interface == 'org.freedesktop.UDisks2.Job'
                            and msg.member == 'Completed'):
                        events.append({
                            'path': msg.path,
                            'body': list(msg.body),
                            'sender': msg.sender,
                        })

                bus.add_message_handler(handler)
                reply = await bus.call(Message(
                    destination='org.freedesktop.DBus',
                    path='/org/freedesktop/DBus',
                    interface='org.freedesktop.DBus',
                    member='AddMatch',
                    signature='s',
                    body=['type=signal,'
                          "path_namespace='/org/freedesktop/UDisks2'"],
                ))
                if reply.message_type == MessageType.ERROR:
                    errors.append(
                        f'AddMatch failed: {reply.body}')
                    return
                ready.set()
                async with asyncio.timeout(30):
                    while not stop.is_set():
                        await asyncio.sleep(0.1)
                bus.disconnect()
            except asyncio.TimeoutError:
                pass

        def run():
            asyncio.run(listen())

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.assertTrue(ready.wait(timeout=15),
                        'dbus-fast connection not ready')
        self.assertFalse(errors, errors[0] if errors else '')

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        time.sleep(5)
        stop.set()
        t.join(timeout=10)

        self.assertGreater(
            len(events), 0,
            f'dbus-fast did NOT receive any JobCompleted signals '
            f'after loop-setup (received {len(events)} total D-Bus '
            f'UDisks2.Job.Completed messages)')


######################################################################
# Test 3 — Subprocess backend: sanity check that loop-setup
#          actually completes
######################################################################

@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestSubprocessBackendReceivesJobCompleted(unittest.TestCase):
    """Sanity check: the subprocess backend (udisksctl monitor) DOES
    receive JobCompleted for the same loop-setup.  If this passes
    but the D-Bus tests fail, the problem is D-Bus-specific."""

    def test_subprocess_backend_receives_job_completed(self):
        from udisks_monitor import JobCompleted, UdisksMonitor
        got = threading.Event()
        mon = UdisksMonitor(backend='subprocess')
        mon.subscribe(lambda _: got.set(), event_type=JobCompleted)
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=15),
                        'subprocess monitor not ready')

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        self.assertTrue(got.wait(timeout=15),
                        'subprocess backend did NOT receive JobCompleted')
        mon.stop()
        mon.join(timeout=5)
