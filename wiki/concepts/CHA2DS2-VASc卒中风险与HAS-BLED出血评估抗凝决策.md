---
title: CHA2DS2-VASc卒中风险与HAS-BLED出血评估抗凝决策
type: concept
tags:
  - 概念/量化评估
  - 心血管/房颤
  - 抗凝决策/CDSS规则
sources:
  - SRC-CMA-CARD-2021-02
  - SRC-CMA-CARD-2024-02
status: verified
last_updated: "2026-10-09"
---

# CHA2DS2-VASc 卒中风险与 HAS-BLED 出血评估抗凝决策规范

## 一、 CHA2DS2-VASc 卒中危险评分系统

| 危险因素 (Risk Factors) | 赋值 | 临床定义与核查要点 |
| :--- | :---: | :--- |
| **C** (Congestive heart failure) | 1 | 充血性心力衰竭体征、左心室射血分数 LVEF $\le 40\%$ |
| **H** (Hypertension) | 1 | 静息血压多次 $\ge 140/90	ext{ mmHg}$ 或正在接受降压药物治疗 |
| **A2** (Age $\ge 75$ years) | **2** | 年龄满 75 周岁及以上 |
| **D** (Diabetes mellitus) | 1 | 明确空腹血糖升高、HbA1c $\ge 6.5\%$ 或正在使用降糖药物 |
| **S2** (Stroke / TIA / TE) | **2** | 既往缺血性脑卒中、短暂性脑缺血发作或全身动脉血栓栓塞史 |
| **V** (Vascular disease) | 1 | 明确既往心肌梗死、外周动脉疾病 (PAD) 或主动脉斑块 |
| **A** (Age 65～74 years) | 1 | 年龄处于 65 周岁至 74 周岁区间 |
| **Sc** (Sex category - Female) | 1 | 女性性别（单一女性无其他危险因素时得分无效） |

### 临床决策红线
- **男性 $\ge 2$ 分，女性 $\ge 3$ 分**：**强烈推荐长期口服抗凝药物**（I类推荐，A级证据，首选 DOACs 如 [[利伐沙班片]], [[达比加群酯胶囊]]）；
- **男性 1 分，女性 2 分**：推荐口服抗凝治疗（IIa类推荐，权衡出血风险）；
- **男性 0 分，女性 1 分**：低卒中风险，不推荐抗血小板或抗凝治疗。

---

## 二、 HAS-BLED 出血风险评分系统

| 危险因素 (Bleeding Risk) | 赋值 | 临床定义与纠正策略 |
| :--- | :---: | :--- |
| **H** (Hypertension) | 1 | 未控制高血压，收缩压 SBP $> 160	ext{ mmHg}$（可逆因素，强化降压） |
| **A** (Abnormal renal/liver) | 1或2 | 肾功异常（透析/移植/Scr $\ge 200\mu	ext{mol/L}$ 各1分）；肝功异常（转氨酶>3倍正常） |
| **S** (Stroke) | 1 | 既往脑卒中史 |
| **B** (Bleeding) | 1 | 既往大出血病史或活动性出血体质 |
| **L** (Labile INR) | 1 | 服用华法林患者治疗窗内时间 TTR $< 60\%$（换用 DOACs 可消除此风险） |
| **E** (Elderly) | 1 | 年龄 $> 65$ 岁 |
| **D** (Drugs or Alcohol) | 1或2 | 合用抗血小板药物/NSAIDs（1分）；过量饮酒（1分） |

### 核心临床警示
> **HAS-BLED $\ge 3$ 分绝非抗凝禁忌证！**
> 指南明确指出：高出血风险评分提示临床医师必须密切随访，纠正血压、停用非必要 NSAIDs、戒酒、纠正贫血，而非盲目停用抗凝药导致脑梗死致残！

## 三、 关联知识网络
- **权威来源**：[[SRC-CMA-CARD-2021-02]]
- **疾病实体**：[[心房颤动]], [[急性缺血性脑卒中]]
- **核心计算器**：`ClinicalCalculatorRegistry.calc_cha2ds2_vasc`, `calc_has_bled`
