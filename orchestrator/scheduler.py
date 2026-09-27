"""§7.1/§8 调度器: 确定性程序, 模板生成计划实例, 幂等"""
import json, sys, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))

try:
    import yaml
    def load_yaml(p): return yaml.safe_load(Path(p).read_text())
except ImportError:
    # 轻量回退: 无 pyyaml 时用 JSON 模板
    def load_yaml(p):
        return json.loads(Path(p).read_text())

class Scheduler:
    """独立于 Agent 的确定性调度器, 只生成计划, 不执行业务"""

    def __init__(self, base_dir="."):
        self.base = Path(base_dir)
        self.state = self.base / "state"
        self.plans_dir = self.state / "plans"
        self.tasks_dir = self.state / "tasks"
        self.events = self.base / "events"
        for d in (self.state, self.plans_dir, self.tasks_dir, self.events): d.mkdir(parents=True, exist_ok=True)

    def generate_plan_id(self, job_id, date=None):
        """任务ID带日期, 天然幂等"""
        d = date or datetime.now(TZ).strftime("%Y-%m-%d")
        return f"{job_id}_{d}"

    def plan_exists(self, plan_id):
        return (self.plans_dir / f"{plan_id}.json").exists()

    def create_plan(self, job_id, template_path):
        """生成计划实例; 已存在则跳过 (幂等)"""
        plan_id = self.generate_plan_id(job_id)
        if self.plan_exists(plan_id):
            self._emit(plan_id, "SKIPPED", reason="plan already exists (idempotent)")
            return {"plan_id": plan_id, "created": False}

        tpl = load_yaml(template_path)
        now = datetime.now(TZ).isoformat(timespec='seconds')
        tasks = [{
            "id": t["id"], "name": t.get("name",""), "status": "PENDING",
            "depends_on": t.get("depends_on", []),
            "shard": f"state/tasks/{t['id']}.json",
            "result": None, "acceptance_ref": t.get("acceptance_ref"),
        } for t in tpl.get("tasks", [])]

        # 计划实例独立存储 (task.md §8: 每天生成实例, 幂等)
        master = {"plan_id": plan_id, "timezone": "Asia/Shanghai", "status": "PENDING",
                  "version": 1, "created_at": now, "updated_at": now, "tasks": tasks}
        self._atomic(self.plans_dir / f"{plan_id}.json", master)

        # 任务分片 (已存在则不覆盖, 保持非破坏性)
        for t in tasks:
            shard_path = self.tasks_dir / f"{t['id']}.json"
            if shard_path.exists():
                continue
            shard = {
                "task_id": t["id"], "plan_id": plan_id, "status": "PENDING", "version": 1,
                "owner": None, "lease_until": None,
                "idempotency_key": f"{plan_id}/{t['id']}",
                "attempts": 0, "max_attempts": 3,
                "objective": t["name"], "inputs": [], "outputs": [],
                "acceptance": [], "handoff": None,
            }
            self._atomic(shard_path, shard)

        self._emit(plan_id, "CREATED", tasks=len(tasks))
        return {"plan_id": plan_id, "created": True, "tasks": len(tasks)}

    def check_misfire(self, scheduled, grace=3600):
        """错过执行策略 (§8): grace 内补跑, 超过跳过/告警"""
        diff = (datetime.now(TZ) - scheduled).total_seconds()
        if diff <= 1: return "ON_TIME"  # 1秒容差内视为准点
        if diff <= grace: return "CATCH_UP"
        return "MISFIRE_SKIP"

    def _atomic(self, path, data):
        tmp = str(path) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2); fh.flush(); os.fsync(fh.fileno())
        os.rename(tmp, path)

    def _emit(self, plan_id, event, **extra):
        ev = {"ts": datetime.now(TZ).isoformat(timespec='seconds'),
              "scheduler": plan_id, "event": event, **extra}
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        with open(self.events / f"{day}.jsonl", "a") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    s = Scheduler()
    r = s.create_plan("elevator_policy_research", "templates/daily_plan.yaml")
    print(f"[OK] scheduler plan: {r}")
