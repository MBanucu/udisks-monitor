"""Replicate interleaved pattern: subprocess then dbus-next back-to-back, 4 pairs."""
import asyncio
import subprocess
import tempfile
import os
import unittest


async def _dbus_cycle():
    from dbus_next.aio import MessageBus
    from dbus_next import BusType, Message, MessageType

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    reply = await bus.call(Message(
        destination='org.freedesktop.DBus',
        path='/org/freedesktop/DBus',
        interface='org.freedesktop.DBus',
        member='AddMatch',
        signature='s',
        body=['type=signal,sender=org.freedesktop.UDisks2'],
    ))
    if reply.message_type == MessageType.ERROR:
        bus.disconnect()
        return 'AddMatch failed'

    count = [0]
    bus.add_message_handler(lambda m: count.__setitem__(0, count[0] + 1))

    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                   capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)

    r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        os.unlink(path)
        bus.disconnect()
        return f'loop-setup failed: {r.stderr.strip()[:200]}'

    device = None
    for line in r.stdout.splitlines():
        if '/dev/' in line:
            device = line.strip().split()[-1].rstrip('.')

    if device:
        subprocess.run(['udisksctl', 'unmount', '-b', device, '--no-user-interaction'],
                       capture_output=True)
        subprocess.run(['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
                       capture_output=True)

    os.unlink(path)
    bus.disconnect()
    return f'ok signals={count[0]}'


async def _subprocess_cycle():
    """Use subprocess-based udisksctl just like the real monitor loop."""
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                   capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)

    r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        os.unlink(path)
        return f'loop-setup failed: {r.stderr.strip()[:200]}'

    device = None
    for line in r.stdout.splitlines():
        if '/dev/' in line:
            device = line.strip().split()[-1].rstrip('.')

    if device:
        subprocess.run(['udisksctl', 'unmount', '-b', device, '--no-user-interaction'],
                       capture_output=True)
        subprocess.run(['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
                       capture_output=True)

    os.unlink(path)
    return 'ok'


class TestDbusNextParity(unittest.TestCase):
    def test_pair_1_dbus(self):
        print('\n=== PAIR 1 DBUS ===')
        result = asyncio.run(_dbus_cycle())
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'PAIR 1 DBUS: {result}')

    def test_pair_1_subprocess(self):
        print('\n=== PAIR 1 SUBPROCESS ===')
        result = asyncio.run(asyncio.to_thread(_subprocess_cycle))
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'PAIR 1 SUBPROCESS: {result}')

    def test_pair_2_dbus(self):
        print('\n=== PAIR 2 DBUS ===')
        result = asyncio.run(_dbus_cycle())
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'PAIR 2 DBUS: {result}')

    def test_pair_2_subprocess(self):
        print('\n=== PAIR 2 SUBPROCESS ===')
        result = asyncio.run(asyncio.to_thread(_subprocess_cycle))
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'PAIR 2 SUBPROCESS: {result}')

    def test_pair_3_dbus(self):
        print('\n=== PAIR 3 DBUS ===')
        result = asyncio.run(_dbus_cycle())
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'PAIR 3 DBUS: {result}')

    def test_pair_3_subprocess(self):
        print('\n=== PAIR 3 SUBPROCESS ===')
        result = asyncio.run(asyncio.to_thread(_subprocess_cycle))
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'PAIR 3 SUBPROCESS: {result}')

    def test_pair_4_dbus(self):
        print('\n=== PAIR 4 DBUS ===')
        result = asyncio.run(_dbus_cycle())
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'PAIR 4 DBUS: {result}')

    def test_pair_4_subprocess(self):
        print('\n=== PAIR 4 SUBPROCESS ===')
        result = asyncio.run(asyncio.to_thread(_subprocess_cycle))
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'PAIR 4 SUBPROCESS: {result}')
