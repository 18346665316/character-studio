"""One execution lease shared by UI, CLI, MCP and their Python children."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import fcntl
import os
import threading

_active = threading.local()
_ENV = 'STUDIO_TASK_LOCK_FD'


class TaskBusyError(ValueError):
    """Contention is a rejected request, not failure of the task holding the lease."""


def lock_path(root):
    return Path(root).resolve() / '.local/panel/worker.lock'


def acquire(root):
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


@contextmanager
def task_lock(root, inherited_fd=None):
    """Reentrant in a call chain; a passed descriptor transfers the same lease."""
    path = lock_path(root)
    current = getattr(_active, 'lease', None)
    if current and current[0] == path:
        yield current[1]
        return
    fd = inherited_fd
    if fd is None and os.environ.get(_ENV):
        fd = int(os.environ[_ENV])
    if fd is not None:
        try:
            actual, expected = os.fstat(fd), path.stat()
            if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                raise ValueError('任务锁不属于当前项目')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError):
            raise ValueError('继承的任务锁无效') from None
        # Own a duplicate, leaving the caller responsible for the original fd.
        fd = os.dup(fd)
    else:
        fd = acquire(root)
    if fd is None:
        raise TaskBusyError('已有任务在运行，请等待完成后再操作')
    os.set_inheritable(fd, False)
    _active.lease = (path, fd)
    try:
        yield fd
    finally:
        _active.lease = current
        os.close(fd)


def serialized(root):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with task_lock(root(*args, **kwargs)):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def child_options():
    """Explicit descriptor handoff; ordinary subprocesses do not inherit the lease."""
    env = {**os.environ, 'PYTHONUNBUFFERED':'1'}
    env.pop(_ENV, None)
    current = getattr(_active, 'lease', None)
    if current:
        fd = current[1]
        env[_ENV] = str(fd)
        return {'env': env, 'pass_fds': (fd,)}
    return {'env': env}
