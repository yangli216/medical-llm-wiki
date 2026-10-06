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

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "status": cmd_status,
        "lint": cmd_lint,
        "index": cmd_index,
        "search": cmd_search,
        "ask": cmd_ask,
        "serve": cmd_serve,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
