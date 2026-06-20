"""Diagnostic: are CI matrix jobs isolated (separate VMs) or shared?

Checks hostname, UDisks2 PID, D-Bus daemon PID, and D-Bus
machine ID across jobs to determine if they share a host.
"""

import os
import socket
import subprocess
import unittest


def _sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


class TestCIIsolation(unittest.TestCase):

    def test_host_identity(self):
        host = socket.gethostname()
        print(f'\n  hostname: {host}')
        print(f'  runner:   {os.environ.get("RUNNER_NAME", "?")}')

    def test_udisks2_state(self):
        result = _sh('pidof udisksd 2>/dev/null || echo "not running"')
        print(f'\n  udisksd PID: {result.stdout.strip()}')

    def test_dbus_machine_id(self):
        result = _sh('cat /etc/machine-id 2>/dev/null || cat /var/lib/dbus/machine-id 2>/dev/null || echo "not found"')
        print(f'\n  D-Bus machine-id: {result.stdout.strip()}')

    def test_dbus_daemon_pid(self):
        result = _sh('pidof dbus-daemon 2>/dev/null || echo "not found"')
        print(f'\n  dbus-daemon PID: {result.stdout.strip()}')

    def test_concurrent_file_touch(self):
        path = '/tmp/ci-isolation-check'
        with open(path, 'a') as f:
            f.write(f'{socket.gethostname()}\n')
        with open(path) as f:
            lines = f.read().strip().split('\n')
        print(f'\n  /tmp/ci-isolation-check lines: {len(lines)}')
        for i, line in enumerate(lines):
            print(f'    [{i}] {line}')
        if len(lines) > 1:
            print(f'  ** SHARED HOST detected: {len(lines)} runners wrote to same file **')
        else:
            print('  isolated runner (single writer)')


if __name__ == '__main__':
    unittest.main()
