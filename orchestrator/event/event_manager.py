"""Event Log: 追加式事件日志 (task.md §4.3)"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))

class EventManager:
    def __init__(self, base_dir="."):
        self.dir = Path(base_dir) / "events"
        self.dir.mkdir(parents=True, exist_ok=True)

    def append(self, task_id, from_state, to_state, agent="orchestrator", **extra):
        """追加写，不修改历史"""
        ev = {
            "ts": datetime.now(TZ).isoformat(timespec='seconds'),
            "task_id": task_id,
            "from": from_state,
            "to": to_state,
            "agent": agent,
        }
        ev.update(extra)
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        with open(self.dir / f"{day}.jsonl", "a") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def tail(self, n=10):
        files = sorted(self.dir.glob("*.jsonl"))
        if not files: return []
        lines = files[-1].read_text().strip().splitlines()
        return [json.loads(x) for x in lines[-n:]]

if __name__ == "__main__":
    em = EventManager()
    print("[OK] EventManager initialized")
