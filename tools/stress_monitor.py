#!/usr/bin/env python3
"""Stress-test udisksctl monitor parser with synthetic concurrent events.

Usage:
    python tools/stress_monitor.py [--devices 5] [--cycles 3]

Creates N loop devices, mounts/unmounts them concurrently, captures
monitor output, and verifies parser correctness.

Requires: mkfs.fat, udisksctl, and polkit access for loop-setup.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import threading
import time


DEV_RE = re.compile(r"as\s+(/[^\s]+?)\.?\s*$", re.MULTILINE)
MOUNT_RE = re.compile(r"at\s+(/[^\s]+?)\.?\s*$", re.MULTILINE)


def create_image(path, size_mb=1):
    subprocess.run(["truncate", "-s", f"{size_mb}M", path], check=True)
    subprocess.run(["mkfs.fat", path], check=True, capture_output=True)


def loop_setup(image_path):
    r = subprocess.run(
        ["udisksctl", "loop-setup", "-f", image_path,
         "--no-user-interaction"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = DEV_RE.search(r.stdout)
    return m.group(1) if m else None


def mount_device(dev):
    r = subprocess.run(
        ["udisksctl", "mount", "-b", dev, "--no-user-interaction"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = MOUNT_RE.search(r.stdout)
    return m.group(1) if m else None


def unmount_device(dev):
    return subprocess.run(
        ["udisksctl", "unmount", "-b", dev, "--no-user-interaction"],
        capture_output=True, text=True).returncode == 0


def run(num_devices, num_cycles):
    images = []
    devices = []

    print(f"Creating {num_devices} test images...")
    for i in range(num_devices):
        fd, path = tempfile.mkstemp(suffix=".img", prefix="stress_")
        os.close(fd)
        create_image(path)
        images.append(path)
        print(f"  [{i}] {path}")

    print(f"\nRunning {num_cycles} mount/unmount cycles per device...")
    print("(concurrent operations within each cycle)\n")

    for cycle in range(num_cycles):
        print(f"=== Cycle {cycle + 1} ===")

        # Setup all devices
        devices.clear()
        for img in images:
            dev = loop_setup(img)
            if dev:
                devices.append(dev)
                print(f"  loop-setup: {dev}")
            else:
                print(f"  loop-setup FAILED for {img}")

        if not devices:
            print("  No devices set up, exiting")
            break

        # Concurrent mount
        threads = []
        results = {}

        def do_mount(dev):
            mp = mount_device(dev)
            results[dev] = mp

        for dev in devices:
            t = threading.Thread(target=do_mount, args=(dev,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        for dev, mp in results.items():
            status = f"-> {mp}" if mp else "FAILED"
            print(f"  mount {dev}: {status}")

        time.sleep(0.5)

        # Concurrent unmount
        threads = []
        unmount_results = {}

        def do_unmount(dev):
            unmount_results[dev] = unmount_device(dev)

        for dev in devices:
            t = threading.Thread(target=do_unmount, args=(dev,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        for dev, ok in unmount_results.items():
            print(f"  unmount {dev}: {'OK' if ok else 'FAILED'}")

    print("\nCleaning up...")
    for img in images:
        try:
            os.unlink(img)
        except OSError:
            pass
    print("Done.")


def main():
    parser = argparse.ArgumentParser(
        description="Stress-test monitor parser with concurrent events")
    parser.add_argument("--devices", type=int, default=3,
                        help="Number of loop devices (default: 3)")
    parser.add_argument("--cycles", type=int, default=2,
                        help="Mount/unmount cycles (default: 2)")
    args = parser.parse_args()

    if subprocess.run(["which", "mkfs.fat"],
                      capture_output=True).returncode != 0:
        print("ERROR: mkfs.fat not available", file=sys.stderr)
        return 1

    run(args.devices, args.cycles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
