# RHN 门诊医生站 AI 治疗方案推荐与 CDSS 知识赋能集成指南

本文档面向 **RHN 智慧门诊医生站**（`/Users/yangli/Documents/rhn`）开发团队，阐述如何通过医学权威知识库（`Medical LLM Wiki`，`/Users/yangli/Documents/llm`）的 **35 套标准化临床决策协议**、**43 部国家权威指南** 及 **35 条 CDSS 处方前置安全拦截规则** 进行真实工业级落地赋能，杜绝任何 mock 数据。

---

## 1. 赋能架构总览与双模接入网关

知识库服务（`http://127.0.0.1:8080`）原生提供两种集成接入路径：

```
┌────────────────────────────────────────────────────────────────────────┐
│                        RHN 门诊医生站 (Outpatient)                     │
│  - 门诊接诊病历书写 (ClinicalRecordSheetView.tsx)                      │
│  - AI 方案生成与草稿审查弹窗 (AiPlanTemplateDraftModal.tsx)             │
│  - 处置与医嘱推荐面板 (ClinicalAiAssistantPanel.tsx)                    │
│  - 知识参考检索面板 (ClinicalKnowledgeSearchPanel)                      │
└───────────────────┬────────────────────────────────┬───────────────────┘
                    │ 方式一：OpenAI 协议零侵入对接  │ 方式二：REST API 直连
                    ▼                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Medical LLM Wiki CDSS 知识引擎网关                   │
│                                                                        │
│  [OpenAI 兼容层]                                                       │
│   • POST /v1/chat/completions (支持非流式 JSON 及 SSE 流式逐字推送)    │
│   • GET /v1/models (服务状态探测与模型清单)                            │
│                                                                        │
│  [RHN 知识检索层]                                                      │
│   • POST /api/knowledge/search (对齐 PmphaiClinicalKnowledgeGateway)   │
│                                                                        │
│  [原生 CDSS REST API]                                                  │
│   • POST /api/cdss/compile-rhn-plan (直接输出 PlanIntent 与 orderDraft) │
│   • POST /api/cdss/audit (35 条国家标准处方前置安全拦截)               │
│   • GET /api/cdss/protocols & GET /api/cdss/protocols/<id>             │
│                                                                        │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │ 核心知识基石：                                                     │ │
│  │  - 35 套门诊标准化推荐协议 (PROT-HTN-001 ~ PROT-RABIES-035)       │ │
│  │  - 35 条 CDSS 强行阻断与警戒规则 (Rule 01 ~ Rule 35)              │ │
│  │  - 43 部国家权威医学指南 + 219 篇互联词条 + SQLite FTS5 引擎       │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 方式一：RHN 零侵入对接配置（推荐，无需修改 Java 代码）

RHN 后端内置的 `OpenAiCompatibleClinicalAiModelGateway.java` 与 `PmphaiClinicalKnowledgeGateway.java` 已经完整实现了基于 OpenAI ChatCompletion 与知识搜索接口的通信。

仅需在 RHN 的 `application.yml`（或 `application-postgres-local.yml`）中配置知识库服务地址：

```yaml
rhn:
  ai:
    mode: ENABLED
    provider: openai-compatible
    model: medical-cdss-wiki
    endpoint: http://127.0.0.1:8080/v1/chat/completions
    knowledge-endpoint: http://127.0.0.1:8080/api/knowledge/search
    request-timeout: PT30S
    max-output-tokens: 3000
    suggestion-ttl: PT30M
```

配置后，RHN 即可在以下业务链路中获得 100% 真实的权威数据赋能：
1. **方案编译器（`compilePlan` / `compilePlanStreaming`）**：
   - 输入病种关键词（如“膝骨关节炎”、“原发性高血压”、“良性前列腺增生”、“犬咬伤暴露”）；
   - 网关自动命中协议，以毫秒级返回结构化 `PlanIntent`；
   - 原生包含无占位符的 6 段全阴性规范门诊病历范文；
   - 包含标准 ICD-10 诊断及具备真实剂型规格的药品/检验医嘱条目。
2. **智能接诊辅助（`analyze`）**：
   - 自动生成初步诊断候选（`diagnosisCandidates`）、6 段门诊病历草稿（`recordDraft`）及处置建议（`treatmentRecommendations`）；
   - 同步调用 35 条 CDSS 规则进行处方安全审核，返回真实严重程度的 `safetyAlerts`。
3. **知识检索（`knowledgeSearch`）**：
   - 医生在医生站搜索疾病或药物时，直通 219 篇权威指南图谱，返回国家指南出处与引用证据。

---

## 3. 方式二：原生 REST API 对接规范

若 RHN 模块希望直接消费轻量级结构化 JSON，可直接请求原生 REST 端点：

### 1. 方案一键智能编译 (`POST /api/cdss/compile-rhn-plan`)
- **请求参数**:
```json
{
  "input": "膝骨关节炎"
}
```
- **真实响应数据（绝无 mock）**:
```json
{
  "success": true,
  "protocolId": "PROT-KOA-032",
  "scopeType": "HOSPITAL",
  "sourceType": "AI_INPUT",
  "planIntent": {
    "name": "门诊膝骨关节炎阶梯镇痛与关节保护方案",
    "description": "依据国家权威指南建立的门诊标准化诊疗协议（ICD-10: M17.9）",
    "noteTemplateContent": {
      "chiefComplaint": "双膝关节间歇性酸胀疼痛伴活动受限 6 个月，加重 1 周。",
      "presentIllness": "患者 6 个月前无明显外伤诱因出现双侧膝关节隐痛酸胀，以负重行走、上下楼梯及蹲起时明显...",
      "medicalHistory": "既往体健，无高血压、糖尿病、冠心病及慢性肾脏病史。无慢性胃炎及胃十二指肠溃疡出血史...",
      "physicalExam": "体温 36.5℃，脉搏 74 次/分，呼吸 18 次/分，血压 126/78 mmHg。发育正常，体型偏胖...",
      "healthEducation": "1. 体重管理与减重指导... 2. 日常关节保护习惯... 3. 功能锻炼指导...",
      "followUp": "外用贴膏与口服药物规律治疗 2~4 周后门诊复查评估膝关节疼痛 VAS 评分与日常活动能力..."
    },
    "items": [
      {
        "kind": "DIAGNOSIS",
        "name": "膝骨关节炎 [M17.9]",
        "sourceQuote": "",
        "origin": "SUGGESTED",
        "details": "门诊标准 ICD-10 诊断，符合中老年双膝活动后酸痛、晨僵<30min及骨摩擦感。"
      },
      {
        "kind": "MEDICATION",
        "name": "双氯芬酸钠凝胶贴膏",
        "sourceQuote": "",
        "origin": "SUGGESTED",
        "details": "用法：每次 1 贴，每日 1 次，贴敷患侧膝关节；连用 14 天；依据：一线首选局部外用 NSAIDs..."
      },
      {
        "kind": "MEDICATION",
        "name": "塞来昔布胶囊",
        "sourceQuote": "",
        "origin": "SUGGESTED",
        "details": "用法：每次 0.2g，每日 1 次，餐后温水送服；连服 14 天；依据：高选择性 COX-2 抑制剂..."
      }
    ],
    "referenceTemplateId": null
  },
  "treatmentRecommendations": [
    {
      "type": "MEDICATION",
      "catalogItemId": "STD-PROT-KOA-032-2",
      "code": "M17.9-MED-2",
      "name": "双氯芬酸钠凝胶贴膏",
      "specification": "50mg/贴",
      "rationale": "用法：每次 1 贴，每日 1 次，贴敷患侧膝关节；连用 14 天；依据：一线首选局部外用 NSAIDs...",
      "orderDraft": {
        "routeCode": "外用",
        "frequencyCode": "QD",
        "doseValue": 1.0,
        "doseUnit": "贴",
        "durationValue": 14,
        "quantity": 1,
        "instruction": "用法：每次 1 贴，每日 1 次，贴敷患侧膝关节"
      }
    }
  ]
}
```

### 2. 处方前置安全核查与拦截 (`POST /api/cdss/audit`)
医生开立医嘱或保存处方前，实时调用此接口拦截不安全用药：
- **请求参数**:
```json
{
  "medications": ["地塞米松片", "塞来昔布胶囊", "双氯芬酸钠缓释片"],
  "patient": {
    "age": 68,
    "is_koa": true
  }
}
```
- **真实响应数据**:
```json
{
  "is_safe": false,
  "total_alerts": 2,
  "red_count": 2,
  "yellow_count": 0,
  "alerts": [
    {
      "ruleId": "RULE-KOA-SYSTEMIC-STEROID",
      "severity": "RED",
      "title": "膝骨关节炎严禁常规全身口服或静滴糖皮质激素",
      "message": "骨关节炎属于非化脓性退行性软骨退变，常规口服或静滴糖皮质激素并不能阻断疾病进展，反而加速关节软骨破坏坏死、诱发股骨头无菌性坏死及全身骨质疏松！绝对禁止系统性使用激素，首选外用或口服非甾体抗炎药。",
      "guideline": "《膝骨关节炎基层诊疗指南（2019年）》"
    },
    {
      "ruleId": "RULE-SAFETY-DUAL-NSAIDS",
      "severity": "RED",
      "title": "严禁口服两种及以上非甾体抗炎药(NSAIDs)",
      "message": "处方中检测到多种 NSAIDs (塞来昔布, 双氯芬酸) 重复口服。不增加镇痛疗效，急剧增加急性消化道穿孔大出血及肾损伤风险！",
      "guideline": "《非特异性腰痛基层全科诊疗与康复管理指南》"
    }
  ]
}
```

---

## 4. 基层 35 套标准协议与 35 条 CDSS 安全规则清单

### A. 35 套门诊标准化诊疗协议 (Protocols)
| 协议编号 | 疾病/场景名称 | ICD-10 编码 | 临床科室分类 |
| :--- | :--- | :--- | :--- |
| `PROT-HTN-001` | 原发性高血压门诊规范诊疗方案 | `I10` | 心血管内科 |
| `PROT-T2DM-002` | 2型糖尿病门诊规范初诊与控糖方案 | `E11.9` | 内分泌科 |
| `PROT-HUA-003` | 高尿酸血症与痛风门诊分期诊疗方案 | `M10.9` | 内分泌代谢科 |
| `PROT-DLP-004` | 门诊血脂异常危险分层与他汀调脂方案 | `E78.5` | 心血管内科 |
| `PROT-COPD-005` | 慢性阻塞性肺疾病门诊稳定期吸入治疗方案 | `J44.9` | 呼吸内科 |
| `PROT-URI-006` | 急性上呼吸道感染门诊对症方案 | `J06.9` | 呼吸内科/全科 |
| `PROT-BRONCH-007` | 急性支气管炎门诊止咳化痰方案 | `J20.9` | 呼吸内科/全科 |
| `PROT-PHARYNG-008`| 急性咽峡炎/扁桃体炎阶梯抗感染方案 | `J02.9` | 耳鼻喉科/全科 |
| `PROT-GERD-009` | 胃食管反流病门诊抑酸抗反流方案 | `K21.9` | 消化内科 |
| `PROT-GASTR-010` | 慢性胃炎门诊黏膜保护与对症方案 | `K29.5` | 消化内科 |
| `PROT-LBP-011` | 门诊非特异性下腰痛阶梯康复与药物方案 | `M54.5` | 骨科/康复科 |
| `PROT-CAD-012` | 门诊慢性稳定性冠心病二级预防ABCDE方案 | `I25.1` | 心血管内科 |
| `PROT-ISCHEM-013` | 门诊缺血性脑卒中/TIA二级预防抗栓降脂方案 | `I63.9` | 神经内科 |
| `PROT-INSOM-014` | 门诊慢性失眠非药物认知行为与短程助眠方案 | `F51.0` | 神经内科/全科 |
| `PROT-ANX-015` | 门诊广泛性焦虑障碍阶梯抗焦虑与身心调节方案 | `F41.1` | 精神心理科/全科 |
| `PROT-DERM-016` | 门诊成人特应性皮炎/湿疹阶梯护肤与抗炎方案 | `L20.9` | 皮肤科 |
| `PROT-TINEA-017` | 门诊皮肤浅部真菌病（足癣/体股癣）外用抗真菌方案 | `B35.9` | 皮肤科 |
| `PROT-UTI-018` | 门诊单纯性下尿路感染（急性膀胱炎）经验性抗菌方案 | `N30.0` | 泌尿外科/肾内科 |
| `PROT-RHIN-019` | 门诊变应性鼻炎（过敏性鼻炎）阶梯鼻喷与抗组胺方案 | `J30.4` | 耳鼻喉科 |
| `PROT-CONJ-020` | 门诊急性结膜炎分型对症滴眼液抗感染方案 | `H10.9` | 眼科 |
| `PROT-OSTEO-021` | 原发性骨质疏松症门诊阶梯抗骨吸收与防跌倒方案 | `M81.9` | 内分泌科/骨科 |
| `PROT-DRYEYE-022`| 门诊干眼症分型人工泪液与眼表抗炎方案 | `H04.1` | 眼科 |
| `PROT-CONSTIP-023`| 门诊成人慢性便秘阶梯容积/渗透性导泻方案 | `K59.0` | 消化内科 |
| `PROT-DIARRHEA-024`| 门诊急性非感染性腹泻口服补液与肠道黏膜保护方案 | `K52.9` | 消化内科/全科 |
| `PROT-VERTIGO-025`| 门诊良性阵发性位置性眩晕(BPPV)与前庭对症方案 | `H81.1` | 耳鼻喉科/神经内科 |
| `PROT-ORAL-026` | 门诊复发性阿弗他溃疡局部消炎止痛与促愈合方案 | `K12.0` | 口腔科 |
| `PROT-THYROID-027`| 门诊成人原发性甲状腺功能减退症左甲状腺素替代方案 | `E03.9` | 内分泌科 |
| `PROT-FATTY-028` | 门诊代谢相关脂肪性肝病(MAFLD)生活方式与保肝方案 | `K76.0` | 消化内科/感染科 |
| `PROT-ALLERGY-029`| 门诊成人轻中度哮喘吸入糖皮质激素/LABA阶梯控制方案 | `J45.9` | 呼吸内科 |
| `PROT-PED-030` | 门诊儿童急性上呼吸道感染退热对症与重症警示方案 | `J06.9` | 儿科 |
| `PROT-PED-031` | 门诊儿童急性支气管炎对症化痰与排痰护理方案 | `J20.9` | 儿科 |
| `PROT-KOA-032` | 门诊膝骨关节炎阶梯镇痛与关节保护方案 | `M17.9` | 骨科/全科 |
| `PROT-URT-033` | 门诊急性荨麻疹与过敏性风团阶梯抗敏方案 | `L50.9` | 皮肤科/全科 |
| `PROT-BPH-034` | 良性前列腺增生门诊改善排尿与联合缩腺方案 | `N40` | 泌尿外科/全科 |
| `PROT-RABIES-035`| 门诊动物致伤暴露后规范处置与免疫接种方案 | `Z20.3` | 急诊/犬伤门诊/全科 |

### B. 35 条 CDSS 处方前置安全拦截规则
包含：
- `RULE-SAFETY-RAS-DUAL`（严禁双重 RAS 轴阻断）
- `RULE-SAFETY-PREGNANCY-RAS`（妊娠期禁用普利/沙坦类）
- `RULE-SAFETY-METFORMIN-RENAL`（重度肾功能不全禁用二甲双胍）
- `RULE-SAFETY-NITRATE-PDE5`（硝酸酯类合用 PDE-5 抑制剂致死低血压）
- `RULE-SAFETY-DUAL-NSAIDS`（严禁重复口服多种 NSAIDs）
- `RULE-KOA-SYSTEMIC-STEROID`（膝骨关节炎严禁常规口服/静滴激素）
- `RULE-BPH-ANTICHOLINERGIC`（良性前列腺增生严禁使用阿托品等抗胆碱药）
- `RULE-RABIES-III-PASSIVE-IMMUNITY`（狂犬病 III 级出血暴露必须同时开具 HRIG 免疫球蛋白）
- `RULE-TETANUS-DEEP-DIRTY`（深部污染创面防范破伤风）
- `RULE-BPH-HYPOTENSION-TAMSULOSIN`（高龄多重降压患者坦索罗辛体位性低血压警戒）
- `RULE-ALLERGY-PENICILLIN`（青霉素过敏患者严禁处方阿莫西林）
等 35 项权威规则。

---

## 5. 服务启动与自动化测试

```bash
# 启动双模知识库与网关服务（默认端口 8080）
python3 tools/cli.py serve --port 8080

# 运行真实集成联调测试套件（无 mock，真实验证）
python3 -m unittest tests/test_rhn_live_integration.py
```
