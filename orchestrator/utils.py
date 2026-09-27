"""§11 异常恢复与并发控制: 原子写/锁/幂等/租约/重试"""
import json, os, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

def now_iso(): return datetime.now(TZ).isoformat(timespec='seconds')

def atomic_write_json(path, data):
    """原子写: tmp + fsync + rename"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.flush(); os.fsync(fh.fileno())
    os.rename(tmp, path)

def read_json(path):
    return json.loads(Path(path).read_text())

class FileLock:
    """任务锁: O_CREAT|O_EXCL, 带超时与心跳"""
    def __init__(self, lock_dir, name, lease_seconds=300):
        self.path = Path(lock_dir) / f"{name}.lock"
        self.lease_seconds = lease_seconds

    def acquire(self, wait=0, stale_after=None):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + wait
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({"pid": os.getpid(), "ts": now_iso(),
                                          "expires": (datetime.now(TZ)+timedelta(seconds=self.lease_seconds)).isoformat(timespec='seconds')}).encode())
                os.close(fd)
                return True
            except FileExistsError:
                if stale_after and self._is_stale(stale_after):
                    self.release(); continue
                if time.time() >= deadline: return False
                time.sleep(0.1)

    def _is_stale(self, seconds):
        try:
            age = time.time() - self.path.stat().st_mtime
            return age > seconds
        except FileNotFoundError:
            return False

    def release(self):
        if self.path.exists(): self.path.unlink()

    def __enter__(self): assert self.acquire(); return self
    def __exit__(self, *a): self.release()

def idempotency_key(plan_id, task_id): return f"{plan_id}/{task_id}"

def content_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def lease_expired(lease_until):
    return lease_until is not None and now_iso() > lease_until

def backoff_seconds(attempt, base=2, cap=300):
    """指数退避"""
    return min(base ** attempt, cap)

def resolve_retry(shard):
    """重试策略: 未超限→RETRY, 超限→DEAD_LETTER"""
    if shard.get("attempts", 0) >= shard.get("max_attempts", 3):
        return "DEAD_LETTER"
    return "RETRY"
