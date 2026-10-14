# 原文溯源与专业审核

当前遗留内容均保持待审核。`raw/docs/` 的整理摘要不能作为官方原文证明；页面标题中的“官方核准”也不能替代原文件、来源核验和专业审校。

## 取得并归档原文

从发布机构、期刊或药品批准持有人的正式发布渠道取得对应版本的原始 PDF 或全文。药品需核对具体制剂、生产企业、批准文号及修订日期，不能用“说明书汇编”摘要代替单品种核准原件。

```bash
python3 -m tools.cli archive-source SRC-NHC-NUT-2024-01 /绝对路径/原文.pdf --official-url https://官方发布页
```

该命令保留已有整理摘要，新增 `raw/originals/` 归档，记录采集时间和 SHA-256，来源核验状态仍为 pending。已有原件不得覆盖，修订版应登记新 ID。Web 导入也会保存上传 PDF 的原始字节；错误 PDF、无效来源 ID 和重复来源会被拒绝。

`official_url` 记录待核验的发布地址；`content_sha256` 对应整理文本，`original_sha256` 对应原始文件。两者不可互相替代。URL 不存在时留空，不能填写猜测地址。

## 登记已完成的来源核验

人工核对机构、题名、版本和原文件后，创建以下 JSON。审核人必须填写实际核验者；哈希从该来源元数据读取。

```json
{
  "kind": "source",
  "subject": "SRC-NHC-NUT-2024-01",
  "review": {
    "decision": "approved",
    "reviewer": "实际核验者姓名",
    "reviewed_at": "2026-10-13",
    "artifact_sha256": "原始文件的完整 SHA-256"
  }
}
```

```bash
python3 -m tools.cli record-review /绝对路径/来源核验记录.json
```

归档文件不存在、哈希不匹配或缺少官方 URL 时无法登记通过。

## 登记已完成的专业审校

由医师或药师核对诊断切点、适应症、剂量、肾功能指标、禁忌、人群范围、药物相互作用以及证据等级。需要区别 eGFR 与 CrCl、不同适应症和制剂版本，并为每项关键规则保留原文定位。

```json
{
  "kind": "page",
  "subject": "页面文件名（不含 .md）",
  "review": {
    "status": "approved",
    "reviewer": "实际审校医师或药师姓名",
    "reviewer_role": "pharmacist",
    "reviewed_at": "2026-10-13",
    "content_sha256": "当前页面或规则的内容 SHA-256",
    "evidence_refs": [
      {
        "source_id": "已核验的来源 ID",
        "original_sha256": "对应原始文件的 SHA-256",
        "locator": "第 12 页，第 3.2 节或说明书【禁忌】",
        "quote": "审校者逐字核对的原文摘录"
      }
    ]
  }
}
```

规则记录使用 `kind: rule` 和规则 ID；页面记录使用 `kind: page` 和文件 stem。内容哈希可以通过 Python 中的 `tools.quality.page_digest(WikiGraph(root).pages[page_id])` 或 `rule_digest(rule)` 取得。审核记录必须覆盖该页面/规则的全部关键临床内容，引用数量不能代替审校责任。

用同一 `record-review` 命令登记。角色仅接受 `physician` 或 `pharmacist`。没有完成真实审校不得填写 approved。页面通过后设为 verified；改变正文或临床元数据会使旧审核记录失效，API 会重新显示 pending。

这些是本地人工审核记录，工具检查字段、内容哈希、引用来源和原文件绑定，不认证审核人的执业身份，也不自动验证 PDF 中每条摘录的临床含义。用于正式多人流程时，须接入机构的身份认证、审核权限和审计记录。

## 检查与采用

```bash
python3 -m tools.cli lint
python3 -m tools.cli audit-quality
python3 -m tools.cli audit-quality --strict
python3 -m tools.cli sync-readme --check
```

lint 校验结构和审核记录一致性；`audit-quality --strict` 在来源核验或专业审核尚未完成时返回退出码 1。`/api/quality` 同步暴露归档、来源核验和专业审核计数。临床 REST 响应中的 `clinicalReview.requiresClinicianReview` 表示仍需专业审核；处方规则的 PASS 不等于临床安全认证。

临床页面范围为疾病、药物、概念、综合、症状、协议、说明书整理页和来源导读；索引、操作日志与机构介绍不计入临床审核分母。

当前优化没有代替医师/药师完成审校，也没有把遗留摘要改写为官方原件。取得原文与完成专业审校后，才能逐条消除质量缺口。
