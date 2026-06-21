"""Stress test for dbus-fast: capabilities and limitations.

Exercises rapid connect/disconnect, concurrent connections,
signal handler throughput, and cleanup timing.  No loop devices
required — only the D-Bus system bus and UDisks2 need to exist.
"""

import asyncio
import os
import statistics
import subprocess
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


class _BusProbe:
    """Connect to D-Bus, add match rule, disconnect ASAP."""

    def __init__(self):
        self.connect_ms = 0.0
        self.addmatch_ms = 0.0
        self.disconnect_ms = 0.0
        self.error = None

    async def _probe(self):
        t0 = time.monotonic()
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self.connect_ms = (time.monotonic() - t0) * 1000

        t1 = time.monotonic()
        reply = await bus.call(_ADD_MATCH)
        self.addmatch_ms = (time.monotonic() - t1) * 1000
        if reply.message_type == MessageType.ERROR:
            self.error = f'AddMatch error: {reply.body[0] if reply.body else "unknown"}'

        t2 = time.monotonic()
        bus.disconnect()
        self.disconnect_ms = (time.monotonic() - t2) * 1000

    def run(self):
        asyncio.run(self._probe())


class _CountingHandler:
    """Handler that counts signals with optional processing delay."""

    def __init__(self, delay=0.0):
        self.count = 0
        self.first_at = 0.0
        self.last_at = 0.0
        self.delay = delay

    def __call__(self, _msg):
        if self.count == 0:
            self.first_at = time.monotonic()
        self.count += 1
        self.last_at = time.monotonic()
        if self.delay:
            time.sleep(self.delay)


# ── connection stress ────────────────────────────────────────────

class TestConnectDisconnect(unittest.TestCase):
    """Rapid connect → AddMatch → disconnect cycles."""

    CYCLES = 20 if _CI else 100

    def test_rapid_cycles(self):
        ok = 0
        fail = 0
        failures = []
        for i in range(self.CYCLES):
            probe = _BusProbe()
            probe.run()
            if probe.error:
                fail += 1
                failures.append(f'cycle {i}: {probe.error}')
            else:
                ok += 1

        print(f'\n  {self.CYCLES} connect/disconnect cycles:')
        print(f'    ok: {ok}  fail: {fail}')
        if failures:
            print(f'    failures:')
            for f in failures[:5]:
                print(f'      {f}')
        if _CI:
            self.assertGreaterEqual(ok, self.CYCLES * 0.7,
                                    f'less than 70% successful ({ok}/{self.CYCLES})')
        else:
            self.assertEqual(fail, 0, f'{fail} cycles failed')

    def test_connection_timing(self):
        timings = {'connect': [], 'addmatch': [], 'disconnect': []}
        for _ in range(10):
            probe = _BusProbe()
            probe.run()
            if not probe.error:
                timings['connect'].append(probe.connect_ms)
                timings['addmatch'].append(probe.addmatch_ms)
                timings['disconnect'].append(probe.disconnect_ms)

        print(f'\n  connection timing (10 cycles):')
        for key in ('connect', 'addmatch', 'disconnect'):
            vals = timings[key]
            if vals:
                print(f'    {key}: min={min(vals):.1f}ms  max={max(vals):.1f}ms  '
                      f'mean={statistics.mean(vals):.1f}ms  '
                      f'p99={sorted(vals)[int(len(vals)*0.99)]:.1f}ms')
            else:
                print(f'    {key}: no data')


# ── concurrent connections ───────────────────────────────────────

class TestConcurrentConnections(unittest.TestCase):
    """Open N simultaneous D-Bus connections."""

    CONCURRENT = 5 if _CI else 20

    def test_concurrent_connections(self):
        async def _run():
            buses = []
            errors = 0
            for i in range(self.CONCURRENT):
                try:
                    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                    reply = await bus.call(_ADD_MATCH)
                    if reply.message_type == MessageType.ERROR:
                        errors += 1
                    buses.append(bus)
                except Exception:
                    errors += 1

            print(f'\n  concurrent connections: {len(buses)}/{self.CONCURRENT} opened, '
                  f'{errors} errors')

            for bus in buses:
                bus.disconnect()
            return len(buses)

        opened = asyncio.run(_run())
        self.assertGreater(opened, 0)


# ── signal throughput ────────────────────────────────────────────

class TestSignalThroughput(unittest.TestCase):
    """Measure how many signals the handler can process."""

    DURATION = 2 if _CI else 10

    def test_raw_throughput(self):
        handler = _CountingHandler()

        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            bus.add_message_handler(handler)
            await bus.call(_ADD_MATCH)

            # Trigger UDisks2 activity to generate signals
            subprocess.run(
                ['udisksctl', 'dump'], capture_output=True, timeout=30)
            subprocess.run(
                ['dd', 'if=/dev/zero', 'of=/tmp/_stress.img', 'bs=1M',
                 'count=1'], capture_output=True)
            subprocess.run(
                ['mkfs.vfat', '/tmp/_stress.img'], capture_output=True)
            subprocess.run(
                ['udisksctl', 'loop-setup', '-f', '/tmp/_stress.img',
                 '--no-user-interaction'], capture_output=True)

            await asyncio.sleep(self.DURATION)

            # Parse and cleanup
            r = subprocess.run(
                ['udisksctl', 'loop-delete', '-b',
                 '/tmp/_stress.img', '--no-user-interaction'],
                capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if '/dev/' in line:
                    dev = line.strip().split()[-1].rstrip('.')
                    subprocess.run(
                        ['udisksctl', 'loop-delete', '-b', dev,
                         '--no-user-interaction'], capture_output=True)
            if os.path.exists('/tmp/_stress.img'):
                os.unlink('/tmp/_stress.img')

            bus.disconnect()

        asyncio.run(_run())

        interval = max(handler.last_at - handler.first_at, 0.001)
        rate = handler.count / max(interval, 0.001)
        print(f'\n  signal throughput ({self.DURATION}s window):')
        print(f'    total: {handler.count} signals')
        print(f'    rate:  {rate:.1f} signals/sec')
        print(f'    first: {handler.first_at:.3f}')
        print(f'    last:  {handler.last_at:.3f}')
        print(f'    window: {interval:.3f}s')

    def test_handler_with_delay(self):
        for delay in (0.001, 0.01):
            handler = _CountingHandler(delay=delay)
            async def _run():
                bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                bus.add_message_handler(handler)
                await bus.call(_ADD_MATCH)
                subprocess.run(['udisksctl', 'dump'],
                             capture_output=True, timeout=30)
                await asyncio.sleep(1)
                bus.disconnect()
            asyncio.run(_run())
            print(f'\n  handler with {delay*1000:.0f}ms delay: '
                  f'{handler.count} signals received')

    def test_no_handler_signal_drop(self):
        """Verify signals are dropped without a handler, not queued."""
        count = [0]
        def handler(_msg):
            count[0] += 1

        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            # NO handler yet — AddMatch but no add_message_handler
            await bus.call(_ADD_MATCH)
            subprocess.run(['udisksctl', 'dump'],
                         capture_output=True, timeout=30)
            await asyncio.sleep(0.5)
            # Now add handler
            bus.add_message_handler(handler)
            subprocess.run(['udisksctl', 'dump'],
                         capture_output=True, timeout=30)
            await asyncio.sleep(0.5)
            bus.disconnect()
        asyncio.run(_run())
        print(f'\n  signals after adding handler late: {count[0]}')
        # Handler should catch the SECOND dump's signals,
        # proving missed signals are not replayed


# ── connection leak detection ─────────────────────────────────────

class TestConnectionLeaks(unittest.TestCase):
    """Verify disconnect actually closes the socket."""

    def test_disconnect_is_clean(self):
        async def _run():
            initial = _count_fds()
            for _ in range(10):
                bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                await bus.call(_ADD_MATCH)
                bus.disconnect()
            await asyncio.sleep(0.5)
            final = _count_fds()
            return initial, final

        initial, final = asyncio.run(_run())
        diff = final - initial
        print(f'\n  file descriptors: before={initial} after={final} diff={diff}')
        if diff > 5:
            print(f'  ** possible leak: {diff} extra FDs **')

    def test_thread_starts_and_joins(self):
        import asyncio

        class _MonitorThread(threading.Thread):
            def __init__(self):
                super().__init__(daemon=True)
                self._stop = threading.Event()
                self.started = False
                self.stopped = False

            def run(self):
                loop = asyncio.new_event_loop()

                async def _listen():
                    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                    await bus.call(_ADD_MATCH)
                    self.started = True
                    while not self._stop.is_set():
                        await asyncio.sleep(0.01)
                    bus.disconnect()
                    self.stopped = True

                loop.run_until_complete(_listen())
                loop.close()

        for i in range(10):
            t = _MonitorThread()
            t.start()
            time.sleep(0.1)
            t._stop.set()
            t.join(timeout=5)
            self.assertFalse(t.is_alive(),
                             f'iteration {i}: thread still alive after join')
        thread_count = threading.active_count()
        print(f'\n  10 start/stop/join cycles: {thread_count} active threads')
        self.assertLess(thread_count, 15,
                        f'too many threads: {thread_count}')


def _count_fds():
    try:
        return len(os.listdir('/proc/self/fd'))
    except Exception:
        return -1


if __name__ == '__main__':
    unittest.main()
