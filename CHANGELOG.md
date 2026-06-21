# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-06-20

### Added

- Pluggable backend architecture (`udisks_monitor/_backends/`) with a base `_Backend` protocol and a backend factory (`_get_backend()`).
- Native D-Bus backend (`_DBusBackend`) that subscribes directly to UDisks2 D-Bus signals via `dbus-fast`, providing typed event data without `udisksctl monitor` overhead.
- `backend` parameter on `UdisksMonitor` — `'auto'` (default, uses D-Bus), `'dbus'` (D-Bus), or `'subprocess'` (udisksctl monitor parser).
- Backend parity integration tests verifying both backends produce equivalent `JobCompleted`, `DevicePropertyChanged`, `InterfaceAdded`, and `InterfaceRemoved` events through the same EventBus.
- Unit tests for D-Bus signal translation, path filtering, interface filtering, and Variant handling.

### Changed

- `UdisksMonitor` now delegates event collection to a pluggable backend instead of directly spawning `udisksctl monitor` in `_monitor.py`.
- `dbus-fast` moved from optional dependency to hard dependency. Removed `_DbusAvailable` sentinel and all `ImportError` fallback logic.
- D-Bus is now the default backend (`'auto'` = `'dbus'`).

### Fixed

- `dbus_fast.signature.Variant` values are now properly unwrapped in all D-Bus signal handlers (`InterfaceAdded` properties, `JobAdded` Objects/Operation fields, and `DevicePropertyChanged` values).
- `time.sleep` polling eliminated from all tests. `test_backend_parity` and `test_events` now use `threading.Event` callbacks subscribed via `event_type=` filter on the EventBus.
- Removed `time.sleep(0.3)` from integration test cleanup helper.

## [0.2.0] - 2026-06-16

### Added

- `timestamp: str` field on all 7 event dataclasses (`DevicePropertyChanged`, `InterfaceAdded`, `InterfaceRemoved`, `JobAdded`, `JobProperties`, `JobCompleted`, `JobRemoved`), captured from `udisksctl monitor`'s `HH:MM:SS.mmm:` prefix.
- Nix build now runs the full test suite via `unittestCheckHook`.

### Changed

- Use `strip-ansi` library for ANSI escape sequence handling, replacing the inline regex-based approach for broader sequence coverage.

### Fixed

- Fix parsing of `udisksctl monitor` output when timestamp prefix is present, which previously broke detection of `JobAdded`, `JobRemoved`, and `JobProperties` events.
- Fix `_stop` attribute conflict with Python 3.10's `threading.Thread._stop` internal method, which caused `TypeError` on `join()`.
- Fix LICENSE file not being included in built (sdist/wheel) packages.
- Fix `ValueError('boom')` stderr noise in CI from the expected-exception test.
- Fix flaky integration test race conditions by creating loop devices before starting the monitor, eliminating all `@unittest.skipIf` CI guards.

## [0.1.0] - 2026-06-16

### Added

- Initial release: event-driven pub/sub wrapper around `udisksctl monitor`.
- Typed event dataclasses for all UDisks2 event types.
- EventBus with subscription filtering by event type, device, interface, operation, and property.
- `UdisksMonitor` class for spawning `udisksctl monitor` in a background thread.
- Nix flake and `default.nix` for building with Nix.

[unreleased]: https://github.com/MBanucu/udisks-monitor/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/MBanucu/udisks-monitor/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/MBanucu/udisks-monitor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/MBanucu/udisks-monitor/releases/tag/v0.1.0
