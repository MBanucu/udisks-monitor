"""Diagnostic H1: Does D-Bus connection order vs UDisks2 activation matter?"""

import asyncio
import os
import subprocess
import tempfile
import time
import unittest

from dbus_fast.aio import MessageBus


async def _connect_and_add_match(signal_count: list):
    """Connect to D-Bus and add a match rule for UDisks2 signals."""
    bus = await MessageBus().connect()

    def _on_signal(msg):
        signal_count[0] += 1

    bus.add_message_handler(_on_signal)
    await bus.call(
        {
            "destination": "org.freedesktop.DBus",
            "path": "/org/freedesktop/DBus",
            "interface": "org.freedesktop.DBus",
            "member": "AddMatch",
            "signature": "s",
            "body": ["type=signal,sender=org.freedesktop.UDisks2"],
        }
    )

    return bus


def _run(cmd, timeout=30):
    """Run a command and return (rc, stdout, stderr, elapsed)."""
    t0 = time.monotonic()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    elapsed = time.monotonic() - t0
    return p.returncode, p.stdout.strip(), p.stderr.strip(), elapsed


def _create_image():
    """Create a temp 1MB vfat image file."""
    fd, path = tempfile.mkstemp(suffix=".img")
    os.close(fd)
    _run(["truncate", "-s", "1M", path])
    _run(["mkfs.vfat", path])
    return path


def _ensure_session_bus():
    """Ensure DBUS_SESSION_BUS_ADDRESS is set, starting a bus if needed."""
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        print(f"Using existing session bus: {os.environ['DBUS_SESSION_BUS_ADDRESS']}")
        return
    print("No session bus found, launching via dbus-launch...")
    p = subprocess.run(
        ["dbus-launch", "--sh-syntax"],
        capture_output=True, text=True, timeout=10,
    )
    for line in p.stdout.splitlines():
        if line.startswith("DBUS_SESSION_BUS_ADDRESS="):
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = line.split("=", 1)[1].strip(";\"'")
        elif line.startswith("DBUS_SESSION_BUS_PID="):
            os.environ["DBUS_SESSION_BUS_PID"] = line.split("=", 1)[1].strip(";\"'")
    print(f"Started session bus: {os.environ['DBUS_SESSION_BUS_ADDRESS']}")


class TestActivationOrder(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _ensure_session_bus()

    def test_before_connect_first_then_activate(self):
        """BEFORE: connect to D-Bus first, then trigger UDisks2 activation."""
        print("\n=== SCENARIO BEFORE: connect first, then activate ===")
        image = _create_image()
        print(f"Image: {image}")

        loop_rc = None
        loop_t = None
        delete_rc = None
        delete_t = None
        signal_count = [0]

        async def _async_main():
            nonlocal loop_rc, loop_t, delete_rc, delete_t
            bus = await _connect_and_add_match(signal_count)

            loop_rc, _, _, loop_t = _run(
                ["udisksctl", "loop-setup", "-f", image, "--no-user-interaction"]
            )
            delete_rc, _, _, delete_t = _run(
                ["udisksctl", "loop-delete", "-b", "loop0", "--no-user-interaction"]
            )

            bus.disconnect()

        asyncio.run(_async_main())

        print(f"Signal count received: {signal_count[0]}")
        print(f"loop-setup rc={loop_rc} time={loop_t:.3f}s")
        print(f"loop-delete rc={delete_rc} time={delete_t:.3f}s")
        print("=== END SCENARIO BEFORE ===\n")

        os.unlink(image)

    def test_after_activate_first_then_connect(self):
        """AFTER: force UDisks2 activation first, then connect to D-Bus."""
        print("\n=== SCENARIO AFTER: activate first, then connect ===")
        image = _create_image()
        print(f"Image: {image}")

        # Force UDisks2 activation
        rc, out, err, t = _run(["udisksctl", "dump"])
        print(f"udisksctl dump rc={rc} stdout_len={len(out)} stderr_len={len(err)} time={t:.3f}s")
        print("Waiting 2s for UDisks2 startup to settle...")
        time.sleep(2)
        print("Done waiting. Now connecting to D-Bus.")

        loop_rc = None
        loop_t = None
        delete_rc = None
        delete_t = None
        signal_count = [0]

        async def _async_main():
            nonlocal loop_rc, loop_t, delete_rc, delete_t
            bus = await _connect_and_add_match(signal_count)

            loop_rc, _, _, loop_t = _run(
                ["udisksctl", "loop-setup", "-f", image, "--no-user-interaction"]
            )
            delete_rc, _, _, delete_t = _run(
                ["udisksctl", "loop-delete", "-b", "loop0", "--no-user-interaction"]
            )

            bus.disconnect()

        asyncio.run(_async_main())

        print(f"Signal count received: {signal_count[0]}")
        print(f"loop-setup rc={loop_rc} time={loop_t:.3f}s")
        print(f"loop-delete rc={delete_rc} time={delete_t:.3f}s")
        print("=== END SCENARIO AFTER ===\n")

        os.unlink(image)
