import asyncio
import os
import subprocess
import tempfile
import threading
import time
import unittest

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

ADD_MATCH = Message(
    destination='org.freedesktop.DBus',
    path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus',
    member='AddMatch',
    signature='s',
    body=['type=signal,sender=org.freedesktop.UDisks2'],
)


class TestSubscriberLoad(unittest.TestCase):

    def test_subscriber_load(self):
        """Simulate 7 subscribers with Event.set() in handler - heavy load."""
        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

            events = [threading.Event() for _ in range(7)]
            signal_count = [0]

            def handler(msg):
                signal_count[0] += 1
                for evt in events:
                    evt.set()

            bus.add_message_handler(handler)
            reply = await bus.call(ADD_MATCH)
            ok = reply.message_type != MessageType.ERROR
            print(f'  AddMatch: {"OK" if ok else "FAIL"}')

            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(
                ['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                capture_output=True, check=True)
            subprocess.run(
                ['mkfs.vfat', path], capture_output=True, check=True)

            t0 = time.monotonic()
            r = subprocess.run(
                ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                capture_output=True, text=True, timeout=60)
            t1 = time.monotonic()
            print(f'  loop-setup: rc={r.returncode} time={(t1 - t0) * 1000:.0f}ms')
            if r.returncode != 0:
                print(f'  loop-setup FAILED: {r.stderr.strip()[:300]}')

            device = None
            for line in r.stdout.splitlines():
                if '/dev/' in line:
                    device = line.strip().split()[-1].rstrip('.')

            if device:
                t2 = time.monotonic()
                r2 = subprocess.run(
                    ['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
                    capture_output=True, text=True, timeout=60)
                t3 = time.monotonic()
                print(f'  loop-delete: rc={r2.returncode} time={(t3 - t2) * 1000:.0f}ms')
                if r2.returncode != 0:
                    print(f'  loop-delete FAILED: {r2.stderr.strip()[:300]}')
            else:
                print('  WARNING: could not parse device name')

            print(f'  signals received: {signal_count[0]}')
            os.unlink(path)
            bus.disconnect()

        asyncio.run(_run())

    def test_subscriber_load_no_events(self):
        """Control: same as above but WITHOUT event.set() in handler."""
        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

            signal_count = [0]

            def handler(msg):
                signal_count[0] += 1

            bus.add_message_handler(handler)
            reply = await bus.call(ADD_MATCH)
            ok = reply.message_type != MessageType.ERROR
            print(f'  AddMatch: {"OK" if ok else "FAIL"}')

            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(
                ['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                capture_output=True, check=True)
            subprocess.run(
                ['mkfs.vfat', path], capture_output=True, check=True)

            t0 = time.monotonic()
            r = subprocess.run(
                ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                capture_output=True, text=True, timeout=60)
            t1 = time.monotonic()
            print(f'  loop-setup: rc={r.returncode} time={(t1 - t0) * 1000:.0f}ms')
            if r.returncode != 0:
                print(f'  loop-setup FAILED: {r.stderr.strip()[:300]}')

            device = None
            for line in r.stdout.splitlines():
                if '/dev/' in line:
                    device = line.strip().split()[-1].rstrip('.')

            if device:
                t2 = time.monotonic()
                r2 = subprocess.run(
                    ['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
                    capture_output=True, text=True, timeout=60)
                t3 = time.monotonic()
                print(f'  loop-delete: rc={r2.returncode} time={(t3 - t2) * 1000:.0f}ms')
                if r2.returncode != 0:
                    print(f'  loop-delete FAILED: {r2.stderr.strip()[:300]}')
            else:
                print('  WARNING: could not parse device name')

            print(f'  signals received: {signal_count[0]}')
            os.unlink(path)
            bus.disconnect()

        asyncio.run(_run())
