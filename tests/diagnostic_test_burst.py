"""Diagnostic: verify UDisks2 emitter signal burst on activation.

Connects to D-Bus, subscribes to UDisks2 signals, counts how many
arrive in the first seconds after AddMatch.  This tests the theory
that fresh UDisks2 activation (not pre-running daemon) causes a
large burst of initialization signals.
"""

import asyncio
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


class _BurstCollector:

    def __init__(self):
        self.counts = {}   # iface.member -> count
        self.total = 0
        self._start = 0.0
        self._first_at = 0.0

    def on_message(self, msg):
        if self._start == 0.0:
            self._start = time.monotonic()
            self._first_at = self._start
        key = f'{msg.interface}.{msg.member}'
        self.counts[key] = self.counts.get(key, 0) + 1
        self.total += 1

    def elapsed(self):
        if self._start == 0.0:
            return 0.0
        return time.monotonic() - self._start


class TestUDisks2SignalBurst(unittest.TestCase):
    """Connect to D-Bus, subscribe to UDisks2 signals, count burst."""

    DURATION = 10   # seconds to listen

    def test_signal_burst_on_fresh_connection(self):
        collector = _BurstCollector()

        async def _listen():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            bus.add_message_handler(collector.on_message)

            reply = await bus.call(_ADD_MATCH)
            if reply.message_type == MessageType.ERROR:
                bus.disconnect()
                err = reply.body[0] if reply.body else 'unknown'
                raise RuntimeError(f'AddMatch failed: {err}')

            start = time.monotonic()
            while time.monotonic() - start < self.DURATION:
                await asyncio.sleep(0.2)

            bus.disconnect()

        asyncio.run(_listen())

        elapsed = collector.elapsed()
        print(f'\n  DURATION: {self.DURATION}s  elapsed: {elapsed:.1f}s'
              f'  total signals: {collector.total}')
        if collector.total == 0:
            print('  WARNING: zero signals received — UDisks2 may not emit')
        else:
            first_gap = collector._first_at - collector._start if collector._first_at else 0
            print(f'  first signal after: {first_gap:.3f}s')
            rate = collector.total / max(elapsed, 0.1)
            print(f'  rate: {rate:.1f} signals/sec')
            print('  breakdown:')
            for key, count in sorted(collector.counts.items(),
                                     key=lambda x: -x[1]):
                print(f'    {key}: {count}')
            if collector.total >= 20:
                print('  BURST DETECTED (>=20 signals)')


if __name__ == '__main__':
    unittest.main()
