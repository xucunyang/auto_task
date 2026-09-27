"""任务分片协议 + DAG + 状态机校验 (task.md §4.2/§5)"""
import json, sys, glob, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

REQ = ['task_id','plan_id','status','version','owner','lease_until','idempotency_key',
       'attempts','max_attempts','objective','inputs','outputs','acceptance','handoff']
VALID = {'PENDING','READY','RUNNING','SUBMITTED','VERIFYING','DONE','FAILED','RETRY',
         'DEAD_LETTER','BLOCKED','WAITING_APPROVAL','CANCELLED','SKIPPED'}

def main():
    files = sorted(glob.glob(str(ROOT/'state/tasks/*.json')))
    assert files, "无任务分片"
    shards = {}
    for f in files:
        t = json.load(open(ROOT/f))
        miss = [k for k in REQ if k not in t]
        assert not miss, f"{f} 缺字段: {miss}"
        assert t['status'] in VALID, f"{f} 非法状态 {t['status']}"
        assert t['idempotency_key'] == f"{t['plan_id']}/{t['task_id']}", f"{f} 幂等键错误"
        assert t['attempts'] <= t['max_attempts']
        assert isinstance(t['acceptance'], list) and t['acceptance'], f"{f} acceptance 不能为空"
        shards[t['task_id']] = t
    # DAG 无环 + 依赖存在
    def has_cycle(g):
        vis = {}
        def dfs(n):
            if vis.get(n) == 1: return True
            if vis.get(n) == 2: return False
            vis[n] = 1
            for d in g.get(n, []):
                if dfs(d): return True
            vis[n] = 2; return False
        return any(dfs(n) for n in g)
    deps = {k: v.get('dag_deps', v.get('depends_on', [])) for k, v in shards.items()}
    assert not has_cycle(deps), "DAG 存在环"
    for k, v in deps.items():
        for d in v:
            assert d in shards, f"{k} 依赖 {d} 不存在"
    # 状态机转换合法性
    spec = importlib.util.spec_from_file_location('orch', str(ROOT/'orchestrator/orchestrator.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert not m.can_transition('PENDING', 'DONE'), "必须禁止 PENDING→DONE"
    assert m.can_transition('SUBMITTED', 'VERIFYING')
    print(f"[PASS] 分片协议 14字段/{len(shards)}片/DAG无环/状态机合法")
    return 0

if __name__ == '__main__':
    sys.exit(main())
