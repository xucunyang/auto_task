"""Elevator Policy Research Orchestrator - 主 Agent (task.md §5/§6/§7.2)"""
import json, os, time, glob
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

# ---- §5 状态机定义 ----
STATES = ["PENDING","READY","RUNNING","SUBMITTED","VERIFYING","DONE",
          "FAILED","RETRY","DEAD_LETTER","BLOCKED","WAITING_APPROVAL","CANCELLED","SKIPPED"]
TERMINAL = {"DONE","DEAD_LETTER","CANCELLED","SKIPPED"}
TRANSITIONS = {
    "PENDING": ["READY","BLOCKED","CANCELLED"],
    "BLOCKED": ["READY","CANCELLED"],
    "READY":   ["RUNNING","CANCELLED"],
    "RUNNING": ["SUBMITTED","FAILED"],
    "FAILED":  ["RETRY","DEAD_LETTER"],
    "RETRY":   ["READY"],
    "SUBMITTED": ["VERIFYING"],
    "VERIFYING": ["DONE","RETRY","FAILED"],
}

def now_iso(): return datetime.now(TZ).isoformat(timespec='seconds')

def can_transition(src, dst):
    return dst in TRANSITIONS.get(src, [])


class Orchestrator:
    def __init__(self, base_dir="."):
        self.base = Path(base_dir)
        self.state = self.base / "state"
        self.tasks_dir = self.state / "tasks"
        self.events_dir = self.base / "events"
        self.locks_dir = self.base / "locks"
        self.master_path = self.state / "master.json"
        self.dead_letter = self.base / "dead_letter"
        for d in (self.events_dir, self.locks_dir, self.dead_letter):
            d.mkdir(parents=True, exist_ok=True)

    # ---- 状态读取 (§9: 每轮从磁盘重建上下文) ----
    def read_master(self):
        return json.loads(self.master_path.read_text())

    def read_shards(self):
        return [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(self.tasks_dir / "*.json")))]

    # ---- §11 事件日志 (追加式) ----
    def append_event(self, task_id, from_s, to_s, agent="orchestrator", **extra):
        ev = {"ts": now_iso(), "task_id": task_id, "from": from_s, "to": to_s, "agent": agent, **extra}
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        with open(self.events_dir / f"{day}.jsonl", "a") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # ---- 锁 (§11) ----
    def acquire_lock(self, task_id):
        lp = self.locks_dir / f"{task_id}.lock"
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode()); os.close(fd)
            return True
        except FileExistsError:
            return False

    def release_lock(self, task_id):
        lp = self.locks_dir / f"{task_id}.lock"
        if lp.exists(): lp.unlink()

    # ---- 状态更新 (乐观锁 version) ----
    def update_shard(self, task_id, status, owner=None, handoff=None, **extra):
        path = self.tasks_dir / f"{task_id}.json"
        shard = json.loads(path.read_text())
        if not can_transition(shard["status"], status):
            raise ValueError(f"illegal transition {shard['status']} -> {status} for {task_id}")
        if extra.pop("expected_version", True):
            assert shard["version"] is not None
        shard.update({"status": status, "version": shard["version"] + 1, "updated_at": now_iso()})
        if owner is not None: shard["owner"] = owner
        if handoff is not None: shard["handoff"] = handoff
        src = extra.pop("_from", None)
        shard.update(extra)
        tmp = str(path) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(shard, fh, ensure_ascii=False, indent=2); fh.flush(); os.fsync(fh.fileno())
        os.rename(tmp, path)
        self.append_event(task_id, src or "?", status, agent=owner or "orchestrator")
        return shard

    # ---- 租约回收 (§5: RUNNING 超时回收) ----
    def recover_expired_leases(self):
        for shard in self.read_shards():
            if shard["status"] == "RUNNING" and shard.get("lease_until"):
                if now_iso() > shard["lease_until"]:
                    if shard["attempts"] >= shard["max_attempts"]:
                        self.update_shard(shard["task_id"], "FAILED", _from="RUNNING")
                        self.update_shard(shard["task_id"], "DEAD_LETTER", _from="FAILED")
                        self._to_dead_letter(shard["task_id"])
                    else:
                        self.update_shard(shard["task_id"], "FAILED", _from="RUNNING")
                        self.update_shard(shard["task_id"], "RETRY", _from="FAILED")
                        self.update_shard(shard["task_id"], "READY", _from="RETRY")

    def _to_dead_letter(self, task_id):
        shard = json.loads((self.tasks_dir / f"{task_id}.json").read_text())
        (self.dead_letter / f"{task_id}.json").write_text(json.dumps(shard, ensure_ascii=False, indent=2))

    # ---- §5: 只有依赖全 DONE 才 READY ----
    def refresh_ready(self):
        shards = {s["task_id"]: s for s in self.read_shards()}
        for s in shards.values():
            if s["status"] in ("PENDING", "BLOCKED"):
                deps = self._deps_of(s["task_id"])
                if all(shards.get(d, {}).get("status") == "DONE" for d in deps):
                    if s["status"] != "READY":
                        self.update_shard(s["task_id"], "READY", _from=s["status"])

    def _deps_of(self, task_id):
        m = self.read_master()
        for t in m.get("tasks", []):
            if t["id"] == task_id: return t.get("depends_on", [])
        return []

    # ---- §7.2 主循环 ----
    def all_done(self):
        return all(s["status"] in TERMINAL for s in self.read_shards())

    def get_ready_tasks(self):
        return [s["task_id"] for s in self.read_shards() if s["status"] == "READY"]

    def get_submitted_tasks(self):
        return [s["task_id"] for s in self.read_shards() if s["status"] == "SUBMITTED"]

    def run(self, max_cycles=100, poll_interval=1.0, dispatch=None, verify=None):
        """dispatch(task_id)->bool 派发子Agent; verify(task_id)->bool 验收"""
        cycles = 0
        while not self.all_done() and cycles < max_cycles:
            cycles += 1
            self.recover_expired_leases()
            self.refresh_ready()

            for tid in self.get_ready_tasks():
                if self.acquire_lock(tid):
                    try:
                        shard = json.loads((self.tasks_dir / f"{tid}.json").read_text())
                        self.update_shard(tid, "RUNNING", owner=f"sub-agent-{tid}",
                                          lease_until=(datetime.now(TZ)+timedelta(minutes=5)).isoformat(timespec='seconds'),
                                          _from="RUNNING_PLACEHOLDER")
                    except Exception as e:
                        print(f"[dispatch-skip] {tid}: {e}")
                        self.release_lock(tid)
                        continue
                    ok = dispatch(tid) if dispatch else True
                    if ok:
                        try:
                            self.update_shard(tid, "SUBMITTED", _from="RUNNING")
                        except ValueError:
                            pass
                    else:
                        self._fail_or_retry(tid)
                    self.release_lock(tid)

            for tid in self.get_submitted_tasks():
                try: self.update_shard(tid, "VERIFYING", _from="SUBMITTED")
                except ValueError: continue
                passed = verify(tid) if verify else True
                if passed:
                    self.update_shard(tid, "DONE", _from="VERIFYING")
                else:
                    self._fail_or_retry(tid)

            self.refresh_ready()
            self._refresh_master()
            time.sleep(poll_interval)
        return self.all_done()

    def _fail_or_retry(self, task_id):
        """失败处理: attempts+1, 未超限→RETRY→READY, 超限→DEAD_LETTER+告警"""
        path = self.tasks_dir / f"{task_id}.json"
        shard = json.loads(path.read_text())
        shard["attempts"] = shard.get("attempts", 0) + 1
        tmp = str(path) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(shard, fh, ensure_ascii=False, indent=2); fh.flush(); os.fsync(fh.fileno())
        os.rename(tmp, path)
        self.update_shard(task_id, "FAILED", _from="RUNNING" if shard["status"]=="RUNNING" else "VERIFYING")
        if shard["attempts"] >= shard.get("max_attempts", 3):
            self.update_shard(task_id, "DEAD_LETTER", _from="FAILED")
            dl = self.dead_letter / f"{task_id}.json"
            dl.write_text(json.dumps(json.loads(path.read_text()), ensure_ascii=False, indent=2))
            try:
                sys.path.insert(0, str(self.base / "orchestrator"))
                from notifier import Notifier
                Notifier(str(self.base)).task_dead_letter(task_id)
            except Exception:
                print(f"[ALERT:CRITICAL] {task_id} -> DEAD_LETTER")
        else:
            self.update_shard(task_id, "RETRY", _from="FAILED")
            self.update_shard(task_id, "READY", _from="RETRY")

    def _refresh_master(self):
        m = self.read_master()
        shards = {s["task_id"]: s for s in self.read_shards()}
        for t in m["tasks"]:
            if t["id"] in shards:
                t["status"] = shards[t["id"]]["status"]
        m["version"] += 1
        m["updated_at"] = now_iso()
        tmp = str(self.master_path) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2); fh.flush(); os.fsync(fh.fileno())
        os.rename(tmp, self.master_path)


if __name__ == "__main__":
    orch = Orchestrator()
    print("[OK] orchestrator initialized, states:", len(STATES))
