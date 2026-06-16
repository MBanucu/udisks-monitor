# 12 — Agent Tools

This document describes the tools and scripts in `tools/` designed to be
usable by LLM coding agents for analyzing `udisksctl monitor` behavior,
regression testing parsers, and investigating issues.

## Tool inventory

| Tool | Purpose | Agent-friendly |
|------|---------|---------------|
| `capture_monitor.py` | Capture live monitor output with labels | Yes — non-interactive with `--duration` |
| `analyze_monitor.py` | Parse and summarize captured output | Yes — text output, exit codes |
| `inspect_regex.py` | Test regexes against captured/live output | Yes — `--errors-only` for CI |
| `stress_monitor.py` | Concurrent stress test with real devices | Yes — fully automated |

## Agent workflows

### Workflow 1: Verify parser after udisks2 update

```
AGENT INSTRUCTION:
When the udisks2 package version changes, verify the monitor parser:

1. Capture fresh output:
   python tools/capture_monitor.py --output /tmp/verify.txt --duration 30

2. Analyze for unexpected patterns:
   python tools/analyze_monitor.py /tmp/verify.txt --verbose
   → Check: any new operation types? any regex gaps?

3. Verify regex coverage:
   python tools/inspect_regex.py /tmp/verify.txt --errors-only
   → Check: any lines with "NO_MATCH" that aren't job properties?

4. If gaps found: read _monitor.py regexes, propose patches.
```

### Workflow 2: Investigate detach failure

```
AGENT INSTRUCTION:
When umount_image reports detach failures, capture the monitor:

1. Start capture:
   python tools/capture_monitor.py --output /tmp/debug.txt --duration 60 &
   CAPTURE_PID=$!

2. Reproduce the failure (run the failing unmount_image command)

3. Wait for capture to finish:
   wait $CAPTURE_PID

4. Analyze:
   python tools/analyze_monitor.py /tmp/debug.txt --verbose

5. Check specifically:
   - Did BackingFile become empty?
   - Did any filesystem-mount job fire during detach window?
   - Were there cleanup jobs that might indicate internal issues?
   - How many concurrent jobs were running?

6. Report findings and suggest code fixes.
```

### Workflow 3: Stress test changes

```
AGENT INSTRUCTION:
When modifying _monitor.py or _strategy.py, run stress test:

1. Unit tests first:
   python -m unittest discover -s tests -v

2. Stress test with real devices:
   python tools/stress_monitor.py --devices 3 --cycles 3

3. If stress test fails:
   - Check which step failed (setup, mount, unmount)
   - Verify udisks2 daemon is running: systemctl status udisks2
   - Check polkit: pkcheck --action-id org.freedesktop.udisks2.loop-setup ...
   - If polkit issues, run as local session user

4. Capture+analyze during stress:
   python tools/capture_monitor.py --output /tmp/stress.txt --duration 10 &
   python tools/stress_monitor.py --devices 2 --cycles 2
   wait
   python tools/analyze_monitor.py /tmp/stress.txt
```

### Workflow 4: Compare behavior between systems

```
AGENT INSTRUCTION:
When debugging platform-specific issues, compare captures:

1. On system A:
   python tools/capture_monitor.py --output /tmp/sys_a.txt

2. On system B (repeat same operations):
   python tools/capture_monitor.py --output /tmp/sys_b.txt

3. Analyze both:
   python tools/analyze_monitor.py /tmp/sys_a.txt > /tmp/a_report.txt
   python tools/analyze_monitor.py /tmp/sys_b.txt > /tmp/b_report.txt

4. Diff:
   diff /tmp/a_report.txt /tmp/b_report.txt

5. Report differences in:
   - Operation types seen
   - BackingFile transition timing
   - Concurrent job count
   - Regex match rates
```

## Report format for agents

When an agent runs `analyze_monitor.py`, it should parse the output and
produce a structured report:

```
## Monitor Analysis Report

### Environment
- udisks2 version: <from dpkg -l udisks2 or rpm -q udisks2>
- Kernel: <uname -r>
- Session: active / SSH / headless

### Statistics
- Lines captured: N
- Events: N job_added, N job_completed, N props_changed, ...
- Max concurrent jobs: N
- Regex match rate: N%

### BackingFile transitions
- device loop0: /tmp/a.img → (empty) → /tmp/b.img (recycled)

### MountPoints transitions
- device loop0: (empty) → /run/media/user/XXX → (empty)

### Anomalies
- [ ] Parse gaps found (N unexpected non-matches)
- [ ] New operation types: ...
- [ ] Missing BackingFile clear
- [ ] Auto-mounter interference detected

### Recommendations
- ...
```

## Using capture files as test fixtures

Capture files can be committed as test fixtures for regression testing:

```bash
# Save a known-good capture
python tools/capture_monitor.py --output tests/fixtures/baseline_mount_cycle.txt

# In tests, verify parser against fixture:
# (see tests/test_concurrent_events_edge.py for examples)
```

## Automation

All tools return exit code 0 on success, non-zero on error. They can be
chained in CI pipelines:

```yaml
# GitHub Actions example
- name: Capture monitor output
  run: python tools/capture_monitor.py --output /tmp/cap.txt --duration 30
- name: Analyze coverage
  run: python tools/inspect_regex.py /tmp/cap.txt --errors-only
```

## Extending the tools

When adding a new tool, follow these conventions:
1. Use argparse for CLI interface
2. Write output suitable for both human reading and agent parsing
3. Return exit code 0 for success, non-zero for errors/warnings
4. Use `# KEY: value` lines for machine-parseable output
5. Document the tool in this file
