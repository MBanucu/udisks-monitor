"""Shared helpers for integration tests."""

import os
import subprocess
import tempfile
import threading
import time

from udisks_monitor import InterfaceAdded, JobCompleted, UdisksMonitor


def _backend():
    """Return the backend to use for integration tests.

    Subprocess backend is preferred in CI because it does not open
    D-Bus connections, avoiding UDisks2 connection accumulation
    across sequential integration tests.
    """
    return 'subprocess' if os.environ.get('CI', '') == 'true' else 'auto'


def udisksctl_available():
    try:
        r = subprocess.run(['udisksctl', 'dump'], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _udisks_alive():
    r = subprocess.run(
        ['busctl', '--system', 'call',
         'org.freedesktop.DBus', '/org/freedesktop/DBus',
         'org.freedesktop.DBus', 'NameHasOwner',
         's', 'org.freedesktop.UDisks2'],
        capture_output=True, text=True, timeout=10)
    return 'true' in r.stdout


def _ensure_udisks_ready():
    """Ensure UDisks2 is alive, restarting only if it is dead.

    Avoids systemd start-limit rate limiting that occurs when
    restarting before every test method.
    """
    if _udisks_alive():
        return
    subprocess.run(
        ['sudo', 'systemctl', 'reset-failed', 'udisks2'],
        capture_output=True, text=True, timeout=10)
    subprocess.run(
        ['sudo', 'systemctl', 'restart', 'udisks2'],
        capture_output=True, text=True, timeout=30)
    time.sleep(2)
    if not _udisks_alive():
        raise RuntimeError('UDisks2 did not become ready after restart')


def _restart_udisks():
    """Force-restart UDisks2 unconditionally.

    Use sparingly — only when a test class needs a guaranteed fresh
    daemon (e.g. parity tests).  Most tests should use
    :func:`_ensure_udisks_ready` instead.
    """
    subprocess.run(
        ['sudo', 'systemctl', 'reset-failed', 'udisks2'],
        capture_output=True, text=True, timeout=10)
    subprocess.run(
        ['sudo', 'systemctl', 'restart', 'udisks2'],
        capture_output=True, text=True, timeout=30)
    time.sleep(2)
    if not _udisks_alive():
        raise RuntimeError('UDisks2 did not become ready after restart')


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


def _restore_udisks(max_retries=3):
    """Robustly restore UDisks2 after it becomes unresponsive.

    Detaches dangling loop devices, kills lingering udisksd processes,
    resets systemd failure counters, and starts a fresh daemon.
    Verifies the new instance responds to D-Bus introspection.

    Returns True if UDisks2 is alive after recovery, False otherwise.
    """
    for attempt in range(max_retries):
        # Detach any remaining loop devices first
        subprocess.run(
            ['sudo', 'losetup', '-D'],
            capture_output=True, timeout=10)

        # Kill lingering udisksd processes
        subprocess.run(
            ['sudo', 'pkill', '-9', 'udisksd'],
            capture_output=True, timeout=5)
        subprocess.run(
            ['sudo', 'systemctl', 'stop', 'udisks2'],
            capture_output=True, timeout=10)
        time.sleep(2)
        subprocess.run(
            ['sudo', 'systemctl', 'reset-failed', 'udisks2'],
            capture_output=True, timeout=10)
        subprocess.run(
            ['sudo', 'systemctl', 'start', 'udisks2'],
            capture_output=True, timeout=10)
        time.sleep(3)

        if _udisks_alive():
            r = subprocess.run(
                ['busctl', '--system', 'call',
                 'org.freedesktop.UDisks2',
                 '/org/freedesktop/UDisks2',
                 'org.freedesktop.DBus.Introspectable',
                 'Introspect'],
                capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and 'interface' in r.stdout:
                return True

        if attempt < max_retries - 1:
            time.sleep(2)

    return False


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


def _collect_events_with_retry(backend, max_retries=3):
    """Run a loop-setup + delete cycle, retrying on UDisks2 failure.

    Detects when UDisks2 is unresponsive and restores it before
    retrying so a transient state does not produce a false failure.
    """
    for attempt in range(max_retries):
        events = _collect_events(backend)
        if events is not None:
            return events
        if not _udisks_alive():
            _restore_udisks()
        elif attempt < max_retries - 1:
            time.sleep(2)
    return None


def _collect_events(backend):
    """Run one loop-setup + loop-delete cycle and return captured events."""
    events = []
    interface_added = threading.Event()
    job_completed = threading.Event()

    mon = UdisksMonitor(backend=backend)
    mon.subscribe(lambda _: interface_added.set(), event_type=InterfaceAdded)
    mon.subscribe(lambda _: job_completed.set(), event_type=JobCompleted)
    mon.subscribe(lambda e: events.append(e))
    mon.start()

    if not mon.ready.wait(timeout=15):
        mon.stop()
        mon.join(timeout=5)
        return None

    try:
        dev, img, _name = make_image()
    except Exception:
        mon.stop()
        mon.join(timeout=5)
        return None

    try:
        if not interface_added.wait(timeout=5):
            return None
        subprocess.run(['udisksctl', 'loop-delete', '-b', dev,
                        '--no-user-interaction'], capture_output=True)
        if not job_completed.wait(timeout=5):
            return None
    finally:
        cleanup(dev, img)
        mon.stop()
        mon.join(timeout=5)

    return events
