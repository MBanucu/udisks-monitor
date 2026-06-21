"""Test dbus-next rapid connect/disconnect stress on 3.14."""
import asyncio, subprocess, tempfile, os, time, unittest

async def _cycle():
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

class TestDbusNextStress(unittest.TestCase):
    def test_cycle_1(self): self._run(1)
    def test_cycle_2(self): self._run(2)
    def test_cycle_3(self): self._run(3)
    def test_cycle_4(self): self._run(4)
    def test_cycle_5(self): self._run(5)
    def test_cycle_6(self): self._run(6)
    def test_cycle_7(self): self._run(7)
    def test_cycle_8(self): self._run(8)
    
    def _run(self, n):
        print(f'\n=== CYCLE {n} ===')
        result = asyncio.run(_cycle())
        print(f'  {result}')
        if 'failed' in result:
            self.fail(f'CYCLE {n}: {result}')
