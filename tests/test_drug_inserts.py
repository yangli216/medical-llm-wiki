"""
Comprehensive Verification Tests for Drug Insert Monographs & CDSS Auditor.
Validates all 62 real clinical drug monographs, eGFR renal cutoffs, pregnancy blocks,
pediatric restrictions, and lethal DDI redlines without mock data.
"""

import unittest
from pathlib import Path
from tools.compiler.compiler import WikiGraph
from tools.search.searcher import WikiSearcher
from tools.cdss.drug_checker import DrugInsertRepository, DrugContraindicationAuditor


class TestDrugInsertRepository(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.repo = DrugInsertRepository(cls.root_dir)

    def test_all_100_drugs_loaded(self):
        """Verify that all high-frequency primary-care and TCM essential drug monographs are loaded."""
        drugs = self.repo.list_all()
        self.assertGreaterEqual(len(drugs), 137, f"Expected at least 137 drug monographs, got {len(drugs)}")

    def test_essential_categories_represented(self):
        """Verify that all major clinical therapeutic classes are fully represented."""
        drugs = self.repo.list_all()
        categories = {d["category"] for d in drugs}
        expected_categories = {
            "心血管系统",
            "内分泌与代谢系统",
            "呼吸与抗过敏系统",
            "消化系统",
            "骨科、镇痛与抗炎系统",
            "神经与精神系统",
            "泌尿生殖系统",
            "感染性疾病与皮肤外用系统",
            "急症与破伤风狂犬病被动免疫系统",
            "中成药/呼吸系统清热解毒",
        }
        for ec in expected_categories:
            self.assertIn(ec, categories, f"Category '{ec}' must be represented in monographs")

    def test_alias_and_trade_name_resolution(self):
        """Verify that drugs can be resolved by generic, simplified, trade name, ATC code, or clinic spec."""
        # Lianhua Qingwen with clinic spec
        lh = self.repo.get("连花清瘟胶囊 0.35g")
        self.assertIsNotNone(lh)
        self.assertEqual(lh["id"], "连花清瘟胶囊")
        self.assertEqual(self.repo.get("连花清瘟胶囊")["id"], "连花清瘟胶囊")
        self.assertEqual(self.repo.get("以岭连花清瘟")["id"], "连花清瘟胶囊")
        # Generic name
        d1 = self.repo.get("盐酸二甲双胍片")
        self.assertIsNotNone(d1)
        self.assertEqual(d1["id"], "盐酸二甲双胍片")

        # Simplified name
        d2 = self.repo.get("二甲双胍")
        self.assertIsNotNone(d2)
        self.assertEqual(d2["id"], "盐酸二甲双胍片")

        # Trade name (Glucophage -> 格华止)
        d3 = self.repo.get("格华止")
        self.assertIsNotNone(d3)
        self.assertEqual(d3["id"], "盐酸二甲双胍片")

        # Trade name (Lipitor -> 立普妥)
        d4 = self.repo.get("立普妥")
        self.assertIsNotNone(d4)
        self.assertEqual(d4["id"], "阿托伐他汀钙片")

        # Trade name (Plavix -> 波立维)
        d5 = self.repo.get("波立维")
        self.assertIsNotNone(d5)
        self.assertEqual(d5["id"], "硫酸氢氯吡格雷片")

        # ATC Code resolution
        d6 = self.repo.get("C09AA02")  # Enalapril ATC
        self.assertIsNotNone(d6)
        self.assertEqual(d6["id"], "马来酸依那普利片")

    def test_frontmatter_structural_integrity(self):
        """Verify that all monographs have valid dosage limits and contraindication metadata."""
        for d in self.repo._drugs.values():
            self.assertTrue(len(d["generic_name"]) > 0, f"Empty generic name in {d['id']}")
            self.assertTrue(len(d["max_daily_dose"]) > 0, f"Empty max daily dose in {d['id']}")
            self.assertTrue(len(d["standard_maintenance_dose"]) > 0, f"Empty maintenance dose in {d['id']}")
            self.assertTrue(len(d["key_contraindications"]) > 0, f"Empty key contraindications in {d['id']}")
            self.assertTrue("renal_impairment" in d["special_populations"], f"Missing renal guidance in {d['id']}")
            self.assertTrue("pregnancy" in d["special_populations"], f"Missing pregnancy guidance in {d['id']}")


class TestDrugContraindicationAuditor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.auditor = DrugContraindicationAuditor(root_dir=cls.root_dir)

    def test_metformin_egfr_block_and_warning(self):
        """Metformin: eGFR < 30 mL/min must be strongly BLOCKED; 30~44 must WARN."""
        # Case 1: Severe renal failure (eGFR = 22) -> BLOCK
        patient_severe = {"age": 68, "egfr": 22}
        res_severe = self.auditor.audit("二甲双胍", patient_severe)
        self.assertFalse(res_severe["canPrescribe"])
        self.assertEqual(res_severe["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "RENAL_EGFR_LT_30" for a in res_severe["alerts"]))

        # Case 2: Moderate-to-severe (eGFR = 38) -> WARNING
        patient_mod = {"age": 65, "egfr": 38}
        res_mod = self.auditor.audit("二甲双胍", patient_mod)
        self.assertTrue(res_mod["canPrescribe"])
        self.assertEqual(res_mod["level"], "WARNING")
        self.assertTrue(any(a["rule"] == "RENAL_EGFR_30_44" for a in res_mod["alerts"]))

        # Case 3: Preserved renal function (eGFR = 85) -> PASS
        patient_normal = {"age": 55, "egfr": 85}
        res_normal = self.auditor.audit("二甲双胍", patient_normal)
        self.assertTrue(res_normal["canPrescribe"])
        self.assertEqual(res_normal["level"], "PASS")

    def test_pregnancy_ras_inhibitor_block(self):
        """Enalapril and Valsartan are strictly prohibited in pregnant patients."""
        patient_pregnant = {"age": 28, "pregnancy": True}
        res = self.auditor.audit("马来酸依那普利片", patient_pregnant)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "PREGNANCY_RAS_INHIBITOR" for a in res["alerts"]))

        res_arb = self.auditor.audit("缬沙坦胶囊", patient_pregnant)
        self.assertFalse(res_arb["canPrescribe"])
        self.assertEqual(res_arb["level"], "BLOCK")

    def test_pediatric_quinolone_block(self):
        """Quinolones are strictly contraindicated in patients under 18 years old."""
        patient_child = {"age": 14}
        res = self.auditor.audit("左氧氟沙星片", patient_child)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "PEDIATRIC_QUINOLONES_LT_18" for a in res["alerts"]))

    def test_nitroglycerin_pde5_inhibitor_ddi_block(self):
        """Nitroglycerin combined with Sildenafil/Tadalafil must trigger fatal shock BLOCK."""
        patient = {
            "age": 62,
            "concurrent_drugs": ["枸橼酸西地那非片"],
        }
        res = self.auditor.audit("硝酸甘油片", patient)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_NITRO_PDE5I" for a in res["alerts"]))

    def test_clopidogrel_omeprazole_ddi_block(self):
        """Clopidogrel combined with Omeprazole must trigger black box BLOCK."""
        patient = {
            "age": 60,
            "concurrent_drugs": ["奥美拉唑肠溶胶囊"],
        }
        res = self.auditor.audit("硫酸氢氯吡格雷片", patient)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_CLOPIDOGREL_OMEPRAZOLE" for a in res["alerts"]))

    def test_clarithromycin_simvastatin_ddi_block(self):
        """Clarithromycin combined with Simvastatin causes rhabdomyolysis -> BLOCK."""
        patient = {
            "age": 55,
            "concurrent_drugs": ["辛伐他汀"],
        }
        res = self.auditor.audit("克拉霉素片", patient)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_CLARITHRO_SIMVASTATIN" for a in res["alerts"]))

    def test_dual_ras_blockade(self):
        """Combining ACEI (Enalapril) and ARB (Valsartan) must be BLOCKED."""
        patient = {
            "age": 58,
            "concurrent_drugs": ["缬沙坦胶囊"],
        }
        res = self.auditor.audit("马来酸依那普利片", patient)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_DUAL_RAS_BLOCKADE" for a in res["alerts"]))

    def test_batch_prescription_auditing(self):
        """audit_prescription should cross-check all items in a single order."""
        # Lethal combo: Nitroglycerin + Sildenafil in same prescription
        rx_danger = ["硝酸甘油片", "西地那非片"]
        res_danger = self.auditor.audit_prescription(rx_danger, {"age": 58})
        self.assertFalse(res_danger["canPrescribe"])
        self.assertEqual(res_danger["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_NITRO_PDE5I" for a in res_danger["alerts"]))

        # Safe combo: Metformin + Acarbose for healthy kidney patient
        rx_safe = ["盐酸二甲双胍片", "阿卡波糖片"]
        res_safe = self.auditor.audit_prescription(rx_safe, {"age": 50, "egfr": 90})
        self.assertTrue(res_safe["canPrescribe"])
        self.assertEqual(res_safe["level"], "PASS")

    def test_sacubitril_valsartan_acei_washout_36h_ddi_block(self):
        """ARNI + ACEI triggers fatal angioedema block (36h washout required)."""
        patient = {
            "age": 64,
            "concurrent_drugs": ["马来酸依那普利片"],
        }
        res = self.auditor.audit("沙库巴曲缬沙坦钠片", patient)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_ARNI_ACEI_WASHOUT_36H" for a in res["alerts"]))

        # Reverse audit
        patient_rev = {
            "age": 64,
            "concurrent_drugs": ["沙库巴曲缬沙坦钠片"],
        }
        res_rev = self.auditor.audit("马来酸依那普利片", patient_rev)
        self.assertFalse(res_rev["canPrescribe"])
        self.assertEqual(res_rev["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_ACEI_ARNI_WASHOUT_36H" for a in res_rev["alerts"]))

    def test_febuxostat_azathioprine_ddi_block(self):
        """Febuxostat + Azathioprine triggers fatal bone marrow suppression block."""
        patient = {
            "age": 45,
            "concurrent_drugs": ["硫唑嘌呤片"],
        }
        res = self.auditor.audit("非布司他片", patient)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "DDI_FEBUXOSTAT_AZATHIOPRINE" for a in res["alerts"]))

    def test_rivaroxaban_severe_renal_block_and_adjust(self):
        """Rivaroxaban: eGFR < 15 triggers BLOCK; 15~49 triggers 15mg dose reduction warning."""
        # eGFR = 12 -> BLOCK
        patient_severe = {"age": 72, "egfr": 12}
        res_severe = self.auditor.audit("利伐沙班片", patient_severe)
        self.assertFalse(res_severe["canPrescribe"])
        self.assertEqual(res_severe["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "RENAL_RIVAROXABAN_LT_15" for a in res_severe["alerts"]))

        # eGFR = 35 -> WARNING for 15mg qd
        patient_mod = {"age": 72, "egfr": 35}
        res_mod = self.auditor.audit("利伐沙班片", patient_mod)
        self.assertTrue(res_mod["canPrescribe"])
        self.assertEqual(res_mod["level"], "WARNING")
        self.assertTrue(any(a["rule"] == "RENAL_RIVAROXABAN_15_49_ADJUST" for a in res_mod["alerts"]))

    def test_dabigatran_severe_renal_and_valve_block(self):
        """Dabigatran: eGFR < 30 mL/min triggers BLOCK; Mechanical heart valve triggers BLOCK."""
        # eGFR = 25 -> BLOCK
        patient_renal = {"age": 70, "egfr": 25}
        res_renal = self.auditor.audit("甲磺酸达比加群酯胶囊", patient_renal)
        self.assertFalse(res_renal["canPrescribe"])
        self.assertEqual(res_renal["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "RENAL_DABIGATRAN_LT_30" for a in res_renal["alerts"]))

        # Mechanical heart valve -> BLOCK
        patient_valve = {"age": 60, "egfr": 80, "conditions": ["人工机械瓣膜置换术后"]}
        res_valve = self.auditor.audit("甲磺酸达比加群酯胶囊", patient_valve)
        self.assertFalse(res_valve["canPrescribe"])
        self.assertEqual(res_valve["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "CONDITION_DABIGATRAN_MECHANICAL_VALVE" for a in res_valve["alerts"]))

    def test_semaglutide_mtc_block(self):
        """Semaglutide: Personal/family history of MTC / MEN 2 triggers black box BLOCK."""
        patient_mtc = {"age": 42, "conditions": ["甲状腺髓样癌家族史"]}
        res_mtc = self.auditor.audit("司美格鲁肽注射液", patient_mtc)
        self.assertFalse(res_mtc["canPrescribe"])
        self.assertEqual(res_mtc["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "CONDITION_SEMAGLUTIDE_MTC" for a in res_mtc["alerts"]))

    def test_spironolactone_severe_renal_block(self):
        """Spironolactone: eGFR < 30 triggers fatal hyperkalemia BLOCK."""
        patient = {"age": 68, "egfr": 22}
        res = self.auditor.audit("螺内酯片", patient)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "RENAL_SPIRONOLACTONE_LT_30" for a in res["alerts"]))

    def test_reserpine_depression_block(self):
        """Compound Reserpine / Triamterene: Active depression triggers suicide BLOCK."""
        patient = {"age": 58, "conditions": ["重度抑郁症"]}
        res = self.auditor.audit("复方利血平氨苯蝶啶片", patient)
        self.assertFalse(res["canPrescribe"])
        self.assertEqual(res["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "CONDITION_RESERPINE_DEPRESSION" for a in res["alerts"]))

    def test_tramadol_pediatric_and_epilepsy_block(self):
        """Tramadol: Age < 12 triggers pediatric respiratory depression BLOCK; Epilepsy triggers BLOCK."""
        # Age 9 -> BLOCK
        res_child = self.auditor.audit("盐酸曲马多缓释片", {"age": 9})
        self.assertFalse(res_child["canPrescribe"])
        self.assertEqual(res_child["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "PEDIATRIC_TRAMADOL_LT_12" for a in res_child["alerts"]))

        # Epilepsy -> BLOCK
        res_epi = self.auditor.audit("盐酸曲马多缓释片", {"age": 35, "conditions": ["继发性癫痫病史"]})
        self.assertFalse(res_epi["canPrescribe"])
        self.assertEqual(res_epi["level"], "BLOCK")
        self.assertTrue(any(a["rule"] == "CONDITION_TRAMADOL_EPILEPSY" for a in res_epi["alerts"]))


class TestDrugSearchIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.searcher = WikiSearcher(cls.root_dir)

    def test_drug_inserts_search(self):
        """Verify WikiSearcher.search_drug_inserts retrieves relevant monographs."""
        hits = self.searcher.search_drug_inserts("降压 钙通道阻滞剂", limit=5)
        self.assertTrue(len(hits) > 0)
        titles = [h["title"] for h in hits]
        # Should contain CCB drugs
        self.assertTrue(any("氨氯地平" in t or "硝苯地平" in t for t in titles))


if __name__ == "__main__":
    unittest.main()
