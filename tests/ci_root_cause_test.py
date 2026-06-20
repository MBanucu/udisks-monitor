"""Diagnostic: find why UDisks2 fails in CI with D-Bus backend but not locally.

Tests activation timing, D-Bus broker identity, match rule count,
and whether our dbus-fast connection interferes with loop-setup.
"""

import asyncio
import os
import subprocess
import time
import unittest

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus


def _sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True,
                         text=True, timeout=60, **kw)


_ADD_MATCH = Message(
    destination='org.freedesktop.DBus',
    path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus',
    member='AddMatch',
    signature='s',
    body=['type=signal,sender=org.freedesktop.UDisks2'],
)


class TestActivationTiming(unittest.TestCase):
    """Measure how long UDisks2 activation takes."""

    def test_udisks2_already_running(self):
        r = _sh("busctl --system call org.freedesktop.DBus "
                "/org/freedesktop/DBus org.freedesktop.DBus "
                "NameHasOwner s org.freedesktop.UDisks2 2>/dev/null || echo 'FAIL'")
        has = r.stdout.strip().split()[-1] if r.stdout.strip() else 'unknown'
        print(f'\n  UDisks2 running: {has}  (b = true/1, empty = likely false)')

    def test_udisks2_activation_latency(self):
        async def _measure():
            t0 = time.monotonic()
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            t1 = time.monotonic()
            reply = await bus.call(Message(
                destination='org.freedesktop.DBus',
                path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus',
                member='NameHasOwner',
                signature='s',
                body=['org.freedesktop.UDisks2'],
            ))
            t2 = time.monotonic()
            bus.disconnect()
            return t1 - t0, t2 - t1

        connect_time, call_time = asyncio.run(_measure())
        print(f'\n  D-Bus connect: {connect_time*1000:.0f}ms')
        print(f'  NameHasOwner:  {call_time*1000:.0f}ms')

    def test_busctl_activation_latency(self):
        t0 = time.monotonic()
        r = _sh("busctl --system call org.freedesktop.DBus "
                "/org/freedesktop/DBus org.freedesktop.DBus "
                "StartServiceByName su org.freedesktop.UDisks2 0 2>/dev/null || echo 'FAIL'")
        t1 = time.monotonic()
        print(f'\n  StartServiceByName: {(t1-t0)*1000:.0f}ms')
        print(f'  result: {r.stdout.strip()[:120]}')

    def test_loop_setup_timing(self):
        fd, path = tempfile_fast()
        subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                        'count=1'], capture_output=True, check=True)
        subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
        t0 = time.monotonic()
        r = subprocess.run(
            ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
            capture_output=True, text=True)
        t1 = time.monotonic()
        print(f'\n  loop-setup: {(t1-t0)*1000:.0f}ms (rc={r.returncode})')
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if '/dev/' in line:
                    dev = line.strip().split()[-1].rstrip('.')
                    subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                                   '--no-user-interaction'], capture_output=True)
        else:
            print(f'  stderr: {r.stderr.strip()[:200]}')
        os.unlink(path)


class TestDBusBroker(unittest.TestCase):
    """Identify the D-Bus broker and its match rule state."""

    def test_broker_identity(self):
        r = _sh("busctl --system call org.freedesktop.DBus "
                "/org/freedesktop/DBus org.freedesktop.DBus "
                "GetId 2>/dev/null | sed 's/s \"//;s/\"$//' || echo 'FAIL'")
        uid = r.stdout.strip().split()[-1].strip('"') if r.stdout.strip() else 'unknown'
        r2 = _sh("ps --no-headers -eo comm,pid | grep -E 'dbus-(daemon|broker)' | head -3 || echo 'none'")
        print(f'\n  D-Bus ID: {uid}')
        print(f'  broker:')
        for line in r2.stdout.strip().split('\n'):
            print(f'    {line}')

    def test_match_rule_count(self):
        before = _sh("busctl --system call org.freedesktop.DBus "
                     "/org/freedesktop/DBus org.freedesktop.DBus "
                     "Debug.GetStats 2>/dev/null || echo 'no debug api'")
        print(f'\n  pre-AddMatch bus stats: {before.stdout.strip()[:200]}')


class TestDBusBackendInterference(unittest.TestCase):
    """Does our D-Bus backend connection break subsequent udisksctl calls?"""

    def test_loop_setup_after_dbus_connect(self):
        async def _connect_and_leave():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            reply = await bus.call(_ADD_MATCH)
            ok = reply.message_type != MessageType.ERROR
            return bus, ok

        bus, addmatch_ok = asyncio.run(_connect_and_leave())
        print(f'\n  AddMatch OK: {addmatch_ok}')

        try:
            fd, path = tempfile_fast()
            subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                            'count=1'], capture_output=True, check=True)
            subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
            t0 = time.monotonic()
            r = subprocess.run(
                ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                capture_output=True, text=True)
            t1 = time.monotonic()
            print(f'  loop-setup with dbus conn: {(t1-t0)*1000:.0f}ms (rc={r.returncode})')
            if r.returncode != 0:
                print(f'  stderr: {r.stderr.strip()[:300]}')
            else:
                for line in r.stdout.splitlines():
                    if '/dev/' in line:
                        dev = line.strip().split()[-1].rstrip('.')
                        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                                       '--no-user-interaction'], capture_output=True)
            os.unlink(path)
        finally:
            bus.disconnect()

    def test_match_rules_visible_after_addmatch(self):
        async def _check():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            reply = await bus.call(_ADD_MATCH)
            ok = reply.message_type != MessageType.ERROR
            bus.disconnect()
            return ok
        ok = asyncio.run(_check())
        r = _sh("busctl --system call org.freedesktop.DBus "
                "/org/freedesktop/DBus org.freedesktop.DBus "
                "Debug.GetStats 2>/dev/null || echo 'no debug api'")
        print(f'\n  AddMatch OK: {ok}')
        print(f'  post-AddMatch stats: {r.stdout.strip()[:200]}')


def tempfile_fast():
    import tempfile
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    return fd, path


if __name__ == '__main__':
    unittest.main()
