"""
Unified CLI Entrypoint for Medical LLM Wiki.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add root directory to sys.path so modules can import cleanly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.collector.collector import SourceCollector
from tools.compiler.compiler import WikiGraph
from tools.linter.linter import WikiLinter
from tools.search.searcher import WikiSearcher


def cmd_status(args):
    collector = SourceCollector(ROOT_DIR)
    graph = WikiGraph(ROOT_DIR)
    graph.load_graph()
    stats = graph.get_stats()
    raw_val = collector.validate_sources()

    print("=" * 65)
    print("  🏥 中国医学权威指南与标准 LLM Wiki 知识库状态概览")
    print("=" * 65)
    print(f"📁 根工作目录: {ROOT_DIR}")
    print(f"📚 原始来源层 (raw/):")
    print(f"  • 已注册指南文献: {raw_val['total_registered']} 部")
    print(f"  • 有效文档完整性: {raw_val['valid_count']} / {raw_val['total_registered']}")
    print(f"🧠 知识图谱层 (wiki/):")
    print(f"  • 总编译页面数:   {stats['total_pages']} 篇")
    print(f"  • 双向链接引用数: {stats['total_links']} 条")
    print(f"  • 图谱连接密度:   {stats['graph_density']}")
    print(f"  • 分类分布明细:   {stats['type_counts']}")
    print(f"  • 孤岛页面数:     {stats['orphan_count']}")
    print("=" * 65)


def cmd_lint(args):
    linter = WikiLinter(ROOT_DIR)
    report = linter.run_all_checks()
    print(linter.format_report(report))
    if not report["is_healthy"]:
        sys.exit(1)


def cmd_index(args):
    searcher = WikiSearcher(ROOT_DIR)
    count = searcher.index_wiki(force=True)
    print(f"✅ 成功索引 {count} 篇知识库词条到 SQLite FTS5 全文索引数据库！")


def cmd_search(args):
    searcher = WikiSearcher(ROOT_DIR)
    searcher.index_wiki()  # Ensure index is up to date
    hits = searcher.search(args.query, limit=args.limit)

    print(f"\n🔍 针对关键词 '{args.query}' 的搜索结果 (共匹配 {len(hits)} 条):")
    print("-" * 65)
    if not hits:
        print("未找到匹配的词条。")
        return

    for i, h in enumerate(hits, 1):
        print(f"[{i}] {h['title']} (类型: {h['type']}) | 路径: wiki/{h['rel_path']}")
        print(f"    摘要: {h['snippet']}")
        print("-" * 65)


def cmd_ask(args):
    searcher = WikiSearcher(ROOT_DIR)
    searcher.index_wiki()
    res = searcher.synthesize_answer(args.question)
    print("\n" + res["answer"] + "\n")


def cmd_serve(args):
    from tools.server.app import run_server
    # Ensure index exists
    searcher = WikiSearcher(ROOT_DIR)
    searcher.index_wiki()
    run_server(port=args.port)


def cmd_cdss(args):
    import json
    from tools.cdss.engine import CdssEngine
    engine = CdssEngine(ROOT_DIR)

    if args.recommend:
        results = engine.search_protocols(args.recommend, limit=args.limit)
        print(f"\n📋 针对临床输入 '{args.recommend}' 召回的权威门诊协议方案 (共 {len(results)} 条):")
        print("=" * 65)
        for r in results:
            print(f"[{r['rank']}] {r['title']} [ICD-10: {r['icd10']}] (类别: {r['category']})")
            print(f"    方案摘要: {r['summary'][:120]}...")
            print("-" * 65)
    elif args.compile:
        compiled = engine.compile_rhn_plan(args.compile)
        if compiled.get("success"):
            print(f"\n✅ 成功编译为 RHN PlanIntent 结构化方案：{compiled['planIntent']['name']}")
            print("=" * 65)
            print("【方案摘要 (Description)】:", compiled["planIntent"]["description"])
            print("【临床处置陈述 (Narrative)】:\n" + compiled["planIntent"]["narrative"][:200] + "...")
            print("【病历模板 (noteTemplateContent)】:")
            for k, v in compiled["planIntent"]["noteTemplateContent"].items():
                print(f"  • {k}: {v[:50]}...")
            print(f"【推荐医嘱条目数 (Items)】: {len(compiled['planIntent']['items'])} 项")
            print(f"【可采纳医嘱草稿数 (Treatment Recommendations)】: {len(compiled['treatmentRecommendations'])} 项")
        else:
            print(f"❌ 编译失败: {compiled.get('error')}")
    elif args.audit:
        profile = {}
        if args.egfr:
            profile["egfr"] = float(args.egfr)
        if args.age:
            profile["age"] = int(args.age)
        if args.pregnant:
            profile["is_pregnant"] = True

        res = engine.audit_prescription(args.meds, profile)
        print(f"\n🛡️  CDSS 处方前置安全核查报告 (审查药品: {', '.join(args.meds)}):")
        print("=" * 65)
        if res["is_safe"] and res["total_alerts"] == 0:
            print("✅ 处方安全核查通过：未检出绝对禁忌证或高危处方瀑布。")
        else:
            status_text = "❌ 存在高危严重禁忌，必须强行阻断！" if not res["is_safe"] else "⚠️  存在用药警戒，建议核对。"
            print(status_text)
            print(f"告警统计: 红色阻断 {res['red_count']} 条，黄色预警 {res['yellow_count']} 条\n")
            for idx, a in enumerate(res["alerts"], 1):
                icon = "🛑" if a["severity"] == "RED" else "⚠️"
                print(f"{icon} [{idx}] 【{a['title']}】 ({a['severity']})")
                print(f"    说明: {a['message']}")
                print(f"    依据: {a.get('guideline', '')}")
                print("-" * 65)
    else:
        # Default list all protocols
        protocols = engine.repo.list_all()
        print(f"\n📚 知识库内置门诊临床决策推荐协议库 (共收录 {len(protocols)} 部国家级规范方案):")
        print("=" * 65)
        for idx, p in enumerate(protocols, 1):
            print(f"[{idx}] {p.protocol_id} | {p.title} [ICD-10: {p.icd10}] ({p.category})")
        print("-" * 65)


def cmd_rename_page(args):
    graph = WikiGraph(ROOT_DIR)
    graph.load_graph()
    res = graph.rename_page(args.old_id, args.new_id)
    if not res.get("success"):
        print(f"❌ 重命名失败: {res.get('error')}")
        sys.exit(1)

    print("=" * 65)
    print("  🔄 知识库词条重构与双向引用批量安全更新完成")
    print("=" * 65)
    print(f"原词条 ID:     {res['old_id']}")
    print(f"新词条 ID:     {res['new_id']}")
    print(f"原物理文件:   wiki/{res['old_path']}")
    print(f"新物理文件:   wiki/{res['new_path']}")
    print(f"受影响词条数: {res['affected_files_count']} 篇")
    if res["affected_files"]:
        print("已自动同步更新以下文件中的 WikiLink 引用:")
        for af in res["affected_files"][:10]:
            print(f"  • wiki/{af}")
        if len(res["affected_files"]) > 10:
            print(f"  ... 以及其他 {len(res['affected_files']) - 10} 篇文件")

    # Run lint to ensure zero broken links
    linter = WikiLinter(ROOT_DIR)
    rep = linter.run_all_checks()
    if rep["is_healthy"]:
        print("✅ 全库一致性体检通过: 0 断链、0 孤岛，知识图谱拓扑完整！")
    else:
        print(f"⚠️ 警告: 重命名后存在 {len(rep['broken_links'])} 处断链，请人工检查！")


def main():
    parser = argparse.ArgumentParser(
        description="Medical LLM Wiki: 中国医学权威指南与标准本地知识库管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # status
    subparsers.add_parser("status", help="查看知识库整体状态与统计指标")

    # lint
    subparsers.add_parser("lint", help="对知识库执行断链、孤岛与模式健康体检")

    # index
    subparsers.add_parser("index", help="构建或重建 SQLite FTS5 本地全文索引")

    # rename-page
    p_rename = subparsers.add_parser("rename-page", help="安全重命名知识库词条并批量重构全库 WikiLink 引用与索引")
    p_rename.add_argument("old_id", help="原词条 ID (文件名 stem)")
    p_rename.add_argument("new_id", help="新词条 ID (新文件名 stem)")

    # search
    p_search = subparsers.add_parser("search", help="对知识库执行全文搜索与关键词高亮匹配")
    p_search.add_argument("query", help="搜索查询词")
    p_search.add_argument("-n", "--limit", type=int, default=8, help="最多返回结果数")

    # ask
    p_ask = subparsers.add_parser("ask", help="基于本地权威指南知识库进行多文档综合研判与问答")
    p_ask.add_argument("question", help="临床诊疗与用药问题")

    # serve
    p_serve = subparsers.add_parser("serve", help="启动本地知识图谱与指南交互式 Web 阅读服务")
    p_serve.add_argument("-p", "--port", type=int, default=8080, help="服务端口 (默认 8080)")

    # cdss
    p_cdss = subparsers.add_parser("cdss", help="门诊医生站 AI 方案推荐、编译与 CDSS 安全审查")
    p_cdss.add_argument("--recommend", help="根据主诉或诊断推荐门诊治疗方案协议")
    p_cdss.add_argument("--compile", help="编译为 RHN 门诊医生站 PlanIntent 格式 JSON")
    p_cdss.add_argument("--audit", action="store_true", help="对拟开处方进行前置安全审查")
    p_cdss.add_argument("--meds", nargs="+", default=[], help="拟开药品清单")
    p_cdss.add_argument("--egfr", type=float, help="患者 eGFR 估算肾小球滤过率")
    p_cdss.add_argument("--age", type=int, help="患者年龄")
    p_cdss.add_argument("--pregnant", action="store_true", help="是否妊娠期")
    p_cdss.add_argument("-n", "--limit", type=int, default=5, help="最多推荐方案数")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "status": cmd_status,
        "lint": cmd_lint,
        "index": cmd_index,
        "rename-page": cmd_rename_page,
        "search": cmd_search,
        "ask": cmd_ask,
        "serve": cmd_serve,
        "cdss": cmd_cdss,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
