"""Diagnostic: repeat the same integration test 10 times to isolate
whether failures are caused by number of unique tests or just number
of UDisks2 operations regardless of test variety."""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from udisks_monitor import (DevicePropertyChanged, InterfaceAdded,
                            InterfaceRemoved, JobAdded, JobCompleted,
                            JobProperties, JobRemoved, UdisksMonitor)

ALL_TYPES = (DevicePropertyChanged, InterfaceAdded, InterfaceRemoved,
             JobAdded, JobProperties, JobCompleted, JobRemoved)

RELIABLE = ALL_TYPES  # or exclude InterfaceRemoved if needed


def make_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                    'count=1'], capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    try:
        r = subprocess.run(
            ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
            capture_output=True, text=True)
        r.check_returncode()
    except subprocess.CalledProcessError:
        os.unlink(path)
        raise RuntimeError(
            f'loop-setup failed (rc={r.returncode}): '
            f'stdout={r.stdout} stderr={r.stderr}')
    for line in r.stdout.splitlines():
        if '/dev/' in line and 'loop' in line:
            return line.strip().split()[-1].rstrip('.'), path
    os.unlink(path)
    raise RuntimeError(f'parse fail: {r.stdout}')


def cleanup(device, img_path):
    for _ in range(3):
        subprocess.run(
            ['udisksctl', 'unmount', '-b', device, '--no-user-interaction'],
            capture_output=True)
        r = subprocess.run(
            ['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
            capture_output=True)
        if r.returncode == 0:
            break
        time.sleep(0.1)
    if os.path.exists(img_path):
        os.unlink(img_path)


class _Recorder:
    def __init__(self, mon):
        self.events = []
        self.received = {et: threading.Event() for et in ALL_TYPES}
        for et in ALL_TYPES:
            evt_ref = self.received[et]
            mon.subscribe(lambda e, r=evt_ref: (self.events.append(e), r.set()),
                          event_type=et)

    def wait_for(self, et, timeout=5):
        return self.received[et].wait(timeout=timeout)

    def types_seen(self):
        return {type(e) for e in self.events}


class TestRepeat10x(unittest.TestCase):

    def _cycle(self, n):
        print(f'\n=== CYCLE {n} ===')
        mon = UdisksMonitor()
        mon.start()
        if not mon.ready.wait(timeout=10):
            mon.stop()
            mon.join(timeout=5)
            print(f'  CYCLE {n}: NOT READY')
            return False
        rec = _Recorder(mon)
        dev, img = make_image()
        print(f'  device: {dev}')
        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)
        ok = rec.wait_for(JobCompleted, timeout=5)
        mon.stop()
        mon.join(timeout=5)
        cleanup(dev, img)
        seen = rec.types_seen()
        print(f'  JobCompleted: {ok}  signals: {len(rec.events)}  '
              f'types: {len(seen)}')
        if not ok:
            print(f'  CYCLE {n}: JobCompleted not received')
        return ok

    def test_cycle_1(self):
        self.assertTrue(self._cycle(1), 'cycle 1: JobCompleted not received')

    def test_cycle_2(self):
        self.assertTrue(self._cycle(2), 'cycle 2: JobCompleted not received')

    def test_cycle_3(self):
        self.assertTrue(self._cycle(3), 'cycle 3: JobCompleted not received')

    def test_cycle_4(self):
        self.assertTrue(self._cycle(4), 'cycle 4: JobCompleted not received')

    def test_cycle_5(self):
        self.assertTrue(self._cycle(5), 'cycle 5: JobCompleted not received')

    def test_cycle_6(self):
        self.assertTrue(self._cycle(6), 'cycle 6: JobCompleted not received')

    def test_cycle_7(self):
        self.assertTrue(self._cycle(7), 'cycle 7: JobCompleted not received')

    def test_cycle_8(self):
        self.assertTrue(self._cycle(8), 'cycle 8: JobCompleted not received')

    def test_cycle_9(self):
        self.assertTrue(self._cycle(9), 'cycle 9: JobCompleted not received')

    def test_cycle_10(self):
        self.assertTrue(self._cycle(10), 'cycle 10: JobCompleted not received')
