"""Shared helpers for integration tests."""

import os
import subprocess
import tempfile
import time


def _ci():
    return os.environ.get('CI', '') == 'true'


def test_monitor(**kwargs):
    """Return a UdisksMonitor suitable for the test environment.

    In CI, defaults to the subprocess backend to avoid overloading
    the UDisks2 daemon with persistent dbus-fast connections.
    """
    from udisks_monitor import UdisksMonitor
    if _ci() and 'backend' not in kwargs:
        kwargs['backend'] = 'subprocess'
    return UdisksMonitor(**kwargs)


def udisksctl_available():
    try:
        r = subprocess.run(['udisksctl', 'dump'], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def make_image():
    """Create a small VFAT image, set up a loop device, unmount it."""
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M',
                    'count=1'], capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    try:
        r = subprocess.run(
            ['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'],
            capture_output=True, text=True)
        r.check_returncode()
    except subprocess.CalledProcessError:
        os.unlink(path)
        raise RuntimeError(
            f'loop-setup failed (rc={r.returncode}):\n'
            f'stdout: {r.stdout}\n'
            f'stderr: {r.stderr}') from None
    for line in r.stdout.splitlines():
        if '/dev/' in line and 'loop' in line:
            device = line.strip().split()[-1].rstrip('.')
            return device, path, device.split('/')[-1]
    os.unlink(path)
    raise RuntimeError(f'could not parse loop-setup output:\n{r.stdout}')


def cleanup(device, img_path):
    for _ in range(3):
        r = subprocess.run(
            ['udisksctl', 'unmount', '-b', device, '--no-user-interaction'],
            capture_output=True, text=True)
        r2 = subprocess.run(
            ['udisksctl', 'loop-delete', '-b', device, '--no-user-interaction'],
            capture_output=True, text=True)
        if r2.returncode == 0:
            break
        time.sleep(0.1)
    if os.path.exists(img_path):
        os.unlink(img_path)
