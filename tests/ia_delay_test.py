import os, subprocess, tempfile, threading, time, unittest
from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor

def make_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'], capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'], capture_output=True, text=True)
    r.check_returncode()
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
    if os.path.exists(img):
        os.unlink(img)

def one_cycle(delay=0):
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
    if delay:
        time.sleep(delay)
    dev, img = make_image()
    try:
        ok = ia.wait(timeout=5)
        if not ok:
            return None, 'no InterfaceAdded after delay={}s'.format(delay)
        subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True)
        jc.wait(timeout=5)
    finally:
        cleanup(dev, img)
        mon.stop()
        mon.join(timeout=5)
    return events, 'ok'

class TestIADelay(unittest.TestCase):

    def _run(self, n, delay):
        print(f'\n=== CYCLE {n} (delay={delay}s) ===')
        events, status = one_cycle(delay=delay)
        if events is None:
            self.fail(f'CYCLE {n}: {status}')
        print(f'  OK: {len(events)} events, {len({type(e) for e in events})} types')

    # No delay - baseline (should show the 30% miss rate)
    def test_no_delay_1(self): self._run(1, 0)
    def test_no_delay_2(self): self._run(2, 0)
    def test_no_delay_3(self): self._run(3, 0)
    def test_no_delay_4(self): self._run(4, 0)
    def test_no_delay_5(self): self._run(5, 0)

    # 1 second delay - should eliminate the race
    def test_delay_1s_1(self): self._run(6, 1)
    def test_delay_1s_2(self): self._run(7, 1)
    def test_delay_1s_3(self): self._run(8, 1)
    def test_delay_1s_4(self): self._run(9, 1)
    def test_delay_1s_5(self): self._run(10, 1)
