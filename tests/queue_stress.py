"""Interleaved stress test: subprocess → dbus-fast back-to-back pairs.

Tests that the worker-thread signal processing fix handles rapid
subprocess / D-Bus cycling without hanging, crashing, or losing events.

Runs 8 interleaved pairs.  Each pair:
  1. Subprocess monitor: start, loop-setup, wait InterfaceAdded,
     loop-delete, wait JobCompleted, stop.
  2. D-Bus (dbus-fast) monitor: start, loop-setup, wait InterfaceAdded,
     loop-delete, wait JobCompleted, stop.
"""

import subprocess
import threading
import time
import unittest

from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor

from tests.integration.helpers import cleanup, make_image, udisksctl_available

PAIRS = 8


def _run_one_backend(backend_label, backend_name):
    """Run a single monitor lifecycle and return (ok, error_message)."""
    mon = UdisksMonitor(backend=backend_name)
    ia = threading.Event()
    jc = threading.Event()

    mon.subscribe(lambda _: ia.set(), event_type=InterfaceAdded)
    mon.subscribe(lambda _: jc.set(), event_type=JobCompleted)
    mon.start()

    if not mon.ready.wait(timeout=15):
        mon.stop()
        mon.join(timeout=5)
        return False, f'{backend_label}: monitor never became ready'

    try:
        dev, img, _name = make_image()
        if not ia.wait(timeout=10):
            return False, f'{backend_label}: InterfaceAdded not received'
        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)
        if not jc.wait(timeout=10):
            return False, f'{backend_label}: JobCompleted not received'
    except Exception as exc:
        return False, f'{backend_label}: {type(exc).__name__}: {exc}'
    finally:
        cleanup(dev, img)
        mon.stop()
        mon.join(timeout=5)

    return True, None


def _monitor_ttl_filter():
    """Restart the dbus-daemon monitoring state if wild subscribers are stale.

    The dbus-fast backend keeps a persistent connection; cycling
    monitors quickly can leave D-Bus match rules in a confused state.
    Not currently needed, but kept as a hook for future diagnostics.
    """


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestQueueStress(unittest.TestCase):

    def test_interleaved_pairs(self):
        results = []
        for i in range(PAIRS):
            time.sleep(0.1)
            ok, err = _run_one_backend(f'pair-{i + 1} subprocess', 'subprocess')
            results.append(('subprocess', i + 1, ok, err))
            time.sleep(0.1)
            ok, err = _run_one_backend(f'pair-{i + 1} dbus', 'dbus')
            results.append(('dbus', i + 1, ok, err))

        passed = sum(1 for _, _, ok, _ in results if ok)
        failed = PAIRS * 2 - passed

        failures = [(b, p, e) for b, p, ok, e in results if not ok]
        report = [f'\nPassed {passed}/{PAIRS * 2} interleaved cycles']
        if failures:
            report.append(f'Failed {len(failures)}:')
            for backend, pair_idx, err in failures:
                report.append(f'  pair-{pair_idx} {backend}: {err}')

        self.assertEqual(passed, PAIRS * 2,
                         '\n'.join(report))


if __name__ == '__main__':
    unittest.main()
