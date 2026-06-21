"""Final retest: subprocess backend with Timer+event-driven ready, 10 cycles."""
import subprocess
import threading
import time
import unittest

from udisks_monitor import UdisksMonitor, InterfaceAdded


def _random_sparse_file():
    """Create a sparse file for loop device setup."""
    proc = subprocess.run(
        ['mktemp', '--suffix=.img'],
        capture_output=True, text=True, check=True)
    path = proc.stdout.strip()
    subprocess.run(['truncate', '-s', '10M', path], check=True)
    return path


def one_cycle(cycle_num):
    """Run one test cycle: start monitor, loop-setup, wait for InterfaceAdded, loop-delete.

    Returns (ok, ready_mode, ready_s, ia_s) tuple.
    ready_mode: 'timer' or 'event'
    ready_s: seconds from monitor.start() until ready.set()
    ia_s: seconds from loop-setup until InterfaceAdded received
    """
    ok = True
    ready_mode = 'unknown'
    ready_s = 0.0
    ia_s = 0.0

    img = _random_sparse_file()

    mon = UdisksMonitor(backend='subprocess')

    events = []
    ia_event = threading.Event()

    def on_ia(evt):
        events.append(evt)
        ia_event.set()

    mon.subscribe(on_ia, device='loop0')

    # Measure ready timing
    t0 = time.monotonic()
    mon.start()

    # Wait for ready with timeout
    if not mon.ready.wait(timeout=5.0):
        mon.stop()
        mon.join(timeout=2)
        subprocess.run(['rm', '-f', img])
        return (False, 'timeout', time.monotonic() - t0, 0)

    ready_s = time.monotonic() - t0

    # Ready was set either by Timer (0.5s) or event-driven
    if ready_s < 0.1:
        ready_mode = 'event'
    elif 0.4 <= ready_s <= 0.7:
        ready_mode = 'timer'
    else:
        ready_mode = f'timer_late_{ready_s:.3f}'

    # Create loop device
    t_setup = time.monotonic()
    subprocess.run(
        ['udisksctl', 'loop-setup', '-f', img, '--no-user-interaction'],
        capture_output=True, text=True, check=True)

    # Wait for InterfaceAdded
    if not ia_event.wait(timeout=10.0):
        ok = False
    ia_s = time.monotonic() - t_setup

    # Delete loop device
    subprocess.run(
        ['udisksctl', 'loop-delete', '-b', '/dev/loop0', '--no-user-interaction'],
        capture_output=True, text=True)

    # Clean up
    subprocess.run(['rm', '-f', img])

    mon.stop()
    mon.join(timeout=5)

    return (ok, ready_mode, ready_s, ia_s)


class TestRetestFinal(unittest.TestCase):
    """10-cycle diagnostic of subprocess backend ready/event timing."""

    cycles = []

    @classmethod
    def tearDownClass(cls):
        if cls.cycles:
            ok_count = sum(1 for c in cls.cycles if c[0])
            miss_count = sum(1 for c in cls.cycles if not c[0])
            timer_count = sum(1 for c in cls.cycles if c[1] == 'timer')
            event_count = sum(1 for c in cls.cycles if c[1] == 'event')
            other_count = len(cls.cycles) - timer_count - event_count
            print(f"\n{'='*60}")
            print(f"FINAL RETEST RESULTS ({len(cls.cycles)} cycles)")
            print(f"  Pass: {ok_count}  Miss: {miss_count}  Miss rate: {miss_count/len(cls.cycles)*100:.0f}%")
            print(f"  Ready via Timer: {timer_count}  Event: {event_count}  Other: {other_count}")
            for i, (ok, mode, rs, ia) in enumerate(cls.cycles, 1):
                status = 'PASS' if ok else 'MISS'
                print(f"  Cycle {i:2d}: {status}  ready={rs:.3f}s ({mode})  ia_delay={ia:.3f}s")
            print(f"{'='*60}\n")

    def test_cycle_01(self):
        result = one_cycle(1)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 1: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_02(self):
        result = one_cycle(2)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 2: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_03(self):
        result = one_cycle(3)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 3: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_04(self):
        result = one_cycle(4)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 4: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_05(self):
        result = one_cycle(5)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 5: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_06(self):
        result = one_cycle(6)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 6: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_07(self):
        result = one_cycle(7)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 7: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_08(self):
        result = one_cycle(8)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 8: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_09(self):
        result = one_cycle(9)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 9: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")

    def test_cycle_10(self):
        result = one_cycle(10)
        self.cycles.append(result)
        self.assertTrue(result[0], f"Miss: cycle 10: ready_mode={result[1]} ready_s={result[2]:.3f} ia_s={result[3]:.3f}")
