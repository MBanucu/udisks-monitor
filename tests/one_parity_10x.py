import os, subprocess, tempfile, threading, time, unittest
from udisks_monitor import (InterfaceAdded, JobCompleted, UdisksMonitor)

def make_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'], capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    try:
        r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'], capture_output=True, text=True)
        r.check_returncode()
    except subprocess.CalledProcessError:
        os.unlink(path)
        raise RuntimeError(f'loop-setup FAILED: {r.stderr.strip()[:300]}')
    for line in r.stdout.splitlines():
        if '/dev/' in line and 'loop' in line:
            return line.strip().split()[-1].rstrip('.'), path
    os.unlink(path)
    raise RuntimeError(f'parse fail: {r.stdout}')

def cleanup(dev, img):
    for _ in range(3):
        subprocess.run(['udisksctl', 'unmount', '-b', dev, '--no-user-interaction'], capture_output=True)
        r = subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True)
        if r.returncode == 0:
            break
        time.sleep(0.1)
    if os.path.exists(img):
        os.unlink(img)

def one_cycle():
    """Single _collect_events-like cycle: start udisksctl monitor, loop ops, stop."""
    events = []
    ia = threading.Event()
    jc = threading.Event()
    mon = UdisksMonitor(backend='subprocess')
    mon.subscribe(lambda _: ia.set(), event_type=InterfaceAdded)
    mon.subscribe(lambda _: jc.set(), event_type=JobCompleted)
    mon.subscribe(lambda e: events.append(e))
    mon.start()
    if not mon.ready.wait(timeout=10):
        mon.stop(); mon.join(timeout=5)
        return None, 'not ready'
    dev, img = make_image()
    try:
        if not ia.wait(timeout=5):
            return None, 'no InterfaceAdded'
        subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True)
        if not jc.wait(timeout=5):
            return None, 'no JobCompleted'
    finally:
        cleanup(dev, img)
        mon.stop()
        mon.join(timeout=5)
    return events, 'ok'

class TestOneParity10x(unittest.TestCase):

    def test_cycle_1(self): self._run(1)
    def test_cycle_2(self): self._run(2)
    def test_cycle_3(self): self._run(3)
    def test_cycle_4(self): self._run(4)
    def test_cycle_5(self): self._run(5)
    def test_cycle_6(self): self._run(6)
    def test_cycle_7(self): self._run(7)
    def test_cycle_8(self): self._run(8)
    def test_cycle_9(self): self._run(9)
    def test_cycle_10(self): self._run(10)

    def _run(self, n):
        print(f'\n=== CYCLE {n} ===')
        events, status = one_cycle()
        if events is None:
            self.fail(f'CYCLE {n}: {status}')
        print(f'  CYCLE {n}: {len(events)} events, {len({type(e) for e in events})} types')
