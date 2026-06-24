"""Diagnostic tests to determine why JobCompleted is not received via D-Bus
backend on CI runners.

Key insight: parity tests (which pass) do loop-setup + loop-delete before
checking JobCompleted.  D-Bus signal tests (which fail) only do loop-setup.
Hypothesis: loop-setup's JobCompleted is lost/missed, but loop-delete's
JobCompleted is received.
"""

import os
import signal
import subprocess
import threading
import time
import unittest

from tests.integration.helpers import (_restore_udisks,
                                       cleanup, make_image,
                                       udisksctl_available)

_IS_CI = os.environ.get('CI', '') == 'true'


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestJobCompletedSource(unittest.TestCase):
    """Determine whether JobCompleted arrives from loop-setup,
    loop-delete, or neither."""

    @classmethod
    def setUpClass(cls):
        _restore_udisks()

    def setUp(self):
        _restore_udisks()

    def test_job_completed_from_loop_setup_alone(self):
        """Subscribe only to JobCompleted, do loop-setup, check for it."""
        from udisks_monitor import JobCompleted, UdisksMonitor

        for attempt in range(3):
            got = threading.Event()
            mon = UdisksMonitor(backend='dbus')
            mon.subscribe(lambda _: got.set(), event_type=JobCompleted)
            mon.start()
            if not mon.ready.wait(timeout=15):
                mon.stop()
                mon.join(timeout=5)
                _restore_udisks()
                continue

            dev, img, _name = make_image()
            self.addCleanup(cleanup, dev, img)

            received = got.wait(timeout=15)
            mon.stop()
            mon.join(timeout=5)

            if received:
                return
            cleanup(dev, img)
            _restore_udisks()

        self.fail('JobCompleted not received from loop-setup alone '
                  'after 3 attempts with UDisks2 restarts')

    def test_job_completed_from_loop_setup_then_delete(self):
        """Do loop-setup + loop-delete; should get JobCompleted from
        loop-delete even if loop-setup's is missed."""
        from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor

        for attempt in range(3):
            got_ia = threading.Event()
            got_jc = threading.Event()
            events = []
            mon = UdisksMonitor(backend='dbus')
            mon.subscribe(lambda _: got_ia.set(), event_type=InterfaceAdded)
            mon.subscribe(lambda _: got_jc.set(), event_type=JobCompleted)
            mon.subscribe(lambda e: events.append(e))
            mon.start()
            if not mon.ready.wait(timeout=15):
                mon.stop()
                mon.join(timeout=5)
                _restore_udisks()
                continue

            dev, img, _name = make_image()
            self.addCleanup(cleanup, dev, img)

            ia_ok = got_ia.wait(timeout=10)
            if not ia_ok:
                mon.stop()
                mon.join(timeout=5)
                cleanup(dev, img)
                _restore_udisks()
                continue

            subprocess.run(
                ['udisksctl', 'loop-delete', '-b', dev,
                 '--no-user-interaction'],
                capture_output=True)

            jc_ok = got_jc.wait(timeout=10)
            mon.stop()
            mon.join(timeout=5)

            if jc_ok:
                jc_events = [e for e in events
                             if isinstance(e, JobCompleted)]
                self.assertGreater(
                    len(jc_events), 0,
                    'JobCompleted Event set but no events in list')
                return

            cleanup(dev, img)
            _restore_udisks()

        self.fail('JobCompleted not received from loop-setup+delete '
                  'after 3 attempts with UDisks2 restarts')

    def test_job_completed_from_two_operations(self):
        """Do two loop-setup+delete cycles on one D-Bus connection.
        If the first cycle's JobCompleted arrives but the second
        doesn't, the problem is connection degradation."""
        from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor

        jc_count = []
        ia_count = []
        events = []

        got_ia = threading.Event()
        got_jc = threading.Event()

        def on_ia(_):
            ia_count.append(len(ia_count))
            got_ia.set()

        def on_jc(_):
            jc_count.append(len(jc_count))
            got_jc.set()

        mon = UdisksMonitor(backend='dbus')
        mon.subscribe(on_ia, event_type=InterfaceAdded)
        mon.subscribe(on_jc, event_type=JobCompleted)
        mon.subscribe(lambda e: events.append(e))
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=15),
                        'monitor not ready')

        results = []
        for cycle in range(3):
            got_ia.clear()
            got_jc.clear()
            jc_before = len(jc_count)
            ia_before = len(ia_count)

            try:
                dev, img, _name = make_image()
            except Exception:
                results.append((cycle, 'make_image_failed', 0, 0))
                _restore_udisks()
                continue

            ia_ok = got_ia.wait(timeout=10)
            jc_ok = got_jc.wait(timeout=10)

            jc_received = len(jc_count) - jc_before
            ia_received = len(ia_count) - ia_before

            subprocess.run(
                ['udisksctl', 'loop-delete', '-b', dev,
                 '--no-user-interaction'],
                capture_output=True)
            cleanup(dev, img)

            status = 'ok' if (ia_ok and jc_ok) else \
                     'NO_JC' if (ia_ok and not jc_ok) else \
                     'NO_IA' if (not ia_ok and jc_ok) else \
                     'NOTHING'
            results.append((cycle, status, ia_received, jc_received))

            if not ia_ok:
                _restore_udisks()
                time.sleep(2)
                # restart monitor if UDisks2 went bad
                mon.stop()
                mon.join(timeout=5)
                mon = UdisksMonitor(backend='dbus')
                mon.subscribe(on_ia, event_type=InterfaceAdded)
                mon.subscribe(on_jc, event_type=JobCompleted)
                mon.subscribe(lambda e: events.append(e))
                mon.start()
                self.assertTrue(mon.ready.wait(timeout=15))

        mon.stop()
        mon.join(timeout=5)

        failures = [(c, s, ia, jc) for c, s, ia, jc in results
                    if s != 'ok']
        self.assertFalse(
            failures,
            f'Some cycles failed:\n'
            + '\n'.join(f'  cycle {c}: {s} (IA={ia}, JC={jc})'
                        for c, s, ia, jc in results))


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
@unittest.skipUnless(_IS_CI, 'CI-only diagnostic')
class TestBusctlMonitorCI(unittest.TestCase):
    """Verify busctl monitor (with sudo) sees JobCompleted on fresh
    UDisks2 right after restart."""

    @classmethod
    def setUpClass(cls):
        _restore_udisks()

    def setUp(self):
        _restore_udisks()

    def test_busctl_with_sudo_sees_job_completed(self):
        finished = threading.Event()
        lines = []

        def run_monitor():
            proc = subprocess.Popen(
                ['sudo', 'busctl', 'monitor', '--system',
                 '--match',
                 "type='signal',path_namespace='/org/freedesktop/UDisks2'"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True)
            try:
                for raw in proc.stdout:
                    line = raw.rstrip('\n')
                    lines.append(line)
                    if 'Completed' in line:
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

        received = finished.wait(timeout=20)
        signal_lines = [l for l in lines if l.strip()]
        self.assertTrue(
            received,
            f'busctl monitor did NOT see Completed signal.\n'
            f'All signals captured ({len(signal_lines)} lines):\n'
            + '\n'.join(signal_lines[-30:]))


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
@unittest.skipUnless(_IS_CI, 'CI-only diagnostic')
class TestSubprocessFresh(unittest.TestCase):
    """Run subprocess backend immediately after UDisks2 restart."""

    @classmethod
    def setUpClass(cls):
        _restore_udisks()

    def setUp(self):
        _restore_udisks()

    def test_subprocess_fresh_receives_job_completed(self):
        from udisks_monitor import JobCompleted, InterfaceAdded, UdisksMonitor
        got_jc = threading.Event()
        got_ia = threading.Event()
        all_events = []
        mon = UdisksMonitor(backend='subprocess')
        mon.subscribe(lambda _: got_jc.set(), event_type=JobCompleted)
        mon.subscribe(lambda _: got_ia.set(), event_type=InterfaceAdded)
        mon.subscribe(lambda e: all_events.append(e))
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=15),
                        'subprocess monitor not ready')

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        ia_ok = got_ia.wait(timeout=10)
        jc_ok = got_jc.wait(timeout=15)

        mon.stop()
        mon.join(timeout=5)

        seen = {type(e).__name__ for e in all_events}
        self.assertTrue(ia_ok,
            f'InterfaceAdded not received by subprocess backend.\n'
            f'Events seen: {seen}')
        self.assertTrue(jc_ok,
            f'JobCompleted not received by subprocess backend.\n'
            f'Events seen: {seen}. '
            f'InterfaceAdded received={ia_ok}')
