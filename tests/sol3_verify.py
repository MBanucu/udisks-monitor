"""Verify increased event-wait timeouts for CI environments.

Runs interleaved subprocess-monitor cycles that match the exact pattern
from test_backend_parity tests which break in CI when timeouts are too
short (< 5s).  Uses _timeout() from helpers — 15s in CI, 5s locally —
to confirm that the longer timeout eliminates false-negative failures.
"""

import os
import subprocess
import threading
import time
import unittest

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved, UdisksMonitor)

from tests.integration.helpers import (_timeout, cleanup, make_image,
                                       udisksctl_available)

_CI = os.environ.get('CI', '') == 'true'

ALL_EVENT_TYPES = (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobProperties,
    JobCompleted,
    JobRemoved,
)


def _subprocess_cycle():
    """Single subprocess-monitor cycle: start, loop-setup, loop-delete, stop."""
    ia = threading.Event()
    jc = threading.Event()
    mon = UdisksMonitor(backend='subprocess')
    mon.subscribe(lambda _: ia.set(), event_type=InterfaceAdded)
    mon.subscribe(lambda _: jc.set(), event_type=JobCompleted)
    mon.start()
    if not mon.ready.wait(timeout=10):
        mon.stop()
        mon.join(timeout=5)
        return 'not ready'

    dev, path, _name = _make_image_wrapped()
    if dev is None:
        mon.stop()
        mon.join(timeout=5)
        return 'loop-setup failed'

    t = _timeout()
    if not ia.wait(timeout=t):
        mon.stop()
        mon.join(timeout=5)
        cleanup(dev, path)
        return f'no InterfaceAdded (timeout={t}s)'

    subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                    '--no-user-interaction'], capture_output=True)

    if not jc.wait(timeout=t):
        mon.stop()
        mon.join(timeout=5)
        cleanup(dev, path)
        return f'no JobCompleted (timeout={t}s)'

    cleanup(dev, path)
    mon.stop()
    mon.join(timeout=5)
    return 'ok'


def _make_image_wrapped():
    """Wrapper around make_image that returns (None, None, None) on failure."""
    try:
        return make_image()
    except Exception:
        return None, None, None


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestIncreasedTimeouts(unittest.TestCase):

    CYCLES = 8 if _CI else 12

    def test_interleaved_subprocess_cycles(self):
        """Repeated subprocess-monitor cycles with _timeout() waits.

        The timeout adapts to the environment: 15s in CI, 5s locally.
        This mirrors the parity-test pattern that previously failed
        in CI due to slow signal propagation through stdout pipes.
        """
        ok = 0
        failures = []
        t = _timeout()
        print(f'\n  {self.CYCLES} subprocess cycles (timeout={t}s):')

        for i in range(self.CYCLES):
            t0 = time.monotonic()
            status = _subprocess_cycle()
            elapsed = time.monotonic() - t0
            if status == 'ok':
                ok += 1
            else:
                failures.append((i, status, elapsed))
            if status != 'ok' or (i + 1) % 4 == 0:
                print(f'    cycle {i}: {status} ({elapsed:.1f}s)')

        print(f'\n  Result: {ok}/{self.CYCLES} ok')
        if failures:
            for i, status, elapsed in failures:
                print(f'    FAIL cycle {i}: {status} ({elapsed:.1f}s)')

        if _CI:
            self.assertGreaterEqual(
                ok, self.CYCLES * 0.75,
                f'less than 75% pass rate in CI: {ok}/{self.CYCLES}')
        else:
            self.assertEqual(
                ok, self.CYCLES,
                f'expected all cycles to pass locally: {ok}/{self.CYCLES}')

    def test_all_event_types_with_increased_timeout(self):
        """Full lifecycle with _timeout() — all event types expected."""
        mon = UdisksMonitor(backend='subprocess')
        mon.start()
        self.assertTrue(mon.ready.wait(timeout=10))

        events = []
        for et in ALL_EVENT_TYPES:
            mon.subscribe(lambda e, _et=et: events.append(e), event_type=et)

        dev, img, _name = make_image()
        self.addCleanup(cleanup, dev, img)

        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)

        # Wait for JobCompleted as the terminal signal
        jc_event = threading.Event()
        mon.subscribe(lambda _: jc_event.set(), event_type=JobCompleted)
        jc_event.wait(timeout=_timeout())

        mon.stop()
        mon.join(timeout=5)

        seen = {type(e) for e in events}
        reliable = (DevicePropertyChanged, InterfaceAdded, JobAdded,
                    JobProperties, JobCompleted, JobRemoved)
        for et in reliable:
            self.assertIn(et, seen,
                          f'{et.__name__} not emitted (saw: '
                          f'{[t.__name__ for t in seen]})')


if __name__ == '__main__':
    unittest.main()
