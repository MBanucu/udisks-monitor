# udisks-monitor

Event-driven pub/sub wrapper around `udisksctl monitor` (Linux).

[![PyPI version](https://img.shields.io/pypi/v/udisks-monitor)](https://pypi.org/project/udisks-monitor/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/)
[![License](https://img.shields.io/github/license/MBanucu/udisks-monitor)](LICENSE)
[![OS](https://img.shields.io/badge/OS-Linux-blue)](https://github.com/MBanucu/udisks-monitor)

[![CI](https://img.shields.io/github/actions/workflow/status/MBanucu/udisks-monitor/test.yml?branch=main)](https://github.com/MBanucu/udisks-monitor/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/MBanucu/udisks-monitor/branch/main/graph/badge.svg)](https://codecov.io/gh/MBanucu/udisks-monitor)

[![Downloads total](https://pepy.tech/badge/udisks-monitor)](https://pepy.tech/project/udisks-monitor)
[![Downloads/month](https://pepy.tech/badge/udisks-monitor/month)](https://pepy.tech/project/udisks-monitor)
[![Downloads/week](https://pepy.tech/badge/udisks-monitor/week)](https://pepy.tech/project/udisks-monitor)

One lightweight dependency (`strip-ansi`). Parses the human-readable output of
`udisksctl monitor` into typed event dataclasses with wall-clock timestamps,
dispatching to subscribers via an in-process event bus.

## Install

```bash
pip install udisks-monitor
```

## Quickstart

```python
from udisks_monitor import UdisksMonitor, DevicePropertyChanged, JobProperties

mon = UdisksMonitor()

# Subscribe by event type and filter
@mon.on(DevicePropertyChanged, device='loop0', property_='BackingFile')
def on_backing(evt):
    if not evt.value:
        print(f"{evt.device_name} detached")

@mon.on(JobProperties, operation='filesystem-mount')
def on_mount(evt):
    print(f"mount job for {evt.objects}")

mon.start()
mon.join()
```

## Events

| Event | When |
|-------|------|
| `DevicePropertyChanged` | A property on any device interface changed |
| `InterfaceAdded` | A D-Bus interface appeared on a device |
| `InterfaceRemoved` | A D-Bus interface was removed |
| `JobAdded` | A UDisks2 job was created |
| `JobProperties` | The operation and target objects of a job |
| `JobCompleted` | A job finished (success/failure) |
| `JobRemoved` | A job object was torn down |

All events carry a `timestamp: str` field with the `HH:MM:SS.mmm` wall-clock
time from `udisksctl monitor`.

## Subscription filters

```python
bus = EventBus()

# By event type
bus.subscribe(fn, event_type=DevicePropertyChanged)

# By operation string (matches JobProperties with that operation)
bus.subscribe(fn, event_type='filesystem-mount')

# By device name
bus.subscribe(fn, device='loop0')

# By D-Bus interface
bus.subscribe(fn, interface='org.freedesktop.UDisks2.Loop')

# By property name
bus.subscribe(fn, property_='BackingFile')

# Combined
bus.subscribe(fn,
    event_type=DevicePropertyChanged,
    device='loop0',
    property_='MountPoints')

# Decorator style
@bus.on(DevicePropertyChanged, device='loop0', property_='BackingFile')
def handler(evt): ...
```

## Nix

```nix
{
  inputs.udisks-monitor.url = "github:MBanucu/udisks-monitor";
}
```

## License

GPL-3.0-only
