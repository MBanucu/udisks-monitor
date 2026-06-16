#!/usr/bin/env python3
"""Analyze captured udisksctl monitor output.

Usage:
    python tools/analyze_monitor.py capture.txt [--verbose]

Parses a capture file (produced by capture_monitor.py) and reports:
  - Event type counts (jobs, property changes, interface changes)
  - Job operations observed and their targets
  - BackingFile transitions
  - MountPoints transitions
  - Interleaving statistics (concurrent job detection)
  - Regex match rates (how well the parser regexes match each line type)

Useful for LLM agents to understand monitor behavior changes over time
or after udisks2 version upgrades.
"""

import argparse
import re
import sys
from collections import defaultdict


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BACKING_RE = re.compile(r"BackingFile:\s+(.*)")
OP_RE = re.compile(r"Operation:\s+(\S+)")
OBJ_RE = re.compile(r"Objects:\s+(\S+)")


def device_from_path(line):
    idx = line.find("/block_devices/")
    if idx == -1:
        return None
    rest = line[idx + len("/block_devices/"):]
    colon = rest.find(":")
    if colon != -1:
        rest = rest[:colon]
    return rest.strip()


def parse_capture(filepath):
    lines = []
    markers = []
    in_markers = False
    in_output = False
    in_stderr = False

    with open(filepath) as f:
        for raw in f:
            if raw.startswith("# === MARKERS ==="):
                in_markers = True
                in_output = False
                in_stderr = False
                continue
            if raw.startswith("# === MONITOR OUTPUT ==="):
                in_markers = False
                in_output = True
                in_stderr = False
                continue
            if raw.startswith("# === STDERR ==="):
                in_markers = False
                in_output = False
                in_stderr = True
                continue

            if in_markers and raw.startswith("MARKER|"):
                parts = raw.strip().split("|", 3)
                if len(parts) == 4:
                    markers.append(
                        (int(parts[1]), parts[2], parts[3]))
            elif in_output:
                parts = raw.strip().split("|", 1)
                if len(parts) == 2:
                    lines.append((int(parts[0]), parts[1]))

    return markers, lines


def analyze(lines):
    stats = {
        "total_lines": len(lines),
        "job_added": 0,
        "job_removed": 0,
        "job_completed": 0,
        "properties_changed": 0,
        "interface_added": 0,
        "interface_removed": 0,
        "preamble": 0,
        "empty": 0,
        "unknown": 0,
    }
    operations = defaultdict(int)
    job_targets = set()
    backing_transitions = []
    current_device = None
    mount_transitions = []
    job_stack = 0
    max_concurrent = 0
    regex_checks = {
        "ANSI_lines": 0,
        "ANSI_matched": 0,
        "BACKING_lines": 0,
        "BACKING_matched": 0,
    }

    for _, line in lines:
        clean = ANSI_RE.sub("", line)
        has_ansi = clean != line
        if has_ansi:
            regex_checks["ANSI_lines"] += 1
            regex_checks["ANSI_matched"] += 1

        if not clean.strip():
            stats["empty"] += 1
            continue

        if "Monitoring the udisks daemon" in clean:
            stats["preamble"] += 1
            continue
        if "The udisks-daemon is running" in clean:
            stats["preamble"] += 1
            continue

        if clean.startswith("Added /org/freedesktop/UDisks2/jobs/"):
            stats["job_added"] += 1
            job_stack += 1
            max_concurrent = max(max_concurrent, job_stack)
            continue

        if clean.startswith("Removed /org/freedesktop/UDisks2/jobs/"):
            stats["job_removed"] += 1
            job_stack = max(0, job_stack - 1)
            continue

        if "::Completed" in clean:
            stats["job_completed"] += 1
            continue

        if "Properties Changed" in clean:
            stats["properties_changed"] += 1
        elif "Added interface" in clean:
            stats["interface_added"] += 1
        elif "Removed interface" in clean:
            stats["interface_removed"] += 1

        dev = device_from_path(clean)
        if dev:
            current_device = dev

        m = OP_RE.search(clean)
        if m:
            operations[m.group(1)] += 1
            o = OBJ_RE.search(clean)
            if o:
                target = device_from_path(o.group(1))
                if target:
                    job_targets.add(target)

        if current_device and "BackingFile" in clean:
            regex_checks["BACKING_lines"] += 1
            bm = BACKING_RE.search(clean)
            if bm:
                regex_checks["BACKING_matched"] += 1
                val = bm.group(1).strip()
                backing_transitions.append((current_device, val))

        if current_device and "MountPoints:" in clean and ":" in clean:
            mp_match = re.search(r"MountPoints:\s+(.*)", clean)
            if mp_match:
                val = mp_match.group(1).strip()
                mount_transitions.append((current_device, val))

    return stats, operations, job_targets, backing_transitions, \
        mount_transitions, max_concurrent, regex_checks


def report(stats, ops, targets, backing, mounts, max_concurrent, regex):
    print("=" * 60)
    print("MONITOR OUTPUT ANALYSIS")
    print("=" * 60)
    print(f"\nTotal lines: {stats['total_lines']}")
    print(f"  Preamble:        {stats['preamble']:>4}")
    print(f"  Empty:           {stats['empty']:>4}")
    print(f"  Job Added:       {stats['job_added']:>4}")
    print(f"  Job Removed:     {stats['job_removed']:>4}")
    print(f"  Job Completed:   {stats['job_completed']:>4}")
    print(f"  Props Changed:   {stats['properties_changed']:>4}")
    print(f"  Interface Add:   {stats['interface_added']:>4}")
    print(f"  Interface Rem:   {stats['interface_removed']:>4}")
    print(f"  Max concurrent:  {max_concurrent:>4}")

    print(f"\nOperations observed ({len(ops)} types):")
    for op, count in sorted(ops.items()):
        print(f"  {op:30s} {count:>4}")

    print(f"\nJob targets ({len(targets)} devices):")
    for t in sorted(targets):
        print(f"  {t}")

    print(f"\nBackingFile transitions ({len(backing)}):")
    for dev, val in backing:
        val_display = val if val else "(empty)"
        print(f"  {dev:10s} -> {val_display}")

    print(f"\nMountPoints transitions ({len(mounts)}):")
    for dev, val in mounts:
        val_display = val if val else "(empty)"
        print(f"  {dev:10s} -> {val_display}")

    print(f"\nRegex match rates:")
    if regex["ANSI_lines"]:
        print(f"  ANSI:    {regex['ANSI_matched']}/{regex['ANSI_lines']} "
              f"({100*regex['ANSI_matched']//regex['ANSI_lines']}%)")
    if regex["BACKING_lines"]:
        print(f"  Backing: {regex['BACKING_matched']}/{regex['BACKING_lines']} "
              f"({100*regex['BACKING_matched']//regex['BACKING_lines']}%)")

    print(f"\nSummary: {len(ops)} operation types, "
          f"{len(targets)} devices targeted, "
          f"{len(backing)} BackingFile changes, "
          f"{len(mounts)} MountPoint changes, "
          f"max {max_concurrent} concurrent jobs")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze captured udisksctl monitor output")
    parser.add_argument("file", help="Capture file to analyze")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print every event")
    args = parser.parse_args()

    try:
        markers, lines = parse_capture(args.file)
    except FileNotFoundError:
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Loaded {len(lines)} monitor lines, {len(markers)} markers\n")

    stats, ops, targets, backing, mounts, max_con, regex = analyze(lines)

    if args.verbose:
        for idx, line in lines:
            print(f"  [{idx:05d}] {line[:120]}")

    report(stats, ops, targets, backing, mounts, max_con, regex)

    return 0


if __name__ == "__main__":
    sys.exit(main())
