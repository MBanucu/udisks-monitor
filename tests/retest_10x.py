import os, subprocess, tempfile, threading, time, unittest
from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor

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

def one_cycle():
    events = []
    ia = threading.Event()
    jc = threading.Event()
    mon = UdisksMonitor(backend='subprocess')
    mon.subscribe(lambda _: ia.set(), event_type=InterfaceAdded)
    mon.subscribe(lambda _: jc.set(), event_type=JobCompleted)
    mon.subscribe(lambda e: events.append(e))
    
    t0 = time.monotonic()
    mon.start()
    ok = mon.ready.wait(timeout=10)
    t_ready = (time.monotonic() - t0) * 1000
    if not ok:
        mon.stop(); mon.join(timeout=5)
        return None, f'not ready ({t_ready:.0f}ms)'
    
    dev, img = make_image()
    try:
        t_ia = time.monotonic()
        got = ia.wait(timeout=5)
        ia_elapsed = (time.monotonic() - t_ia) * 1000
        if not got:
            return None, f'no InterfaceAdded (waited {ia_elapsed:.0f}ms, ready in {t_ready:.0f}ms)'
        subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True)
        jc.wait(timeout=5)
    finally:
        cleanup(dev, img)
        mon.stop()
        mon.join(timeout=5)
    return events, f'ready={t_ready:.0f}ms ia={ia_elapsed:.0f}ms'

class TestRetest10x(unittest.TestCase):
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
        print(f'  CYCLE {n}: {len(events)} events, {status}')
