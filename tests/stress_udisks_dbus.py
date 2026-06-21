"""Performance test for UDisks2 + dbus-fast combination.

Measures throughput limits, connection limits, and combined stress
of the UDisks2 daemon under load from dbus-fast subscriptions +
loop device operations.  Designed to find the breaking point where
UDisks2 becomes unresponsive in CI.
"""

import asyncio
import os
import statistics
import subprocess
import tempfile
import threading
import time
import unittest

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

_ADD_MATCH = Message(
    destination='org.freedesktop.DBus',
    path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus',
    member='AddMatch',
    signature='s',
    body=['type=signal,sender=org.freedesktop.UDisks2'],
)

_CI = os.environ.get('CI', '') == 'true'


# ── helpers ──────────────────────────────────────────────────────

def _make_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'],
                   capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    r = subprocess.run(
        ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
        capture_output=True, text=True, timeout=60)
    r.check_returncode()
    for line in r.stdout.splitlines():
        if '/dev/' in line and 'loop' in line:
            return line.strip().split()[-1].rstrip('.'), path
    os.unlink(path)
    raise RuntimeError(f'parse fail: {r.stdout}')

def _delete_image(dev, path):
    subprocess.run(['udisksctl', 'unmount', '-b', dev,
                    '--no-user-interaction'], capture_output=True)
    for _ in range(3):
        r = subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                           '--no-user-interaction'],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            break
    if os.path.exists(path):
        os.unlink(path)


# ── single monitor throughput ────────────────────────────────────

class TestSingleMonitorThroughput(unittest.TestCase):
    """How many loop operations can one dbus-fast monitor handle?"""

    CYCLES = 5 if _CI else 20

    def test_loop_ops_throughput(self):
        """Rapid loop-setup → loop-delete cycles with one monitor."""
        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            await bus.call(_ADD_MATCH)
            count = [0]
            bus.add_message_handler(lambda _: count.__setitem__(0, count[0] + 1))

            ops = []
            for i in range(self.CYCLES):
                t0 = time.monotonic()
                try:
                    dev, path = _make_image()
                    t_setup = time.monotonic() - t0
                    _delete_image(dev, path)
                    t_total = time.monotonic() - t0
                    ops.append(('ok', t_setup, t_total))
                except Exception as e:
                    ops.append(('fail', 0, time.monotonic() - t0))
                    print(f'    cycle {i}: {e}')

            bus.disconnect()
            return ops, count[0]

        ops, signals = asyncio.run(_run())
        ok = sum(1 for o in ops if o[0] == 'ok')
        fail = len(ops) - ok
        if ok:
            setups = [o[1] for o in ops if o[0] == 'ok']
            totals = [o[2] for o in ops if o[0] == 'ok']
            print(f'\n  {self.CYCLES} cycles with 1 monitor:')
            print(f'    ok: {ok}  fail: {fail}')
            print(f'    setup:  min={min(setups)*1000:.0f}ms  '
                  f'mean={statistics.mean(setups)*1000:.0f}ms  '
                  f'p99={sorted(setups)[int(len(setups)*0.99)]*1000:.0f}ms')
            print(f'    total:  min={min(totals)*1000:.0f}ms  '
                  f'mean={statistics.mean(totals)*1000:.0f}ms')
            print(f'    signals: {signals} ({signals/max(ok,1):.1f}/cycle)')


# ── rapid close/reopen ───────────────────────────────────────────

class TestRapidCloseReopen(unittest.TestCase):
    """Open monitor → loop-setup → close monitor, repeat.  This is
    the exact pattern that breaks UDisks2 in the parity tests."""

    CYCLES = 8 if _CI else 30

    def test_close_reopen_dbns_dbns(self):
        """Alternating: close D-Bus monitor, open new D-Bus monitor."""
        async def _cycle():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            await bus.call(_ADD_MATCH)
            bus.add_message_handler(lambda _: None)
            dev, path = _make_image()
            _delete_image(dev, path)
            bus.disconnect()

        ok = 0
        fail = 0
        for i in range(self.CYCLES):
            try:
                asyncio.run(_cycle())
                ok += 1
            except Exception as e:
                fail += 1
                print(f'    cycle {i}: {e}')
        print(f'\n  {self.CYCLES} close/reopen D-Bus cycles:')
        print(f'    ok: {ok}  fail: {fail}')
        if ok < self.CYCLES * 0.5:
            self.fail(f'less than 50% pass rate: {ok}/{self.CYCLES}')

    def test_interleaved_backends(self):
        """Alternate: subprocess monitor → loop ops → close,
        then D-Bus monitor → loop ops → close.  This is the
        exact parity-test pattern that breaks UDisks2."""
        from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor

        def _subprocess_cycle():
            ia = threading.Event()
            jc = threading.Event()
            mon = UdisksMonitor(backend='subprocess')
            mon.subscribe(lambda _: ia.set(), event_type=InterfaceAdded)
            mon.subscribe(lambda _: jc.set(), event_type=JobCompleted)
            mon.start()
            if not mon.ready.wait(timeout=10):
                mon.stop(); mon.join(timeout=5)
                return 'not ready'
            dev, path = _make_image()
            ia.wait(timeout=5)
            _delete_image(dev, path)
            mon.stop(); mon.join(timeout=5)
            return 'ok'

        async def _dbus_cycle():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            await bus.call(_ADD_MATCH)
            bus.add_message_handler(lambda _: None)
            dev, path = _make_image()
            _delete_image(dev, path)
            bus.disconnect()

        cycles = 4 if _CI else 10
        ok = 0
        fail = 0
        for i in range(cycles):
            # Subprocess first, then D-Bus — same order as _collect_events
            status = _subprocess_cycle()
            if status != 'ok':
                fail += 1
                print(f'    pair {i}: subprocess failed ({status})')
                continue
            try:
                asyncio.run(_dbus_cycle())
                ok += 1
            except Exception as e:
                fail += 1
                print(f'    pair {i}: dbus failed after subprocess ({e})')
        print(f'\n  {cycles} interleaved pairs (subprocess→dbus):')
        print(f'    ok: {ok}  fail: {fail}')
        if _CI:
            self.assertGreaterEqual(ok, cycles * 0.5,
                                    f'less than 50% pass: {ok}/{cycles}')


# ── concurrent monitor load ──────────────────────────────────────

class TestConcurrentMonitorLoad(unittest.TestCase):
    """How many concurrent dbus-fast monitors can UDisks2 handle?"""

    MAX = 4 if _CI else 15

    def test_concurrent_monitor_ramp(self):
        """Open monitors one by one, do a loop op after each, find limit."""
        async def _open(n):
            buses = []
            for i in range(n):
                try:
                    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                    await bus.call(_ADD_MATCH)
                    bus.add_message_handler(lambda _: None)
                    buses.append(bus)
                except Exception as e:
                    print(f'    failed at {i}/{n}: {e}')
                    break
            return buses

        async def _cleanup(buses):
            for bus in buses:
                bus.disconnect()

        for n in (1, 2, 3, 4):
            buses = asyncio.run(_open(n))
            ok = len(buses)
            print(f'    {n} concurrent monitors: {ok} opened')

            if ok == n:
                # Do a loop operation with all monitors open
                try:
                    dev, path = _make_image()
                    _delete_image(dev, path)
                    print(f'    {n} monitors: loop-op OK')
                except Exception as e:
                    print(f'    {n} monitors: loop-op FAILED ({e})')

            asyncio.run(_cleanup(buses))
            if ok < n:
                print(f'    max concurrent: {ok}')
                break


# ── signal loss under load ───────────────────────────────────────

class TestSignalLoss(unittest.TestCase):
    """Does UDisks2 drop signals when monitors are rapidly
    connecting/disconnecting?"""

    CYCLES = 4 if _CI else 10

    def test_signal_count_across_cycles(self):
        """Count signals per cycle — should stay stable."""
        async def _cycle():
            signals = []
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            bus.add_message_handler(lambda m: signals.append(m))
            await bus.call(_ADD_MATCH)
            dev, path = _make_image()
            _delete_image(dev, path)
            bus.disconnect()
            return len(signals)

        counts = []
        for i in range(self.CYCLES):
            try:
                n = asyncio.run(_cycle())
                counts.append(n)
            except Exception as e:
                print(f'    cycle {i}: {e}')
                counts.append(-1)

        valid = [c for c in counts if c > 0]
        print(f'\n  signal counts across {self.CYCLES} cycles:')
        print(f'    counts: {counts}')
        if valid:
            print(f'    min={min(valid)} max={max(valid)} '
                  f'mean={statistics.mean(valid):.1f}')
            # Signal count should be consistent — UDisks2 shouldn't
            # drop signals just because we're cycling monitors
            ratio = min(valid) / max(valid) if max(valid) else 0
            print(f'    consistency: {ratio:.2f} (1.0 = perfect)')
            if _CI and ratio < 0.5:
                print('    ** signal loss detected **')


# ── long-running monitor endurance ───────────────────────────────

class TestMonitorEndurance(unittest.TestCase):
    """Keep a monitor open and hammer UDisks2 with loop operations."""

    DURATION = 3 if _CI else 15

    def test_sustained_operations(self):
        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            await bus.call(_ADD_MATCH)
            count = [0]
            bus.add_message_handler(lambda _: count.__setitem__(0, count[0] + 1))

            ok = 0
            fail = 0
            deadline = time.monotonic() + self.DURATION
            while time.monotonic() < deadline:
                try:
                    dev, path = _make_image()
                    _delete_image(dev, path)
                    ok += 1
                except Exception:
                    fail += 1

            bus.disconnect()
            return ok, fail, count[0]

        ok, fail, signals = asyncio.run(_run())
        rate = ok / max(self.DURATION, 0.1)
        print(f'\n  sustained ops ({self.DURATION}s): {ok} ok, {fail} fail, '
              f'{rate:.1f} ops/sec, {signals} signals')
        self.assertGreater(ok, 0)


if __name__ == '__main__':
    unittest.main()
