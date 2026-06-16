# 11 — Manual Testing

Procedures for manually testing `udisksctl monitor` behavior and verifying
parser correctness against live systems.

## Quick smoke test

```bash
# 1. Start monitor in background
udisksctl monitor > /tmp/monitor.out 2>/tmp/monitor.err &
MONPID=$!

# 2. Create a test image
truncate -s 1M /tmp/test.img
mkfs.fat /tmp/test.img

# 3. Set up loop device
udisksctl loop-setup -f /tmp/test.img --no-user-interaction

# 4. Mount it
udisksctl mount -b /dev/loopN --no-user-interaction

# 5. Unmount it
udisksctl unmount -b /dev/loopN --no-user-interaction

# 6. Stop monitor
kill $MONPID

# 7. Inspect output
cat /tmp/monitor.out
```

## Test scenarios

### 1. Single device lifecycle

Perform setup → mount → unmount → loop-delete and verify:
- `BackingFile` is set after setup, empty after delete
- `MountPoints` is populated after mount, empty after unmount
- `filesystem-mount` and `filesystem-unmount` jobs appear
- `Filesystem` interface added/removed

### 2. Concurrent operations

Perform 3× setup, 3× mount, 3× unmount concurrently:
- Verify events interleave correctly
- Verify `_current_device` tracking is robust
- Verify no lost BackingFile transitions

```bash
# In separate terminals or via &
udisksctl loop-setup -f /tmp/a.img --no-user-interaction &
udisksctl loop-setup -f /tmp/b.img --no-user-interaction &
udisksctl loop-setup -f /tmp/c.img --no-user-interaction &
wait
```

### 3. Device number recycling

Detach a device then immediately set up a new image:
- Verify BackingFile clears then is set again on same device number
- Verify parser doesn't confuse old and new BackingFile values

```bash
udisksctl loop-delete -b /dev/loopN --no-user-interaction
# Immediately:
udisksctl loop-setup -f /tmp/other.img --no-user-interaction
```

### 4. Auto-mounter race

On a desktop with gvfs running, unmount and immediately loop-delete:
- Auto-mounter may re-mount between unmount and delete
- Monitor should show `filesystem-mount` job during detach window

### 5. Path edge cases

Create images at paths with spaces, Unicode, or special characters:
- Verify BackingFile values are correctly extracted and stripped

```bash
mkdir -p "/tmp/test dir with spaces"
truncate -s 1M "/tmp/test dir with spaces/image.img"
mkfs.fat "/tmp/test dir with spaces/image.img"
udisksctl loop-setup -f "/tmp/test dir with spaces/image.img" --no-user-interaction
```

### 6. Cleanup jobs

During rapid detach, UDisks2 emits internal `cleanup` jobs. Verify:
- Cleanup jobs have empty Objects
- Parser correctly handles empty Objects field
- Cleanup jobs don't interfere with mount/unmount job detection

## Using the analysis tools

```bash
# Capture monitor output with operation labels
python tools/capture_monitor.py --output capture.txt --duration 60

# Analyze the capture
python tools/analyze_monitor.py capture.txt --verbose

# Inspect regex matches line-by-line
python tools/inspect_regex.py capture.txt --errors-only

# Stress test with concurrent operations
python tools/stress_monitor.py --devices 5 --cycles 3
```

## Regression testing after udisks2 upgrades

When the udisks2 package is updated:

1. Capture a baseline with the current version
2. After upgrade, capture with the new version
3. Run the same operations in both captures
4. Diff the parsed output using `analyze_monitor.py`

```bash
# Before upgrade
python tools/capture_monitor.py --output baseline.txt

# After upgrade (repeat same operations)
python tools/capture_monitor.py --output after_upgrade.txt

# Compare
python tools/analyze_monitor.py baseline.txt > /tmp/before.txt
python tools/analyze_monitor.py after_upgrade.txt > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt
```

## Behavioral changes to watch for

| Change | Risk | Mitigation |
|--------|------|------------|
| New ANSI codes added | Regex may miss lines | `inspect_regex.py --errors-only` |
| New job operations listed | Operation catalog incomplete | Check `analyze_monitor.py` output |
| Timestamp format changes | Preamble parsing may break | Verify parser ignores timestamps |
| Properties renamed | BackingFile regex fails | `BACKING_RE` needs update |
| Object path format changes | `_device_name_from_path` fails | Check device ID extraction |
| New interfaces added | May emit unexpected property lines | `inspect_regex.py` flags unknowns |
| Daemon output to stdout | False matches on warn/info lines | Check stderr vs stdout separation |
