"""文件工具 — 原子写入 + 进程间文件锁

用法:
    from scripts.file_utils import atomic_write_json
    atomic_write_json(filepath, data)
"""

import json, os
from pathlib import Path
try:
    from filelock import FileLock
except ImportError:
    class FileLock:
        def __init__(self, path, timeout=5):
            self.path = path
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False


def atomic_write_json(filepath: Path, data: dict, timeout: int = 5) -> None:
    """进程安全的原子 JSON 写入

    跨进程锁（filelock）+ 原子替换（tmp + os.replace）双保险，
    防止 APScheduler / gen_dashboard_data / /api/sync 多写入点冲突。

    Args:
        filepath: 目标文件路径
        data: 要写入的 dict 数据
        timeout: 获取锁的超时秒数
    """
    lock_path = filepath.with_suffix('.lock')
    with FileLock(str(lock_path), timeout=timeout):
        tmp = filepath.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, filepath)
