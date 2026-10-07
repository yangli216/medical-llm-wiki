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

    def test_all_62_drugs_loaded(self):
        """Verify that exactly all 62 high-frequency primary-care drug monographs are loaded."""
        drugs = self.repo.list_all()
        self.assertEqual(len(drugs), 62, f"Expected 62 drug monographs, got {len(drugs)}")

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
        }
        for ec in expected_categories:
            self.assertIn(ec, categories, f"Category '{ec}' must be represented in monographs")

    def test_alias_and_trade_name_resolution(self):
        """Verify that drugs can be resolved by generic, simplified, trade name, or ATC code."""
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
