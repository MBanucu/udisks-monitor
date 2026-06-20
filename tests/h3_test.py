"""Diagnostic: does AddMatch survive disconnect and interfere with next iteration?"""

import asyncio
import subprocess
import tempfile
import time
import os
import unittest

from dbus_fast.aio import MessageBus as AioMessageBus
from dbus_fast import BusType, Message, MessageType


def mkfs_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(
        ['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
        capture_output=True, check=True,
    )
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    return path


def loop_setup(img_path):
    r = subprocess.run(
        ['udisksctl', 'loop-setup', '-f', img_path, '--no-user-interaction'],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return None, r.returncode, r.stderr.strip()
    for line in r.stdout.splitlines():
        if '/dev/' in line and 'loop' in line:
            device = line.strip().split()[-1].rstrip('.')
            return device, r.returncode, ''
    return None, -1, f'parse error: {r.stdout.strip()}'


def loop_delete(device):
    r = subprocess.run(
        ['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stderr.strip()


class TestMatchRuleCleanup(unittest.TestCase):

    def test_three_iterations(self):
        results = []

        for i in range(1, 4):
            print(f'\n=== ITERATION {i} ===', flush=True)

            # Force UDisks2
            subprocess.run(['udisksctl', 'dump'], capture_output=True, timeout=30)

            # Create image and loop-setup
            img_path = None
            device = None
            loop_setup_rc = None
            loop_setup_err = None
            loop_delete_rc = None
            loop_delete_err = None
            t0_setup = 0
            t0_delete = 0
            signal_count = 0

            try:
                img_path = mkfs_image()

                # asyncio: connect, add match, count signals
                async def run():
                    nonlocal signal_count, device, loop_setup_rc, loop_setup_err
                    nonlocal loop_delete_rc, loop_delete_err
                    nonlocal t0_setup, t0_delete

                    bus = await AioMessageBus(bus_type=BusType.SYSTEM).connect()

                    signals = []

                    def handler(msg):
                        if msg.message_type == MessageType.SIGNAL:
                            signals.append(msg)

                    bus.add_message_handler(handler)

                    reply = await bus.call(Message(
                        destination='org.freedesktop.DBus',
                        path='/org/freedesktop/DBus',
                        interface='org.freedesktop.DBus',
                        member='AddMatch',
                        signature='s',
                        body=['type=signal,sender=org.freedesktop.UDisks2'],
                    ))
                    if reply.message_type == MessageType.ERROR:
                        raise RuntimeError(
                            f'AddMatch failed: {reply.body[0] if reply.body else "unknown"}')

                    await asyncio.sleep(0.1)

                    t0_setup = time.monotonic()
                    device, loop_setup_rc, loop_setup_err = loop_setup(img_path)
                    t_setup_elapsed = time.monotonic() - t0_setup

                    if device:
                        await asyncio.sleep(0.2)

                        t0_delete = time.monotonic()
                        loop_delete_rc, loop_delete_err = loop_delete(device)
                        t_delete_elapsed = time.monotonic() - t0_delete

                        await asyncio.sleep(0.5)

                    signal_count = len(signals)
                    bus.disconnect()

                asyncio.run(run())

            except Exception as e:
                print(f'  EXCEPTION: {e}', flush=True)

            finally:
                # Cleanup image file
                if img_path and os.path.exists(img_path):
                    try:
                        os.unlink(img_path)
                    except OSError:
                        pass

                # Print results
                setup_elapsed = time.monotonic() - t0_setup if t0_setup else 0
                delete_elapsed = time.monotonic() - t0_delete if t0_delete else 0
                print(f'  signals received : {signal_count}', flush=True)
                print(f'  loop-setup        : rc={loop_setup_rc} ({setup_elapsed:.2f}s)', flush=True)
                if loop_setup_err:
                    print(f'  loop-setup stderr : {loop_setup_err}', flush=True)
                print(f'  loop-delete       : rc={loop_delete_rc} ({delete_elapsed:.2f}s)', flush=True)
                if loop_delete_err:
                    print(f'  loop-delete stderr: {loop_delete_err}', flush=True)

                results.append({
                    'iteration': i,
                    'signals': signal_count,
                    'loop_setup_rc': loop_setup_rc,
                    'loop_setup_err': loop_setup_err,
                    'loop_delete_rc': loop_delete_rc,
                    'loop_delete_err': loop_delete_err,
                })

            time.sleep(1)

        print('\n=== SUMMARY ===', flush=True)
        for r in results:
            print(f'  iter {r["iteration"]}: signals={r["signals"]} '
                  f'setup_rc={r["loop_setup_rc"]} delete_rc={r["loop_delete_rc"]}',
                  flush=True)
            if r['loop_setup_err']:
                print(f'    setup_err: {r["loop_setup_err"]}', flush=True)
            if r['loop_delete_err']:
                print(f'    delete_err: {r["loop_delete_err"]}', flush=True)

        success = all(r['loop_setup_rc'] == 0 for r in results)
        self.assertTrue(success, 'one or more loop-setup calls failed')
