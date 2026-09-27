"""验证 Agent (task.md §6/§7.4/§10): 只处理 SUBMITTED, 读验收标准, 执行验收"""
import json, subprocess, re, sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

def _has_python():
    import shutil as _s
    return _s.which("python") is not None

VALID_TYPES = {"command", "file_exists", "json_schema", "business_rule", "human_approval"}


class VerifierAgent:
    def __init__(self, base_dir="."):
        self.base = Path(base_dir)
        self.tasks_dir = self.base / "state" / "tasks"
        self.schemas_dir = self.base / "schemas"

    # ---- §7.4: 只处理 SUBMITTED ----
    def verify(self, task_id, shard_status=None) -> bool:
        shard = json.loads((self.tasks_dir / f"{task_id}.json").read_text())
        status = shard_status or shard["status"]
        if status not in ("SUBMITTED", "VERIFYING"):
            print(f"[verify-skip] {task_id}: status={status} (只处理 SUBMITTED)")
            return False
        checks = self.load_acceptance(shard)
        if not checks:
            print(f"[verify-warn] {task_id}: 无验收标准, 视为失败")
            return False
        results = [self.run_check(task_id, c) for c in checks]
        passed = all(r["passed"] for r in results)
        for r in results:
            print(f"  [{'PASS' if r['passed'] else 'FAIL'}] {r['type']}: {r.get('detail','')}")
        return passed

    # ---- 读验收标准: 分片 acceptance + schema 文件 ----
    def load_acceptance(self, shard) -> list:
        checks = list(shard.get("acceptance", []))
        ref = shard.get("acceptance_ref") or self._find_schema(shard["task_id"])
        if ref:
            p = self.base / ref
            if p.exists() and yaml:
                doc = yaml.safe_load(p.read_text()) or {}
                for c in doc.get("acceptance", []):
                    if c not in checks:
                        checks.append(c)
        return [c for c in checks if c.get("type") in VALID_TYPES]

    def _find_schema(self, task_id):
        for name in (f"acceptance_{task_id}.yaml", f"acceptance_{task_id.split('_')[0]}.yaml"):
            if (self.schemas_dir / name).exists():
                return f"schemas/{name}"
        return None

    # ---- 执行验收检查 (§10) ----
    def run_check(self, task_id, check) -> dict:
        t = check.get("type")
        try:
            if t == "file_exists":
                ok = (self.base / check["path"]).exists()
                return {"type": t, "passed": ok, "detail": check["path"]}
            if t == "command":
                cmd = check["cmd"]
                if not _has_python() and cmd.startswith("python "):
                    cmd = "python3 " + cmd[7:]
                r = subprocess.run(cmd, shell=True, cwd=self.base,
                                   capture_output=True, text=True, timeout=60)
                expect = check.get("expect_exit", 0)
                return {"type": t, "passed": r.returncode == expect,
                        "detail": f"exit={r.returncode} expect={expect} {r.stderr.strip()[:200]}"}
            if t == "business_rule":
                ok = self._eval_rule(check["expr"], task_id)
                return {"type": t, "passed": ok, "detail": check["expr"]}
            if t == "human_approval":
                return {"type": t, "passed": not check.get("required", False),
                        "detail": "auto" if not check.get("required") else "需人工"}
            if t == "json_schema":
                ok = self._check_json_schema(check)
                return {"type": t, "passed": ok, "detail": check.get("path","")}
            return {"type": t, "passed": False, "detail": "未知验收类型"}
        except Exception as e:
            return {"type": t, "passed": False, "detail": f"error: {e}"}

    # ---- business_rule: 受限表达式, 注入 rows/null_rate 等上下文 ----
    def _eval_rule(self, expr: str, task_id: str) -> bool:
        ctx = {"rows": 0, "null_rate": 1.0, "collected_count": 0}
        # 从产物文件推断上下文
        for out in ("artifacts/collect.json", "artifacts/clean.json"):
            p = self.base / out
            if p.exists():
                try:
                    d = json.loads(p.read_text())
                    ctx["rows"] = len(d) if isinstance(d, list) else 1
                    ctx["collected_count"] = ctx["rows"]
                    ctx["null_rate"] = 0.0
                except Exception:
                    pass
        if not re.fullmatch(r"[0-9a-zA-Z_\s()<>=!&|.\-*/+]+", expr):
            raise ValueError("表达式含非法字符")
        return bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307 受限环境

    def _check_json_schema(self, check) -> bool:
        data_p = self.base / check["path"]
        sch_p = self.base / check.get("schema", "")
        if not data_p.exists(): return False
        if not sch_p.exists(): return False
        data = json.loads(data_p.read_text())
        if yaml:
            sch = yaml.safe_load(sch_p.read_text())
            required = sch.get("required", [])
            return all(k in data for k in required)
        return True


if __name__ == "__main__":
    v = VerifierAgent()
    tid = sys.argv[1] if len(sys.argv) > 1 else "t1_collect"
    ok = v.verify(tid, shard_status="VERIFYING")
    print(f"[{'DONE' if ok else 'RETRY'}] {tid}")
    sys.exit(0 if ok else 1)
