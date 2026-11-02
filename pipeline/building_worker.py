"""Panel child process: inherit the shared production lease."""
from pathlib import Path
import sys
from task_lock import task_lock
from building_pipeline import execute

if __name__ == '__main__':
    root=Path(__file__).resolve().parents[1]
    with task_lock(root,inherited_fd=int(sys.argv[2])):
        execute(root,sys.argv[1])
