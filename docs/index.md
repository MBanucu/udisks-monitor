# udisksctl monitor — Documentation

`udisksctl monitor` is a command-line tool that watches D-Bus events from the
**UDisks2** daemon and prints structured change notifications to stdout. It is the
primary mechanism for observing block device lifecycle, filesystem operations,
and property mutations on a running Linux system.

## Contents

| # | File | Topic |
|---|------|-------|
| 1 | [01-overview.md](01-overview.md) | Command overview, invocation, purpose |
| 2 | [02-output-structure.md](02-output-structure.md) | Output anatomy, ANSI colours, timestamps |
| 3 | [03-event-types.md](03-event-types.md) | Complete event catalogue |
| 4 | [04-job-lifecycle.md](04-job-lifecycle.md) | Job creation, completion, removal, operations |
| 5 | [05-property-changes.md](05-property-changes.md) | Property-changed events across interfaces |
| 6 | [06-loop-devices.md](06-loop-devices.md) | Loop device events and the `BackingFile` property |
| 7 | [07-interface-changes.md](07-interface-changes.md) | Added/removed interface events |
| 8 | [08-parsing-output.md](08-parsing-output.md) | Parsing monitor output in Python |
| 9 | [09-integration-patterns.md](09-integration-patterns.md) | Integration patterns for applications |
| 10 | [10-troubleshooting.md](10-troubleshooting.md) | Known warnings, edge cases, debugging |
| 11 | [11-manual-testing.md](11-manual-testing.md) | Manual test procedures and scenario guide |
| 12 | [12-agent-tools.md](12-agent-tools.md) | LLM agent tools for analysis and regression |

## Quick fact sheet

- **Binary**: `udisksctl` (part of `udisks2` package)
- **Invocation**: `udisksctl monitor` (no arguments)
- **Output**: line-buffered text on stdout, warnings on stderr
- **D-Bus**: connects to `org.freedesktop.UDisks2` on the system bus
- **Requires**: no special privileges — polkit authorises read-only monitoring for active local sessions

## Relationship to udisks-monitor

The `udisks-monitor` Python library wraps `udisksctl monitor` in a background
thread with an event-driven pub/sub architecture.  It provides typed event
dataclasses for all 7 UDisks2 event types and an `EventBus` with subscription
filtering by type, device, interface, operation, and property.
