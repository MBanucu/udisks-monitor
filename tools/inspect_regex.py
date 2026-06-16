#!/usr/bin/env python3
"""Test regex patterns against captured or live udisksctl monitor output.

Usage:
    python tools/inspect_regex.py <capture.txt         # from file
    python tools/inspect_regex.py --live --duration 30  # from live monitor

Reports which regexes match each line and highlights mismatches.
Designed for LLM agents to verify that parser regexes correctly
handle new/changed udisksctl monitor output formats.
"""

import argparse
import re
import subprocess
import sys
import threading
import time


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BACKING_RE = re.compile(r"BackingFile:\s+(.*)")
OP_RE = re.compile(r"Operation:\s+(\S+)")
OBJ_RE = re.compile(r"Objects:\s+(\S+)")
MOUNT_RE = re.compile(r"MountPoints:\s+(.*)")


def device_from_path(line):
    idx = line.find("/block_devices/")
    if idx == -1:
        return None
    rest = line[idx + len("/block_devices/"):]
    colon = rest.find(":")
    if colon != -1:
        rest = rest[:colon]
    return rest.strip()


def test_line(line, line_idx):
    clean = ANSI_RE.sub("", line)
    matches = []

    if clean.startswith("Added /org/freedesktop/UDisks2/jobs/"):
        matches.append("JOB_ADDED")
    if clean.startswith("Removed /org/freedesktop/UDisks2/jobs/"):
        matches.append("JOB_REMOVED")
    if "::Completed" in clean:
        matches.append("JOB_COMPLETED")
    if "Properties Changed" in clean:
        matches.append("PROPS_CHANGED")
    if "Added interface" in clean:
        matches.append("IFACE_ADDED")
    if "Removed interface" in clean:
        matches.append("IFACE_REMOVED")
    if "Monitoring the udisks daemon" in clean:
        matches.append("PREAMBLE")
    if "The udisks-daemon is running" in clean:
        matches.append("DAEMON_READY")

    dev = device_from_path(clean)
    if dev:
        matches.append(f"DEVICE={dev}")

    m = OP_RE.search(clean)
    if m:
        matches.append(f"OPERATION={m.group(1)}")
    m = OBJ_RE.search(clean)
    if m:
        matches.append(f"OBJECTS={m.group(1)}")
    m = BACKING_RE.search(clean)
    if m:
        val = m.group(1).strip()
        matches.append(f"BACKING={'EMPTY' if not val else val}")
    m = MOUNT_RE.search(clean)
    if m:
        val = m.group(1).strip()
        matches.append(f"MOUNTPOINTS={'EMPTY' if not val else val}")

    if not clean.strip():
        matches.append("EMPTY_LINE")

    if not matches:
        matches.append("NO_MATCH")

    return matches


def from_file(filepath):
    with open(filepath) as f:
        for raw in f:
            if raw.startswith("#"):
                continue
            parts = raw.strip().split("|", 1)
            if len(parts) != 2:
                continue
            line_idx = parts[0]
            line_text = parts[1]
            yield line_idx, line_text


def from_live(duration):
    proc = subprocess.Popen(
        ["udisksctl", "monitor"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    started = threading.Event()
    lines = []

    def reader():
        for line in proc.stdout:
            lines.append(line.rstrip("\n"))
            started.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    if not started.wait(timeout=10):
        print("ERROR: monitor did not start")
        proc.terminate()
        return
    time.sleep(duration)
    proc.terminate()
    proc.wait(timeout=3)

    for i, line in enumerate(lines):
        yield str(i), line


def main():
    parser = argparse.ArgumentParser(
        description="Test regex patterns against monitor output")
    parser.add_argument("file", nargs="?", help="Capture file (stdin if -)")
    parser.add_argument("--live", action="store_true",
                        help="Read from live udisksctl monitor")
    parser.add_argument("--duration", type=int, default=30,
                        help="Duration for --live capture")
    parser.add_argument("--errors-only", "-e", action="store_true",
                        help="Only show lines with NO_MATCH or parsing gaps")
    args = parser.parse_args()

    if args.live:
        source = from_live(args.duration)
    elif args.file and args.file != "-":
        source = from_file(args.file)
    elif args.file == "-" or not sys.stdin.isatty():
        source = enumerate(sys.stdin, start=0)
    else:
        parser.print_help()
        return 1

    total = 0
    no_match = 0
    gaps = 0  # lines where we'd expect a match but got nothing
    job_props = {"Operation", "Objects", "Bytes", "Cancelable",
                 "ExpectedEndTime", "Progress", "ProgressValid",
                 "Rate", "StartTime", "StartedByUID"}

    for line_idx, line_text in source:
        total += 1
        matches = test_line(line_text, line_idx)
        matched_tags = [m for m in matches if not m.startswith("DEVICE=")]

        if "NO_MATCH" in matched_tags:
            no_match += 1
            # Check if this is a job property line (expected to not match)
            clean = ANSI_RE.sub("", line_text)
            is_job_prop = any(f"    {p}" in clean for p in job_props)
            if not is_job_prop:
                gaps += 1

        if not args.errors_only or "NO_MATCH" in matched_tags:
            prefix = "!" if "NO_MATCH" in matched_tags else " "
            print(f"{prefix}[{line_idx}] {line_text[:130]}")
            if matched_tags:
                print(f"   -> {' | '.join(matched_tags)}")

    print(f"\n--- Summary ---")
    print(f"Total lines: {total}")
    print(f"No match:     {no_match}")
    print(f"Parse gaps:   {gaps} (unexpected non-matches)")
    print(f"Coverage:     {(total - no_match) * 100 // max(total, 1)}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
