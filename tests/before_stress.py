"""Interleaved subprocess -> dbus-fast stress test (before pre-filter).

Tests 8 pairs of subprocess -> dbus-fast back-to-back loop operations,
measuring pass/fail rate and categorizing each failure reason.
"""

import asyncio
import subprocess
import tempfile
import threading
import time
import unittest
import os

from dbus_fast import BusType, Message
from dbus_fast.aio import MessageBus

from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor

_ADD_MATCH = Message(
    destination='org.freedesktop.DBus',
    path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus',
    member='AddMatch',
    signature='s',
    body=['type=signal,sender=org.freedesktop.UDisks2'],
)

PAIRS = 8


# ── helpers ──────────────────────────────────────────────────────

def _make_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                   capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    r = subprocess.run(
        ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
        capture_output=True, text=True, timeout=60)
    r.check_returncode()
    for line in r.stdout.splitlines():
        if '/dev/' in line and 'loop' in line:
            return line.strip().split()[-1].rstrip('.'), path
    os.unlink(path)
    raise RuntimeError(f'parse fail: {r.stdout}')


def _delete_image(dev, path):
    subprocess.run(['udisksctl', 'unmount', '-b', dev,
                    '--no-user-interaction'], capture_output=True)
    for _ in range(3):
        r = subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                           '--no-user-interaction'],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            break
    if os.path.exists(path):
        os.unlink(path)


# ── interleaved subprocess -> dbus-fast stress test ──────────────

class TestBeforePrefilterInterleaved(unittest.TestCase):
    """8 interleaved pairs: subprocess -> dbus-fast back-to-back.

    Each pair: start subprocess monitor, loop-setup, wait for
    InterfaceAdded, loop-delete, wait for JobCompleted, stop monitor;
    then start dbus-fast monitor, loop-setup, loop-delete, disconnect.
    """

    def test_interleaved_pairs(self):
        results = []

        for i in range(PAIRS):
            pair_result = {'pair': i, 'status': 'ok', 'error': None}

            # ── subprocess leg ──────────────────────────────
            ia = threading.Event()
            jc = threading.Event()
            try:
                mon = UdisksMonitor(backend='subprocess')
                mon.subscribe(lambda _: ia.set(), event_type=InterfaceAdded)
                mon.subscribe(lambda _: jc.set(), event_type=JobCompleted)
                mon.start()
            except Exception as e:
                pair_result['status'] = 'FAIL'
                pair_result['error'] = f'subprocess start error: {e}'
                results.append(pair_result)
                continue

            if not mon.ready.wait(timeout=10):
                mon.stop()
                mon.join(timeout=5)
                pair_result['status'] = 'FAIL'
                pair_result['error'] = 'subprocess not ready'
                results.append(pair_result)
                continue

            try:
                dev, path = _make_image()
            except Exception as e:
                mon.stop()
                mon.join(timeout=5)
                pair_result['status'] = 'FAIL'
                pair_result['error'] = f'subprocess loop-setup failed: {e}'
                results.append(pair_result)
                continue

            if not ia.wait(timeout=5):
                _delete_image(dev, path)
                mon.stop()
                mon.join(timeout=5)
                pair_result['status'] = 'FAIL'
                pair_result['error'] = 'subprocess no InterfaceAdded'
                results.append(pair_result)
                continue

            try:
                subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                                '--no-user-interaction'],
                               capture_output=True, text=True, timeout=60,
                               check=True)
            except subprocess.CalledProcessError as e:
                _delete_image(dev, path)
                mon.stop()
                mon.join(timeout=5)
                pair_result['status'] = 'FAIL'
                pair_result['error'] = f'subprocess loop-delete failed: {e}'
                results.append(pair_result)
                continue

            if not jc.wait(timeout=5):
                _delete_image(dev, path)
                mon.stop()
                mon.join(timeout=5)
                pair_result['status'] = 'FAIL'
                pair_result['error'] = 'subprocess no JobCompleted'
                results.append(pair_result)
                continue

            _delete_image(dev, path)
            mon.stop()
            mon.join(timeout=5)

            # ── dbus-fast leg ──────────────────────────────
            try:
                asyncio.run(self._dbus_cycle())
            except Exception as e:
                pair_result['status'] = 'FAIL'
                pair_result['error'] = f'dbus-fast error: {e}'
                results.append(pair_result)
                continue

            # Both legs passed
            results.append(pair_result)

        # ── report ─────────────────────────────────────────
        ok = sum(1 for r in results if r['status'] == 'ok')
        fail = len(results) - ok

        print(f'\n  Interleaved stress test ({PAIRS} pairs):')
        print(f'    ok: {ok}  fail: {fail}')
        for r in results:
            if r['status'] != 'ok':
                print(f'    pair {r["pair"]}: {r["error"]}')

        # Count error types
        from collections import Counter
        error_types = Counter(r['error'] for r in results if r['error'])
        if error_types:
            print(f'\n  Error breakdown:')
            for err, count in error_types.most_common():
                print(f'    {count}x {err}')

        self.assertGreaterEqual(
            ok, PAIRS * 0.5,
            f'Less than 50% pass rate: {ok}/{PAIRS} pairs passed'
        )

    @staticmethod
    async def _dbus_cycle():
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        await bus.call(_ADD_MATCH)
        bus.add_message_handler(lambda _: None)
        dev, path = _make_image()
        _delete_image(dev, path)
        bus.disconnect()


if __name__ == '__main__':
    unittest.main()
