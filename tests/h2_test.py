"""H2 diagnostic: tests whether D-Bus signal handler blocks the asyncio
event loop during UDisks2 loop operations."""

import asyncio
import os
import subprocess
import tempfile
import time
import unittest

from dbus_fast.aio import MessageBus
from dbus_fast import BusType, Message, MessageType


class _Results:
    __slots__ = ('signal_count', 'setup_rc', 'setup_stdout', 'setup_stderr',
                 'delete_rc', 'delete_stdout', 'delete_stderr',
                 'setup_time', 'delete_time')


class TestHandlerBlocking(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        subprocess.run(['udisksctl', 'dump'],
                       capture_output=True, timeout=30)

    async def _run_test(self, check_interface):
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

        signal_count = [0]

        def dummy_publish(*args, **kwargs):
            pass

        def on_message(msg):
            if msg.message_type != MessageType.SIGNAL:
                return
            signal_count[0] += 1
            if check_interface:
                if msg.interface == 'org.freedesktop.DBus.ObjectManager':
                    if msg.member == 'InterfacesAdded':
                        dummy_publish()
                    elif msg.member == 'InterfacesRemoved':
                        dummy_publish()
                elif msg.interface == 'org.freedesktop.DBus.Properties':
                    if msg.member == 'PropertiesChanged':
                        dummy_publish()
                elif msg.interface == 'org.freedesktop.UDisks2.Job':
                    if msg.member == 'Completed':
                        dummy_publish()

        bus.add_message_handler(on_message)

        reply = await bus.call(Message(
            destination='org.freedesktop.DBus',
            path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus',
            member='AddMatch',
            signature='s',
            body=['type=signal,sender=org.freedesktop.UDisks2'],
        ))
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(
                f'AddMatch failed: {reply.body[0] if reply.body else "unknown"}')

        fd, img_path = tempfile.mkstemp(suffix='.img')
        os.close(fd)
        try:
            subprocess.run(
                ['dd', 'if=/dev/zero', 'of=' + img_path, 'bs=1M', 'count=1'],
                capture_output=True, check=True)

            t0 = time.perf_counter()
            setup = await asyncio.to_thread(
                subprocess.run,
                ['udisksctl', 'loop-setup', '-f', img_path,
                 '--no-user-interaction'],
                capture_output=True, timeout=30,
            )
            setup_time = time.perf_counter() - t0

            await asyncio.sleep(1)

            t0 = time.perf_counter()
            delete = await asyncio.to_thread(
                subprocess.run,
                ['udisksctl', 'loop-delete', '-f', img_path,
                 '--no-user-interaction'],
                capture_output=True, timeout=30,
            )
            delete_time = time.perf_counter() - t0

            await asyncio.sleep(1)
        finally:
            try:
                os.unlink(img_path)
            except OSError:
                pass

        bus.disconnect()

        r = _Results()
        r.signal_count = signal_count[0]
        r.setup_rc = setup.returncode
        r.setup_stdout = setup.stdout.decode()
        r.setup_stderr = setup.stderr.decode()
        r.delete_rc = delete.returncode
        r.delete_stdout = delete.stdout.decode()
        r.delete_stderr = delete.stderr.decode()
        r.setup_time = setup_time
        r.delete_time = delete_time
        return r

    def _print_results(self, label, r):
        print(f'\n--- {label} ---')
        print(f'Signal count: {r.signal_count}')
        print(f'loop-setup rc: {r.setup_rc}')
        if r.setup_stdout:
            print(f'loop-setup stdout: {r.setup_stdout.strip()}')
        if r.setup_stderr:
            print(f'loop-setup stderr: {r.setup_stderr.strip()}')
        print(f'loop-delete rc: {r.delete_rc}')
        if r.delete_stdout:
            print(f'loop-delete stdout: {r.delete_stdout.strip()}')
        if r.delete_stderr:
            print(f'loop-delete stderr: {r.delete_stderr.strip()}')
        print(f'Setup time: {r.setup_time:.3f}s')
        print(f'Delete time: {r.delete_time:.3f}s')

    def test_handler_with_interface_member_checks(self):
        results = asyncio.run(self._run_test(check_interface=True))
        self._print_results(
            'Test 1: Handler with interface/member checks', results)
        self.assertGreater(results.signal_count, 0,
                           'Expected at least one D-Bus signal')

    def test_handler_simple_counter(self):
        results = asyncio.run(self._run_test(check_interface=False))
        self._print_results(
            'Test 2: Handler with simple counter (no checks)', results)
        self.assertGreater(results.signal_count, 0,
                           'Expected at least one D-Bus signal')
