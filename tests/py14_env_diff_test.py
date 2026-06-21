import os, subprocess, sys, unittest

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

class TestEnvDiff(unittest.TestCase):

    def test_python_version(self):
        print(f'\n>>> PYTHON: {sys.version}')
        print(f'>>> HOSTNAME: {os.uname().nodename}')

    def test_udisks2_package(self):
        r = sh('dpkg -l udisks2 2>/dev/null | grep udisks || echo "no dpkg"')
        print(f'\n>>> udisks2 pkg: {r.stdout.strip()}')
        r2 = sh('udisksctl --version 2>/dev/null || echo NO')
        print(f'>>> udisksctl: {r2.stdout.strip()[:100]}')

    def test_daemon_pid_and_uptime(self):
        r = sh('systemctl show udisks2 --property=MainPID,ActiveEnterTimestamp,ExecMainStartTimestamp 2>/dev/null || echo NO')
        print(f'\n>>> udisks2 daemon:')
        for line in r.stdout.strip().split('\n'):
            print(f'    {line}')
        r2 = sh('ps -o pid,etimes,args -p $(pgrep -x udisksd 2>/dev/null) 2>/dev/null || echo "no udisksd"')
        print(f'>>> udisksd process:')
        for line in r2.stdout.strip().split('\n'):
            print(f'    {line}')

    def test_dbus_version(self):
        r = sh('busctl --version 2>/dev/null || dbus-daemon --version 2>/dev/null | head -1 || echo NO')
        print(f'\n>>> busctl version: {r.stdout.strip()[:100]}')
        r2 = sh('ps --no-headers -eo comm,pid | grep -E "dbus-(daemon|broker)" | head -3 || echo none')
        print(f'>>> D-Bus processes:')
        for line in r2.stdout.strip().split('\n'):
            print(f'    {line}')

    def test_kernel_and_os(self):
        r = sh('uname -r')
        print(f'\n>>> kernel: {r.stdout.strip()}')
        r2 = sh('cat /etc/os-release | head -3 || echo NO')
        print(f'>>> os:')
        for line in r2.stdout.strip().split('\n'):
            print(f'    {line}')

    def test_loop_module_info(self):
        r = sh('cat /proc/modules 2>/dev/null | grep "^loop " | head -1 || echo "no loop"')
        print(f'\n>>> loop module: {r.stdout.strip()[:100]}')
        r2 = sh('losetup -a 2>/dev/null | head -5 || echo none')
        print(f'>>> existing loop devices:')
        for line in r2.stdout.strip().split('\n')[:5]:
            print(f'    {line}')

    def test_pip_list(self):
        r = sh('python -m pip list 2>/dev/null | grep -E "dbus-fast|strip-ansi" || echo none')
        print(f'\n>>> pip packages:')
        for line in r.stdout.strip().split('\n'):
            print(f'    {line}')
