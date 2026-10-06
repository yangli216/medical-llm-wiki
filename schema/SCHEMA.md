# 中国医学权威指南与标准 LLM Wiki 架构规范 (Wiki Schema)

本文档是本项目（**Medical LLM Wiki**）的核心规范定义文件，基于 Andrej Karpathy 提出的 **LLM Wiki** 架构设计思想，专门面向中国医学权威发布的临床指南、行业标准和临床路径进行知识编译与维护。

---

## 1. 架构三层模型 (Three-Tier Architecture)

```
raw/                  -> 不可变源文献层 (Immutable Source of Truth)
                         存放官方指南、标准原文与结构化元数据注册表，只读不篡改。
                         
wiki/                 -> 知识图谱与互联维基层 (Compiled Knowledge Base)
                         由 LLM/编译器持续维护的 Markdown 互联知识库，面向人类与模型。
                         
schema/ & tools/      -> 规范定义与自动化工具链层 (Schema & Tooling)
                         约束知识格式、提供入库校验、全库体检 (Linter) 与检索问答引擎。
```

---

## 2. 目录规范与文件分类

| 目录路径 | 页面类型 (`type`) | 职责描述 |
| :--- | :--- | :--- |
| `wiki/index.md` | `index` | 知识库全景导航与分类索引，每次入库后必须同步更新。 |
| `wiki/log.md` | `log` | 知识库变更流水账，严格按时间倒序/正序记录所有 Ingest / Update / Lint 操作。 |
| `wiki/sources/` | `source` | 指南来源研读页面。对单篇原始文献的结构化提炼、证据等级解析及关联变更追踪。 |
| `wiki/entities/diseases/` | `disease` | 疾病实体。包含流行病学、分型分期、诊断要点、治疗原则、随访管理。 |
| `wiki/entities/drugs/` | `drug` | 药物与疗法实体。包含药物类别、作用机制、临床适应证、用法用量、禁忌证与不良反应。 |
| `wiki/entities/organizations/`| `organization` | 权威发布机构实体。包含机构职责、主要下设专科分会及发布的代表性指南。 |
| `wiki/concepts/` | `concept` | 诊断标准、临床路径、筛查策略、评分量表（如 CURB-65、GOLD 分级、CNLC 分期）。 |
| `wiki/synthesis/` | `synthesis` | 跨病种/跨指南综合专题。共病综合管理、多药联合安全、药物相互作用、MDT 综合决策。 |

---

## 3. Frontmatter 元数据标准规范

知识库内每个 Markdown 文件必须以标准 YAML Frontmatter 开头，字段规范如下：

```yaml
---
title: 原发性高血压
type: disease # 枚举: disease | drug | concept | organization | source | synthesis | index
tags:
  - 医学/心血管
  - 慢病管理
aliases:
  - 高血压
  - 基础高血压
sources:
  - SRC-CMA-CARD-2024-01
  - SRC-NHC-PH-2023-01
last_updated: "2026-10-06"
status: verified # verified | draft | deprecated
---
```

### 字段说明：
1. **`title`** (必填): 规范中文全称。
2. **`type`** (必填): 页面所属分类。
3. **`tags`** (必填): 层级化标签（如 `医学/呼吸系统`、`药物/降压药`）。
4. **`aliases`** (可选): 别名列表，方便在 Obsidian 及检索系统快速匹配。
5. **`sources`** (必填，除 index/log 外): 引用的原始源 ID 列表（必须在 `raw/metadata.json` 中存在）。
6. **`last_updated`** (必填): 最后一次更新日期（YYYY-MM-DD）。
7. **`status`** (必填): 状态，包括 `verified`（已校验）、`draft`（草稿）、`deprecated`（已废止/被新版替代）。

---

## 4. 双向链接与引用规范

为了在 **Obsidian** 和各类标准 Markdown 阅读器中都能完美呈现：

1. **内链格式**: 
   - 优先使用双向链接语法：`[[页面名]]` 或 `[[页面名|显示别名]]`。
   - 例如：`根据 [[原发性高血压诊疗标准]]，首选药物为 [[钙通道阻滞剂]] 或 [[RAS抑制剂]]。`
2. **反向链接 (Backlinks)**:
   - 页面底部维护标准的 `## 关联页面与反向引用` 区域，清晰列出上下游关联。
3. **证据等级与推荐强度标注规范**:
   遵循中华医学会及国家卫健委通用的推荐标准：
   - **推荐级别**:
     - **I 类推荐**：已证实和/或一致公认有益、有用和有效（应当使用）。
     - **IIa 类推荐**：证据/观点倾向于有用/有效（应用是合理的）。
     - **IIb 类推荐**：其有用性/有效性尚未明确确立（可考虑应用）。
     - **III 类推荐**：已证实和/或一致公认无用和无效，甚至有害（不推荐/禁止使用）。
   - **证据水平**:
     - **证据 A 级**：来自多项随机临床试验 (RCT) 或 Meta 分析。
     - **证据 B 级**：来自单项 RCT 或大型非随机研究。
     - **证据 C 级**：专家共识、病例报告或标准护理。

---

## 5. 知识维护与质量体检 (Linting) 规则

为避免知识库随时间膨胀出现信息断裂，必须遵循以下健康检查规则：
1. **零死链 (No Broken Links)**: 凡是出现的 `[[WikiLink]]` 必须能对应到真实存在的实体或概念页面。
2. **拒绝孤岛页面 (No Orphan Pages)**: 除了主索引 `index.md`，每个页面必须至少有 1 个入向链接 (Inbound link) 和 1 个出向链接 (Outbound link)。
3. **版本更新与废弃标注 (Supersession Tracking)**: 当新版指南发布（如 2024版替代 2018版），旧版核心推荐点必须在综合页或来源页显著标记变更对比，避免过时陈旧信息产生临床误导。
4. **同质化冲突预警 (Contradiction Flagging)**: 若不同权威专科指南在交汇领域存在剂量、切点或药物选择差异（如老年患者降压目标切点、抗凝与抗板联合时长），必须在 `synthesis/` 专题页明确列出各方立场与临床裁量指引。
