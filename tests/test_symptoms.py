import json
import re
import threading
import time
import unittest
import urllib.request
import urllib.parse
from pathlib import Path
from tools.linter.authority_auditor import AuthorityAuditor
from tools.linter.linter import WikiLinter
from tools.server.app import run_server


class TestSymptomDifferentialTrees(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.symptoms_dir = cls.root_dir / "wiki" / "symptoms"

        # Start a local test server
        cls.port = 8798
        cls.server_thread = threading.Thread(
            target=run_server,
            kwargs={"port": cls.port},
            daemon=True
        )
        cls.server_thread.start()
        time.sleep(1.0)

    def test_symptoms_files_exist_and_complete(self):
        """测试 12 套门诊高频核心症状鉴别树全部存在且符合规范"""
        self.assertTrue(self.symptoms_dir.exists())
        files = list(self.symptoms_dir.glob("*.md"))
        self.assertGreaterEqual(len(files), 12, "必须收录不少于 12 套核心症状鉴别树")

        expected_symptoms = [
            "急性腹痛鉴别诊断",
            "胸痛鉴别诊断",
            "头痛鉴别诊断",
            "发热鉴别诊断",
            "咳嗽与咳痰鉴别诊断",
            "呼吸困难鉴别诊断",
            "头晕与眩晕鉴别诊断",
            "急性腹泻鉴别诊断",
            "恶心与呕吐鉴别诊断",
            "便血与黑便鉴别诊断",
            "心悸鉴别诊断",
            "血尿鉴别诊断",
        ]
        file_stems = [f.stem for f in files]
        for exp in expected_symptoms:
            self.assertIn(exp, file_stems, f"缺少关键症状鉴别树: {exp}")

    def test_symptoms_pmph_and_red_flags_integrity(self):
        """测试每篇症状鉴别树均锚定人卫版《诊断学》国家标准并包含致死红旗征排查"""
        for f in self.symptoms_dir.glob("*.md"):
            content = f.read_text(encoding="utf-8")
            self.assertIn("SRC-PMPH-DIAG-2024-01", content, f"{f.name} 必须溯源至人卫版规划教材 SRC-PMPH-DIAG-2024-01")
            self.assertTrue(
                "红旗征" in content or "Red Flags" in content,
                f"{f.name} 必须包含急危重症致命红旗征强制排雷"
            )
            self.assertTrue(
                "type: symptom" in content,
                f"{f.name} Frontmatter type 必须为 symptom"
            )
            # 必须包含对至少 1 个疾病实体的双向链接 [[疾病]]
            links = re.findall(r"\[\[([^\]]+)\]\]", content)
            self.assertGreaterEqual(len(links), 2, f"{f.name} 必须与下游疾病实体建立双向拓扑关联")

    def test_linter_zero_broken_links_and_orphans(self):
        """验证全库 Linter 静态体检无孤岛、无断链"""
        linter = WikiLinter(self.root_dir)
        report = linter.run_all_checks()
        self.assertTrue(report["is_healthy"], f"发现 Linter 异常: {report['broken_links']}, {report['orphans']}")
        self.assertEqual(report["broken_link_count"], 0)
        self.assertEqual(report["orphan_count"], 0)
        self.assertEqual(report["stats"]["type_counts"].get("symptom"), 12)

    def test_authority_auditor_symptom_dimension(self):
        """测试权威性审计引擎对症状学鉴别树的审计打分"""
        auditor = AuthorityAuditor(self.root_dir)
        res = auditor.audit()
        sym = res["symptoms"]
        self.assertGreaterEqual(sym["totalSymptoms"], 12)
        self.assertEqual(sym["pmphStandardRatio"], 1.0)
        self.assertEqual(sym["redFlagsCoverageRatio"], 1.0)
        self.assertEqual(sym["diseaseLinkedRatio"], 1.0)
        self.assertEqual(res["grade"], "未完成来源核验与临床审核")
        self.assertFalse(res["quality"]["clinicalReady"])

    def test_server_api_symptoms_list_and_search(self):
        """测试 HTTP API /api/symptoms 列表与搜索"""
        # 1. 获取全量症状列表
        url = f"http://127.0.0.1:{self.port}/api/symptoms"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertGreaterEqual(data["total"], 12)
            self.assertTrue(any(s["title"] == "急性腹痛鉴别诊断" for s in data["symptoms"]))

        # 2. 关键词检索
        search_url = f"http://127.0.0.1:{self.port}/api/symptoms?q=" + urllib.parse.quote("腹痛")
        with urllib.request.urlopen(search_url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertGreaterEqual(data["total"], 1)
            titles = [s["title"] for s in data["symptoms"]]
            self.assertIn("急性腹痛鉴别诊断", titles)

    def test_server_api_symptom_detail(self):
        """测试 HTTP API /api/symptoms/{id} 详情及 HTML 渲染"""
        url = f"http://127.0.0.1:{self.port}/api/symptoms/" + urllib.parse.quote("急性腹痛鉴别诊断")
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["id"], "急性腹痛鉴别诊断")
            self.assertIn("红旗征", data["rawText"])
            self.assertIn("急性阑尾炎", data["rawText"])
            self.assertIn("<h1", data["html"])


if __name__ == "__main__":
    unittest.main()
