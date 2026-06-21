"""unit tests for EventBus — subscription filtering and publish."""

import io
import unittest
from contextlib import redirect_stderr

from udisks_monitor._events import (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobCompleted,
    JobProperties,
)
from udisks_monitor._pubsub import EventBus, SubscriptionFilter


class TestSubscriptionFilter(unittest.TestCase):
    def test_match_by_type(self):
        f = SubscriptionFilter(event_type=DevicePropertyChanged)
        ev = DevicePropertyChanged('', 'loop0', '', 'BackingFile', '')
        self.assertTrue(f.matches(ev))
        self.assertFalse(f.matches(JobProperties('', 0, '', '')))

    def test_match_by_operation_string(self):
        f = SubscriptionFilter(event_type=('filesystem-mount',))
        ev = JobProperties('', 0, 'filesystem-mount', '/org/.../loop0')
        self.assertTrue(f.matches(ev))
        ev2 = JobProperties('', 0, 'filesystem-unmount', '/org/.../loop0')
        self.assertFalse(f.matches(ev2))

    def test_match_by_device(self):
        f = SubscriptionFilter(device='loop0')
        ev = DevicePropertyChanged('', 'loop0', '', 'BackingFile', '')
        self.assertTrue(f.matches(ev))
        ev2 = DevicePropertyChanged('', 'loop1', '', 'BackingFile', '')
        self.assertFalse(f.matches(ev2))

    def test_match_by_interface(self):
        f = SubscriptionFilter(interface='org.freedesktop.UDisks2.Loop')
        ev = DevicePropertyChanged('', 'loop0',
                                   'org.freedesktop.UDisks2.Loop',
                                   'BackingFile', '')
        self.assertTrue(f.matches(ev))
        ev2 = DevicePropertyChanged('', 'loop0',
                                    'org.freedesktop.UDisks2.Block',
                                    'Size', '0')
        self.assertFalse(f.matches(ev2))

    def test_match_by_property(self):
        f = SubscriptionFilter(property_='BackingFile')
        ev = DevicePropertyChanged('', 'loop0', '', 'BackingFile', '/tmp/x')
        self.assertTrue(f.matches(ev))
        ev2 = DevicePropertyChanged('', 'loop0', '', 'Autoclear', 'true')
        self.assertFalse(f.matches(ev2))

    def test_match_by_operation(self):
        f = SubscriptionFilter(operation='loop-delete')
        ev = JobProperties('', 0, 'loop-delete', '/org/.../loop0')
        self.assertTrue(f.matches(ev))
        ev2 = JobProperties('', 0, 'filesystem-mount', '/org/.../loop0')
        self.assertFalse(f.matches(ev2))

    def test_combined_filters(self):
        f = SubscriptionFilter(event_type=DevicePropertyChanged,
                               device='loop0', property_='BackingFile')
        ev = DevicePropertyChanged('', 'loop0',
                                   'org.freedesktop.UDisks2.Loop',
                                   'BackingFile', '')
        self.assertTrue(f.matches(ev))
        # wrong device
        ev2 = DevicePropertyChanged('', 'loop1',
                                    'org.freedesktop.UDisks2.Loop',
                                    'BackingFile', '')
        self.assertFalse(f.matches(ev2))
        # wrong property
        ev3 = DevicePropertyChanged('', 'loop0',
                                    'org.freedesktop.UDisks2.Loop',
                                    'Autoclear', 'false')
        self.assertFalse(f.matches(ev3))

    def test_job_completed_filter(self):
        f = SubscriptionFilter(event_type=JobCompleted)
        self.assertTrue(f.matches(
            JobCompleted('/org/.../jobs/1', 1, True, '')))
        self.assertFalse(f.matches(
            InterfaceRemoved('/org/.../loop0', 'loop0',
                             'org.freedesktop.UDisks2.Filesystem')))

    def test_type_and_operation_combo(self):
        f = SubscriptionFilter(event_type=JobProperties,
                               operation='filesystem-mount')
        ev = JobProperties('', 0, 'filesystem-mount', '/org/.../loop0')
        self.assertTrue(f.matches(ev))
        ev2 = JobProperties('', 0, 'filesystem-unmount', '/org/.../loop0')
        self.assertFalse(f.matches(ev2))


class TestEventBus(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.received: list = []

    def _collector(self, evt):
        self.received.append(evt)

    def test_subscribe_and_publish(self):
        self.bus.subscribe(self._collector)
        ev = DevicePropertyChanged('', 'loop0', '', 'BackingFile', '')
        self.bus.publish(ev)
        self.assertEqual(len(self.received), 1)
        self.assertIs(self.received[0], ev)

    def test_filtered_subscription(self):
        self.bus.subscribe(self._collector, event_type=DevicePropertyChanged)
        self.bus.publish(JobProperties('', 0, 'op', '/org/.../x'))
        self.assertEqual(len(self.received), 0)
        self.bus.publish(DevicePropertyChanged('', 'loop0', '', 'P', ''))
        self.assertEqual(len(self.received), 1)

    def test_unsubscribe(self):
        cb = self._collector  # single bound method for identity comparison
        self.assertEqual(len(self.bus), 0)
        self.bus.subscribe(cb)
        self.assertEqual(len(self.bus), 1)
        self.bus.unsubscribe(cb)
        self.assertEqual(len(self.bus), 0)
        self.bus.publish(DevicePropertyChanged('', '', '', '', ''))
        self.assertEqual(len(self.received), 0)

    def test_clear(self):
        self.bus.subscribe(self._collector)
        self.bus.subscribe(lambda e: None)
        self.assertEqual(len(self.bus), 2)
        self.bus.clear()
        self.assertEqual(len(self.bus), 0)

    def test_on_decorator(self):
        @self.bus.on(DevicePropertyChanged, device='loop0')
        def handler(evt):
            self.received.append(evt)

        self.bus.publish(DevicePropertyChanged('', 'loop0', '', 'P', 'v'))
        self.assertEqual(len(self.received), 1)
        self.bus.publish(DevicePropertyChanged('', 'loop1', '', 'P', 'v'))
        self.assertEqual(len(self.received), 1)

    def test_callback_exception_does_not_crash(self):
        def bad_handler(evt):
            raise ValueError('boom')

        self.bus.subscribe(bad_handler)
        with redirect_stderr(io.StringIO()):
            self.bus.publish(DevicePropertyChanged('', '', '', '', ''))
        self.assertTrue(True)

    def test_multiple_subscribers_same_event(self):
        results1 = []
        results2 = []

        self.bus.subscribe(lambda e: results1.append(e))
        self.bus.subscribe(lambda e: results2.append(e))

        ev = DevicePropertyChanged('', 'loop0', '', 'P', 'v')
        self.bus.publish(ev)
        self.assertEqual(len(results1), 1)
        self.assertEqual(len(results2), 1)

    def test_subscribed_types_empty(self):
        self.assertEqual(self.bus.subscribed_types, frozenset())

    def test_subscribed_types_filtered(self):
        self.bus.subscribe(lambda _: None, event_type=InterfaceAdded)
        self.bus.subscribe(lambda _: None, event_type=JobCompleted)
        self.assertEqual(
            self.bus.subscribed_types,
            frozenset({InterfaceAdded, JobCompleted}),
        )

    def test_subscribed_types_catch_all(self):
        self.bus.subscribe(lambda _: None, event_type=InterfaceAdded)
        self.bus.subscribe(lambda _: None)
        self.assertIsNone(self.bus.subscribed_types)

    def test_subscribed_types_string_event_type(self):
        self.bus.subscribe(lambda _: None, event_type='filesystem-mount')
        self.assertEqual(self.bus.subscribed_types, frozenset({JobProperties}))

    def test_subscribed_types_tuple_with_string(self):
        self.bus.subscribe(lambda _: None, event_type=(InterfaceAdded, 'filesystem-mount'))
        self.assertEqual(
            self.bus.subscribed_types,
            frozenset({InterfaceAdded, JobProperties}),
        )
