import os
import signal
import subprocess
import sys
import threading
import time

from traduko.service.parentwatch import ParentWatchdog, pid_alive


def test_pid_alive_for_own_process() -> None:
    assert pid_alive(os.getpid()) is True


def test_pid_alive_for_exited_process() -> None:
    proc = subprocess.Popen(["true"])
    proc.wait()
    assert pid_alive(proc.pid) is False


def test_terminates_when_parent_disappears() -> None:
    alive = {"value": True}
    fired = threading.Event()
    dog = ParentWatchdog(
        12345,
        interval=0.01,
        is_alive=lambda pid: alive["value"],
        terminate=fired.set,
    )
    dog.start()
    try:
        time.sleep(0.05)
        assert not fired.is_set()
        alive["value"] = False
        assert fired.wait(timeout=2.0)
    finally:
        dog.stop()


def test_stop_ends_watch_without_terminating() -> None:
    fired = threading.Event()
    dog = ParentWatchdog(
        12345, interval=0.01, is_alive=lambda pid: True, terminate=fired.set
    )
    dog.start()
    dog.stop()
    assert not dog.is_watching
    assert not fired.is_set()


def test_child_process_exits_when_watched_parent_dies() -> None:
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    child_code = (
        "import time\n"
        "from traduko.service.parentwatch import ParentWatchdog\n"
        f"ParentWatchdog({parent.pid}, interval=0.05).start()\n"
        "time.sleep(60)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_code])
    try:
        time.sleep(0.5)
        assert child.poll() is None, "child must stay up while the parent lives"
        parent.kill()
        parent.wait()
        # Default termination path: SIGTERM to itself.
        assert child.wait(timeout=10) == -signal.SIGTERM
    finally:
        for proc in (parent, child):
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_hard_exits_when_sigterm_is_swallowed() -> None:
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    child_code = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "from traduko.service.parentwatch import ParentWatchdog\n"
        f"ParentWatchdog({parent.pid}, interval=0.05, grace=0.2).start()\n"
        "time.sleep(60)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_code])
    try:
        time.sleep(0.5)
        assert child.poll() is None
        parent.kill()
        parent.wait()
        # SIGTERM is ignored, so the watchdog must os._exit(1) after grace.
        assert child.wait(timeout=10) == 1
    finally:
        for proc in (parent, child):
            if proc.poll() is None:
                proc.kill()
                proc.wait()
