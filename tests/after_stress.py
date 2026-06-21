import asyncio, os, subprocess, tempfile, threading, time, unittest
from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor
from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Message, MessageType

_ADD_MATCH = Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus', member='AddMatch', signature='s',
    body=['type=signal,sender=org.freedesktop.UDisks2'])

def _make_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'], capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'], capture_output=True, text=True, timeout=60)
    r.check_returncode()
    for line in r.stdout.splitlines():
        if '/dev/' in line:
            return line.strip().split()[-1].rstrip('.'), path
    os.unlink(path)
    raise RuntimeError(f'parse fail: {r.stdout}')

def _delete_image(dev, path):
    subprocess.run(['udisksctl', 'unmount', '-b', dev, '--no-user-interaction'], capture_output=True)
    for _ in range(3):
        r = subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            break
    if os.path.exists(path):
        os.unlink(path)

class TestAfterPrefilter(unittest.TestCase):
    PAIRS = 8

    def test_interleaved_pairs(self):
        ok = 0
        fail = 0
        failures = []
        for i in range(self.PAIRS):
            # Subprocess cycle
            ia = threading.Event()
            jc = threading.Event()
            mon = UdisksMonitor(backend='subprocess')
            mon.subscribe(lambda _: ia.set(), event_type=InterfaceAdded)
            mon.subscribe(lambda _: jc.set(), event_type=JobCompleted)
            mon.start()
            if not mon.ready.wait(timeout=10):
                mon.stop(); mon.join(timeout=5)
                fail += 1; failures.append(f'pair {i}: subprocess not ready')
                continue
            try:
                dev, path = _make_image()
            except Exception as e:
                mon.stop(); mon.join(timeout=5)
                fail += 1; failures.append(f'pair {i}: subprocess loop-setup: {e}')
                continue
            if not ia.wait(timeout=5):
                _delete_image(dev, path); mon.stop(); mon.join(timeout=5)
                fail += 1; failures.append(f'pair {i}: subprocess no InterfaceAdded')
                continue
            _delete_image(dev, path)
            if not jc.wait(timeout=5):
                mon.stop(); mon.join(timeout=5)
                fail += 1; failures.append(f'pair {i}: subprocess no JobCompleted')
                continue
            mon.stop(); mon.join(timeout=5)
            
            # D-Bus cycle
            async def _dbus():
                bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                await bus.call(_ADD_MATCH)
                bus.add_message_handler(lambda _: None)
                dev, path = _make_image()
                _delete_image(dev, path)
                bus.disconnect()
            try:
                asyncio.run(_dbus())
                ok += 1
            except Exception as e:
                fail += 1
                failures.append(f'pair {i}: dbus: {e}')
        
        print(f'\n  {self.PAIRS} interleaved pairs:')
        print(f'    ok: {ok}  fail: {fail}')
        for f in failures:
            print(f'    {f}')
        
        if ok < self.PAIRS * 0.5:
            self.fail(f'less than 50% pass: {ok}/{self.PAIRS}')
