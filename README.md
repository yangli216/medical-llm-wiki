# Medical LLM Wiki & CDSS Engine

本项目提供本地医学资料整理、Wiki 双向链接、全文检索、门诊协议编译和确定性处方规则检查。支持 OpenAI 兼容接口与 REST API，供 RHN 等系统集成。

目前的知识内容以人工或模型整理的摘要为主。注册来源、原文归档、来源核验和医师/药师临床审核是不同状态；页面、规则与 GRADE 字段的存在不代表已经完成专业核验。药品页面为整理稿，不能凭页面标题认定它是官方核准说明书原件。

## 当前资产统计

下表由代码生成，可用 `python3 -m tools.cli sync-readme` 更新，用 `--check` 检查是否过期。链接数采用每页去重的出向引用口径，不代表互相回链的链接对。

<!-- inventory:start -->
| 资产 | 当前数量 |
| :--- | ---: |
| 注册来源（包含指南、共识、教材及汇编） | 66 |
| Wiki 页面（包含 index/log） | 479 |
| 页面出向引用（每页去重） | 3720 |
| 门诊协议 | 51 |
| 药品说明书整理页 | 142 |
| 疾病 / 药物 / 概念 / 综合 / 症状 | 57 / 41 / 54 / 14 / 12 |
| 临床检验 / 医技检查 | 19 / 12 |
| 临床规则 / 说明书规则 | 46 / 64 |
| 测试方法（静态计数，非本次通过数） | 129 |
| 已归档原始文件 / 已核验来源 | 26 / 0 |
| 有效临床审核：页面 / 规则 | 0 / 0 |
<!-- inventory:end -->

## 本地启动与验证

```bash
python3 -m pip install -r requirements.txt
python3 -m tools.cli serve --port 8788
```

访问 [http://127.0.0.1:8788](http://127.0.0.1:8788)。默认端口仍为 8080；若 RHN 已占用该端口，可使用 8788。

```bash
python3 -m tools.cli inventory          # 实时资产统计
python3 -m tools.cli lint               # 链接、结构、规则来源 ID、审核记录一致性
python3 -m tools.cli audit-quality      # 原文归档、来源核验、临床审核缺口
python3 -m tools.cli audit-quality --strict  # 缺口未补齐时退出码为 1
python3 -m tools.cli audit-authority    # 字段覆盖及来源/审核状态；不提供临床认证评分
python3 -m tools.cli sync-readme
python3 -m tools.cli sync-readme --check
python3 -m unittest discover -s tests
```

测试验证软件行为和回归场景，通过数须以当次运行结果为准；不能据此推断所有内容已临床审核。

## 来源与审核流程

- `raw/docs/`：整理摘要或 PDF 提取文本，用 `content_kind` 区分。
- `raw/originals/`：取得的原始文件，登记官方 URL、采集时间、文件路径及 SHA-256。
- `raw/metadata.json`：来源登记和来源核验记录。空值表示尚未取得信息。
- `wiki/`：编译后的 Markdown 页面；新页面默认 `draft`。
- `reviews/clinical_reviews.json`：页面专业审核记录；规则审核存于各规则的 `clinical_review` 字段。

导入 PDF 会保存原始字节并记录哈希，但不会自动宣称发布机构或临床内容已经核验。已有来源 ID 不允许覆盖；修订版使用新的 ID。已取得的原文可通过 `archive-source` 挂接到现有来源，再登记实际完成的来源核验与专业审核。

操作格式见 [知识质量与审核指南](docs/KNOWLEDGE_QUALITY.md)，入库规范见 [INGEST_GUIDE](schema/INGEST_GUIDE.md)。

首轮公开原件采集已归档10个来源（8份PDF、1份DOC、1份HTML），版本差异、转载渠道和完整性限制见 [采集报告](docs/PUBLIC_SOURCE_COLLECTION_2026-10-13.md)。骨质疏松再刊版省略部分参考文献，HTML外链资产未全部打包；归档数量不是全文完整性或审核通过数量。

第二轮新增10个来源（8份PDF、2份HTML），累计20/61个已有归档。整期期刊中的文章定位、转载水印、书目校正与未解决的版本歧义见 [第二轮报告](docs/PUBLIC_SOURCE_COLLECTION_2026-10-14.md)；未确认出版社字节一致性或再分发授权。

第三轮保存7份文件（5份PDF含1份补充件、2份HTML），新增归档6个来源并独立登记4个新版本/系列，累计26/65个来源已有主归档。见 [第三轮报告](docs/PUBLIC_SOURCE_COLLECTION_2026-10-14_ROUND_03.md) 与 [版本时效核查](docs/SOURCE_VERSION_REVIEW_2026-10-14.md)：正式换版、勘误、修订计划与专题更新分开记录，“未核验到新版”不是绝对最新保证。

## 服务结构与集成

```text
tools/server/app.py          HTTP 路由、静态资源与响应
tools/server/ingestion.py    PDF 解析和来源导入
tools/server/knowledge_api.py 知识文档、检索与证据链接口
tools/server/chat_api.py     OpenAI 兼容协议及 SSE
tools/server/rendering.py    CommonMark 渲染与 WikiLink/callout 扩展
tools/server/static/         HTML、CSS、JavaScript
tools/cdss/                  协议编译、规则判断与量表计算
tools/quality.py             原文、引用及审核一致性检查
```

运行态指标由 `GET /api/inventory` 提供，质量状态由 `GET /api/quality` 提供。临床 REST 响应增加 `clinicalReview.requiresClinicianReview`；`PASS` / `canPrescribe` 仅表示当前规则计算结果，下游采用时须同时处理审核状态。

对接 OpenAI 协议时使用 `http://127.0.0.1:8788/v1/chat/completions`；检索接口为 `http://127.0.0.1:8788/api/knowledge/search`。完整协议见 [RHN 对接文档](docs/RHN_CDSS_INTEGRATION.md)。
