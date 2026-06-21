"""Diagnostic: dump ALL UDisks2 signals received during loop operations."""

import asyncio
import os
import subprocess
import tempfile
import time
import unittest

from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Message, MessageType

_ADD_MATCH = Message(
    destination='org.freedesktop.DBus',
    path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus',
    member='AddMatch',
    signature='s',
    body=['type=signal,sender=org.freedesktop.UDisks2'],
)


class TestSignalDump(unittest.TestCase):

    def test_loop_setup_signals(self):
        """Print every signal received during loop-setup."""
        signals = []

        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            bus.add_message_handler(lambda m: signals.append(m))
            await bus.call(_ADD_MATCH)

            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                           'count=1'], capture_output=True, check=True)
            subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)

            t0 = time.monotonic()
            r = subprocess.run(
                ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                capture_output=True, text=True, timeout=60)
            dt = (time.monotonic() - t0) * 1000
            print(f'\n  loop-setup: rc={r.returncode} ({dt:.0f}ms)')
            if r.returncode != 0:
                print(f'  stderr: {r.stderr.strip()[:300]}')

            await asyncio.sleep(1)

            for line in r.stdout.splitlines():
                if '/dev/' in line and 'loop' in line:
                    dev = line.strip().split()[-1].rstrip('.')
                    subprocess.run(
                        ['udisksctl', 'loop-delete', '-b', dev,
                         '--no-user-interaction'], capture_output=True)

            bus.disconnect()
            os.unlink(path)

        asyncio.run(_run())

        print(f'\n  total signals: {len(signals)}')
        print()
        print(f'  {"interface":<48} {"member":<28} path')
        print(f'  {"-"*48} {"-"*28} {"-"*40}')
        for s in signals:
            path = s.path or ''
            if len(path) > 40:
                path = '...' + path[-37:]
            print(f'  {s.interface or "":<48} {s.member or "":<28} {path}')

    def test_loop_delete_signals(self):
        """Print every signal received during loop-delete."""
        signals = []

        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            bus.add_message_handler(lambda m: signals.append(m))
            await bus.call(_ADD_MATCH)

            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                           'count=1'], capture_output=True, check=True)
            subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)

            r = subprocess.run(
                ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                print(f'\n  loop-setup FAILED: {r.stderr.strip()[:200]}')
                bus.disconnect()
                return

            # Let setup signals flush
            await asyncio.sleep(0.5)
            before = len(signals)

            for line in r.stdout.splitlines():
                if '/dev/' in line and 'loop' in line:
                    dev = line.strip().split()[-1].rstrip('.')

            t0 = time.monotonic()
            r2 = subprocess.run(
                ['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'],
                capture_output=True, text=True, timeout=60)
            dt = (time.monotonic() - t0) * 1000
            print(f'\n  loop-delete: rc={r2.returncode} ({dt:.0f}ms)')

            await asyncio.sleep(0.5)

            bus.disconnect()
            os.unlink(path)

            delete_signals = signals[before:]
            print(f'\n  delete signals: {len(delete_signals)}')
            print()
            print(f'  {"interface":<48} {"member":<28} path')
            print(f'  {"-"*48} {"-"*28} {"-"*40}')
            for s in delete_signals:
                path = s.path or ''
                if len(path) > 40:
                    path = '...' + path[-37:]
                print(f'  {s.interface or "":<48} {s.member or "":<28} {path}')

        asyncio.run(_run())

    def test_mount_related_signals(self):
        """Specifically look for mount-related signals (filesystem,
        loop, block interfaces)."""
        signals = []

        async def _run():
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            bus.add_message_handler(lambda m: signals.append(m))
            await bus.call(_ADD_MATCH)

            fd, path = tempfile.mkstemp(suffix='.img')
            os.close(fd)
            subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                           'count=1'], capture_output=True, check=True)
            subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)

            r = subprocess.run(
                ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
                capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                print(f'\n  loop-setup FAILED: {r.stderr.strip()[:200]}')
                bus.disconnect()
                os.unlink(path)
                return

            for line in r.stdout.splitlines():
                if '/dev/' in line and 'loop' in line:
                    dev = line.strip().split()[-1].rstrip('.')

            await asyncio.sleep(1)

            subprocess.run(
                ['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'],
                capture_output=True)

            await asyncio.sleep(1)

            bus.disconnect()
            os.unlink(path)

        asyncio.run(_run())

        print(f'\n  total signals (setup + delete): {len(signals)}')

        # Organize by interface + member
        grouped = {}
        for s in signals:
            key = f'{s.interface or "None"}.{s.member or "None"}'
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(s)

        print()
        for key in sorted(grouped):
            sigs = grouped[key]
            print(f'  {key}: {len(sigs)}')
            for s in sigs[:3]:
                body_repr = ''
                if s.body and len(s.body) > 0:
                    body_repr = str(s.body[0])[:80]
                if body_repr:
                    print(f'      body[0]: {body_repr}')
