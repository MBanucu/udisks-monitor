#!/usr/bin/env python3
"""Capture udisksctl monitor output while performing operations.

Usage:
    python tools/capture_monitor.py --output capture.txt --duration 60

Runs `udisksctl monitor` via subprocess.PIPE (no timestamps on lines),
prompts for operation labels, and writes annotated output to a file.

This tool is usable by both humans and LLM agents.
"""

import argparse
import subprocess
import sys
import threading
import time
from datetime import datetime


def capture(output_path, duration):
    started = threading.Event()
    out_lines = []
    err_lines = []

    def reader(stream, lines, event_set=None):
        for line in stream:
            lines.append(line.rstrip("\n"))
            if event_set and not event_set.is_set():
                event_set.set()

    proc = subprocess.Popen(
        ["udisksctl", "monitor"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    t_out = threading.Thread(target=reader,
                             args=(proc.stdout, out_lines, started),
                             daemon=True)
    t_err = threading.Thread(target=reader,
                             args=(proc.stderr, err_lines),
                             daemon=True)
    t_out.start()
    t_err.start()

    if not started.wait(timeout=10):
        print("ERROR: monitor did not start")
        proc.terminate()
        proc.wait()
        return 1

    print("Monitor running. Perform operations, type labels, or 'quit'.")
    print(f"Saving to: {output_path}")

    markers = []
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        try:
            label = input("[label] > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if label.lower() in ("quit", "q", "exit"):
            break
        if label:
            markers.append((len(out_lines), datetime.now().isoformat(), label))
            print(f"  Marked at line {markers[-1][0]}: '{label}'")

    print("\nStopping monitor...")
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    with open(output_path, "w") as f:
        f.write("# udisksctl monitor capture\n")
        f.write(f"# Captured: {datetime.now().isoformat()}\n")
        f.write(f"# Duration: {duration}s\n")
        f.write("# Format: LINENUM|TIMESTAMP|LABEL  (marker lines)\n")
        f.write("# Format: LINENUM|MONITOR_LINE     (output lines)\n")
        f.write("=" * 60 + "\n")
        f.write("\n# === MARKERS ===\n")
        for idx, ts, label in markers:
            f.write(f"MARKER|{idx}|{ts}|{label}\n")
        f.write("\n# === MONITOR OUTPUT ===\n")
        for i, line in enumerate(out_lines):
            f.write(f"{i:05d}|{line}\n")
        if err_lines:
            f.write("\n# === STDERR ===\n")
            for i, line in enumerate(err_lines):
                f.write(f"{i:05d}|{line}\n")

    print(f"Wrote {len(out_lines)} lines + {len(markers)} markers "
          f"to {output_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Capture udisksctl monitor output")
    parser.add_argument("--output", default="capture.txt",
                        help="Output file path")
    parser.add_argument("--duration", type=int, default=120,
                        help="Max capture duration in seconds")
    args = parser.parse_args()
    sys.exit(capture(args.output, args.duration))


if __name__ == "__main__":
    main()
