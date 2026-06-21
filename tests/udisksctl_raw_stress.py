"""Stress test: raw udisksctl monitor + UDisks2, no Python wrapper."""
import os, subprocess, tempfile, threading, time, unittest

def _spawn_monitor():
    """Spawn udisksctl monitor, return the process and a thread-safe output list."""
    proc = subprocess.Popen(
        ['udisksctl', 'monitor'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    lines = []
    stop = threading.Event()

    def reader():
        try:
            for line in proc.stdout:
                if stop.is_set():
                    break
                lines.append(line.rstrip('\n'))
        except Exception:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    return proc, lines, stop, t

def _make_image():
    fd, path = tempfile.mkstemp(suffix='.img')
    os.close(fd)
    subprocess.run(['dd', 'if=/dev/zero', 'of=' + path, 'bs=1M', 'count=1'], capture_output=True, check=True)
    subprocess.run(['mkfs.vfat', path], capture_output=True, check=True)
    try:
        r = subprocess.run(['udisksctl', 'loop-setup', '-f', path, '--no-user-interaction'], capture_output=True, text=True, timeout=60)
        r.check_returncode()
    except subprocess.CalledProcessError:
        os.unlink(path)
        raise RuntimeError(f'loop-setup FAILED: {r.stderr.strip()[:200]}')
    for line in r.stdout.splitlines():
        if '/dev/' in line:
            return line.strip().split()[-1].rstrip('.'), path
    os.unlink(path)
    raise RuntimeError(f'parse fail: {r.stdout}')

def _delete_image(dev, path):
    for _ in range(3):
        subprocess.run(['udisksctl', 'unmount', '-b', dev, '--no-user-interaction'], capture_output=True)
        r = subprocess.run(['udisksctl', 'loop-delete', '-b', dev, '--no-user-interaction'], capture_output=True)
        if r.returncode == 0:
            break
    if os.path.exists(path):
        os.unlink(path)


class TestRawUdisksctlMonitor(unittest.TestCase):
    """Stress test the raw udisksctl monitor."""

    CYCLES = 10

    def test_rapid_loop_ops_single_monitor(self):
        """One monitor, many loop ops — does it miss events?"""
        proc, lines, stop, thread = _spawn_monitor()
        time.sleep(1)  # Let it connect to D-Bus

        results = []
        for i in range(self.CYCLES):
            before = len(lines)
            try:
                dev, path = _make_image()
                _delete_image(dev, path)
                results.append('ok')
            except RuntimeError as e:
                results.append(f'FAIL: {e}')
                break

            # Wait briefly for signals to arrive
            time.sleep(0.3)
            after = len(lines)
            results[-1] += f' (+{after - before} lines)'

        stop.set()
        proc.terminate()
        proc.wait(timeout=5)
        thread.join(timeout=5)

        print(f'\n  {self.CYCLES} cycles with 1 persistent monitor:')
        ok = sum(1 for r in results if r.startswith('ok'))
        fail = len(results) - ok
        print(f'    ok: {ok}  fail: {fail}')
        print(f'    total stdout lines: {len(lines)}')
        for r in results:
            print(f'    {r}')

        if fail > self.CYCLES * 0.3:
            self.fail(f'{fail}/{self.CYCLES} cycles failed')

    def test_close_reopen_monitor(self):
        """Close and reopen the monitor between each cycle — parity test pattern."""
        ok = 0
        fail = 0
        for i in range(self.CYCLES):
            proc, lines, stop, thread = _spawn_monitor()
            time.sleep(0.5)  # Let it connect

            try:
                dev, path = _make_image()
                _delete_image(dev, path)
                ok += 1
            except RuntimeError as e:
                fail += 1
                print(f'    cycle {i}: {e}')

            time.sleep(1)  # Let signals arrive
            stop.set()
            proc.terminate()
            proc.wait(timeout=5)
            thread.join(timeout=5)
            print(f'    cycle {i}: {"ok" if fail == 0 or i+1 > fail else "FAIL"} '
                  f'(+{len(lines)} lines)')

        print(f'\n  {self.CYCLES} close/reopen cycles:')
        print(f'    ok: {ok}  fail: {fail}')
        if ok < self.CYCLES * 0.5:
            self.fail(f'less than 50% pass: {ok}/{self.CYCLES}')


class TestRawUdisksctlSignalCount(unittest.TestCase):
    """Check if udisksctl monitor accurately reports signals."""

    def test_signal_lines_per_operation(self):
        """Count stdout lines for a single loop-setup+delete cycle."""
        proc, lines, stop, thread = _spawn_monitor()
        time.sleep(0.5)

        before = len(lines)
        dev, path = _make_image()
        _delete_image(dev, path)
        time.sleep(1)
        after = len(lines)

        stop.set()
        proc.terminate()
        proc.wait(timeout=5)
        thread.join(timeout=5)

        total = after - before
        print(f'\n  stdout lines from 1 loop-setup+delete: {total}')

        # Count by type
        has_ia = any('Added interface ' in l for l in lines[before:after])
        has_ir = any('Removed interface ' in l for l in lines[before:after])
        has_job = any('/jobs/' in l for l in lines[before:after])
        has_prop = any('Properties Changed' in l for l in lines[before:after])
        has_completed = any('::Completed' in l for l in lines[before:after])
        print(f'    InterfaceAdded: {has_ia}')
        print(f'    InterfaceRemoved: {has_ir}')
        print(f'    Jobs: {has_job}')
        print(f'    Properties: {has_prop}')
        print(f'    Completed: {has_completed}')

        self.assertGreater(total, 5, 'too few signal lines')
