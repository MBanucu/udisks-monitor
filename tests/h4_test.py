import os, subprocess, tempfile, threading, time, unittest
from udisks_monitor import UdisksMonitor, DevicePropertyChanged

class TestExactFlow(unittest.TestCase):

    def setUp(self):
        self.mon = UdisksMonitor(backend='dbus')

    def tearDown(self):
        self.mon.stop()
        self.mon.join(timeout=5)

    def _make_image(self):
        fd, path = tempfile.mkstemp(suffix='.img')
        os.close(fd)
        subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                      capture_output=True, check=True)
        subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
        r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                          capture_output=True, text=True)
        r.check_returncode()
        device = None
        for line in r.stdout.splitlines():
            if '/dev/' in line and 'loop' in line:
                device = line.strip().split()[-1].rstrip('.')
        if not device:
            raise RuntimeError(f'parse fail: {r.stdout}')
        return device, path

    def test_one_cycle(self):
        print('\n=== CYCLE 1 ===')
        self.mon.start()
        t0 = time.monotonic()
        ok = self.mon.ready.wait(timeout=10)
        print(f'  monitor ready: {ok} ({time.monotonic()-t0:.1f}s)')
        if not ok:
            self.skipTest('monitor not ready')

        dev, img = self._make_image()
        print(f'  device: {dev}')

        r = subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'],
                          capture_output=True, text=True, timeout=30)
        print(f'  loop-delete: rc={r.returncode}')
        os.unlink(img)

    def test_second_cycle(self):
        print('\n=== CYCLE 2 ===')
        self.mon.start()
        ok = self.mon.ready.wait(timeout=10)
        print(f'  monitor ready: {ok}')
        if not ok:
            self.skipTest('monitor not ready')

        dev, img = self._make_image()
        print(f'  device: {dev}')

        r = subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'],
                          capture_output=True, text=True, timeout=30)
        print(f'  loop-delete: rc={r.returncode}')
        os.unlink(img)

    def test_third_cycle(self):
        print('\n=== CYCLE 3 ===')
        self.mon.start()
        ok = self.mon.ready.wait(timeout=10)
        print(f'  monitor ready: {ok}')
        if not ok:
            self.skipTest('monitor not ready')

        dev, img = self._make_image()
        print(f'  device: {dev}')

        r = subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'],
                          capture_output=True, text=True, timeout=30)
        print(f'  loop-delete: rc={r.returncode}')
        os.unlink(img)
