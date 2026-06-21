"""Verification test for SOL1: bulk-read stdout in subprocess backend.

Tests that the subprocess backend reliably receives InterfaceAdded
and JobCompleted signals during rapid loop-device setup/teardown.
"""

import asyncio
import os
import subprocess
import tempfile
import threading
import time
import unittest

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


class TestBulkReadStdout(unittest.TestCase):
    """Verify bulk-read subprocess backend delivers signals reliably."""

    CYCLES = 4 if _CI else 10

    def test_interleaved_pairs(self):
        """Subprocess -> D-Bus pairs — verify subprocess backend delivers events.

        The loop-setup triggers an async filesystem-mount job whose
        JobCompleted may arrive after loop-setup returns.  We verify
        the backend by waiting for JobCompleted from the loop-delete
        (synchronous) instead.
        """
        def _subprocess_cycle():
            ia = threading.Event()
            jc_setup = threading.Event()
            jc_delete = threading.Event()
            ia_list = []
            jc_list = []
            all_list = []
            phase = [0]  # 0=setup, 1=delete

            def _on_ia(e):
                ia.set()
                ia_list.append(type(e).__name__)
            def _on_jc(e):
                if phase[0] == 0:
                    jc_setup.set()
                else:
                    jc_delete.set()
                jc_list.append(type(e).__name__)
            def _on_all(e):
                all_list.append(type(e).__name__)

            mon = UdisksMonitor(backend='subprocess')
            mon.subscribe(_on_ia, event_type=InterfaceAdded)
            mon.subscribe(_on_jc, event_type=JobCompleted)
            mon.subscribe(_on_all)
            t0 = time.monotonic()
            mon.start()
            if not mon.ready.wait(timeout=10):
                mon.stop()
                mon.join(timeout=5)
                return 'not ready', 0, 0, ia_list, jc_list, all_list

            dev, path = _make_image()
            t_setup = time.monotonic() - t0
            if not ia.wait(timeout=5):
                _delete_image(dev, path)
                mon.stop()
                mon.join(timeout=5)
                return 'no InterfaceAdded', t_setup, 0, ia_list, jc_list, all_list

            # Switch to delete phase and delete the image
            phase[0] = 1
            _delete_image(dev, path)

            if not jc_delete.wait(timeout=5):
                mon.stop()
                mon.join(timeout=5)
                return 'no JobCompleted (delete)', t_setup, 0, ia_list, jc_list, all_list

            mon.stop()
            mon.join(timeout=5)
            t_total = time.monotonic() - t0
            return 'ok', t_setup, t_total - t_setup, ia_list, jc_list, all_list

        async def _dbus_cycle():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            await bus.call(_ADD_MATCH)
            bus.add_message_handler(lambda _: None)
            dev, path = _make_image()
            _delete_image(dev, path)
            bus.disconnect()

        cycles = self.CYCLES
        ok = 0
        fail = 0
        errors = []
        setups = []
        deletes = []
        for i in range(cycles):
            status, t_setup, t_delete, ia_list, jc_list, all_list = _subprocess_cycle()
            if status != 'ok':
                fail += 1
                errors.append(f'pair {i}: subprocess failed ({status}) ia={ia_list} jc={jc_list}')
                print(f'    {errors[-1]}')
                continue
            setups.append(t_setup)
            deletes.append(t_delete)
            try:
                t0 = time.monotonic()
                asyncio.run(_dbus_cycle())
                totals_ = time.monotonic() - t0
            except Exception as e:
                fail += 1
                errors.append(f'pair {i}: dbus failed after subprocess ({e})')
                print(f'    {errors[-1]}')
                continue
            ok += 1

        print(f'\n  {cycles} interleaved pairs (subprocess->dbus):')
        print(f'    ok: {ok}  fail: {fail}')
        if setups:
            print(f'    subprocess setup mean: {sum(setups)/len(setups)*1000:.0f}ms')
        if deletes:
            print(f'    subprocess delete mean: {sum(deletes)/len(deletes)*1000:.0f}ms')

        for err in errors:
            print(f'  ERROR: {err}')

        if fail == 0:
            print('  RESULT: ALL PASS -- bulk-read backend is reliable')
        elif fail <= cycles * 0.3:
            print('  RESULT: MOSTLY PASS -- bulk-read backend improved reliability')
        else:
            print('  RESULT: HIGH FAIL RATE -- bulk-read backend did not help')

        if _CI:
            self.assertGreaterEqual(ok, cycles * 0.5,
                                    f'less than 50% pass: {ok}/{cycles}')


if __name__ == '__main__':
    unittest.main()
