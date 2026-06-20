"""Diagnostic: is UDisks2 shared (single instance) or per-job activation?

Checks UDisks2 D-Bus unique name and parent PID to determine if
multiple matrix jobs share one UDisks2 daemon or each gets its own.
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

    def test_udisks2_dbus_name(self):
        r = _sh("busctl --system call org.freedesktop.DBus "
                "/org/freedesktop/DBus org.freedesktop.DBus "
                "GetNameOwner s org.freedesktop.UDisks2 2>/dev/null "
                "|| echo 'FAIL'")
        print(f'\n  UDisks2 D-Bus owner: {r.stdout.strip()}')

    def test_udisks2_pids_and_parent(self):
        r = _sh("ps --no-headers -eo pid,ppid,args 2>/dev/null | "
                "grep '[u]disksd' | head -10 || echo 'no udisksd'")
        print(f'\n  udisksd processes:')
        for line in r.stdout.strip().split('\n'):
            print(f'    {line}')

    def test_udisks2_systemctl_status(self):
        r = _sh("systemctl status udisks2 2>/dev/null | head -15 || echo 'not a service'")
        print(f'\n  udisks2 service status:')
        for line in r.stdout.strip().split('\n'):
            print(f'    {line}')

    def test_udisks2_activation_count(self):
        path = '/tmp/ci-udisks-names'
        name = _sh("busctl --system call org.freedesktop.DBus "
                   "/org/freedesktop/DBus org.freedesktop.DBus "
                   "GetNameOwner s org.freedesktop.UDisks2 2>/dev/null "
                   "|| echo 'FAIL'").stdout.strip()
        host = socket.gethostname()
        with open(path, 'a') as f:
            f.write(f'[{host}] {name}\n')
        with open(path) as f:
            content = f.read().strip()
        lines = [l for l in content.split('\n') if l]
        print(f'\n  /tmp/ci-udisks-names ({len(lines)} entries):')
        for l in lines:
            print(f'    {l}')
        if len(lines) > 1:
            unique = set(l.split('] ', 1)[1] for l in lines if '] ' in l)
            print(f'  unique D-Bus names: {unique}')
            if len(unique) > 1:
                print('  ** MULTIPLE UDisks2 instances detected **')
            else:
                print('  ** SAME UDisks2 instance across all jobs **')


if __name__ == '__main__':
    unittest.main()
