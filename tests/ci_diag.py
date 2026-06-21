import asyncio, os, subprocess, sys, tempfile, time, unittest
from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Message, MessageType

_ADD_MATCH = Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus', member='AddMatch', signature='s',
    body=['type=signal,sender=org.freedesktop.UDisks2'])

class TestCIDiagnostics(unittest.TestCase):

    def test_udisks2_version_and_status(self):
        r = subprocess.run(['dpkg', '-l', 'udisks2'], capture_output=True, text=True)
        print(f'\n  udisks2 package: {r.stdout.splitlines()[-1] if r.stdout.strip() else "NOT INSTALLED"}')
        r2 = subprocess.run(['systemctl', 'show', 'udisks2',
            '--property=ActiveState,SubState,MainPID,MemoryCurrent,CPUUsageNSec'],
            capture_output=True, text=True)
        print(f'  udisks2 status:')
        for line in r2.stdout.strip().split('\n'):
            print(f'    {line}')
        r3 = subprocess.run(['busctl', '--system', 'call', 'org.freedesktop.DBus',
            '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
            's', 'org.freedesktop.UDisks2'], capture_output=True, text=True)
        print(f'  UDisks2 D-Bus PID: {r3.stdout.strip()}')

    def test_dbus_daemon_info(self):
        r = subprocess.run(['dpkg', '-l', 'dbus-daemon', 'dbus-broker'], capture_output=True, text=True)
        print(f'\n  D-Bus packages:')
        for line in r.stdout.splitlines()[-3:]:
            print(f'    {line}')
        r2 = subprocess.run(['busctl', '--system', 'call', 'org.freedesktop.DBus',
            '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetConnectionCredentials',
            's', 'org.freedesktop.DBus'], capture_output=True, text=True)
        print(f'  D-Bus credentials: {r2.stdout.strip()[:200]}')

    def test_bare_loop_setup_timing(self):
        """Measure loop-setup timing with NO Python D-Bus connections."""
        fd, path = tempfile.mkstemp(suffix='.img')
        os.close(fd)
        subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'], capture_output=True, check=True)
        subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
        times = []
        for i in range(5):
            t0 = time.monotonic()
            r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                              capture_output=True, text=True, timeout=30)
            dt = (time.monotonic() - t0) * 1000
            times.append(dt)
            print(f'  run {i}: rc={r.returncode} {dt:.0f}ms')
            if r.returncode != 0:
                print(f'    stderr: {r.stderr.strip()[:200]}')
                break
            for line in r.stdout.splitlines():
                if '/dev/' in line:
                    dev = line.strip().split()[-1].rstrip('.')
            subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True)
        os.unlink(path)
        print(f'  timing: min={min(times):.0f}ms max={max(times):.0f}ms mean={sum(times)/len(times):.0f}ms')

    def test_raw_dbus_connect_and_loop(self):
        """Connect via dbus-fast, do loop ops, measure if it works."""
        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            await bus.call(_ADD_MATCH)
            bus.add_message_handler(lambda _: None)

            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'], capture_output=True, check=True)
            subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)

            t0 = time.monotonic()
            r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                              capture_output=True, text=True, timeout=30)
            dt = (time.monotonic() - t0) * 1000
            print(f'\n  loop-setup: rc={r.returncode} {dt:.0f}ms')
            if r.returncode != 0:
                print(f'  FAIL: {r.stderr.strip()[:200]}')

            bus.disconnect()
            os.unlink(path)
        asyncio.run(_run())

    @unittest.skipUnless(os.environ.get('CI'), 'CI only')
    def test_ten_bare_cycles(self):
        """10 rapid loop-setup+delete cycles, NO Python D-Bus connections."""
        ok = 0
        fail = 0
        for i in range(10):
            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'], capture_output=True)
            subprocess.run(['mkfs.vfat', path], capture_output=True)
            r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                              capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                ok += 1
                for line in r.stdout.splitlines():
                    if '/dev/' in line:
                        dev = line.strip().split()[-1].rstrip('.')
                subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True)
            else:
                fail += 1
                print(f'    bare cycle {i}: FAIL ({r.stderr.strip()[:150]})')
            os.unlink(path)
            time.sleep(0.5)
        print(f'\n  10 bare cycles: ok={ok} fail={fail}')
        if fail > 3:
            self.fail(f'{fail}/10 bare cycles failed — UDisks2 unstable WITHOUT Python')

    @unittest.skipUnless(os.environ.get('CI'), 'CI only')
    def test_ten_dbus_cycles(self):
        """10 rapid cycles, each with a fresh dbus-fast connection."""
        async def _run_all():
            ok = 0
            fail = 0
            for i in range(10):
                try:
                    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                    await bus.call(_ADD_MATCH)
                    bus.add_message_handler(lambda _: None)
                    fd, path = tempfile.mkstemp(suffix='.img')
                    os.close(fd)
                    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'], capture_output=True)
                    subprocess.run(['mkfs.vfat', path], capture_output=True)
                    r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                                      capture_output=True, text=True, timeout=30)
                    if r.returncode == 0:
                        ok += 1
                        for line in r.stdout.splitlines():
                            if '/dev/' in line:
                                dev = line.strip().split()[-1].rstrip('.')
                        subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True)
                    else:
                        fail += 1
                        print(f'    dbus cycle {i}: FAIL ({r.stderr.strip()[:150]})')
                    bus.disconnect()
                except Exception as e:
                    fail += 1
                    print(f'    dbus cycle {i}: EXCEPTION: {e}')
                os.unlink(path)
                await asyncio.sleep(0.5)
            return ok, fail
        ok, fail = asyncio.run(_run_all())
        print(f'\n  10 dbus-fast cycles: ok={ok} fail={fail}')
        if fail > 5:
            self.fail(f'{fail}/10 cycles with dbus-fast failed')
