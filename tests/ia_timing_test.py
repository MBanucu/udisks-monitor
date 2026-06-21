import os, subprocess, sys, tempfile, threading, time, unittest
from udisks_monitor import InterfaceAdded, UdisksMonitor

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

class TestIATiming(unittest.TestCase):

    def test_timing(self):
        print(f'\n## Python: {sys.version}', flush=True)

        times = {}
        ia_event = threading.Event()
        timestamps = []

        def handler(evt):
            timestamps.append(('ia_received', time.monotonic()))
            ia_event.set()

        mon = UdisksMonitor(backend='subprocess')
        mon.subscribe(handler, event_type=InterfaceAdded)

        t0 = time.monotonic()
        mon.start()
        times['mon_start'] = time.monotonic() - t0

        ok = mon.ready.wait(timeout=10)
        times['ready'] = time.monotonic() - t0
        print(f'\n  monitor ready: {ok} ({times["ready"]*1000:.0f}ms)', flush=True)
        if not ok:
            mon.stop()
            self.fail('monitor not ready')

        t_img = time.monotonic()
        dev, img = make_image()
        times['loop_setup'] = time.monotonic() - t_img
        print(f'  loop-setup: {(times["loop_setup"])*1000:.0f}ms  dev={dev}', flush=True)

        t_wait = time.monotonic()
        got = ia_event.wait(timeout=10)
        elapsed = time.monotonic() - t_wait
        times['ia_wait'] = time.monotonic() - t0
        print(f'  InterfaceAdded received: {got}  wait: {elapsed*1000:.0f}ms', flush=True)

        if got and timestamps:
            ia_after_setup = timestamps[0][1] - t_img
            print(f'  IA after loop-setup start: {ia_after_setup*1000:.0f}ms', flush=True)

        for label, ts in timestamps:
            print(f'    [{label}] at +{(ts - t0)*1000:.0f}ms', flush=True)

        total = time.monotonic() - t0
        print(f'  total time: {total*1000:.0f}ms', flush=True)

        # Clean up
        mon.stop()
        mon.join(timeout=5)
        cleanup(dev, img)

        if not got:
            self.fail('InterfaceAdded event was NOT received')
