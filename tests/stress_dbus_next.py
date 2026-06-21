"""Interleaved stress test: subprocess vs dbus-next, 4 back-to-back pairs."""

import subprocess
import threading
import time
import unittest

from udisks_monitor import (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
    UdisksMonitor,
)

from tests.integration.helpers import cleanup, make_image, udisksctl_available

ALL_EVENT_TYPES = (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobProperties,
    JobCompleted,
    JobRemoved,
)

_RELIABLE_TYPES = (
    DevicePropertyChanged,
    InterfaceAdded,
    JobAdded,
    JobProperties,
    JobCompleted,
    JobRemoved,
)

PAIRS = 4
BACKENDS = ('subprocess', 'dbus-next')


def _run_cycle(backend):
    """Run a single loop-setup → loop-delete cycle and return collected events."""
    events = []
    interface_added = threading.Event()
    job_completed = threading.Event()

    mon = UdisksMonitor(backend=backend)
    mon.subscribe(lambda _: interface_added.set(), event_type=InterfaceAdded)
    mon.subscribe(lambda _: job_completed.set(), event_type=JobCompleted)
    mon.subscribe(lambda e: events.append(e))
    mon.start()

    if not mon.ready.wait(timeout=15):
        mon.stop()
        mon.join(timeout=5)
        return None, f'{backend}: failed to start (ready timeout)'

    try:
        dev, img, _name = make_image()
    except Exception as exc:
        mon.stop()
        mon.join(timeout=5)
        return None, f'{backend}: make_image failed: {exc}'

    try:
        if not interface_added.wait(timeout=10):
            cleanup(dev, img)
            mon.stop()
            mon.join(timeout=5)
            return None, f'{backend}: InterfaceAdded timeout'

        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)

        if not job_completed.wait(timeout=15):
            cleanup(dev, img)
            mon.stop()
            mon.join(timeout=5)
            return None, f'{backend}: JobCompleted timeout'
    finally:
        cleanup(dev, img)
        mon.stop()
        mon.join(timeout=5)

    return events, None


def _summarise(events):
    if events is None:
        return {}
    counts = {}
    for e in events:
        key = type(e).__name__
        counts[key] = counts.get(key, 0) + 1
    return counts


@unittest.skipUnless(udisksctl_available(), 'udisksctl not available')
class TestStressDbusNext(unittest.TestCase):

    def test_interleaved_pairs(self):
        results = []

        for i in range(1, PAIRS + 1):
            for be in BACKENDS:
                label = f'pair {i}/{PAIRS} {be}'
                events, err = _run_cycle(be)
                seen = {type(e) for e in events} if events else set()
                missing = set(_RELIABLE_TYPES) - seen
                results.append({
                    'pair': i,
                    'backend': be,
                    'events': _summarise(events),
                    'ok': err is None and not missing,
                    'error': err,
                    'missing': [t.__name__ for t in missing],
                })
                if err:
                    print(f'  FAIL [{label}]: {err}', flush=True)
                elif missing:
                    print(f'  WARN [{label}]: missing {missing}', flush=True)
                else:
                    counts = _summarise(events)
                    print(f'  OK   [{label}]: {counts}', flush=True)
                time.sleep(0.5)

        print('\n=== RESULTS ===')
        passed = 0
        failed = 0
        for r in results:
            status = 'PASS' if r['ok'] else 'FAIL'
            if r['ok']:
                passed += 1
            else:
                failed += 1
            detail = r['error'] or ''
            if not detail and r['missing']:
                detail = f"missing: {r['missing']}"
            print(f'  {status} pair {r["pair"]} {r["backend"]}: '
                  f'{r["events"]} {detail}')

        print(f'\nPassed: {passed}/{len(results)}, Failed: {failed}/{len(results)}')

        self.assertEqual(failed, 0,
                         f'{failed}/{len(results)} cycles failed')


if __name__ == '__main__':
    unittest.main()
