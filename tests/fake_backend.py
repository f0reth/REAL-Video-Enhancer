"""Controllable backend fixture using the production lifecycle and protocol."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from src.notifications import initialize, emit
from src.lifecycle import install
from src.utils.Util import subprocess_popen_without_terminal

parser = argparse.ArgumentParser()
parser.add_argument("-i")
parser.add_argument("-o")
parser.add_argument("--pause_shared_memory_id")
args, _ = parser.parse_known_args()
initialize()
install()
mode = Path(args.i).stem
emit("stage", stage="rendering")
if mode == "crash":
    os._exit(7)
if mode == "silent":
    sys.exit(0)
if mode in ("cancel", "pause"):
    from multiprocessing import shared_memory
    child = subprocess_popen_without_terminal([sys.executable, "-c", "import time; time.sleep(120)"])
    emit("effective", child_pid=child.pid)
    memory = shared_memory.SharedMemory(name=args.pause_shared_memory_id)
    paused = False
    for _ in range(1000):
        new = memory.buf[0] == 1
        if new != paused:
            emit("paused" if new else "resumed")
            paused = new
        time.sleep(.01)
else:
    # Split inside a UTF-8 sequence, then emit a completion immediately before exit.
    from src import notifications
    payload = '{"event":"stage","stage":"準備"}\n'.encode("utf-8")
    for value in payload:
        os.write(notifications._stream.fileno(), bytes([value]))
    Path(args.o).write_bytes(Path(args.i).read_bytes())
    emit("progress", processed=40, total=40, fps=100, eta="0:00:00")
    emit("completed")
