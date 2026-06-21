"""Verify SOL2: event pre-check for interleaved backends stress test."""

import asyncio
import os
import subprocess
import tempfile
import threading
import time
import unittest

from dbus_fast import BusType, Message, MessageType
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

_CI = os.environ.get('CI', '') == 'true'


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


def _subprocess_cycle():
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
    dev, path = _make_image()
    if not ia.wait(timeout=5):
        _delete_image(dev, path)
        mon.stop()
        mon.join(timeout=5)
        return 'no InterfaceAdded'
    # The loop-setup job may already be complete; the delete
    # operation guarantees a fresh JobCompleted signal.
    _delete_image(dev, path)
    if not jc.wait(timeout=10):
        mon.stop()
        mon.join(timeout=5)
        return 'no JobCompleted'
    mon.stop()
    mon.join(timeout=5)
    return 'ok'


async def _dbus_cycle():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    await bus.call(_ADD_MATCH)
    bus.add_message_handler(lambda _: None)
    dev, path = _make_image()
    _delete_image(dev, path)
    bus.disconnect()


class TestInterleavedBackends(unittest.TestCase):
    """Alternate subprocess and D-Bus monitors with loop operations."""

    CYCLES = 6 if _CI else 15

    def test_interleaved_pairs(self):
        ok = 0
        fail = 0
        failures: list[str] = []
        for i in range(self.CYCLES):
            status = _subprocess_cycle()
            if status != 'ok':
                fail += 1
                failures.append(f'pair {i}: subprocess failed ({status})')
                print(f'    pair {i}: subprocess failed ({status})')
                continue
            try:
                asyncio.run(_dbus_cycle())
                ok += 1
            except Exception as e:
                fail += 1
                failures.append(f'pair {i}: dbus failed after subprocess ({e})')
                print(f'    pair {i}: dbus failed after subprocess ({e})')

        print(f'\n  {self.CYCLES} interleaved pairs (subprocess->dbus):')
        print(f'    ok: {ok}  fail: {fail}')
        if failures:
            print('    failures:')
            for f in failures:
                print(f'      {f}')

        min_pass = max(1, self.CYCLES // 2)
        self.assertGreaterEqual(
            ok, min_pass,
            f'Fewer than 50% pass rate: {ok}/{self.CYCLES}'
        )

        # Check for specific error patterns
        no_ia = sum(1 for f in failures if 'no InterfaceAdded' in f)
        no_jc = sum(1 for f in failures if 'no JobCompleted' in f)
        if no_ia:
            print(f'    ** no InterfaceAdded errors: {no_ia}')
        if no_jc:
            print(f'    ** no JobCompleted errors: {no_jc}')


if __name__ == '__main__':
    unittest.main()
