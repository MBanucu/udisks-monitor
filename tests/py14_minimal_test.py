import asyncio, os, subprocess, tempfile, time, unittest
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

class TestPy14Minimal(unittest.TestCase):

    def test_simple_connect_and_loop_ops(self):
        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            print(f'  dbus connected: {bus.unique_name}')

            reply = await bus.call(ADD_MATCH)
            ok = reply.message_type != MessageType.ERROR
            print(f'  AddMatch: {"OK" if ok else "FAIL"}')

            # minimal handler
            count = [0]
            def handler(msg):
                count[0] += 1
            bus.add_message_handler(handler)

            # loop-setup
            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                         capture_output=True, check=True)
            subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)

            t0 = time.monotonic()
            r = subprocess.run(
                ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                capture_output=True, text=True, timeout=60)
            t1 = time.monotonic()
            print(f'  loop-setup: rc={r.returncode} time={(t1-t0)*1000:.0f}ms')
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
                print(f'  loop-delete: rc={r2.returncode} time={(t3-t2)*1000:.0f}ms')
                if r2.returncode != 0:
                    print(f'  loop-delete FAILED: {r2.stderr.strip()[:300]}')
            else:
                print('  WARNING: could not parse device from loop-setup output')

            print(f'  signals received: {count[0]}')
            os.unlink(path)
            bus.disconnect()

        asyncio.run(_run())

    def test_second_cycle(self):
        async def _run():
            # Force UDisks2 activation first
            subprocess.run(['udisksctl', 'dump'], capture_output=True, timeout=30)

            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            print(f'  dbus connected: {bus.unique_name}')

            reply = await bus.call(ADD_MATCH)
            print(f'  AddMatch: {"OK" if reply.message_type != MessageType.ERROR else "FAIL"}')

            count = [0]
            bus.add_message_handler(lambda msg: count.__setitem__(0, count[0] + 1))

            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                         capture_output=True, check=True)
            subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)

            t0 = time.monotonic()
            r = subprocess.run(
                ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                capture_output=True, text=True, timeout=60)
            t1 = time.monotonic()
            print(f'  loop-setup: rc={r.returncode} time={(t1-t0)*1000:.0f}ms')
            if r.returncode != 0:
                print(f'  stderr: {r.stderr.strip()[:300]}')

            device = None
            for line in r.stdout.splitlines():
                if '/dev/' in line:
                    device = line.strip().split()[-1].rstrip('.')

            if device:
                r2 = subprocess.run(
                    ['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
                    capture_output=True, text=True, timeout=60)
                print(f'  loop-delete: rc={r2.returncode}')

            print(f'  signals: {count[0]}')
            os.unlink(path)
            bus.disconnect()
        asyncio.run(_run())
