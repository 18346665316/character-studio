"""Atomic per-character task progress, shared by CLI, controller and local monitor."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

BASE_DIR = Path(__file__).resolve().parent.parent
LABELS = {'reconstruction': '原画重建', 'prepare': '贴图准备与预览', 'rig': '人工绑定与模型验证',
          'download': '动作下载与验证', 'import': 'Godot 导入', 'render': '图集渲染',
          'weapon':'独立武器重建', 'equipment': '装备与挂点', 'validate': '画面与时序检查', 'review': '人物外观与动作验收', 'complete': '输出完成'}


def update(character, stage, message, status='running', **details):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', character):
        raise ValueError('Invalid character ID')
    directory = BASE_DIR / '.local/progress'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{character}.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    stamp = datetime.now(timezone.utc).isoformat()
    event = {'stage': stage, 'message': message, 'status': status, 'time': stamp}
    events = (previous.get('events', []) + [event])[-40:]
    value = {'character': character, 'stage': stage, 'stage_label': LABELS.get(stage, stage),
             'message': message, 'status': status, 'updated_at': stamp, 'events': events, **details}
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.progress-')
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.replace(temporary, path)
    print(f'[{LABELS.get(stage, stage)}] {message}', flush=True)
    return value


def read(character):
    path = BASE_DIR / '.local/progress' / f'{character}.json'
    return json.loads(path.read_text()) if path.exists() else None


def track_failures(function):
    """Direct library/MCP orchestration also records failures, not only the CLI main."""
    from functools import wraps
    @wraps(function)
    def wrapped(character, *args, **kwargs):
        try:
            return function(character, *args, **kwargs)
        except BaseException as exc:
            current = read(character) or {}
            if current.get('status') != 'failed':
                details = {k: current[k] for k in ('job', 'batch', 'action') if k in current}
                update(character, current.get('stage', 'validate'),
                       '任务已取消' if isinstance(exc, KeyboardInterrupt) else str(exc),
                       status='failed', **details)
            raise
    return wrapped
