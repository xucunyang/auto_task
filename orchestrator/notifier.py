"""Notifier: 告警、日报、人工介入 (task.md §2)"""
import json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))

class Notifier:
    def __init__(self, base_dir="."):
        self.outbox = Path(base_dir) / "logs" / "outbox"
        self.outbox.mkdir(parents=True, exist_ok=True)

    def notify(self, level, subject, body, channel="log"):
        """level: INFO/WARN/CRITICAL; channel: log/email/webhook"""
        msg = {"ts": datetime.now(TZ).isoformat(timespec='seconds'),
               "level": level, "subject": subject, "body": body, "channel": channel}
        f = self.outbox / f"{datetime.now(TZ).strftime('%Y-%m-%d')}.jsonl"
        with open(f, "a") as fh: fh.write(json.dumps(msg, ensure_ascii=False) + "\n")
        if level in ("WARN", "CRITICAL"):
            print(f"[ALERT:{level}] {subject}")
        return msg

    def task_failed(self, task_id, reason): return self.notify("WARN", f"task {task_id} failed", reason)
    def task_dead_letter(self, task_id): return self.notify("CRITICAL", f"task {task_id} in DEAD_LETTER", "需要人工介入")
    def daily_report(self, summary): return self.notify("INFO", "daily report", summary)

if __name__ == "__main__":
    print("[OK] notifier initialized")
