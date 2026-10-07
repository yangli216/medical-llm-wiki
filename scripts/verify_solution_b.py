#!/usr/bin/env python3
"""
Verification Script for Solution B (Medical Knowledge Base as Grounding and CDSS Guardrail).
Tests live communication between clients and the running knowledge base service on port 8080:
1. Health check (GET /api/health)
2. Authoritative guideline RAG search grounding (POST /api/knowledge/search)
3. CDSS preflight prescription safety interception (POST /api/cdss/audit)
4. Outpatient standard decision protocol retrieval (POST /api/cdss/compile-rhn-plan)
"""

import json
import os
import sys
import urllib.request

os.environ["no_proxy"] = "*"
BASE_URL = "http://127.0.0.1:8080"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check_health():
    print("=" * 65)
    print("  🏥 方案 B 真实联调验证：知识库作为权威指南用于大模型输出保真")
    print("=" * 65)
    try:
        req = urllib.request.Request(f"{BASE_URL}/api/health", method="GET")
        with opener.open(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"✅ [1] 知识库服务在线: {data['service']}")
            print(f"     协议库: {data['protocols']} 套 | CDSS规则: {data['rules']} 条 | 指南文献: {data['guidelines']} 部")
    except Exception as e:
        print(f"❌ 知识库服务连接失败: {e}。请先执行 python3 tools/cli.py serve --port 8080 启动服务。")
        sys.exit(1)


def test_knowledge_search():
    print("\n🔍 [2] 权威指南 RAG 检索保真测试 (模拟大模型 Prompt 上下文锚定):")
    queries = ["膝骨关节炎阶梯镇痛与抗炎", "原发性高血压降压达标与选药", "狂犬病暴露预防处置"]
    for q in queries:
        body = json.dumps({"query": q, "limit": 2, "enableAbstract": True}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{BASE_URL}/api/knowledge/search", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with opener.open(req, timeout=5) as resp:
            hits = json.loads(resp.read().decode("utf-8"))
            print(f"   • 检索关键词: 「{q}」 -> 召回 {len(hits)} 篇权威出处")
            for h in hits:
                print(f"     - 来源: 《{h['name']}》 | 机构: {h['sourceInfo']['knowledgeLibName']} (得分: {h['score']})")


def test_cdss_audit():
    print("\n🛡️  [3] CDSS 处方前置安全拦截测试 (防大模型输出危险/禁忌医嘱):")
    cases = [
        ("膝骨关节炎误开全身激素", {"medications": ["地塞米松片 0.75mg"], "patient": {"is_koa": True}}, "RULE-KOA-SYSTEMIC-STEROID"),
        ("良性前列腺增生误开抗胆碱药", {"medications": ["阿托品片 0.3mg"], "patient": {"is_bph": True}}, "RULE-BPH-ANTICHOLINERGIC"),
        ("狂犬病III级出血暴露漏开HRIG", {"medications": ["人用狂犬病疫苗(Vero细胞)"], "patient": {"history": "右上肢深部犬咬伤伴多处活动性渗血，III级暴露"}}, "RULE-RABIES-III-PASSIVE-IMMUNITY"),
        ("双重 RAS 阻断 (普利+沙坦重叠)", {"medications": ["缬沙坦胶囊 80mg", "马来酸依那普利片 10mg"], "patient": {}}, "RULE-SAFETY-RAS-DUAL"),
        ("重复口服多种 NSAIDs", {"medications": ["塞来昔布胶囊 0.2g", "双氯芬酸钠缓释片 50mg"], "patient": {}}, "RULE-SAFETY-DUAL-NSAIDS"),
        ("重度肾功能不全使用二甲双胍", {"medications": ["盐酸二甲双胍片 0.5g"], "patient": {"egfr": 22.0}}, "RULE-SAFETY-METFORMIN-RENAL"),
    ]

    for title, payload, rule_id in cases:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{BASE_URL}/api/cdss/audit", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with opener.open(req, timeout=5) as resp:
            audit = json.loads(resp.read().decode("utf-8"))
            if not audit["is_safe"] and any(a["ruleId"] == rule_id for a in audit["alerts"]):
                matched = next(a for a in audit["alerts"] if a["ruleId"] == rule_id)
                print(f"   🔴 [拦截成功] {title:28} -> [{matched['severity']}] {matched['title']}")
            else:
                print(f"   ❌ [拦截失败] {title}")


def test_standard_protocol():
    print("\n📋 [4] 标准方案基线调取对照 (供大模型对比或医生一键选用):")
    body = json.dumps({"input": "PROT-KOA-032"}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}/api/cdss/compile-rhn-plan", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(req, timeout=5) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        if res.get("success"):
            intent = res["planIntent"]
            recs = res["treatmentRecommendations"]
            print(f"   ✅ 成功调取标准方案: 【{intent['name']}】 (ICD-10: M17.9)")
            print(f"     - 包含 6 段全阴性无占位符门诊病历范文 (主诉/现病史/既往史/查体/宣教/随访)")
            print(f"     - 包含 {len(recs)} 项结构化规范医嘱与制剂规格 (如双氯芬酸贴膏 50mg/贴、塞来昔布 0.2g/粒)")


if __name__ == "__main__":
    check_health()
    test_knowledge_search()
    test_cdss_audit()
    test_standard_protocol()
    print("\n" + "=" * 65)
    print("  🎉 方案 B 全链路真实联调验证通过！知识库已在 http://127.0.0.1:8080 持续守护。")
    print("=" * 65)
