"""Independent terrain production worker, inheriting the project execution lease."""
from pathlib import Path
import sys

from task_lock import task_lock
from terrain import execute


if __name__ == '__main__':
    root = Path(__file__).resolve().parent.parent
    with task_lock(root, inherited_fd=int(sys.argv[2])):
        execute(root, sys.argv[1])
