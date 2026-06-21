"""Architecture 2 verification — queued per-subscriber dispatch.

Runs the D-Bus integration test (JobCompleted arrival) and an
interleaved stress test with multiple concurrent subscribers.
"""

import os
import queue
import subprocess
import tempfile
import threading
import time
import unittest

from udisks_monitor import UdisksMonitor
from udisks_monitor._events import (
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
)


def _loop_setup_delete():
    """Create a loop device via udisksctl and immediately delete it.

    Returns (loop_created, events_during_op) or raises on failure.
    """
    fd, img = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    try:
        subprocess.run(
            ['dd', 'if=/dev/zero', 'of=' + img, 'bs=1M', 'count=1'],
            capture_output=True, check=True)
        subprocess.run(
            ['mkfs.vfat', img], capture_output=True, check=True)

        r = subprocess.run(
            ['udisksctl', 'loop-setup', '-f', img,
             '--no-user-interaction'],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f'loop-setup failed: {r.stderr[:200]}')

        dev = None
        for line in r.stdout.splitlines():
            if '/dev/' in line and 'loop' in line:
                dev = line.strip().split()[-1].rstrip('.')

        if not dev:
            raise RuntimeError('Could not parse loop device from output')

        subprocess.run(
            ['udisksctl', 'loop-delete', '-b', dev,
             '--no-user-interaction'],
            capture_output=True, text=True, timeout=60)
    finally:
        if os.path.exists(img):
            os.unlink(img)


class TestJobCompletedArrives(unittest.TestCase):
    """Verify that JobCompleted events arrive through queued dispatch."""

    def test_job_completed_arrives(self):
        events = []
        done = threading.Event()

        def handler(evt):
            events.append(evt)
            if isinstance(evt, JobCompleted):
                done.set()

        monitor = UdisksMonitor(backend='dbus')
        monitor.subscribe(handler, event_type=JobCompleted)
        monitor.start()
        self.assertTrue(monitor.ready.wait(timeout=10),
                        'Monitor did not become ready within 10s')

        _loop_setup_delete()

        self.assertTrue(done.wait(timeout=10),
                        f'JobCompleted not received within 10s (got {len(events)} events)')
        monitor.stop()
        monitor.join(timeout=5)

        self.assertGreater(len(events), 0, 'Expected at least one event')
        for e in events:
            self.assertIsInstance(e, JobCompleted)
        print(f'  JobCompleted received: {len(events)} event(s)')


class TestInterleavedStress(unittest.TestCase):
    """Stress-test: many subscribers, verifying queued dispatch interleaving."""

    def test_interleaved_stress(self):
        N_SUBSCRIBERS = 10
        ITERATIONS = 10

        pass_count = 0
        fail_count = 0

        for iteration in range(ITERATIONS):
            try:
                self._run_one_stress_iteration(N_SUBSCRIBERS, iteration)
                pass_count += 1
            except Exception as exc:
                fail_count += 1
                print(f'  [iter {iteration}] FAIL: {exc}')

        print(f'\n  Interleaved stress: {pass_count}/{ITERATIONS} passed, '
              f'{fail_count} failed')

        self.assertEqual(fail_count, 0,
                         f'Stress test had {fail_count} failures')

    def _run_one_stress_iteration(self, n_subs, iteration):
        events_per_sub = [[] for _ in range(n_subs)]
        thread_ids = {}
        latches = [threading.Event() for _ in range(n_subs)]

        def make_handler(idx):
            def handler(evt):
                events_per_sub[idx].append(evt)
                thread_ids[idx] = threading.get_ident()
                latches[idx].set()
            return handler

        monitor = UdisksMonitor(backend='dbus')
        for i in range(n_subs):
            monitor.subscribe(make_handler(i))

        monitor.start()
        if not monitor.ready.wait(timeout=10):
            monitor.stop()
            raise RuntimeError('Monitor not ready')

        _loop_setup_delete()

        time.sleep(1)
        monitor.stop()
        monitor.join(timeout=5)

        # Every subscriber must have received events
        for i in range(n_subs):
            if len(events_per_sub[i]) == 0:
                raise AssertionError(
                    f'Subscriber {i} received no events')

        # All subscribers must have been invoked from their own threads
        unique_threads = set(thread_ids.values())
        if len(unique_threads) < n_subs:
            raise AssertionError(
                f'Expected {n_subs} unique threads, got {len(unique_threads)}'
                f' (thread ids: {sorted(unique_threads)})')

        total_events = sum(len(e) for e in events_per_sub)
        print(f'  [iter {iteration}] {n_subs} subs × '
              f'{total_events // max(n_subs, 1)} events/sub '
              f'(total={total_events}, unique_threads={len(unique_threads)})')


class TestEventTypesAcrossSubscribers(unittest.TestCase):
    """Verify diverse event types are dispatched to all matching subs."""

    def test_all_job_events_arrive(self):
        got_job_added = queue.Queue()
        got_job_completed = queue.Queue()
        got_job_removed = queue.Queue()
        catch_all = queue.Queue()

        def on_job_added(evt):
            got_job_added.put(evt)

        def on_job_completed(evt):
            got_job_completed.put(evt)

        def on_job_removed(evt):
            got_job_removed.put(evt)

        def on_any(evt):
            catch_all.put(evt)

        monitor = UdisksMonitor(backend='dbus')
        monitor.subscribe(on_job_added, event_type=JobAdded)
        monitor.subscribe(on_job_completed, event_type=JobCompleted)
        monitor.subscribe(on_job_removed, event_type=JobRemoved)
        monitor.subscribe(on_any, event_type=None)

        monitor.start()
        self.assertTrue(monitor.ready.wait(timeout=10), 'Monitor not ready')

        _loop_setup_delete()

        monitor.stop()
        monitor.join(timeout=5)

        ja = _drain_queue(got_job_added)
        jc = _drain_queue(got_job_completed)
        jr = _drain_queue(got_job_removed)
        ca = _drain_queue(catch_all)

        print(f'  JobAdded={len(ja)}  JobCompleted={len(jc)}  '
              f'JobRemoved={len(jr)}  catch_all={len(ca)}')

        self.assertGreater(len(jc), 0, 'Expected at least one JobCompleted')
        self.assertGreater(len(ca), 0, 'Catch-all subscriber got no events')
        self.assertGreaterEqual(len(ca), len(jc) + len(ja) + len(jr),
                                'Catch-all should get >= sum of typed events')


def _drain_queue(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            break
    return items
