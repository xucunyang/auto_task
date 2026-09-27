"""master.json 协议校验 (task.md §4.1)"""
import json, sys, glob
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

def main():
    m = json.load(open(ROOT/'state/master.json'))
    req = ['plan_id','timezone','status','version','created_at','updated_at','tasks']
    missing = [k for k in req if k not in m]
    assert not missing, f"master 缺字段: {missing}"
    assert isinstance(m['tasks'], list), "tasks 必须是数组"
    assert m['status'] in ('PENDING','RUNNING','DONE','FAILED'), f"非法状态 {m['status']}"
    assert isinstance(m['version'], int)
    ids = set()
    for t in m['tasks']:
        for k in ('id','status','depends_on','shard'):
            assert k in t, f"task 缺字段 {k}"
        ids.add(t['id'])
    shards = {p.split('/')[-1].replace('.json','') for p in glob.glob(str(ROOT/'state/tasks/*.json'))}
    assert ids == shards or ids.issubset(shards), f"master/tasks 与分片不一致: {ids ^ shards}"
    print("[PASS] master.json 协议: 7字段/tasks数组/状态合法/分片索引一致")
    return 0

if __name__ == '__main__':
    sys.exit(main())
