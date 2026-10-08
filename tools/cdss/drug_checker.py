"""
Drug Monograph Repository and CDSS Contraindication Auditor.
Provides structured drug monograph management, fast indexing,
and rigorous rule-based contraindication & DDI auditing aligned with
NMPA official package inserts and China Pharmacopoeia Clinical Formulary.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiPage


class DrugInsertRepository:
    """Manages structured drug insert monographs located in wiki/inserts/."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.inserts_dir = self.root_dir / "wiki" / "inserts"
        self._drugs: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, str] = {}  # alias/generic/trade -> filename stem
        self.load_all()

    def load_all(self) -> None:
        """Loads and parses all drug insert markdown files in wiki/inserts/."""
        self._drugs.clear()
        self._index.clear()

        if not self.inserts_dir.exists():
            return

        for fpath in sorted(self.inserts_dir.glob("*.md")):
            stem = fpath.stem
            page = WikiPage(fpath, self.root_dir / "wiki")
            fm = page.frontmatter
            
            drug_entry = {
                "id": stem,
                "generic_name": fm.get("generic_name", stem),
                "english_name": fm.get("english_name", ""),
                "category": fm.get("category", ""),
                "atc_code": fm.get("atc_code", ""),
                "approval_category": fm.get("approval_category", ""),
                "trade_names": fm.get("trade_names", []),
                "forms_and_specs": fm.get("forms_and_specs", []),
                "max_daily_dose": fm.get("max_daily_dose", ""),
                "standard_maintenance_dose": fm.get("standard_maintenance_dose", ""),
                "key_contraindications": fm.get("key_contraindications", []),
                "special_populations": fm.get("special_populations") if isinstance(fm.get("special_populations"), dict) else {},
                "storage": fm.get("storage", ""),
                "sources": fm.get("sources", []),
                "tags": fm.get("tags", []),
                "raw_body": page.body,
                "title": page.title,
                "rel_path": str(page.rel_path),
            }
            self._drugs[stem] = drug_entry

            # Index primary stem & generic name
            self._index[stem.lower()] = stem
            if drug_entry["generic_name"]:
                self._index[drug_entry["generic_name"].lower()] = stem
                # Index common simplified name (e.g. "二甲双胍" from "盐酸二甲双胍片")
                simplified = re.sub(r"(盐酸|硫酸|富马酸|马来酸|草酸|苯磺酸|酒石酸|枸橼酸|丙酸|微粉化|肠溶|缓释|控释|片|胶囊|气雾剂|散|软膏|乳膏|分散片|滴丸|胶丸|口服溶液)", "", drug_entry["generic_name"])
                if len(simplified) >= 2:
                    self._index[simplified.lower()] = stem

            if drug_entry["english_name"]:
                self._index[drug_entry["english_name"].lower()] = stem

            if drug_entry["atc_code"]:
                self._index[drug_entry["atc_code"].lower()] = stem

            for trade in drug_entry["trade_names"]:
                self._index[trade.lower()] = stem

    def list_all(self) -> List[Dict[str, Any]]:
        """Returns summarized metadata of all registered drug monographs."""
        return [
            {
                "id": d["id"],
                "generic_name": d["generic_name"],
                "english_name": d["english_name"],
                "category": d["category"],
                "atc_code": d["atc_code"],
                "approval_category": d["approval_category"],
                "trade_names": d["trade_names"],
                "forms_and_specs": d["forms_and_specs"],
                "max_daily_dose": d["max_daily_dose"],
                "standard_maintenance_dose": d["standard_maintenance_dose"],
                "key_contraindications": d["key_contraindications"],
                "tags": d["tags"],
                "rel_path": d["rel_path"],
            }
            for d in self._drugs.values()
        ]

    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """Resolves a drug by name, alias, trade name, or ATC code."""
        if not query:
            return None
        q_clean = query.strip().lower()
        if q_clean in self._index:
            return self._drugs.get(self._index[q_clean])
        # Direct stem match
        for stem, d in self._drugs.items():
            if q_clean in stem.lower() or stem.lower() in q_clean:
                return d
            if q_clean in d["generic_name"].lower():
                return d
        return None

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Keyword search across generic names, trade names, indications, and categories."""
        if not query:
            return self.list_all()[:limit]
        q_clean = query.strip().lower()
        exact = self.get(q_clean)
        matches = []
        if exact:
            matches.append(exact)

        for d in self._drugs.values():
            if exact and d["id"] == exact["id"]:
                continue
            if (
                q_clean in d["generic_name"].lower()
                or q_clean in d["english_name"].lower()
                or q_clean in d["category"].lower()
                or any(q_clean in tn.lower() for tn in d["trade_names"])
                or q_clean in d["raw_body"].lower()
            ):
                matches.append(d)
                if len(matches) >= limit:
                    break
        return matches[:limit]


class DrugContraindicationAuditor:
    """Performs rigorous CDSS contraindication and DDI auditing for a patient."""

    def __init__(self, repo: Optional[DrugInsertRepository] = None, root_dir: Optional[Path] = None):
        self.repo = repo or DrugInsertRepository(root_dir)

    def audit(self, drug_query: str, patient: Dict[str, Any]) -> Dict[str, Any]:
        """
        Audits a drug prescription against patient parameters.
        Returns:
            canPrescribe: bool
            level: 'PASS' | 'WARNING' | 'BLOCK'
            alerts: List[Dict[str, str]]
            renalGuidance: str
            specialPopulationNotes: List[str]
            drugInteractions: List[str]
        """
        drug = self.repo.get(drug_query)
        if not drug:
            return {
                "success": False,
                "error": f"未在权威药品说明书知识库中检索到药品: '{drug_query}'",
                "canPrescribe": False,
                "level": "UNKNOWN",
                "alerts": [],
            }

        gname = drug["generic_name"]
        alerts: List[Dict[str, Any]] = []
        notes: List[str] = []
        ddi_alerts: List[str] = []

        # Extract patient attributes
        age = patient.get("age")
        is_pregnant = bool(patient.get("pregnancy")) or bool(patient.get("is_pregnant"))
        is_lactating = bool(patient.get("lactation")) or bool(patient.get("is_lactating"))
        egfr = patient.get("egfr")
        if egfr is not None:
            try:
                egfr = float(egfr)
            except (ValueError, TypeError):
                egfr = None

        conditions = [str(c).lower() for c in patient.get("conditions", [])]
        allergies = [str(a).lower() for a in patient.get("allergies", [])]
        concurrent_drugs = [str(d).lower() for d in patient.get("concurrent_drugs", [])]

        # ---------------- 1. Renal eGFR Cutoffs ----------------
        renal_guidance = drug.get("special_populations", {}).get("renal_impairment", "")
        if egfr is not None:
            # Metformin: eGFR < 30 BLOCK, 30~44 WARNING
            if "二甲双胍" in gname:
                if egfr < 30:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_EGFR_LT_30",
                        "title": "重度肾功能不全绝对禁用",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 30)，说明书明确列为绝对禁忌！严防二甲双胍蓄积诱发致死性乳酸酸中毒（病死率达50%）！",
                        "evidence": "《国家药品监督管理局官方核准盐酸二甲双胍片说明书》【禁忌】及中国药典临床用药须知",
                    })
                elif egfr < 45:
                    alerts.append({
                        "level": "WARNING",
                        "rule": "RENAL_EGFR_30_44",
                        "title": "中重度肾损伤谨慎减量",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (30~44)，建议每日最大剂量不超过 500mg~1000mg，并每3个月严密复查肾功能。",
                        "evidence": "2024版《中国2型糖尿病防治指南》二甲双胍肾功能剂量分级调整规范",
                    })

            # Alendronate: eGFR < 35 BLOCK
            elif "阿仑膦酸钠" in gname:
                if egfr < 35:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_EGFR_LT_35",
                        "title": "重度肾功能不全禁用双膦酸盐",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 35)，双膦酸盐蓄积易致急性肾小管毒性，说明书列为绝对禁忌！",
                        "evidence": "《阿仑膦酸钠片说明书》【禁忌】",
                    })

            # Dapagliflozin: eGFR < 20 or dialysis BLOCK
            elif "达格列净" in gname:
                if egfr < 20:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_EGFR_LT_20",
                        "title": "终末期肾病/透析禁用SGLT2抑制剂",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 20)，无肾小球滤过有效底物，控糖及心肾获益丧失，禁用！",
                        "evidence": "《达格列净片说明书》【特殊人群用药】",
                    })
                elif egfr < 45:
                    alerts.append({
                        "level": "WARNING",
                        "rule": "RENAL_EGFR_LT_45_GLUCOSE",
                        "title": "降糖效果减弱提示",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 45)，达格列净排糖控糖疗效显著衰减，若仅为单纯降糖不推荐起始，但心衰或CKD保护仍可维持10mg qd。",
                        "evidence": "《达格列净片说明书》【用法用量】",
                    })

            # Hydrochlorothiazide / Indapamide: eGFR < 30 BLOCK
            elif "氢氯噻嗪" in gname or "吲达帕胺" in gname:
                if egfr < 30:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_EGFR_LT_30_THIAZIDE",
                        "title": "重度肾功能衰竭禁用噻嗪类利尿剂",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 30)，噻嗪类利尿剂在肾小球滤过率极低时完全丧失利尿降压活性且易蓄积中毒，应换用袢利尿剂（呋塞米/托拉塞米）！",
                        "evidence": "《中国药典临床用药须知》利尿药章节",
                    })

            # Empagliflozin: eGFR < 20 or dialysis BLOCK, < 45 WARNING
            elif "恩格列净" in gname:
                if egfr < 20:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_EGFR_LT_20_EMPA",
                        "title": "终末期肾病/透析禁用SGLT2抑制剂(恩格列净)",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 20)，缺乏肾小球有效滤过底物，控糖与靶器官获益丧失，说明书列为禁忌！",
                        "evidence": "《恩格列净片说明书》【特殊人群用药】",
                    })
                elif egfr < 45:
                    alerts.append({
                        "level": "WARNING",
                        "rule": "RENAL_EGFR_LT_45_EMPA_GLUCOSE",
                        "title": "降糖效果减弱提示",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 45)，恩格列净降糖效果减弱，单纯降糖不建议起始，但心衰/CKD适应证仍可使用10mg qd。",
                        "evidence": "《恩格列净片说明书》【用法用量】",
                    })

            # Rivaroxaban: eGFR < 15 BLOCK, 15~49 WARNING
            elif "利伐沙班" in gname:
                if egfr < 15:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_RIVAROXABAN_LT_15",
                        "title": "重度肾功能不全禁用利伐沙班",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 15)，血药浓度显著蓄积，诱发不可逆大出血风险极高，说明书列为禁忌！",
                        "evidence": "《利伐沙班片说明书》【禁忌】",
                    })
                elif egfr < 50:
                    alerts.append({
                        "level": "WARNING",
                        "rule": "RENAL_RIVAROXABAN_15_49_ADJUST",
                        "title": "中度肾功能受损剂量下调警示",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (15~49)，用于非瓣膜性房颤卒中预防时，推荐剂量由每日20mg下调至每日15mg顿服！",
                        "evidence": "《利伐沙班片说明书》【肾功能不全患者用法用量】",
                    })

            # Dabigatran: eGFR < 30 BLOCK, 30~50 WARNING
            elif "达比加群" in gname:
                if egfr < 30:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_DABIGATRAN_LT_30",
                        "title": "重度肾损伤绝对禁用达比加群酯",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 30)，达比加群80%依赖肾脏原型清除，严重肾功能损害导致极度蓄积诱发致死性出血！",
                        "evidence": "《甲磺酸达比加群酯胶囊说明书》【禁忌】",
                    })
                elif egfr <= 50:
                    alerts.append({
                        "level": "WARNING",
                        "rule": "RENAL_DABIGATRAN_30_50_ADJUST",
                        "title": "中度肾损伤推荐减量使用",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (30~50)，存在出血高危风险，建议酌情减量至每次110mg，每日2次，并严密监测肾功能！",
                        "evidence": "《甲磺酸达比加群酯胶囊说明书》【用法用量】",
                    })

            # Spironolactone / Compound Reserpine (Potassium sparing): eGFR < 30 BLOCK
            elif "螺内酯" in gname or "氨苯蝶啶" in gname:
                if egfr < 30:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_SPIRONOLACTONE_LT_30",
                        "title": "重度肾功能不全禁用保钾利尿剂",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 30)，排钾障碍叠加保钾利尿效应，极易暴发致死性高钾血症与心脏骤停！",
                        "evidence": "《螺内酯片说明书》及《复方利血平氨苯蝶啶片说明书》【禁忌】",
                    })

            # Duloxetine: eGFR < 30 BLOCK
            elif "度洛西汀" in gname:
                if egfr < 30:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_DULOXETINE_LT_30",
                        "title": "终末期肾病禁用盐酸度洛西汀",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 30)，活性代谢物血药浓度增加数十倍，说明书明确列为禁忌！",
                        "evidence": "《盐酸度洛西汀肠溶胶囊说明书》【禁忌】",
                    })

            # Bismuth: eGFR < 30 BLOCK
            elif "铋" in gname:
                if egfr < 30:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_EGFR_LT_30_BISMUTH",
                        "title": "重度肾功能衰竭绝对禁用铋剂",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 30)，吸收的微量铋无法经肾脏排泄，诱发致死性神经系统铋蓄积中毒性脑病及急性肾小管坏死！",
                        "evidence": "《枸橼酸铋钾胶囊说明书》【禁忌】",
                    })

            # Levofloxacin: eGFR < 50 WARNING/ADJUST
            elif "左氧氟沙星" in gname:
                if egfr < 20:
                    alerts.append({
                        "level": "WARNING",
                        "rule": "RENAL_LEVO_LT_20",
                        "title": "严重肾损伤必须延长给药间隔",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 20)，左氧氟沙星首剂0.5g，维持剂量必须调整为每48小时0.25g！",
                        "evidence": "《左氧氟沙星片说明书》【肾功能减退患者用法用量】",
                    })
                elif egfr < 50:
                    alerts.append({
                        "level": "WARNING",
                        "rule": "RENAL_LEVO_LT_50",
                        "title": "中度肾损伤剂量减半滴定",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 50)，首剂0.5g后，维持剂量必须下调至每24小时0.25g！",
                        "evidence": "《左氧氟沙星片说明书》【肾功能减退患者用法用量】",
                    })

            # Benzbromarone: eGFR < 20 BLOCK
            elif "苯溴马隆" in gname:
                if egfr < 20:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_BENZ_LT_20",
                        "title": "重度肾功能损害禁用苯溴马隆",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 20)，促尿酸排泄药失去肾小管分泌作用底物，说明书列为禁忌！",
                        "evidence": "《苯溴马隆片说明书》【禁忌】",
                    })

            # Cetirizine: eGFR < 10 BLOCK
            elif "西替利嗪" in gname:
                if egfr < 10:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_CETIRIZINE_LT_10",
                        "title": "终末期肾病绝对禁用西替利嗪",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 10)，主要以原型经肾排泄，严重蓄积可致中枢中毒！",
                        "evidence": "《盐酸西替利嗪片说明书》【禁忌】",
                    })

            # Rosuvastatin / Pitavastatin: eGFR < 30 BLOCK
            elif any(k in gname for k in ["瑞舒伐他汀", "匹伐他汀"]):
                if egfr < 30:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_ROSUVA_LT_30",
                        "title": "重度肾功能受损禁用他汀强效类",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 30)，血药浓度成倍蓄积，横纹肌溶解与肌毒性风险剧增，说明书列为禁忌！",
                        "evidence": "官方药品说明书【禁忌】及中国药典临床用药须知",
                    })

            # NSAIDs: eGFR < 30 BLOCK
            elif any(k in gname for k in ["布洛芬", "双氯芬酸", "塞来昔布", "依托考昔", "艾瑞昔布"]):
                if egfr < 30:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "RENAL_NSAIDS_LT_30",
                        "title": "重度肾衰竭禁用非甾体抗炎药",
                        "reason": f"患者 eGFR = {egfr} mL/min/1.73m² (< 30)，NSAIDs抑制肾前列腺素合成导致肾血管剧烈收缩，诱发不可逆无尿急性肾损伤！",
                        "evidence": "中国临床药学专家共识《NSAIDs合理用药规范》",
                    })

        # ---------------- 2. Pregnancy & Lactation ----------------
        if is_pregnant:
            # ACEI / ARB / ARNI
            if any(k in gname for k in ["缬沙坦", "氯沙坦", "厄贝沙坦", "依那普利", "沙库巴曲"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "PREGNANCY_RAS_INHIBITOR",
                    "title": "妊娠期绝对禁用 RAS/ARNI 抑制剂 (普利/沙坦/沙库巴曲类)",
                    "reason": "FDA 明确评定为 D 类/严重致畸黑框！妊娠中晚期使用可直接致胎儿肾发育不全、无尿、羊水过少、颅骨发育畸形及胎死宫内！发现妊娠必须立即停药并改用甲基多巴或拉贝洛尔！",
                    "evidence": "《中国高血压防治指南》及官方药品说明书【黑框警告】",
                })
            # Statins
            elif any(k in gname for k in ["阿托伐他汀", "瑞舒伐他汀", "匹伐他汀"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "PREGNANCY_STATIN_X",
                    "title": "妊娠期绝对禁用他汀类降脂药 (FDA X类)",
                    "reason": "胆固醇及其生物合成产物为胎儿神经及器官组织发育所必需，他汀类具有明确的人类致畸性与流产风险，育龄期服药必须严格避孕！",
                    "evidence": "官方药品说明书【禁忌】",
                })
            # Anticoagulants (Rivaroxaban / Dabigatran)
            elif any(k in gname for k in ["利伐沙班", "达比加群"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "PREGNANCY_NOAC",
                    "title": "妊娠期禁用新型口服抗凝药 (NOAC)",
                    "reason": "利伐沙班与达比加群可通过胎盘屏障，具有明显的胚胎毒性与产道大出血风险，孕期抗凝优先选择低分子肝素！",
                    "evidence": "《利伐沙班片说明书》及《甲磺酸达比加群酯胶囊说明书》【禁忌】",
                })
            # Quinolones
            elif any(k in gname for k in ["左氧氟沙星", "莫西沙星", "诺氟沙星"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "PREGNANCY_QUINOLONES",
                    "title": "妊娠期绝对禁用氟喹诺酮类抗菌药",
                    "reason": "动物试验明确显示喹诺酮类可引起负重关节软骨持久性侵蚀坏死畸变，妊娠期禁用！",
                    "evidence": "官方药品说明书【禁忌】",
                })
            # NSAIDs
            elif any(k in gname for k in ["布洛芬", "双氯芬酸", "塞来昔布", "依托考昔", "艾瑞昔布"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "PREGNANCY_NSAIDS_THIRD_TRIMESTER",
                    "title": "妊娠期禁用口服非甾体抗炎药",
                    "reason": "尤其在孕20周后慎用，孕30周后绝对禁用！抑制前列腺素导致胎儿动脉导管过早闭合、持续性肺动脉高压及难产！",
                    "evidence": "国家药监局《关于修订含NSAIDs口服制剂说明书的公告》",
                })
            # Sedative hypnotics & Tramadol
            elif any(k in gname for k in ["艾司唑仑", "唑吡坦", "曲马多"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "PREGNANCY_BENZO_ZDRUG",
                    "title": "妊娠期禁用镇静催眠药及中枢镇痛药",
                    "reason": "致畸畸胎风险，临产前用药可导致新生儿松弛肌无力综合征（Floppy Infant）与严重呼吸中枢抑制！",
                    "evidence": "官方药品说明书【禁忌】",
                })
            # Sulfonylurea
            elif "格列美脲" in gname:
                alerts.append({
                    "level": "BLOCK",
                    "rule": "PREGNANCY_SULFONYLUREA",
                    "title": "妊娠期禁用磺脲类促泌剂",
                    "reason": "可穿透胎盘引起新生儿持久性严重致死性低血糖，孕期控糖必须换用胰岛素！",
                    "evidence": "《格列美脲片说明书》【禁忌】",
                })
            # Gout
            elif any(k in gname for k in ["别嘌醇", "苯溴马隆", "非布司他"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "PREGNANCY_GOUT_DRUGS",
                    "title": "妊娠期禁用降尿酸药物",
                    "reason": "具有生殖胚胎毒性与流产风险，孕妇痛风仅限对症处理，禁用别嘌醇、苯溴马隆与非布司他！",
                    "evidence": "《中国高尿酸血症与痛风诊疗指南》",
                })

        if is_lactating:
            if any(k in gname for k in ["他汀", "格列美脲", "艾司唑仑", "唑吡坦", "左氧氟沙星", "莫西沙星", "诺氟沙星", "利伐沙班", "达比加群"]):
                notes.append("哺乳期提示：该药物可通过母乳排泄，存在潜在婴儿不良反应，建议服药期间暂停母乳喂养。")

        # ---------------- 3. Pediatric & Elderly Rules ----------------
        if age is not None:
            if age < 18:
                # Quinolones in pediatric
                if any(k in gname for k in ["左氧氟沙星", "莫西沙星", "诺氟沙星"]):
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "PEDIATRIC_QUINOLONES_LT_18",
                        "title": "18岁以下未成年人绝对禁用喹诺酮类",
                        "reason": "软骨发育毒性黑框警告！在未成年儿童中可导致负重关节软骨坏死侵蚀与关节病变，18岁以下绝对禁用！",
                        "evidence": "国家药监局法定说明书黑框警告及《抗菌药物临床应用指导原则》",
                    })
                # Tramadol in pediatric
                if "曲马多" in gname and age < 12:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "PEDIATRIC_TRAMADOL_LT_12",
                        "title": "12岁以下儿童绝对禁用曲马多",
                        "reason": "曲马多具有呼吸抑制致死黑框风险，因儿童CYP2D6超快代谢个体差异可暴发致死性阿片中毒，12岁以下禁用！",
                        "evidence": "国家药监局官方说明书【黑框警告】",
                    })
                # Aspirin in viral infection
                if "阿司匹林" in gname and any(c in conditions for c in ["上感", "流感", "感冒", "发热", "水痘", "病毒感染"]):
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "PEDIATRIC_ASPIRIN_REYES",
                        "title": "儿童病毒感染发热严禁使用阿司匹林",
                        "reason": "致死性瑞氏综合征（Reye's Syndrome）黑框警告！儿童在流感或水痘等病毒感染发热期服用阿司匹林可暴发急性脑病与肝脂肪变性（死亡率高达50%）！",
                        "evidence": "《阿司匹林肠溶片说明书》【黑框警告】",
                    })
            elif age >= 65:
                # Estazolam in elderly
                if "艾司唑仑" in gname:
                    alerts.append({
                        "level": "WARNING",
                        "rule": "ELDERLY_ESTAZOLAM_BEERS",
                        "title": "高龄老年人避免常规使用长效安定",
                        "reason": f"患者年龄 {age} 岁 (>= 65)。符合国际 Beers 标准与国家处方精简警示：艾司唑仑具有显著肌松与宿醉效应，老年人夜间极易发生严重跌倒骨折、谵妄及认知急剧衰退，必须优先非药物 CBTI 或选用短半衰期促眠药！",
                        "evidence": "中华医学会《基层医疗卫生机构老年人多重用药与慢病共病全科安全管理指南》",
                    })

        # ---------------- 4. Allergies ----------------
        for alg in allergies:
            if "青霉素" in alg and any(k in gname for k in ["阿莫西林"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "ALLERGY_PENICILLIN_AMOXICILLIN",
                    "title": "青霉素过敏患者绝对禁用阿莫西林",
                    "reason": "阿莫西林为青霉素类β-内酰胺抗菌药，青霉素过敏者使用可诱发致死性过敏性休克与窒息，系统最高级别红色阻断！",
                    "evidence": "《阿莫西林胶囊说明书》【禁忌】",
                })
            elif "头孢" in alg and any(k in gname for k in ["头孢克肟", "头孢呋辛"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "ALLERGY_CEPHALOSPORIN_CEFIXIME",
                    "title": "头孢类过敏患者绝对禁用头孢菌素",
                    "reason": f"头孢菌素过敏史患者禁用{gname}，防严重过敏反应！",
                    "evidence": "官方药品说明书【禁忌】",
                })
            elif "磺胺" in alg and ("塞来昔布" in gname or "吲达帕胺" in gname or "格列美脲" in gname):
                alerts.append({
                    "level": "BLOCK" if "塞来昔布" in gname else "WARNING",
                    "rule": "ALLERGY_SULFONAMIDE_CROSS",
                    "title": "磺胺过敏交叉过敏警告",
                    "reason": f"{gname}化学结构含苯磺酰胺基团，磺胺类药物过敏史者禁用塞来昔布（严重剥脱性皮炎及休克风险）！",
                    "evidence": "《塞来昔布胶囊说明书》【禁忌】",
                })
            elif "阿司匹林" in alg and any(k in gname for k in ["阿司匹林", "布洛芬", "双氯芬酸", "塞来昔布", "依托考昔", "艾瑞昔布"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "ALLERGY_ASPIRIN_TRIAD",
                    "title": "阿司匹林哮喘三联征禁用非甾体抗炎药",
                    "reason": "NSAIDs交叉诱发严重致死性支气管痉挛与喉头水肿，绝对禁用！",
                    "evidence": "国家药监局官方说明书【禁忌】",
                })

        # ---------------- 5. Patient Conditions ----------------
        for cond in conditions:
            # Heart condition + Diclofenac / Etoricoxib / Imrecoxib
            if any(k in cond for k in ["心肌梗死", "冠心病", "心绞痛", "脑梗", "卒中", "cabg"]):
                if any(k in gname for k in ["双氯芬酸", "依托考昔", "塞来昔布"]):
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_CVD_NSAIDS",
                        "title": "确诊心脑血管疾病禁用强效COX-2/双氯芬酸",
                        "reason": f"患者合并心脑血管疾病（{cond}），依托考昔/双氯芬酸显著增加心血管动脉血栓事件、心肌梗死与卒中猝死风险，欧洲EMA及NMPA明确列为禁忌！",
                        "evidence": "官方核准说明书【黑框警告】",
                    })

            # Semaglutide + MTC / MEN 2
            if any(k in cond for k in ["甲状腺髓样癌", "mtc", "men 2", "men2", "多发性内分泌腺瘤"]):
                if "司美格鲁肽" in gname:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_SEMAGLUTIDE_MTC",
                        "title": "甲状腺髓样癌/MEN 2 家族史绝对禁用司美格鲁肽",
                        "reason": "黑框警告！啮齿类及临床监测显示GLP-1受体激动剂具有甲状腺C细胞肿瘤致癌性，既往或家族有MTC或MEN 2病史者绝对禁用！",
                        "evidence": "《司美格鲁肽注射液说明书》【黑框警告】",
                    })

            # Reserpine + Depression
            if any(k in cond for k in ["抑郁", "自杀", "抑郁症", "重性抑郁"]):
                if "复方利血平" in gname:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_RESERPINE_DEPRESSION",
                        "title": "活动性抑郁症患者绝对禁用复方利血平制剂",
                        "reason": "利血平耗竭中枢单胺递质（多巴胺、去甲肾上腺素、5-HT），可诱发严重难治性抑郁发作及恶性自杀冲动，说明书列为绝对禁忌！",
                        "evidence": "《复方利血平氨苯蝶啶片说明书》【禁忌】",
                    })

            # Tramadol + Epilepsy / Respiratory depression
            if any(k in cond for k in ["癫痫", "抽搐", "惊厥", "严重呼吸衰竭"]):
                if "曲马多" in gname:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_TRAMADOL_EPILEPSY",
                        "title": "癫痫病史或严重呼吸抑制禁用曲马多",
                        "reason": "曲马多显著降低大脑惊厥抽搐阈值，诱发大发作性癫痫持续状态，且抑制呼吸中枢，说明书列为禁忌！",
                        "evidence": "《盐酸曲马多缓释片说明书》【禁忌】",
                    })

            # Tolterodine + Urinary retention / glaucoma
            if any(k in cond for k in ["尿潴留", "前列腺肥大伴尿潴留", "重度前列腺增生", "闭角型青光眼"]):
                if "托特罗定" in gname:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_TOLTERODINE_URINARY_RETENTION",
                        "title": "尿潴留或未控制闭角型青光眼绝对禁用托特罗定",
                        "reason": "M受体拮抗剂阻断膀胱逼尿肌收缩，可诱发急性尿潴留危象，说明书列为绝对禁忌！",
                        "evidence": "《酒石酸托特罗定片说明书》【禁忌】",
                    })

            # Dabigatran + Mechanical Heart Valve
            if any(k in cond for k in ["机械瓣", "机械心脏瓣膜", "人工瓣膜置换"]):
                if "达比加群" in gname:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_DABIGATRAN_MECHANICAL_VALVE",
                        "title": "机械心脏瓣膜置换术后绝对禁用达比加群酯",
                        "reason": "RE-ALIGN大型临床试验明确证实：机械瓣患者使用达比加群血栓栓塞与大出血风险显著高于传统华法林，说明书列为绝对禁忌！",
                        "evidence": "《甲磺酸达比加群酯胶囊说明书》【禁忌】",
                    })

            # Peptic ulcer / Bleeding + NSAIDs / Aspirin / Rivaroxaban
            if any(k in cond for k in ["胃溃疡", "十二指肠溃疡", "消化道出血", "穿孔", "黑便", "呕血", "活动性出血"]):
                if any(k in gname for k in ["布洛芬", "双氯芬酸", "阿司匹林", "艾瑞昔布"]):
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_GI_BLEEDING_NSAIDS",
                        "title": "活动性消化性溃疡/大出血绝对禁用NSAIDs",
                        "reason": f"患者存在活动性消化道病变（{cond}），NSAIDs抑制前列腺素并抗血小板，极易诱发暴发性胃肠大出血休克穿孔致死！",
                        "evidence": "《布洛芬缓释胶囊说明书》【禁忌】",
                    })
                elif any(k in gname for k in ["利伐沙班", "达比加群"]):
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_ACTIVE_BLEEDING_NOAC",
                        "title": "活动性大出血疾病绝对禁用新型口服抗凝药",
                        "reason": f"患者存在活动性出血病变（{cond}），强效抗凝治疗导致止血不能，诱发不可逆失血性休克致死！",
                        "evidence": "官方抗凝药品说明书【禁忌】",
                    })

            # Uncontrolled Hypertension + Etoricoxib
            if any(k in cond for k in ["未控制高血压", "重度高血压", "血压>140"]):
                if "依托考昔" in gname:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_UNCONTROLLED_HTN_ETORICOXIB",
                        "title": "未控制高血压患者绝对禁用依托考昔",
                        "reason": "依托考昔升高血压效应极其显著，血压未控制达标（>140/90）者使用可诱发恶性高血压与脑卒中猝死，说明书列为绝对禁忌！",
                        "evidence": "《依托考昔片说明书》【禁忌】",
                    })

            # Heart block / severe bradycardia + Beta blockers / Diltiazem
            if any(k in cond for k in ["窦缓", "心动过缓", "房室传导阻滞", "病窦"]):
                if any(k in gname for k in ["美托洛尔", "比索洛尔", "地尔硫䓬"]):
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_HEART_BLOCK_BETABLOCKER",
                        "title": "严重心动过缓或房室传导阻滞禁用负性变时药",
                        "reason": "负性心率与房室负性传导抑制作用，极易诱发严重阿-斯综合征与心脏骤停！",
                        "evidence": "官方药品说明书【禁忌】",
                    })

            # Myasthenia gravis + Quinolones / Estazolam
            if "重症肌无力" in cond:
                if any(k in gname for k in ["左氧氟沙星", "莫西沙星", "诺氟沙星", "艾司唑仑"]):
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_MYASTHENIA_GRAVIS_BLOCK",
                        "title": "重症肌无力绝对禁用喹诺酮及安定类",
                        "reason": "神经肌肉接头传递抑制，可暴发诱发重症肌无力危象致窒息死亡！",
                        "evidence": "国家药监局官方说明书【黑框警告】",
                    })

            # Uric acid stone + Benzbromarone
            if any(k in cond for k in ["肾结石", "尿酸性肾结石", "尿结石"]):
                if "苯溴马隆" in gname:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_KIDNEY_STONE_BENZ",
                        "title": "尿酸性肾结石病史绝对禁用苯溴马隆",
                        "reason": "促使大量尿酸排入尿路，极易堵塞输尿管诱发急性无尿与梗阻性肾衰竭！",
                        "evidence": "《苯溴马隆片说明书》【禁忌】",
                    })

            # Iodine contrast + Metformin
            if any(k in cond for k in ["碘造影", "造影剂", "增强ct"]):
                if "二甲双胍" in gname:
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "CONDITION_IODINE_CONTRAST_METFORMIN",
                        "title": "血管内注射碘化造影剂前后48小时停用二甲双胍",
                        "reason": "造影剂急性肾损伤可诱发二甲双胍严重蓄积导致致死性乳酸酸中毒，检查前后48小时必须停药！",
                        "evidence": "《中国2型糖尿病防治指南》造影规范",
                    })

        # ---------------- 6. Drug-Drug Interactions (DDI) ----------------
        for cd in concurrent_drugs:
            # Sacubitril/Valsartan (ARNI) + ACEI (Piril) -> 36h Washout Block
            if "沙库巴曲" in gname and any(k in cd for k in ["普利", "依那普利", "培哚普利", "贝那普利", "雷米普利", "卡托普利"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_ARNI_ACEI_WASHOUT_36H",
                    "title": "ARNI 严禁合用 ACEI (36小时洗脱期致死性血管水肿黑框)",
                    "reason": f"患者合用 {cd}。沙库巴曲（脑啡肽酶抑制剂）与普利类（ACEI）双重阻断缓激肽降解途径，极高概率暴发致死性急性喉头血管神经性水肿与窒息猝死！说明书与心衰指南严禁联用，停用ACEI后必须至少间隔36小时才可起始沙库巴曲缬沙坦；反之亦然！",
                    "evidence": "《沙库巴曲缬沙坦钠片说明书》【黑框警告】及国家医保基药临床指导规范",
                })
            # ACEI + Sacubitril/Valsartan (reverse check)
            if any(k in gname for k in ["普利", "依那普利", "培哚普利", "贝那普利"]) and "沙库巴曲" in cd:
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_ACEI_ARNI_WASHOUT_36H",
                    "title": "ACEI 严禁合用 ARNI (36小时洗脱期致死性血管水肿黑框)",
                    "reason": f"普利类药物与沙库巴曲联用极易暴发致死性急性喉头水肿，严禁联合使用，且必须遵循36小时洗脱期！",
                    "evidence": "《沙库巴曲缬沙坦钠片说明书》【黑框警告】",
                })

            # Febuxostat + Azathioprine / Mercaptopurine
            if "非布司他" in gname and any(k in cd for k in ["硫唑嘌呤", "巯嘌呤"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_FEBUXOSTAT_AZATHIOPRINE",
                    "title": "非布司他严禁合用硫唑嘌呤/巯嘌呤 (致死性骨髓抑制黑框)",
                    "reason": f"患者合用 {cd}。非布司他强效抑制黄嘌呤氧化酶，阻断硫唑嘌呤/巯嘌呤的氧化代谢消除，致使细胞毒性活性代谢产物浓度暴增数十倍，诱发致死性全血细胞减少与重度骨髓衰竭，说明书列为绝对禁忌！",
                    "evidence": "《非布司他片说明书》【禁忌】",
                })

            # Nitrates + Sildenafil / Tadalafil (including Isosorbide mononitrate)
            if any(k in gname for k in ["硝酸甘油", "单硝酸异山梨酯"]) and any(k in cd for k in ["西地那非", "他达拉非", "伐地那非", "伟哥", "pde5"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_NITRO_PDE5I",
                    "title": "硝酸酯类合用 PDE-5 抑制剂致死性休克强行阻断",
                    "reason": f"患者合用 {cd}。硝酸酯类与西地那非或他达拉非联用，协同使血管平滑肌cGMP剧增致不可逆恶性低血压休克猝死，系统红色最高级强行拦截！",
                    "evidence": "《单硝酸异山梨酯缓释片说明书》及官方药品说明书【黑框警告】",
                })

            # NOACs (Rivaroxaban / Dabigatran) + Strong CYP3A4/P-gp inhibitors (Ketoconazole / Itraconazole)
            if any(k in gname for k in ["利伐沙班", "达比加群"]) and any(k in cd for k in ["酮康唑", "伊曲康唑", "利托那韦", "伏立康唑"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_NOAC_STRONG_CYP3A4_PGP",
                    "title": "新型口服抗凝药严禁联用强效 CYP3A4/P-gp 抑制剂",
                    "reason": f"患者合用 {cd}。强效抑制剂使利伐沙班/达比加群血药浓度暴露量升高数倍，导致大出血休克致死风险剧增，说明书列为禁忌！",
                    "evidence": "《利伐沙班片说明书》及《甲磺酸达比加群酯胶囊说明书》【禁忌】",
                })

            # Tramadol / Duloxetine + MAOIs
            if any(k in gname for k in ["曲马多", "度洛西汀"]) and any(k in cd for k in ["单胺氧化酶", "司来吉兰", "吗氯贝胺"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_TRAMADOL_MAOI",
                    "title": "曲马多/度洛西汀严禁联用单胺氧化酶抑制剂 (MAOI)",
                    "reason": f"患者合用 {cd}。抑制神经递质再摄取与代谢分解，可诱发恶性五羟色胺综合征（高热、癫痫、昏迷、死亡），必须至少间隔14天！",
                    "evidence": "官方药品说明书【禁忌】",
                })

            # Clopidogrel + Omeprazole
            if "氯吡格雷" in gname and any(k in cd for k in ["奥美拉唑", "艾司奥美拉唑"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_CLOPIDOGREL_OMEPRAZOLE",
                    "title": "氯吡格雷严禁合用奥美拉唑 (支架血栓致死黑框)",
                    "reason": f"患者合用 {cd}。奥美拉唑强效竞争性抑制CYP2C19，阻断氯吡格雷向活性抗血小板形态转化，致抗栓疗效崩塌诱发支架内急性血栓与心肌梗死猝死！必须换用雷贝拉唑或泮托拉唑！",
                    "evidence": "《硫酸氢氯吡格雷片说明书》【黑框警告】",
                })

            # Omeprazole + Clopidogrel (reverse check)
            if "奥美拉唑" in gname and "氯吡格雷" in cd:
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_OMEPRAZOLE_CLOPIDOGREL",
                    "title": "奥美拉唑严禁合用氯吡格雷 (抗血小板失效黑框)",
                    "reason": "奥美拉唑强效抑制CYP2C19破坏氯吡格雷抗血栓疗效，合用患者必须更换为雷贝拉唑或泮托拉唑！",
                    "evidence": "国家药监局与美国FDA黑框警告",
                })

            # Simvastatin + Clarithromycin
            if any(k in gname for k in ["克拉霉素"]) and any(k in cd for k in ["辛伐他汀", "洛伐他汀"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_CLARITHRO_SIMVASTATIN",
                    "title": "克拉霉素严禁合用辛伐他汀 (横纹肌溶解黑框)",
                    "reason": "克拉霉素强效抑制CYP3A4使辛伐他汀血药浓度飙升5~10倍，诱发急性大面积横纹肌溶解与急性肾衰竭，严禁联用！",
                    "evidence": "《克拉霉素片说明书》【禁忌】",
                })

            # Dual RAS Blockade (ACEI + ARB)
            if any(k in gname for k in ["依那普利", "缬沙坦", "氯沙坦", "厄贝沙坦", "沙库巴曲"]) and any(k in cd for k in ["普利", "沙坦"]):
                if not any(k in cd and k in gname for k in ["依那普利", "缬沙坦", "氯沙坦", "厄贝沙坦", "沙库巴曲"]):
                    alerts.append({
                        "level": "BLOCK",
                        "rule": "DDI_DUAL_RAS_BLOCKADE",
                        "title": "严禁联合两种 RAS 抑制剂 (双重阻断)",
                        "reason": "ACEI与ARB联用不增加降压靶器官获益，反而急剧增加严重低血压、晕厥、高钾血症及急性肾衰竭发生率，指南严格禁止双重阻断！",
                        "evidence": "2024版《中国高血压防治指南》及国家药监局警示",
                    })

            # Statin + Gemfibrozil
            if any(k in gname for k in ["阿托伐他汀", "瑞舒伐他汀", "匹伐他汀"]) and "吉非罗齐" in cd:
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_STATIN_GEMFIBROZIL",
                    "title": "他汀类严禁合用吉非罗齐",
                    "reason": "吉非罗齐竞争性抑制他汀葡萄糖醛酸化并阻断OATP1B1摄取，导致他汀肌肉蓄积诱发致死性横纹肌溶解！",
                    "evidence": "《中国血脂管理指南》",
                })

            # Glimepiride + Xiaoke Wan
            if "格列美脲" in gname and any(k in cd for k in ["消渴丸", "格列本脲"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_GLIMEPIRIDE_XIAOKEWAN",
                    "title": "格列美脲严禁与消渴丸等促泌剂叠加",
                    "reason": "消渴丸含有格列本脲化学药成分，两者叠加重复超剂量促泌，极易诱发致死性持久暴发低血糖昏迷！",
                    "evidence": "《中成药临床应用指导原则》【配伍禁忌】",
                })

            # SSRI + MAOI
            if any(k in gname for k in ["艾司西酞普兰", "舍曲林", "度洛西汀"]) and any(k in cd for k in ["单胺氧化酶", "司来吉兰", "吗氯贝胺"]):
                alerts.append({
                    "level": "BLOCK",
                    "rule": "DDI_SSRI_MAOI",
                    "title": "抗抑郁药严禁与 MAOI 联用 (五羟色胺综合征)",
                    "reason": "叠加导致脑内5-HT浓度过度积聚，诱发严重恶性高热、肌阵挛、昏迷及心血管虚脱（五羟色胺综合征致死），必须至少间隔14天洗脱期！",
                    "evidence": "国家药监局官方说明书【禁忌】",
                })

        # Determine overall recommendation
        has_block = any(a["level"] == "BLOCK" for a in alerts)
        has_warn = any(a["level"] == "WARNING" for a in alerts)

        if has_block:
            level = "BLOCK"
            can_prescribe = False
            summary = "【拦截禁止处方】该处方触发了国家药品说明书或临床指南最高级别绝对禁忌或致死性药物相互作用红线，系统已强行阻断！"
        elif has_warn:
            level = "WARNING"
            can_prescribe = True
            summary = "【黄色安全预警】该处方存在剂量滴定、特殊人群监护或潜在相互作用提示，临床医师应仔细核查并权衡利弊。"
        else:
            level = "PASS"
            can_prescribe = True
            summary = "【审核通过】未检索到绝对禁忌证或高危药物相互作用，符合说明书常规规范。"

        return {
            "success": True,
            "drug": {
                "id": drug["id"],
                "generic_name": drug["generic_name"],
                "english_name": drug["english_name"],
                "atc_code": drug["atc_code"],
                "category": drug["category"],
                "max_daily_dose": drug["max_daily_dose"],
                "standard_maintenance_dose": drug["standard_maintenance_dose"],
            },
            "canPrescribe": can_prescribe,
            "level": level,
            "summary": summary,
            "alerts": alerts,
            "renalGuidance": renal_guidance,
            "specialPopulationNotes": notes,
        }

    def audit_prescription(self, medications: List[str], patient: Dict[str, Any]) -> Dict[str, Any]:
        """
        Audits an entire prescription (list of medications) against patient profile,
        automatically cross-checking internal drug-drug interactions among all items.
        """
        if not medications:
            return {
                "success": True,
                "canPrescribe": True,
                "level": "PASS",
                "summary": "处方中无药品项",
                "items": [],
                "alerts": [],
            }

        patient_copy = dict(patient)
        existing_concurrent = list(patient_copy.get("concurrent_drugs", []))

        all_alerts: List[Dict[str, Any]] = []
        item_results: List[Dict[str, Any]] = []

        for i, med in enumerate(medications):
            # Other medications in prescription act as concurrent drugs
            other_meds = [m for j, m in enumerate(medications) if j != i]
            combined_concurrent = list(set(existing_concurrent + other_meds))
            patient_eval = dict(patient_copy)
            patient_eval["concurrent_drugs"] = combined_concurrent

            res = self.audit(med, patient_eval)
            item_results.append({
                "medication": med,
                "audit": res,
            })
            if res.get("success"):
                for a in res.get("alerts", []):
                    # Dedup alerts by rule
                    if not any(x.get("rule") == a.get("rule") for x in all_alerts):
                        all_alerts.append(a)

        has_block = any(a["level"] == "BLOCK" for a in all_alerts)
        has_warn = any(a["level"] == "WARNING" for a in all_alerts)

        if has_block:
            overall_level = "BLOCK"
            can_prescribe = False
            summary = "【处方强行阻断】处方中包含国家药品说明书绝对禁忌或致死性配伍禁忌项！"
        elif has_warn:
            overall_level = "WARNING"
            can_prescribe = True
            summary = "【处方用药预警】处方中存在剂量分级减量或特定人群监护提示。"
        else:
            overall_level = "PASS"
            can_prescribe = True
            summary = "【处方审核通过】全部药品均符合国家说明书与临床规范。"

        return {
            "success": True,
            "canPrescribe": can_prescribe,
            "level": overall_level,
            "summary": summary,
            "alerts": all_alerts,
            "items": item_results,
        }

