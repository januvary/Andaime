# Auto-imported by CPython at startup.
# On network filesystems, mtime-based .pyc invalidation is unreliable —
# Python can load a stale .pyc even after the .py is edited. Disabling
# bytecode writing (and reading) eliminates this class of bugs at a small
# startup-cost price. Essential for portable/network-share deployments.
import sys
sys.dont_write_bytecode = True
