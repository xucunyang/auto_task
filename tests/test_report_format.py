"""报告头格式单元测试: 递增三位编号 + 日期 + 主题"""
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))
from report_format import ReportRegistry

PATTERN = re.compile(r"^\d{3} \d{4}-\d{2}-\d{2} .+")


def main():
    with tempfile.TemporaryDirectory() as d:
        reg = ReportRegistry(d)
        h1 = reg.next_header("2026年9月老旧小区加装电梯政策")
        h2 = reg.next_header("豪爵旅行者TVL350上市至今销量及相关影响")
        assert PATTERN.match(h1), h1
        assert PATTERN.match(h2), h2
        assert h1.startswith("001 ") and h2.startswith("002 "), (h1, h2)
        print(f"[PASS] 报告头格式: '{h1[:20]}...' -> '{h2[:20]}...'")
        # 计数器持久化
        reg2 = ReportRegistry(d)
        h3 = reg2.next_header("下一个主题")
        assert h3.startswith("003 "), h3
        print("[PASS] 序号跨实例持久化递增 (003)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
