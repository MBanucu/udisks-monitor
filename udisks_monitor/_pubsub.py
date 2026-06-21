"""Publish/subscribe event bus for udisksctl monitor events."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from udisks_monitor._events import (
    DevicePropertyChanged,
    Event,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
)


class SubscriptionFilter:
    """Filters events by type, device, interface, operation, or property."""

    __slots__ = ('_event_type', '_device', '_interface', '_operation',
                 '_property')

    def __init__(self, event_type=None, device=None, interface=None,
                 operation=None, property_=None):
        if isinstance(event_type, str):
            event_type = (event_type,)
        self._event_type = event_type
        self._device = device
        self._interface = interface
        self._operation = operation
        self._property = property_

    def matches(self, event: Event) -> bool:
        if self._event_type is not None:
            if isinstance(self._event_type, tuple):
                match_name = (isinstance(event, JobProperties) and
                              event.operation in self._event_type)
                match_type = any(isinstance(event, t) for t in self._event_type
                                 if isinstance(t, type))
                if not (match_name or match_type):
                    return False
            elif isinstance(self._event_type, type):
                if not isinstance(event, self._event_type):
                    return False

        if self._device is not None:
            dev = getattr(event, 'device_name', None)
            if dev != self._device:
                return False

        if self._interface is not None:
            iface = getattr(event, 'interface', None)
            if iface != self._interface:
                return False

        if self._operation is not None:
            op = getattr(event, 'operation', None)
            if op != self._operation:
                return False

        if self._property is not None:
            prop = getattr(event, 'property', None)
            if prop != self._property:
                return False

        return True


Callback = Callable[[Event], Any]


class EventBus:
    """Publish/subscribe dispatcher for monitor events.

    Subscribers register a callback with optional filters.
    When :meth:`publish` is called, matching subscribers are invoked
    synchronously in registration order.  Exceptions in callbacks are
    caught and printed to stderr (they do not crash the monitor).
    """

    def __init__(self):
        self._subs: list[tuple[Callback, SubscriptionFilter]] = []

    def subscribe(self, callback: Callback, *,
                  event_type=None, device=None, interface=None,
                  operation=None, property_=None) -> Callback:
        """Register *callback* for events matching the given filters.

        Returns *callback* so it can be used as a decorator.
        """
        f = SubscriptionFilter(event_type=event_type, device=device,
                               interface=interface, operation=operation,
                               property_=property_)
        self._subs.append((callback, f))
        return callback

    def unsubscribe(self, callback: Callback):
        """Remove all subscriptions held by *callback*."""
        self._subs = [(cb, f) for cb, f in self._subs if cb is not callback]

    def publish(self, event: Event):
        """Deliver *event* to every matching subscriber."""
        for callback, filt in self._subs:
            if filt.matches(event):
                try:
                    callback(event)
                except Exception:
                    traceback.print_exc()

    def on(self, event_type=None, *, device=None, interface=None,
           operation=None, property_=None):
        """Decorator: register the decorated function as a subscriber.

        Usage::

            bus = EventBus()

            @bus.on(DevicePropertyChanged, device='loop0', property_='BackingFile')
            def on_backing(evt):
                print(evt.value)
        """
        def _decorator(fn: Callback) -> Callback:
            return self.subscribe(fn, event_type=event_type, device=device,
                                  interface=interface, operation=operation,
                                  property_=property_)
        return _decorator

    def clear(self):
        """Remove all subscribers."""
        self._subs.clear()

    @property
    def subscribed_types(self) -> 'frozenset | None':
        """Return the set of event-type classes that have at least one
        subscriber.  Returns ``None`` when any subscriber has no
        *event_type* filter (catch-all), meaning *all* types are
        interesting.
        """
        types: set[type] = set()
        for _, filt in self._subs:
            if filt._event_type is None:
                return None
            if isinstance(filt._event_type, tuple):
                for t in filt._event_type:
                    if isinstance(t, type):
                        types.add(t)
                    elif isinstance(t, str):
                        types.add(JobProperties)
            elif isinstance(filt._event_type, type):
                types.add(filt._event_type)
        return frozenset(types) if types else frozenset()

    def __len__(self) -> int:
        return len(self._subs)
