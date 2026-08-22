# Auto-imported by CPython at startup.
# On network filesystems, mtime-based .pyc invalidation is unreliable —
# Python can load a stale .pyc even after the .py is edited. Disabling
# bytecode writing (and reading) eliminates this class of bugs at a small
# startup-cost price. Essential for portable/network-share deployments.
import sys
sys.dont_write_bytecode = True

# app.log live streaming: when the launcher redirects stdout/stderr to a
# file, CPython block-buffers (8KB) — logs sit in memory for the whole
# session and are lost on crashes/kills. Line-buffer stdout and make
# stderr write-through so every line reaches disk immediately.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(line_buffering=True)
    except (AttributeError, ValueError, OSError):
        pass
