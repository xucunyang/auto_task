"""发散影响评估模块单元测试 (主题无关)"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))
from impact_analyzer import ImpactAnalyzer

ia = ImpactAnalyzer(str(ROOT))

def rec(u="https://example.gov.cn/p/1", **kw):
    base = {"title": "t", "publisher": "p", "publish_date": "2026-09-01", "url": u}
    base.update(kw); return base

def main():
    # 1) 三主题 + 兜底包
    assert ia.pick_pack("老旧小区加装电梯政策")["id"] == "housing_elevator"
    assert ia.pick_pack("环境治理与碳排放新规")["id"] == "environment_governance"
    assert ia.pick_pack("三农种粮补贴政策")["id"] == "agriculture_rural"
    assert ia.pick_pack("数字货币")["id"] == "generic"
    print("[PASS] 主题→领域包 路由 (电梯/环境/三农/兜底)")

    # 2) 三主题评估: 每领域利好+利空+来源
    cases = [
        ("2026年9月老旧小区加装电梯政策", [rec(url="https://a.cn/1", title="住宅项目规范 电梯 层高"),
                                          rec(url="https://b.cn/2", title="国债补贴 加装电梯")]),
        ("环境治理新规", [rec(url="https://c.cn/3", title="污染物排放标准 治理"),
                        rec(url="https://d.cn/4", title="碳排放权 交易")]),
        ("三农粮食安全政策", [rec(url="https://e.cn/5", title="粮食收储 农民补贴"),
                          rec(url="https://f.cn/6", title="种业 农机装备")]),
    ]
    for topic, records in cases:
        a = ia.assess(topic, records)
        errs = ia.validate(a)
        assert not errs, f"{topic}: {errs}"
        assert len(a["market"]) >= 2 and len(a["other"]) >= 2
        md = ia.render_markdown(a)
        assert "市场影响" in md and "其他领域影响" in md
        assert "利好" in md and "利空" in md
        assert md.count("https://") >= 4, "渲染必须带来源链接"
        print(f"[PASS] {topic[:12]}...: market={len(a['market'])} other={len(a['other'])} 双向覆盖+溯源")

    # 3) 校验器能拦截: 单向覆盖 / 无来源
    bad = {"market": [{"domain": "X", "direction": "利好", "text": "t", "sources": ["https://x.cn"], "basis": "推断"}],
           "other": [{"domain": "Y", "direction": "利空", "text": "t", "sources": [], "basis": "推断"}]}
    errs = ia.validate(bad)
    assert any("利好+利空" in e for e in errs) and any("来源为空" in e for e in errs)
    print("[PASS] validate 拦截单向覆盖与空来源")
    return 0

if __name__ == "__main__":
    sys.exit(main())
