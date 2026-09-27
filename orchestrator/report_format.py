"""报告头规范 (task.md 报告输出格式): 递增三位编号 + 时间 + 主题
第一行格式: # {NNN} {YYYY-MM-DD} {主题}
由 acceptance_t3 的 grep 检查强制校验; 计数器持久化于 state/report_seq.json
"""
import json
import os
import datetime
from pathlib import Path


class ReportRegistry:
    def __init__(self, base_dir="."):
        self.path = Path(base_dir) / "state" / "report_seq.json"

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"seq": 0, "history": []}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.path) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(tmp, self.path)

    def next_header(self, topic: str) -> str:
        """分配下一个编号, 返回报告首行正文 (不含 '# ' 前缀)"""
        data = self._load()
        data["seq"] += 1
        num = f"{data['seq']:03d}"
        today = datetime.date.today().isoformat()
        data["history"].append({"num": num, "date": today, "topic": topic})
        self._save(data)
        return f"{num} {today} {topic}"
