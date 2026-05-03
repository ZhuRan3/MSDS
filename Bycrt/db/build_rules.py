"""临时脚本：生成 chemical_type_rules.json 和 name_translations.json"""
import sys, json, re
sys.stdout.reconfigure(encoding='utf-8')

DB_DIR = "."

# === chemical_type_rules.json ===
rules = {
    "_meta": {"description": "化学品类型检测规则", "version": "1.0", "updated": "2026-05-03"},
    "type_detection": [
        {"tag": "flammable_liquid", "ghs_keywords": ["易燃液体"]},
        {"tag": "corrosive_acid", "ghs_keywords": ["皮肤腐蚀", "金属腐蚀"],
         "formula_hints": ["HCl", "H2SO4", "HNO3", "H3PO4", "HF"],
         "name_hints": ["酸"], "default_if_no_base_match": True},
        {"tag": "corrosive_alkali", "ghs_keywords": ["皮肤腐蚀", "金属腐蚀"],
         "formula_hints": ["NaOH", "KOH", "Ca(OH)2", "NH3"],
         "name_hints": ["碱", "氢氧化"]},
        {"tag": "toxic", "ghs_keywords": ["急性毒性"]},
        {"tag": "oxidizer", "ghs_keywords": ["氧化性"]},
        {"tag": "flammable_solid", "ghs_keywords": ["易燃固体"]},
        {"tag": "explosive", "ghs_keywords": ["自反应", "爆炸"]},
        {"tag": "compressed_gas", "ghs_keywords": ["高压气体", "加压气体", "液化气体"]},
        {"tag": "aspiration_hazard", "ghs_keywords": ["吸入危害", "吸入危险"]},
    ],
    "heavy_metals": ["Pb", "Hg", "Cd", "Cr", "As", "Cu", "Zn", "Ni", "Co"],
    "decomposition_rules": [
        {"elements": ["C", "H"], "products": ["一氧化碳", "二氧化碳"]},
        {"elements": ["N"], "products": ["氮氧化物"]},
        {"elements": ["S"], "products": ["二氧化硫"]},
        {"elements": ["Cl"], "products": ["氯化氢"]},
        {"elements": ["F"], "products": ["氟化氢"]},
        {"elements": ["Br"], "products": ["溴化氢"]},
        {"elements": ["CN"], "products": ["氰化氢"], "exclude_elements": ["C","H"]},
        {"elements": ["P", "O"], "products": ["磷氧化物"]},
    ],
    "decomposition_metals": ["Pb","Hg","Cd","Cr","Cu","Zn","Ni","Al","Fe","Na","K","Ca","Mg"],
    "transport_class_mapping": [
        {"ghs_keywords": ["易燃液体"], "class": "3", "shipping_name": "易燃液体，未另作规定的"},
        {"ghs_keywords": ["易燃固体", "自热"], "class": "4.1", "shipping_name": "易燃固体"},
        {"ghs_keywords": ["加压气体"], "class": "2.2", "shipping_name": "气体"},
        {"ghs_keywords": ["氧化性"], "class": "5.1", "shipping_name": "氧化性物质"},
        {"ghs_keywords": ["急性毒性"], "class": "6.1", "shipping_name": "毒性物质"},
        {"ghs_keywords": ["腐蚀"], "class": "8", "shipping_name": "腐蚀性物质"},
        {"ghs_keywords": ["水生环境", "环境"], "class": "9", "shipping_name": "环境危害物质"},
    ],
    "chlorinated_cas": ["75-09-2", "67-66-3", "71-55-6", "127-18-4"],
    "solution_concentrations": {
        "7647-01-0": "36-38%",
        "7664-93-9": "95-98%",
        "7697-37-2": "65-70%",
        "7664-38-2": "≥85%",
        "7681-52-9": "10-15%",
        "7722-84-1": "30-50%",
        "64-19-7": "≥99.0%",
    },
    "formula_inference": [
        {"formula": "C6H6O", "chemical_family": "酚类化合物", "un_number": "2021",
         "ghs_classifications": ["皮肤腐蚀/刺激，类别2", "严重眼损伤/眼刺激，类别2",
                                  "特异性靶器官毒性-反复接触，类别2（肝脏）", "致突变性，类别2"],
         "pictograms": ["GHS05", "GHS08"], "signal_word": "危险",
         "ld50_oral": "317 mg/kg (大鼠)", "ld50_dermal": "525 mg/kg (大鼠)",
         "flash_point": "79", "boiling_point": "182", "melting_point": "41",
         "density": "1.07", "eye_damage_category": "类别2", "carcinogenicity_iarc": "未分类"},
        {"formula": "C2H6O", "chemical_family": "醇类化合物", "un_number": "1170",
         "ghs_classifications": ["易燃液体，类别2", "严重眼损伤/眼刺激，类别2A",
                                  "特异性靶器官毒性-一次接触（麻醉效应），类别3"],
         "pictograms": ["GHS02", "GHS07"], "signal_word": "危险",
         "ld50_oral": "7060 mg/kg (大鼠)", "flash_point": "13", "boiling_point": "78", "melting_point": "-114"},
        {"formula": "C3H6O", "chemical_family": "酮类化合物", "un_number": "1193",
         "ghs_classifications": ["易燃液体，类别2", "严重眼损伤/眼刺激，类别2A",
                                  "特异性靶器官毒性-一次接触（麻醉效应），类别3"],
         "pictograms": ["GHS02", "GHS07"], "signal_word": "危险",
         "ld50_oral": "5800 mg/kg (大鼠)", "flash_point": "-20", "boiling_point": "56"},
        {"formula_pattern": "C.*H.*O.*", "chemical_family": "含氧有机化合物", "un_number": "1993"},
        {"formula_pattern": "N.*C.*H.*", "chemical_family": "腈类化合物", "un_number": "1648",
         "ghs_classifications": ["急性毒性-经口，类别3", "急性毒性-经皮，类别3", "急性毒性-吸入，类别3"],
         "pictograms": ["GHS06"], "signal_word": "危险"},
        {"formula_pattern": "OH.*(Na|K|Ca).*", "chemical_family": "无机碱", "un_number": "1823",
         "ghs_classifications": ["皮肤腐蚀/刺激，类别1A", "金属腐蚀物，类别1"],
         "pictograms": ["GHS05"], "signal_word": "危险"},
    ],
    "default_inference": {"chemical_family": "有机化合物", "un_number": "1993"}
}

with open(f"{DB_DIR}/chemical_type_rules.json", "w", encoding="utf-8") as f:
    json.dump(rules, f, ensure_ascii=False, indent=2)
print(f"chemical_type_rules.json written ({len(json.dumps(rules, ensure_ascii=False))} chars)")

# === name_translations.json ===
# Load chemical_db to extract existing names
with open(f"{DB_DIR}/chemical_db.json", "r", encoding="utf-8") as f:
    db = json.load(f)

cn_to_en = {}
for cas, entry in db.items():
    cn = entry.get("chemical_name_cn", "")
    en = entry.get("chemical_name_en", "") or entry.get("iupac_name", "")
    if cn and en:
        cn_to_en[cn] = en

# Add common aliases
aliases = {
    "酒精": "ethanol", "福尔马林": "formaldehyde", "石灰氮": "calcium cyanamide",
    "烧碱": "sodium hydroxide", "火碱": "sodium hydroxide", "苛性钠": "sodium hydroxide",
    "熟石灰": "calcium hydroxide", "醋酸": "acetic acid", "氯仿": "chloroform",
    "洗板水": "isopropanol", "去离子水": "deionized water", "蒸馏水": "distilled water",
}
cn_to_en.update(aliases)

names = {
    "_meta": {"description": "化学品中英文名称映射", "version": "1.0", "updated": "2026-05-03"},
    "cn_to_en": cn_to_en,
}

with open(f"{DB_DIR}/name_translations.json", "w", encoding="utf-8") as f:
    json.dump(names, f, ensure_ascii=False, indent=2)
print(f"name_translations.json written ({len(cn_to_en)} entries)")
