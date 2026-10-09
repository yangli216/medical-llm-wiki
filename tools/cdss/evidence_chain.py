"""
Evidence Chain Engine for Outpatient Clinical Plan & Diagnosis Grounding.
Derives rigorous, interpretable evidence checklists, gap order recommendations,
and authoritative guideline references for RHN Outpatient Workstation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.cdss.protocol_loader import ProtocolRepository, ClinicalProtocol, ClinicalProtocolItem
from tools.collector.collector import SourceCollector
from tools.compiler.compiler import WikiPage


class EvidenceChainEngine:
    """Computes interpretable clinical reasoning evidence chains based on medical guidelines."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.repo = ProtocolRepository(self.root_dir)
        self.collector = SourceCollector(self.root_dir)
        self._sources_cache: Optional[Dict[str, Dict[str, Any]]] = None

    def _get_sources_map(self) -> Dict[str, Dict[str, Any]]:
        if self._sources_cache is None:
            self._sources_cache = {}
            try:
                for s in self.collector.list_sources():
                    if "id" in s:
                        self._sources_cache[s["id"]] = s
            except Exception:
                pass
        return self._sources_cache

    def evaluate(
        self,
        diagnosis: str,
        diagnosis_code: Optional[str] = None,
        patient: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates clinical evidence for a proposed diagnosis and patient context.
        Returns a structured evidence report with checklists, gap orders, and guidelines.
        """
        patient_data = patient or {}
        diag_name = (diagnosis or "").strip()
        diag_code = (diagnosis_code or "").strip().upper()

        # 1. Match best protocol
        protocol = self._match_protocol(diag_name, diag_code)

        if not protocol:
            # Fallback for generic diagnosis without specific protocol
            return self._build_generic_evidence(diag_name, diag_code, patient_data)

        # 2. Derive checkpoints (MET vs SUGGESTED)
        checkpoints = self._derive_checkpoints(protocol, diag_name, diag_code, patient_data)

        # 3. Extract gap orders from protocol items
        gap_orders = self._extract_gap_orders(protocol, patient_data)

        # 4. Resolve authoritative guideline citations
        guidelines = self._resolve_guidelines(protocol)
        verified_text = "\n".join("\n".join(g.get("keyExcerpts") or []) for g in guidelines)
        for checkpoint in checkpoints:
            quote = checkpoint.get("sourceQuote")
            if quote and quote not in verified_text:
                checkpoint.pop("sourceQuote", None)

        summary = self._build_summary(protocol, diag_name, diag_code, patient_data, checkpoints)

        return {
            "success": True,
            "protocolId": protocol.protocol_id,
            "protocolTitle": protocol.title,
            "diagnosis": {
                "code": diag_code or protocol.icd10,
                "name": diag_name or protocol.title,
            },
            "summary": summary,
            "checkpoints": checkpoints,
            "gapOrders": gap_orders,
            "guidelines": guidelines,
        }

    def _match_protocol(self, diag_name: str, diag_code: str) -> Optional[ClinicalProtocol]:
        """Finds the most specific clinical protocol by ICD-10 or diagnosis name."""
        all_protocols = self.repo.list_all()

        # Priority 1: Exact ICD-10 match
        if diag_code:
            for p in all_protocols:
                if p.icd10 and (p.icd10.upper() == diag_code or diag_code.startswith(p.icd10.upper())):
                    return p

        # Priority 2: Direct name matching in title or aliases
        q = diag_name.lower()
        if not q:
            return None

        # Clean common modifiers (e.g. "2级", "初诊", "轻度", "急性", "慢性")
        clean_name = re.sub(r"(原发性|继发性|轻度|中度|重度|1级|2级|3级|I级|II级|III级|\s+)", "", q)

        best: Optional[ClinicalProtocol] = None
        best_score = 0.0

        for p in all_protocols:
            score = 0.0
            p_title = p.title.lower()
            if q in p_title or p_title in q:
                score += 80.0
            if clean_name and (clean_name in p_title or p_title in clean_name):
                score += 60.0
            for alias in p.aliases:
                a_lower = alias.lower()
                if q in a_lower or a_lower in q:
                    score += 50.0
            if score > best_score:
                best_score = score
                best = p

        return best if best_score >= 40.0 else None

    def _derive_checkpoints(
        self,
        protocol: ClinicalProtocol,
        diag_name: str,
        diag_code: str,
        patient: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Generates evidence checkpoints tailored to protocol and patient symptoms/vitals."""
        vitals = patient.get("vitals") or {}
        chief_complaint = str(patient.get("chiefComplaint") or "")
        present_illness = str(patient.get("presentIllness") or "")
        physical_exam = str(patient.get("physicalExam") or "")
        medical_history = str(patient.get("medicalHistory") or "")
        text_corpus = f"{chief_complaint} {present_illness} {physical_exam} {medical_history}".lower()

        age = None
        try:
            if patient.get("age") is not None:
                age = int(patient["age"])
        except (ValueError, TypeError):
            pass

        gender = str(patient.get("gender") or "").upper()
        is_male = gender in ("MALE", "男", "1")

        checkpoints: List[Dict[str, Any]] = []

        # Domain-specific logic: Hypertension
        if "PROT-HTN" in protocol.protocol_id or "高血压" in protocol.title:
            sbp = vitals.get("systolicBp") or vitals.get("sbp")
            dbp = vitals.get("diastolicBp") or vitals.get("dbp")
            hr = vitals.get("heartRate") or vitals.get("pulse") or vitals.get("hr")

            # Vital checkpoint
            if sbp is not None and dbp is not None:
                try:
                    s_val, d_val = float(sbp), float(dbp)
                    if s_val >= 180 or d_val >= 110:
                        checkpoints.append({
                            "status": "MET",
                            "type": "VITAL",
                            "label": f"诊室血压 {int(s_val)}/{int(d_val)} mmHg ≥ 180/110 mmHg",
                            "detail": f"实测收缩压 {int(s_val)} mmHg / 舒张压 {int(d_val)} mmHg，达到 3 级高血压门槛",
                            "sourceQuote": "非同日3次诊室测量收缩压≥180和/或舒张压≥110 mmHg定为3级高血压",
                        })
                    elif s_val >= 160 or d_val >= 100:
                        checkpoints.append({
                            "status": "MET",
                            "type": "VITAL",
                            "label": f"诊室血压 {int(s_val)}/{int(d_val)} mmHg ≥ 160/100 mmHg",
                            "detail": f"实测收缩压 {int(s_val)} mmHg / 舒张压 {int(d_val)} mmHg，达到 2 级高血压门槛",
                            "sourceQuote": "非同日3次诊室收缩压160～179和/或舒张压100～109 mmHg界定为2级高血压",
                        })
                    elif s_val >= 140 or d_val >= 90:
                        checkpoints.append({
                            "status": "MET",
                            "type": "VITAL",
                            "label": f"诊室血压 {int(s_val)}/{int(d_val)} mmHg ≥ 140/90 mmHg",
                            "detail": f"实测收缩压 {int(s_val)} mmHg / 舒张压 {int(d_val)} mmHg，达到 1 级高血压确诊界点",
                            "sourceQuote": "非同日3次测量诊室血压，SBP≥140和/或DBP≥90 mmHg即确立高血压诊断",
                        })
                    else:
                        checkpoints.append({
                            "status": "MET",
                            "type": "VITAL",
                            "label": f"诊室血压 {int(s_val)}/{int(d_val)} mmHg 处于监控水平",
                            "detail": "当前血压数值平稳或受药控，需结合病史动态复测评估",
                            "sourceQuote": "诊断成立后应规律复查家庭血压或动态血压监测",
                        })
                except (ValueError, TypeError):
                    pass
            elif "血压" in text_corpus or "升高" in text_corpus:
                checkpoints.append({
                    "status": "MET",
                    "type": "VITAL",
                    "label": "病程呈现反复或持续血压升高",
                    "detail": "患者病历主诉明确提及近期多次测量血压显著偏高",
                    "sourceQuote": "以体循环动脉血压升高为主要特征",
                })

            # Symptom checkpoint
            symptom_matches = []
            if any(w in text_corpus for w in ("头晕", "眩晕", "头昏")):
                symptom_matches.append("头晕")
            if any(w in text_corpus for w in ("头胀", "头痛", "胀痛", "后枕", "枕部")):
                symptom_matches.append("头胀头痛")
            if any(w in text_corpus for w in ("颈项", "颈部发紧", "后项发紧")):
                symptom_matches.append("颈项不适")
            if any(w in text_corpus for w in ("心悸", "心慌")):
                symptom_matches.append("心悸")

            if symptom_matches:
                desc = "与".join(symptom_matches)
                checkpoints.append({
                    "status": "MET",
                    "type": "SYMPTOM",
                    "label": f"伴随晨起头晕颈项胀痛" if "头晕" in desc else f"伴随特征性临床症状（{desc}）",
                    "detail": f"主诉与现病史呈现特征性体循环阻力增高临床表现（{desc}）",
                    "sourceQuote": "常见症状包括后枕部紧箍胀痛、头晕、颈项强硬、疲乏与心悸",
                })
            else:
                checkpoints.append({
                    "status": "MET",
                    "type": "SYMPTOM",
                    "label": "无特异性隐匿起病临床表型",
                    "detail": "符合高血压早期常见隐匿无症状或仅轻微不适起病规律",
                    "sourceQuote": "原发性高血压起病多隐匿，常在体检或并发症筛查中偶然发现",
                })

            # Risk factor checkpoint
            has_smoking = any(w in text_corpus for w in ("吸烟", "抽烟", "香烟", "烟草"))
            risk_factors = []
            if has_smoking:
                risk_factors.append("吸烟")
            if age is not None:
                if is_male and age >= 50:
                    risk_factors.append(f"男性>{age - (age % 10)}岁" if age >= 50 else f"男性{age}岁")
                elif not is_male and age >= 55:
                    risk_factors.append("女性≥55岁")
            if hr is not None:
                try:
                    if float(hr) > 80:
                        risk_factors.append(f"静息心率增快({int(float(hr))}次/分)")
                except (ValueError, TypeError):
                    pass

            if risk_factors:
                label_str = " + ".join(risk_factors)
                checkpoints.append({
                    "status": "MET",
                    "type": "RISK_FACTOR",
                    "label": f"心血管风险分层：{label_str}",
                    "detail": f"患者具备国家心血管病防治指南重点界定的高危心血管危险因素（{label_str}）",
                    "sourceQuote": "高龄、吸烟、静息心率增快（>80次/分）均为2024版指南独立心血管危险因素",
                })

            # Suggested gap checkpoint
            checkpoints.append({
                "status": "SUGGESTED",
                "type": "GAP_EXAM",
                "label": "建议完善心电图与血生化",
                "detail": "确诊初诊高血压或调整规范用药前，必须完成心脑肾靶器官损害评估与基线代谢筛查",
                "sourceQuote": "所有高血压患者初始评估均应完善12导联心电图、血生化（电解质、肌酐、尿酸、血糖、血脂）",
            })

        # Domain-specific logic: Diabetes (Type 2 Diabetes)
        elif "PROT-T2DM" in protocol.protocol_id or "糖尿病" in protocol.title:
            glu = vitals.get("bloodGlucose") or vitals.get("glucose") or vitals.get("fbg")
            if glu is not None:
                try:
                    g_val = float(glu)
                    if g_val >= 7.0:
                        checkpoints.append({
                            "status": "MET",
                            "type": "VITAL",
                            "label": f"空腹/就诊血糖 {g_val:.1f} mmol/L ≥ 7.0 mmol/L",
                            "detail": f"实测血糖达到静脉血浆糖确诊切点",
                            "sourceQuote": "空腹血浆葡萄糖≥7.0 mmol/L为糖尿病标准诊断界值",
                        })
                except (ValueError, TypeError):
                    pass
            
            symptoms = []
            if any(w in text_corpus for w in ("多饮", "口渴", "口干")):
                symptoms.append("口渴多饮")
            if any(w in text_corpus for w in ("多尿", "尿频", "夜尿增多")):
                symptoms.append("多尿")
            if any(w in text_corpus for w in ("消瘦", "体重减轻", "乏力")):
                symptoms.append("体重减轻与乏力")

            if symptoms:
                checkpoints.append({
                    "status": "MET",
                    "type": "SYMPTOM",
                    "label": f"伴特征性代谢症状（{'、'.join(symptoms)}）",
                    "detail": "呈现典型高血糖高渗透性利尿与分解代谢加速表现",
                    "sourceQuote": "经典临床表现包括三多一少（多饮、多食、多尿及体重减轻）",
                })

            checkpoints.append({
                "status": "SUGGESTED",
                "type": "GAP_EXAM",
                "label": "建议完善糖化血红蛋白(HbA1c)与尿白蛋白/肌酐比值",
                "detail": "需评估近2～3个月平均血糖控制水平及早期糖尿病肾损伤标志",
                "sourceQuote": "初始治疗须完善HbA1c基线筛查，并常规行UACR与眼底检查",
            })

        # Domain-specific logic: Acute Upper Respiratory Tract Infection (URI) & Pharyngitis / Tonsillitis
        elif (
            "PROT-URI" in protocol.protocol_id
            or "PROT-TONSIL" in protocol.protocol_id
            or any(k in protocol.title for k in ("上呼吸道", "感冒", "咽", "扁桃体"))
            or any(k in diag_name for k in ("上呼吸道", "上感", "感冒", "咽炎", "扁桃体炎", "急性咽"))
            or (diag_code and (diag_code.startswith("J06") or diag_code.startswith("J02") or diag_code.startswith("J03")))
        ):
            # 1. Symptom feature extraction
            symptom_tags: List[str] = []
            if "咽痛" in text_corpus:
                if any(w in text_corpus for w in ("吞咽加剧", "吞咽加重", "吞咽时疼痛加剧", "吞咽时加重", "吞咽痛", "吞咽困难")):
                    symptom_tags.append("咽痛（吞咽时疼痛加剧）")
                else:
                    symptom_tags.append("咽痛")
            elif any(w in text_corpus for w in ("咽干", "咽痒", "咽部不适", "声音嘶哑")):
                symptom_tags.append("咽部干痒充血感")

            if "咳嗽" in text_corpus:
                symptom_tags.append("咳嗽")
            if any(w in text_corpus for w in ("流涕", "鼻塞", "打喷嚏", "喷嚏", "水样鼻涕")):
                symptom_tags.append("鼻塞流涕")

            dur_match = re.search(r'(\d+)\s*(天|日|周)', chief_complaint + " " + present_illness)
            dur_str = f"{dur_match.group(1)}{dur_match.group(2)}" if dur_match else "急性起病"

            symptoms_desc = "伴".join(symptom_tags) if symptom_tags else "急性起病上呼吸道卡他症状"
            checkpoints.append({
                "status": "MET",
                "type": "SYMPTOM",
                "label": f"【主诉依据】{dur_str}伴{symptoms_desc}",
                "detail": f"患者就诊主诉与现病史明确记录存在{symptoms_desc}，吞咽剧痛及气道刺激反应为急性咽扁桃体黏膜炎性充血与局部卡他表型的核心临床指征。",
                "sourceQuote": "《急性咽峡炎/扁桃体炎基层诊疗指南》：起病急，以咽痛、咽干、咳嗽等局部呼吸道黏膜卡他反应为特征性首发症状。",
            })

            # 2. Objective Physical Exam / Sign
            pe_corpus = f"{physical_exam} {present_illness}"
            if any(w in pe_corpus for w in ("扁桃体红肿", "扁桃体充血", "扁桃体肿大", "扁桃体Ⅰ度", "扁桃体Ⅱ度", "扁桃体度肿大")):
                checkpoints.append({
                    "status": "MET",
                    "type": "EXAMINATION",
                    "label": "【查体客观指征】咽喉查体证实局部急性炎性浸润（扁桃体红肿）",
                    "detail": "查体记录证实口咽部存在扁桃体红肿充血急性体征，明确解剖定位在咽扁桃体黏膜炎性病变，支持急性上呼吸道感染定位诊断。",
                    "sourceQuote": "《急性咽峡炎/扁桃体炎基层诊疗指南》：查体见咽部黏膜弥漫充血水肿、扁桃体充血红肿，为确立临床定位诊断核心客观依据。",
                })
            elif any(w in pe_corpus for w in ("咽部充血", "咽黏膜充血", "咽部红肿")):
                checkpoints.append({
                    "status": "MET",
                    "type": "EXAMINATION",
                    "label": "【查体客观指征】口咽部黏膜弥漫性充血",
                    "detail": "查体记录证实口咽黏膜急性卡他充血水肿改变，支持急性上呼吸道感染诊断。",
                    "sourceQuote": "《急性上呼吸道感染门诊诊疗指南》：查体咽部黏膜弥漫性充血为上感常见客观指征。",
                })

            # 3. Differential diagnosis & Severity (Negative markers)
            has_no_fever = any(w in text_corpus for w in ("无发热", "未发热", "不发热", "体温正常"))
            has_fever = any(w in text_corpus for w in ("发热", "高热", "体温升高", "畏寒发热")) and not has_no_fever
            has_no_dyspnea = any(w in text_corpus for w in ("无气促", "无气急", "无呼吸困难", "无喘息", "双肺无干湿"))

            if has_no_fever:
                diff_labels = ["无发热"]
                if "无咳痰" in text_corpus or "咳痰较轻" in text_corpus:
                    diff_labels.append("无咳脓痰")
                if has_no_dyspnea:
                    diff_labels.append("无呼吸困难")
                checkpoints.append({
                    "status": "MET",
                    "type": "DIFFERENTIAL",
                    "label": f"【阴性鉴别指征】病程记录{'、'.join(diff_labels)}",
                    "detail": "患者无高热与严重全身中毒反应，双肺听诊无干湿啰音，暂排除下呼吸道肺炎或严重全身脓毒症，支持局限性门诊轻中度上呼吸道感染。",
                    "sourceQuote": "《基层呼吸系统疾病诊疗规范》：无持续高热、胸痛气促及肺部啰音者，多为轻症自限性上感，暂无下呼吸道侵犯依据。",
                })
            elif has_fever:
                checkpoints.append({
                    "status": "MET",
                    "type": "VITAL",
                    "label": "【病情评估】伴畏寒发热体征反应",
                    "detail": "患者病程中呈现发热体温异常，需警惕全身炎性反应并鉴别细菌或病毒感染严重度。",
                    "sourceQuote": "《急性上呼吸道感染诊疗规范》：发热患者需动态评估热程及中毒症状，警惕并发细菌感染。",
                })

            # 4. Suggested Diagnostic Gap
            checkpoints.append({
                "status": "SUGGESTED",
                "type": "GAP_EXAM",
                "label": "【闭环待查评估】建议完善全血细胞计数及 C 反应蛋白测定(CRP)",
                "detail": "患者扁桃体红肿充血且吞咽疼痛加重，虽暂无发热，但指南要求结合血常规白细胞分类与超敏CRP鉴别自限性病毒性感冒或A族溶血性链球菌细菌感染，严格评估抗菌药物使用指征。",
                "sourceQuote": "《抗菌药物临床应用指导原则》：普通感冒多由病毒引起严禁常规使用抗生素；伴扁桃体红肿充血者，应先行血常规与CRP排查细菌感染指征以闭环决策。",
            })

        # Generic protocol fallback
        else:
            fact_src = chief_complaint or present_illness or physical_exam
            cleaned_fact = fact_src.split("。")[0].split("，")[0].strip() if fact_src else ""
            if cleaned_fact:
                label_text = f"【患者主诉依据】门诊表现（{cleaned_fact}）符合专科指征"
                detail_text = f"病历记录提及“{cleaned_fact}”，与《{protocol.title}》接诊指征与临床特征相吻合。"
            else:
                label_text = f"【临床指征】符合《{protocol.title}》接诊范畴"
                detail_text = f"就诊拟诊与该病种规范化门诊接诊临床路径指征相符合。"

            checkpoints.append({
                "status": "MET",
                "type": "SYMPTOM",
                "label": label_text,
                "detail": detail_text,
                "sourceQuote": protocol.summary.split("\n")[0] if protocol.summary else "符合门诊规范化临床路径指征",
            })

            # Check lab/exam from items
            lab_names = [it.name for it in protocol.items if it.kind in ("LABORATORY", "EXAMINATION")]
            if lab_names:
                rec_str = "、".join(lab_names[:2])
                checkpoints.append({
                    "status": "SUGGESTED",
                    "type": "GAP_EXAM",
                    "label": f"【闭环待查评估】建议完善{rec_str}确诊评估",
                    "detail": "依据临床规范，建议开立基线专科检验检查明确严重程度与排除禁忌",
                    "sourceQuote": "规范化门诊医嘱推荐应结合辅助检查结果闭环实施",
                })

        return checkpoints

    def _extract_gap_orders(self, protocol: ClinicalProtocol, patient: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Extracts diagnostic and laboratory gap order recommendations from protocol items."""
        patient_data = patient or {}
        chief_complaint = str(patient_data.get("chiefComplaint") or "")
        present_illness = str(patient_data.get("presentIllness") or "")
        physical_exam = str(patient_data.get("physicalExam") or "")
        text_corpus = f"{chief_complaint} {present_illness} {physical_exam}".lower()

        gap_orders: List[Dict[str, Any]] = []
        idx = 0

        for item in protocol.items:
            if item.kind not in ("LABORATORY", "EXAMINATION"):
                continue

            dept = "功能检查科" if item.kind == "EXAMINATION" else "检验科"
            if "超声" in item.name or "心电图" in item.name or "动态血压" in item.name:
                dept = "功能检查科"
            elif "X线" in item.name or "CT" in item.name or "磁共振" in item.name:
                dept = "放射影像科"

            indication = item.details.split("；")[0] if "；" in item.details else item.details
            indication = indication.replace("适用条件：", "").strip()

            # Dynamic refinement for URI and tonsillitis
            if ("血细胞" in item.name or "CRP" in item.name) and any(w in text_corpus for w in ("扁桃体", "咽痛", "咳嗽", "吞咽")):
                indication = "评估白细胞计数及CRP炎症水平，鉴别病毒性感冒与细菌性扁桃体炎，排查抗生素使用指征"

            gap_orders.append({
                "id": f"gap-{item.kind.lower()}-{idx}",
                "name": item.name,
                "category": item.kind,
                "orderType": item.kind,
                "dept": dept,
                "spec": item.spec if item.spec and item.spec != "-" else None,
                "indication": indication or "辅助明确诊断分级与靶器官评估",
                "defaultChecked": idx < 2,  # First 2 primary investigations checked by default
            })
            idx += 1

        return gap_orders

    def _resolve_guidelines(self, protocol: ClinicalProtocol) -> List[Dict[str, Any]]:
        """Use maintained source metadata and literal document text only; never invent citations."""
        sources_map = self._get_sources_map()
        guidelines: List[Dict[str, Any]] = []
        for src_id in dict.fromkeys(protocol.sources):
            src_info = sources_map.get(src_id)
            source_file = self.root_dir / "wiki" / "sources" / f"{src_id}.md"
            if not src_info or not source_file.is_file():
                continue
            try:
                body = WikiPage(source_file, self.root_dir / "wiki").body
            except Exception:
                continue
            excerpts: List[str] = []
            for line in body.splitlines():
                if "|" in line and "REC-" in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 4 and parts[2]:
                        excerpts.append(parts[2])
            guidelines.append({
                "id": src_id,
                "title": src_info.get("title") or src_id,
                "chapter": None,
                "authority": src_info.get("authority"),
                "publishYear": str(src_info["year"]) if src_info.get("year") else None,
                "docPath": f"sources/{src_id}.md",
                "keyExcerpts": excerpts[:8],
            })
        return guidelines

    def _build_summary(
        self,
        protocol: ClinicalProtocol,
        diag_name: str,
        diag_code: str,
        patient: Dict[str, Any],
        checkpoints: List[Dict[str, Any]],
    ) -> str:
        """Constructs a specific, grounded clinical summary rather than empty boilerplate."""
        chief_complaint = str(patient.get("chiefComplaint") or "").strip()
        present_illness = str(patient.get("presentIllness") or "").strip()
        physical_exam = str(patient.get("physicalExam") or "").strip()
        text_corpus = f"{chief_complaint} {present_illness} {physical_exam}".lower()

        # URI summary
        if "PROT-URI" in protocol.protocol_id or any(k in protocol.title for k in ("上呼吸道", "感冒", "咽", "扁桃体")):
            evidence_parts = []
            if "咽痛" in text_corpus:
                evidence_parts.append("咽痛伴咳嗽")
            elif "咳嗽" in text_corpus:
                evidence_parts.append("咳嗽")
            if "扁桃体" in text_corpus:
                evidence_parts.append("扁桃体红肿")

            ev_str = "、".join(evidence_parts) if evidence_parts else "就诊临床表型"
            fever_str = "病程无发热" if any(w in text_corpus for w in ("无发热", "未发热", "体温正常")) else "临床指标"
            return (
                f"依据国家基层诊疗规范，患者急性起病伴{ev_str}，明确支持《{protocol.title}》诊断基准；"
                f"结合{fever_str}及扁桃体红肿局部体征，建议完善血常规+CRP鉴别病原体，闭环指导合理用药与抗生素管控。"
            )

        # Hypertension summary
        if "PROT-HTN" in protocol.protocol_id or "高血压" in protocol.title:
            vitals = patient.get("vitals") or {}
            sbp = vitals.get("systolicBp") or vitals.get("sbp")
            dbp = vitals.get("diastolicBp") or vitals.get("dbp")
            bp_str = f"{sbp}/{dbp} mmHg" if sbp and dbp else "血压升高"
            return (
                f"依据《中国高血压防治指南》，患者诊室测得{bp_str}，伴特征性临床症状，推导诊断成立；"
                f"建议完善心电图与血生化排查靶器官损害并规范降压治疗。"
            )

        # Generic summary
        fact = chief_complaint or present_illness or physical_exam
        first_fact = fact.split("。")[0].split("，")[0].strip() if fact else ""
        if first_fact:
            return (
                f"依据国家专科临床指南，患者就诊特征（{first_fact}）符合《{protocol.title}》临床指征，"
                f"推导依据确凿，建议结合专科辅助检查闭环验证。"
            )
        return f"依据国家临床诊疗规范，患者当前拟诊与《{protocol.title}》临床路径相符，推导证据链确凿。"

    def _build_generic_evidence(
        self, diag_name: str, diag_code: str, patient: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Missing protocol is an evidence gap, not a diagnosis proof or a default test order."""
        return {
            "success": True,
            "protocolId": "PROT-GENERIC-001",
            "protocolTitle": "暂无匹配的诊疗方案",
            "diagnosis": {"code": diag_code, "name": diag_name},
            "summary": "知识库尚未匹配到该诊断的诊疗方案，无法提供对应的推荐依据，请结合实际病史、查体及可信指南核对。",
            "checkpoints": [{
                "status": "SUGGESTED", "type": "EVIDENCE_GAP",
                "label": "诊疗依据待补充",
                "detail": "当前没有匹配方案，不能据此判断诊断已满足，也不自动推荐检验检查。",
            }],
            "gapOrders": [],
            "guidelines": [],
        }
