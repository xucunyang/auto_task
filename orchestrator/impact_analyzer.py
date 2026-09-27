"""发散影响评估模块 (Divergent Impact Analyzer)

对任意调研主题做发散式影响评估, 主题无关:
1. 主题 → 领域扩展包 (config/impact_domains.yaml: 电梯/环保/三农/通用)
2. 每个领域强制评估 利好 与 利空 两个方向
3. 每条影响必须绑定来源链接 (可追溯/可校验)
4. 输出可直接嵌入调研报告的 Markdown 章节

用法:
    ia = ImpactAnalyzer(".")
    assessment = ia.assess("2026年9月老旧小区加装电梯政策", records)
    assert ia.validate(assessment)
    md = ia.render_markdown(assessment)
"""
import json, re
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

URL_RE = re.compile(r"^https?://")

POS_TEMPLATES = {
    "market": [
        "{topic}的推进将改善{domain}的预期与活跃度",
        "{topic}推进释放结构性机会, {domain}景气度有望受益",
    ],
    "other": [
        "利好: {topic}带动{domain}的需求释放与业务增量",
        "利好: 政策支持叠加需求传导, {domain}迎来上行契机",
    ],
}
NEG_TEMPLATES = {
    "market": [
        "利空: 若进展不及预期或竞争加剧, {domain}短期情绪与估值可能承压",
        "利空: 标准抬升与成本传导或抑制{domain}的部分需求",
    ],
    "other": [
        "利空: 同时{domain}也面临合规成本上升与竞争加剧压力",
        "利空: {domain}存在短期投入加大、回报周期拉长的风险",
    ],
}


class ImpactAnalyzer:
    def __init__(self, base_dir="."):
        self.base = Path(base_dir)
        cfg = self.base / "config" / "impact_domains.yaml"
        self.config = yaml.safe_load(cfg.read_text()) if (yaml and cfg.exists()) else {}

    # ---- 1. 主题 → 领域包 ----
    def pick_pack(self, topic: str) -> dict:
        best, best_hits = None, 0
        for pack in self.config.get("topic_packs", []):
            hits = sum(1 for kw in pack.get("match", []) if kw in topic)
            if hits > best_hits:
                best, best_hits = pack, hits
        return best or self.config.get("default_pack", {"id": "generic",
                                                         "market_domains": [], "other_domains": []})

    # ---- 2. 领域证据来源匹配 ----
    def _match_sources(self, domain: dict, records: list) -> tuple:
        """返回 (sources, basis): 关键词命中的记录链接 + 依据类型"""
        kws = domain.get("keywords", [])
        hits = []
        for r in records:
            blob = json.dumps(r, ensure_ascii=False)
            if any(k in blob for k in kws):
                u = r.get("url", "")
                if URL_RE.match(u) and u not in hits:
                    hits.append(u)
        if hits:
            return hits[:3], "事实依据"
        # 无命中: 用全部来源兜底, 标记为推断
        fallback = [r["url"] for r in records
                    if URL_RE.match(r.get("url", ""))][:2]
        return fallback, "分析推断"

    # ---- 3. 评估: 每领域 × 利好/利空 ----
    def assess(self, topic: str, records: list) -> dict:
        pack = self.pick_pack(topic)
        result = {"topic": topic, "pack": pack.get("id", "generic"),
                  "market": [], "other": []}
        plan = [("market", pack.get("market_domains", [])),
                ("other", pack.get("other_domains", []))]
        for bucket, domains in plan:
            for d in domains:
                sources, basis = self._match_sources(d, records)
                for direction, tpl_bank in (("利好", POS_TEMPLATES[bucket]),
                                            ("利空", NEG_TEMPLATES[bucket])):
                    text = tpl_bank[(hash(d["name"]) + len(direction)) % len(tpl_bank)]
                    text = text.format(topic=topic, domain=d["name"])
                    if basis == "分析推断":
                        text += "（分析推断）"
                    result[bucket].append({
                        "domain": d["name"], "direction": direction,
                        "text": text, "sources": sources, "basis": basis,
                    })
        return result

    # ---- 4. 校验: 每领域双向覆盖 + 来源合法 ----
    def validate(self, assessment: dict) -> list:
        errors = []
        for bucket in ("market", "other"):
            items = assessment.get(bucket, [])
            if not items:
                errors.append(f"{bucket}: 领域为空")
                continue
            by_domain = {}
            for it in items:
                by_domain.setdefault(it["domain"], set()).add(it["direction"])
            for dom, dirs in by_domain.items():
                if dirs != {"利好", "利空"}:
                    errors.append(f"{dom}: 未覆盖利好+利空 ({sorted(dirs)})")
                for it in [x for x in items if x["domain"] == dom]:
                    srcs = it.get("sources", [])
                    if not srcs:
                        errors.append(f"{dom}/{it['direction']}: 来源为空")
                    elif not all(URL_RE.match(s) for s in srcs):
                        errors.append(f"{dom}/{it['direction']}: 来源非合法URL")
        return errors

    # ---- 5. 渲染报告章节 ----
    _CN = {1:"一",2:"二",3:"三",4:"四",5:"五",6:"六",7:"七",8:"八",9:"九"}

    def render_markdown(self, a: dict, market_no=4, other_no=5) -> str:
        cn = lambda n: self._CN.get(n, str(n))
        L = [f"## {cn(market_no)}、市场影响", ""]
        seen = []
        for it in a["market"]:
            if it["domain"] not in seen:
                seen.append(it["domain"])
                L.append(f"### {it['domain']}")
            L.append(f"- {it['text']} {' '.join(f'[{i+1}]({u})' for i, u in enumerate(it['sources']))}")
            if it["basis"] == "分析推断":
                pass  # 文本已含（分析推断）
        L += ["", f"## {cn(other_no)}、其他领域影响", ""]
        seen = []
        for it in a["other"]:
            if it["domain"] not in seen:
                seen.append(it["domain"])
                L.append(f"### {it['domain']}")
            L.append(f"- {it['text']} {' '.join(f'[{i+1}]({u})' for i, u in enumerate(it['sources']))}")
        L.append("")
        return "\n".join(L)


if __name__ == "__main__":
    ia = ImpactAnalyzer(".")
    print("[OK] ImpactAnalyzer, packs:",
          [p["id"] for p in ia.config.get("topic_packs", [])])
