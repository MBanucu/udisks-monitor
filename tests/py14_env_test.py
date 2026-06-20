import subprocess, sys, unittest

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

class TestPy14Environment(unittest.TestCase):

    def test_python_version(self):
        print(f'\n  Python: {sys.version}')
        print(f'  executable: {sys.executable}')

    def test_dbus_fast_version(self):
        try:
            import dbus_fast
            print(f'\n  dbus-fast: {dbus_fast.__version__}')
        except ImportError as e:
            print(f'\n  dbus-fast IMPORT FAILED: {e}')

    def test_udisks2_version(self):
        r = sh('udisksctl dump --version 2>/dev/null || udisksctl --version 2>/dev/null || echo "NO VERSION"')
        print(f'\n  udisksctl --version: {r.stdout.strip()[:200]}')

    def test_udisks2_service(self):
        r = sh('systemctl status udisks2 2>/dev/null | head -5 || echo "no systemctl"')
        print(f'\n  udisks2 service:')
        for line in r.stdout.strip().split('\n'):
            print(f'    {line}')

    def test_udisks2_dump(self):
        r = sh('timeout 30 udisksctl dump 2>&1 | head -5')
        print(f'\n  udisksctl dump (rc={r.returncode}):')
        for line in r.stdout.strip().split('\n')[:5]:
            print(f'    {line}')
        if r.returncode != 0:
            r2 = sh('busctl --system call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus NameHasOwner s org.freedesktop.UDisks2 2>/dev/null || echo FAIL')
            print(f'  UDisks2 on bus: {r2.stdout.strip()}')

    def test_dbus_broker(self):
        r = sh('ps --no-headers -eo comm,pid | grep -E "dbus-(daemon|broker)" | head -5 || echo none')
        print(f'\n  D-Bus broker:')
        for line in r.stdout.strip().split('\n'):
            print(f'    {line}')

    def test_loop_module(self):
        r = sh('lsmod | grep loop 2>/dev/null | head -3 || echo "no lsmod"')
        print(f'\n  loop module:')
        for line in r.stdout.strip().split('\n'):
            print(f'    {line}')
        r2 = sh('cat /proc/modules | grep loop | head -3 2>/dev/null || echo none')
        print(f'  /proc/modules loop:')
        for line in r2.stdout.strip().split('\n'):
            print(f'    {line}')
