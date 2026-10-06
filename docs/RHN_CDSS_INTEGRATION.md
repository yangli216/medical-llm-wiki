# RHN 门诊医生站 AI 治疗方案推荐与 CDSS 知识赋能集成指南

本文档专门面向 **RHN 智慧医疗系统**（`/Users/yangli/Documents/rhn`）的研发团队，说明如何利用当前 **Medical LLM Wiki** 沉淀的中国国家级权威医学指南知识库、门诊临床决策协议库（Protocols）及 CDSS 规则拦截引擎，深度赋能 RHN 门诊医生站的 AI 治疗方案推荐。

---

## 1. 赋能体系全景图

```
┌────────────────────────────────────────────────────────────────────────┐
│                        RHN 门诊医生站 (Outpatient)                     │
│  - 门诊接诊病历书写 (ClinicalRecordSheetView.tsx)                      │
│  - AI 方案生成与草稿审查弹窗 (AiPlanTemplateDraftModal.tsx)             │
│  - 处置与医嘱推荐面板 (ClinicalAiAssistantPanel.tsx)                    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (HTTP REST / RAG 上下文注入)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Medical LLM Wiki CDSS 知识引擎服务                   │
│                    (http://127.0.0.1:8080/api/cdss/...)                │
│                                                                        │
│  ┌───────────────────────┐  ┌─────────────────┐  ┌──────────────────┐ │
│  │ 12 套门诊标准化推荐协议 │  │  RHN 方案编译器 │  │ CDSS 处方前置拦截│ │
│  │  (ICD-10 对齐方案)    │  │   (PlanIntent)  │  │   (Safety Rules) │ │
│  └───────────────────────┘  └─────────────────┘  └──────────────────┘ │
│                                    │                                   │
│  ┌─────────────────────────────────┴─────────────────────────────────┐ │
│  │ 22 部国家权威医学指南 + 111 篇互联图谱 (高血压/糖尿病/慢阻肺/老年共病)│ │
│  └───────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据契约与 RHN 字段无缝映射

本知识库的推荐协议和输出结构在设计阶段已与 RHN 后端及前端数据结构实现 **100% 契约级对齐**：

### A. 方案编译输出映射 (`ClinicalAiModelGateway.PlanIntent`)
| RHN PlanIntent 字段 | 本知识库提供的数据源 | 规范要求与说明 |
| :--- | :--- | :--- |
| `name` | `prot.title` | 简短、规范的门诊诊疗方案名称（如“原发性高血压门诊规范诊疗方案”） |
| `description` | `prot.description` | 一句话方案摘要（附带 ICD-10 编码） |
| `narrative` | `prot.narrative` | 结构化生成的临床决策叙述（覆盖诊断、适用条件、用药、检验、宣教等） |
| `noteTemplateContent` | `prot.note_template` | **门诊病历 6 段范文**（无任何占位符，严禁输出虚假生命体征数值）：<br>• `chiefComplaint` (典型主诉短语)<br>• `presentIllness` (诱因/演变/关键阴性鉴别/一般情况)<br>• `medicalHistory` (既往史标准全阴性)<br>• `physicalExam` (专科查体阴性指征，杜绝生命体征假数值)<br>• `healthEducation` (2~4 条针对性门诊宣教)<br>• `followUp` (常规复诊时限与危象预警) |
| `items` | `prot.items` | 医嘱条目数组，每项包含 `kind`, `name`, `sourceQuote`, `origin`, `details` |

### B. 结构化医嘱草稿映射 (`ClinicalAiTreatmentRecommendation`)
直接可被医生站前端采纳进入处方/处置草稿区：
```json
{
  "type": "MEDICATION",
  "catalogItemId": "STD-PROT-HTN-001-3",
  "code": "I10-MED-3",
  "name": "苯磺酸氨氯地平片",
  "specification": "5mg/片",
  "rationale": "常规用法：每次 5mg 口服 qd 疗程 30天；适用条件：原发性高血压 1~2 级起始降压；目的：平稳持久降压，降低卒中风险；不建议常规使用：严重低血压、重度主动脉瓣狭窄禁用。",
  "orderDraft": {
    "routeCode": "PO",
    "frequencyCode": "QD",
    "doseValue": 5.0,
    "doseUnit": "mg",
    "durationValue": 30,
    "quantity": 1,
    "instruction": "常规用法：每次 5mg 口服 qd 疗程 30天"
  }
}
```

---

## 3. 集成接入方式

### 方式一：HTTP REST 接口实时集成（推荐）

知识库内置服务支持轻量级 HTTP API，RHN 后端可在 Spring Boot 中通过 `RestClient` 或 `WebClient` 直接请求：

#### 1. 方案一键智能编译 (`POST /api/cdss/compile-rhn-plan`)
- **请求体**:
```json
{
  "input": "原发性高血压初诊"
}
```
- **响应体**:
```json
{
  "success": true,
  "protocolId": "PROT-HTN-001",
  "scopeType": "HOSPITAL",
  "sourceType": "AI_INPUT",
  "planIntent": {
    "name": "原发性高血压门诊规范诊疗方案",
    "description": "依据国家权威指南建立的门诊标准化诊疗协议（ICD-10: I10）",
    "narrative": "诊断：原发性高血压 [I10]...",
    "noteTemplateContent": {
      "chiefComplaint": "间断头晕、头胀伴后枕部发紧 2 周，测血压升高 3 天。",
      "presentIllness": "患者诉 2 周前劳累后出现间断头晕...",
      "medicalHistory": "既往体健，否认冠心病、糖尿病...",
      "physicalExam": "神志清楚，精神可...",
      "healthEducation": "1. 低盐低脂平衡膳食...",
      "followUp": "用药后 2 至 4 周首次门诊复诊..."
    },
    "items": [
      {
        "kind": "DIAGNOSIS",
        "name": "原发性高血压 [I10]",
        "sourceQuote": "原发性高血压门诊规范诊疗方案",
        "origin": "SUGGESTED",
        "details": "门诊标准 ICD-10 诊断，依据诊室血压三次非同日测量 ≥140/90 mmHg 确诊。"
      },
      {
        "kind": "MEDICATION",
        "name": "苯磺酸氨氯地平片",
        "sourceQuote": "原发性高血压门诊规范诊疗方案",
        "origin": "SUGGESTED",
        "details": "常规用法：每次 5mg 口服 qd 疗程 30天；适用条件：原发性高血压 1~2 级起始降压；目的：平稳持久降压，降低卒中风险；不建议常规使用：严重低血压、重度主动脉瓣狭窄禁用。"
      }
    ]
  },
  "candidate": { ... },
  "treatmentRecommendations": [ ... ]
}
```

#### 2. 处方前置安全核查与拦截 (`POST /api/cdss/audit`)
门诊医生开立处方时，RHN 后端调用此接口进行秒级禁忌与处方瀑布核查：
- **请求体**:
```json
{
  "medications": ["盐酸二甲双胍片 0.5g", "依那普利片 10mg", "氯沙坦钾片 50mg"],
  "patient": {
    "age": 68,
    "egfr": 26.5,
    "is_pregnant": false
  }
}
```
- **响应体**:
```json
{
  "is_safe": false,
  "total_alerts": 2,
  "red_count": 2,
  "yellow_count": 0,
  "alerts": [
    {
      "ruleId": "RULE-SAFETY-RAS-DUAL",
      "severity": "RED",
      "title": "严禁双重 RAS 轴阻断",
      "message": "严禁 ACEI、ARB 或 ARNI 重叠联合使用。双重阻断不增加临床获益，反而急剧增加急性肾损伤（AKI）和恶性高钾血症风险！",
      "guideline": "《中国高血压防治指南（2024年修订版）》"
    },
    {
      "ruleId": "RULE-SAFETY-METFORMIN-RENAL",
      "severity": "RED",
      "title": "重度肾功能不全禁用二甲双胍",
      "message": "患者 eGFR = 26.5 ml/min/1.73m² (< 30)，二甲双胍蓄积导致致死性乳酸酸中毒风险极高，绝对禁用！",
      "guideline": "《中国2型糖尿病防治指南（2024版）》"
    }
  ]
}
```

---

## 4. CDSS 核心安全核查规则一览

| 规则代码 | 规则名称 | 严重级别 | 触发条件与临床依据 |
| :--- | :--- | :--- | :--- |
| `RULE-SAFETY-RAS-DUAL` | 严禁双重 RAS 阻断 | **RED (强行阻断)** | 同时开具 ACEI（普利类）与 ARB（沙坦类）或 ARNI；增加急性肾衰风险。 |
| `RULE-SAFETY-PREGNANCY-RAS`| 妊娠期禁用 RAS 抑制剂 | **RED (强行阻断)** | 妊娠期女性开具普利/沙坦类药物；胚胎致畸毒性。 |
| `RULE-SAFETY-METFORMIN-RENAL`| 重度肾衰禁用二甲双胍 | **RED (强行阻断)** | 患者 eGFR < 30 ml/min/1.73m² 开具二甲双胍；致死性乳酸酸中毒。 |
| `RULE-SAFETY-METFORMIN-WARN` | 中度肾衰二甲双胍减量预警 | **YELLOW (预警)** | 患者 eGFR 30~44 ml/min/1.73m²；日最大剂量限制 1000mg。 |
| `RULE-SAFETY-NITRATE-PDE5` | 硝酸酯类合用 PDE-5 抑制剂 | **RED (强行阻断)** | 硝酸甘油合用西地那非(24h内)或他达拉非(48h内)；顽固性致死低血压。 |
| `RULE-CASCADE-CCB-EDEMA` | 处方瀑布：CCB水肿误用利尿剂 | **YELLOW (预警)** | 氨氯地平/硝苯地平合用呋塞米等排钾利尿剂；提示水肿机制非水钠潴留。 |
| `RULE-SAFETY-DUAL-NSAIDS` | 严禁重复口服多种 NSAIDs | **RED (强行阻断)** | 同时开具布洛芬与双氯芬酸/塞来昔布等；增加消化道穿孔大出血风险。 |
| `RULE-SAFETY-MONTMORILLONITE`| 蒙脱石散服药时间间隔 | **YELLOW (预警)** | 蒙脱石散与口服抗生素或微生态活菌制剂合用；必须间隔 2 小时以上。 |
| `RULE-PIM-ELDERLY-BZD` | 老年人潜在不适当用药(PIM) | **RED (强行阻断)** | 年龄 ≥65 岁老年人长期开具地西泮/安定等长半衰期镇静剂；高跌倒与骨折风险。 |

---

## 5. 本地开发与测试支持

开发人员可在本项目终端中直接执行以下命令进行调试与验证：

```bash
# 1. 方案推荐检索
python3 tools/cli.py cdss --recommend "高血压初诊"

# 2. 导出 RHN PlanIntent 方案 JSON
python3 tools/cli.py cdss --compile "PROT-T2DM-002"

# 3. 处方安全审计
python3 tools/cli.py cdss --audit --meds "二甲双胍" "依那普利" "氯沙坦" --egfr 25

# 4. 启动后台 API 服务 (默认端口 8080)
python3 tools/cli.py serve --port 8080
```
