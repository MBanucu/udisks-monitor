import threading, time, unittest
from udisks_monitor import UdisksMonitor

class TestJoinTimeout(unittest.TestCase):

    def test_join_timing_single(self):
        print('\n=== Single start/stop/join timing ===')
        mon = UdisksMonitor(backend='dbus')
        mon.start()
        ok = mon.ready.wait(timeout=10)
        print(f'  ready: {ok}')
        if not ok:
            self.skipTest('not ready')
        
        t0 = time.monotonic()
        mon.stop()
        mon.join(timeout=5)
        elapsed = time.monotonic() - t0
        alive = mon.is_alive()
        print(f'  join elapsed: {elapsed*1000:.0f}ms')
        print(f'  thread alive after join: {alive}')
        if alive:
            print('  ** WARNING: thread still alive after 5s join timeout **')

    def test_join_timing_ten_cycles(self):
        print('\n=== 10 start/stop/join cycles ===')
        alive_count = 0
        for i in range(10):
            mon = UdisksMonitor(backend='dbus')
            mon.start()
            ok = mon.ready.wait(timeout=10)
            if not ok:
                print(f'  cycle {i}: NOT READY - skipping')
                continue
            t0 = time.monotonic()
            mon.stop()
            mon.join(timeout=5)
            elapsed = time.monotonic() - t0
            alive = mon.is_alive()
            if alive:
                alive_count += 1
                print(f'  cycle {i}: join={elapsed*1000:.0f}ms ALIVE')
            else:
                if i < 3 or i >= 7:
                    print(f'  cycle {i}: join={elapsed*1000:.0f}ms dead')
        print(f'  alive after 5s: {alive_count}/10 cycles')
        if alive_count > 0:
            print('  ** STALE THREADS DETECTED **')
        # Count total threads still alive
        alive_threads = threading.enumerate()
        print(f'  total threads: {len(alive_threads)}')
        for t in alive_threads:
            if t != threading.current_thread():
                print(f'    {t.name} daemon={t.daemon}')

    def test_three_monitors_at_once(self):
        print('\n=== 3 simultaneous monitors ===')
        monitors = []
        for i in range(3):
            mon = UdisksMonitor(backend='dbus')
            mon.start()
            ok = mon.ready.wait(timeout=10)
            if ok:
                monitors.append(mon)
                print(f'  mon {i}: ready')
            else:
                print(f'  mon {i}: NOT READY')
        
        print(f'  started {len(monitors)}/3 monitors')
        
        # Stop all
        for i, mon in enumerate(monitors):
            t0 = time.monotonic()
            mon.stop()
            mon.join(timeout=5)
            elapsed = time.monotonic() - t0
            alive = mon.is_alive()
            print(f'  mon {i}: join={elapsed*1000:.0f}ms alive={alive}')
        
        total_threads = threading.enumerate()
        print(f'  remaining threads: {len(total_threads)}')

    def test_join_no_timeout(self):
        print('\n=== Join with no timeout ===')
        mon = UdisksMonitor(backend='dbus')
        mon.start()
        ok = mon.ready.wait(timeout=10)
        print(f'  ready: {ok}')
        if not ok:
            self.skipTest('not ready')
        t0 = time.monotonic()
        mon.stop()
        mon.join()  # no timeout - blocks until thread exits
        elapsed = time.monotonic() - t0
        print(f'  join (no timeout): {elapsed*1000:.0f}ms')
        print(f'  thread alive: {mon.is_alive()}')
