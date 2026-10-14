"""Keep the README inventory reproducible rather than hand-maintained."""

from pathlib import Path

from tools.quality import audit_quality, inventory

START = "<!-- inventory:start -->"
END = "<!-- inventory:end -->"


def inventory_markdown(root: Path) -> str:
    stats = inventory(root)
    quality = audit_quality(root)
    types = stats["type_counts"]
    rules = stats["rules_by_file"]
    rows = [
        ("注册来源（包含指南、共识、教材及汇编）", stats["registered_sources"]),
        ("Wiki 页面（包含 index/log）", stats["total_pages"]),
        ("页面出向引用（每页去重）", stats["total_links"]),
        ("门诊协议", types.get("protocol", 0)),
        ("药品说明书整理页", types.get("drug_insert", 0)),
        ("疾病 / 药物 / 概念 / 综合 / 症状", " / ".join(str(types.get(k, 0)) for k in ("disease", "drug", "concept", "synthesis", "symptom"))),
        ("临床规则 / 说明书规则", f"{rules.get('clinical_safety_rules', 0)} / {rules.get('monograph_rules', 0)}"),
        ("测试方法（静态计数，非本次通过数）", stats["test_methods"]),
        ("已归档原始文件 / 已核验来源", f"{quality['originalsArchived']} / {quality['provenanceVerified']}"),
        ("有效临床审核：页面 / 规则", f"{quality['clinicallyReviewedPages']} / {quality['clinicallyReviewedRules']}"),
    ]
    table = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return f"{START}\n| 资产 | 当前数量 |\n| :--- | ---: |\n{table}\n{END}"


def sync_readme(root: Path, check: bool = False) -> bool:
    path = root / "README.md"
    text = path.read_text(encoding="utf-8")
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    updated = before + inventory_markdown(root) + after
    matches = updated == text
    if not check and not matches:
        path.write_text(updated, encoding="utf-8")
    return matches
