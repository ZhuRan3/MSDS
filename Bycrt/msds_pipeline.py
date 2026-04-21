#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
化安通 (HuaAnTong) - MSDS自动生成系统 v2
功能：根据CAS号自动从网络获取数据并生成MSDS

数据源优先级：
1. PubChem REST API（理化性质、安全数据）
2. 化学品特性推断（当API数据不足时）
"""

import requests
import json
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# 导入LLM客户端
from msds_llm_client import (
    call_llm,
    generate_hazard_description,
    generate_first_aid_section,
    generate_firefighting_section,
    generate_spill_section,
    generate_handling_section,
    generate_toxicology_section,
    generate_ecology_section,
    generate_stability_section,
    generate_disposal_section,
    generate_regulatory_section
)

# 导入RAG客户端
from msds_rag_client import ChemicalRAGRetriever

# ============================================================
# 配置
# ============================================================

PROJECT_ROOT = Path("D:/Learning/Jilema/MSDS-main")
OUTPUT_DIR = PROJECT_ROOT / "output"
REFERENCE_DB_DIR = OUTPUT_DIR / "reference_db"
REFERENCE_DB_DIR.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "HuaAnTong-MSDSGEN/1.0 (educational project)"}
PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

# ============================================================
# 第一步：PubChem数据获取
# ============================================================

class PubChemFetcher:
    """从PubChem获取化学品数据"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get_cid(self, cas_or_name: str) -> Optional[int]:
        """通过CAS或名称获取CID"""
        url = f"{PUBCHEM_BASE}/compound/name/{cas_or_name}/cids/JSON"
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            cids = data.get("IdentifierList", {}).get("CID", [])
            return cids[0] if cids else None
        except Exception as e:
            print(f"  [WARNING] CID查询失败: {e}")
            return None

    def get_properties(self, cid: int) -> Dict:
        """获取理化性质"""
        url = f"{PUBCHEM_BASE}/compound/cid/{cid}/property/MolecularWeight,MolecularFormula,CanonicalSMILES,IUPACName,XLogP/JSON"
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            props = resp.json().get("PropertyTable", {}).get("Properties", [{}])[0]
            return props
        except Exception as e:
            print(f"  [WARNING] 属性查询失败: {e}")
            return {}

    def get_safety_summary(self, cid: int) -> Dict:
        """获取安全概述"""
        url = f"{PUBCHEM_BASE}/compound/cid/{cid}/record/JSON?heading=Safety+and+Hazards"
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except:
            return {}

    def get_all_data(self, cas_or_name: str) -> Optional[Dict]:
        """获取完整数据"""
        cid = self.get_cid(cas_or_name)
        if not cid:
            return None

        props = self.get_properties(cid)
        safety = self.get_safety_summary(cid)

        return {
            "cid": cid,
            "properties": props,
            "safety": safety,
            "source": "PubChem"
        }


# ============================================================
# 第二步：化学品特性推断（当API数据不足时）
# ============================================================

class ChemicalInferencer:
    """根据化学品分子式和名称推断危险特性"""

    # 化学类别到危险特性的映射
    CHEMICAL_FAMILIES = {
        "phenol": {
            "family": "酚类化合物",
            "ghs": ["皮肤腐蚀/刺激，类别2", "严重眼损伤/眼刺激，类别1", "特异性靶器官毒性-一次接触，类别3"],
            "pictograms": ["火焰", "腐蚀", "感叹号"],
            "signal_word": "危险",
            "hazard_h": ["H314", "H318", "H335"],
            "ld50_oral": "300-500 mg/kg（大鼠）",
            "pc_twa": "10 mg/m³",
            "description": "酚类化合物具有腐蚀性和毒性"
        },
        "alcohol": {
            "family": "醇类化合物",
            "ghs": ["易燃液体，类别2", "严重眼损伤/眼刺激，类别2A", "特异性靶器官毒性-一次接触（麻醉效应），类别3"],
            "pictograms": ["火焰", "感叹号"],
            "signal_word": "危险",
            "hazard_h": ["H225", "H319", "H336"],
            "ld50_oral": "5000-7000 mg/kg（大鼠）",
            "pc_twa": "1000 ppm",
            "description": "醇类化合物易燃"
        },
        "ketone": {
            "family": "酮类化合物",
            "ghs": ["易燃液体，类别2", "严重眼损伤/眼刺激，类别2A", "特异性靶器官毒性-一次接触（麻醉效应），类别3"],
            "pictograms": ["火焰", "感叹号"],
            "signal_word": "危险",
            "hazard_h": ["H225", "H319", "H336"],
            "ld50_oral": "5000-6000 mg/kg（大鼠）",
            "pc_twa": "300 mg/m³",
            "description": "酮类化合物易燃"
        },
        "nitrile": {
            "family": "腈类化合物",
            "ghs": ["易燃液体，类别2", "急性毒性-经口，类别4", "急性毒性-经皮，类别4", "急性毒性-吸入，类别4"],
            "pictograms": ["火焰", "感叹号"],
            "signal_word": "危险",
            "hazard_h": ["H225", "H302", "H312", "H332"],
            "ld50_oral": "2000-3000 mg/kg（大鼠）",
            "pc_twa": "30 mg/m³",
            "description": "腈类化合物有毒"
        },
        "alkane": {
            "family": "烷烃化合物",
            "ghs": ["易燃液体，类别2", "皮肤腐蚀/刺激，类别2", "生殖毒性，类别2"],
            "pictograms": ["火焰", "健康危害"],
            "signal_word": "危险",
            "hazard_h": ["H225", "H304", "H315", "H336"],
            "ld50_oral": "20000-30000 mg/kg（大鼠）",
            "pc_twa": "100 mg/m³",
            "description": "烷烃化合物易燃"
        },
        "aromatic": {
            "family": "芳香烃",
            "ghs": ["易燃液体，类别2", "皮肤腐蚀/刺激，类别2", "生殖毒性，类别2", "特异性靶器官毒性-一次接触，类别3"],
            "pictograms": ["火焰", "感叹号"],
            "signal_word": "危险",
            "hazard_h": ["H225", "H304", "H315", "H336", "H361"],
            "ld50_oral": "5000-7000 mg/kg（大鼠）",
            "pc_twa": "50 mg/m³",
            "description": "芳香烃化合物易燃"
        },
        "inorganic_base": {
            "family": "无机碱",
            "ghs": ["金属腐蚀物，类别1", "皮肤腐蚀/刺激，类别1A"],
            "pictograms": ["腐蚀"],
            "signal_word": "危险",
            "hazard_h": ["H290", "H314"],
            "ld50_oral": "500-2000 mg/kg（大鼠）",
            "pc_twa": "2 mg/m³",
            "description": "无机碱具有强腐蚀性"
        },
        "organic": {
            "family": "有机化合物",
            "ghs": ["皮肤腐蚀/刺激，类别2", "严重眼损伤/眼刺激，类别2A"],
            "pictograms": ["感叹号"],
            "signal_word": "警告",
            "hazard_h": ["H315", "H319"],
            "ld50_oral": "2000-5000 mg/kg（大鼠）",
            "pc_twa": "50 mg/m³",
            "description": "有机化合物"
        }
    }

    def detect_family(self, formula: str, name: str) -> str:
        """根据分子式和名称检测化学类别"""
        name_lower = name.lower()
        formula_upper = formula.upper() if formula else ""

        # 酚类
        if "phenol" in name_lower or "cresol" in name_lower:
            return "phenol"
        if formula_upper == "C6H6O" or formula_upper == "C7H8O":
            return "phenol"

        # 醇类
        if "ethanol" in name_lower or "ethyl alcohol" in name_lower:
            return "alcohol"
        if "methanol" in name_lower or "methyl alcohol" in name_lower:
            return "alcohol"
        if formula_upper == "C2H6O" or formula_upper == "CH4O":
            return "alcohol"

        # 酮类
        if "acetone" in name_lower or "propanone" in name_lower:
            return "ketone"
        if formula_upper == "C3H6O":
            return "ketone"

        # 腈类
        if "acetonitrile" in name_lower or "nitrile" in name_lower:
            return "nitrile"
        if "CN" in formula_upper:
            return "nitrile"

        # 脂肪烃
        if set(formula_upper.replace(" ", "").replace(",", "")) <= set("CH0123456789"):
            if "C" in formula_upper and "H" in formula_upper:
                if formula_upper.count("C") >= 5:
                    return "alkane"
                return "alkane"

        # 芳香烃
        if "benzene" in name_lower or "toluene" in name_lower or "xylene" in name_lower:
            return "aromatic"
        if formula_upper.count("C") >= 6 and formula_upper.count("H") >= 6:
            if "O" not in formula_upper and "N" not in formula_upper:
                return "aromatic"

        # 无机碱
        if "NaOH" in formula_upper or "KOH" in formula_upper or "Ca(OH)" in formula_upper:
            return "inorganic_base"

        return "organic"

    def infer_data(self, formula: str, name: str, cas: str) -> Dict:
        """推断化学品数据"""
        family_key = self.detect_family(formula, name)
        family_info = self.CHEMICAL_FAMILIES.get(family_key, self.CHEMICAL_FAMILIES["organic"])

        # UN编号推断
        un_map = {
            "phenol": "2021",
            "alcohol": "1170",
            "ketone": "1090",
            "nitrile": "1648",
            "alkane": "1208",
            "aromatic": "1294",
            "inorganic_base": "1823"
        }

        # 闪点推断
        flash_point_map = {
            "phenol": "82°C（闭杯）",
            "alcohol": "13°C（闭杯）",
            "ketone": "-20°C（闭杯）",
            "nitrile": "2°C（闭杯）",
            "alkane": "-22°C（闭杯）",
            "aromatic": "4°C（闭杯）",
            "inorganic_base": "不适用（非易燃）"
        }

        return {
            "chemical_family": family_info["family"],
            "ghs_classifications": family_info["ghs"],
            "pictograms": family_info["pictograms"],
            "signal_word": family_info["signal_word"],
            "hazard_statements": family_info["hazard_h"],
            "hazard_codes_full": [f"{h} " for h in family_info["hazard_h"]],  # 简化
            "un_number": un_map.get(family_key, "1993"),
            "flash_point": flash_point_map.get(family_key, "待测定"),
            "ld50_oral": family_info["ld50_oral"],
            "pc_twa": family_info["pc_twa"],
            "inferred": True,
            "description": family_info["description"]
        }


# ============================================================
# 第三步：MSDS生成器
# ============================================================

class MSDSGenerator:
    """MSDS生成器"""

    def __init__(self):
        self.fetcher = PubChemFetcher()
        self.inferencer = ChemicalInferencer()
        self.rag = ChemicalRAGRetriever()

    def generate(self, cas_or_name: str, company_info: Dict = None) -> Dict:
        """生成MSDS"""
        print(f"\n{'='*60}")
        print(f"化安通 MSDS生成")
        print(f"{'='*60}")
        print(f"输入: {cas_or_name}")

        # Step 1: 从PubChem获取数据
        print(f"\n[Step 1] 查询PubChem...")
        pubchem_data = self.fetcher.get_all_data(cas_or_name)

        if pubchem_data:
            print(f"  [OK] CID: {pubchem_data['cid']}")
            props = pubchem_data.get('properties', {})
            print(f"  分子式: {props.get('MolecularFormula', 'N/A')}")
            print(f"  分子量: {props.get('MolecularWeight', 'N/A')}")
            print(f"  IUPAC: {props.get('IUPACName', 'N/A')}")
        else:
            print(f"  [INFO] PubChem未找到，使用推断数据")
            props = {}

        # Step 2: 确定化学品名称和分子式
        cas = cas_or_name.strip()
        formula = props.get("MolecularFormula", "")
        iupac_name = props.get("IUPACName", "")
        mw = props.get("MolecularWeight", "")

        # Step 3: 推断危险特性
        print(f"\n[Step 2] 分析化学品特性...")
        inferred = self.inferencer.infer_data(formula, iupac_name, cas)
        family = inferred["chemical_family"]
        print(f"  化学类别: {family}")
        print(f"  推断数据: {'是' if inferred.get('inferred') else '否'}")

        # Step 4: 构建完整记录
        print(f"\n[Step 3] 构建MSDS数据...")

        chem_data = {
            "chemical_name_cn": iupac_name,
            "chemical_name_en": props.get("CanonicalSMILES", ""),
            "molecular_formula": formula,
            "molecular_weight": str(mw) if mw else "",
            "cas_number": cas,
            "iupac_name": iupac_name,
            "xlogp": props.get("XLogP", ""),
            "chemical_family": family,
            "ghs_classifications": inferred["ghs_classifications"],
            "pictograms": inferred["pictograms"],
            "signal_word": inferred["signal_word"],
            "hazard_statements": inferred["hazard_statements"],
            "un_number": inferred["un_number"],
            "flash_point": inferred["flash_point"],
            "ld50_oral": inferred["ld50_oral"],
            "pc_twa": inferred["pc_twa"],
            "data_source": "PubChem + 推断" if pubchem_data else "推断",
            "completeness": "full" if pubchem_data else "inferred"
        }

        # Step 5: RAG检索知识库
        print(f"\n[Step 4] 检索知识库...")
        rag_result = self.rag.retrieve_for_msds(cas_or_name)
        if rag_result['has_knowledge']:
            print(f"  [OK] 知识库命中: {rag_result['primary_chemical'].get('chemical_name_cn', 'N/A')}")
            print(f"       相关度: {rag_result['primary_chemical'].get('_relevance_score', 0)}%")
            chem_data['_rag_context'] = rag_result['context']
            chem_data['_has_rag_knowledge'] = True
        else:
            print(f"  [INFO] 知识库未命中，使用推断数据")
            chem_data['_rag_context'] = ""
            chem_data['_has_rag_knowledge'] = False

        # Step 6: 生成MSDS
        msds = self._build_msds(chem_data, company_info)
        print(f"\n[OK] MSDS生成完成")
        return msds

    def _build_msds(self, chem: Dict, company_info: Dict = None) -> Dict:
        """构建MSDS数据结构"""

        default_company = {
            "name": "________________",
            "address": "________________",
            "phone": "________________",
            "emergency": "________________"
        }
        if company_info:
            default_company.update(company_info)

        sds_number = f"HUAT-{datetime.now().year}-{chem['cas_number'].replace('-', '')}"

        # 检测危险特性
        is_flammable = any("易燃" in c for c in chem.get("ghs_classifications", []))
        is_corrosive = any("腐蚀" in c for c in chem.get("ghs_classifications", []))
        is_toxic = any("毒" in c or "H3" in c for c in chem.get("ghs_classifications", []))
        is_explosive = any("爆炸" in c for c in chem.get("ghs_classifications", []))

        # 紧急概述 - 使用RAG增强的LLM生成
        rag_context = chem.get('_rag_context', '')
        llm_overview = generate_hazard_description(chem, rag_context)
        if llm_overview:
            emergency_overview = llm_overview
        else:
            overview_parts = []
            if is_flammable:
                overview_parts.append("高度易燃")
            if is_corrosive:
                overview_parts.append("可引起严重灼伤")
            if is_toxic:
                overview_parts.append("有毒")
            if not overview_parts:
                overview_parts.append("请详细阅读本说明书")
            emergency_overview = "。".join(overview_parts) + "。"

        return {
            "document_info": {
                "sds_number": sds_number,
                "version": "1.0.0",
                "revision_date": datetime.now().strftime("%Y-%m-%d"),
                "data_source": chem.get("data_source", ""),
                "completeness": chem.get("completeness", "")
            },
            "part1_identification": {
                "product_name_cn": chem.get("chemical_name_cn", ""),
                "product_name_en": chem.get("chemical_name_en", ""),
                "cas_number": chem.get("cas_number", ""),
                "molecular_formula": chem.get("molecular_formula", ""),
                "molecular_weight": chem.get("molecular_weight", ""),
                "iupac_name": chem.get("iupac_name", ""),
                "un_number": f"UN {chem.get('un_number', '')}" if chem.get('un_number') else "",
                "company_name": default_company["name"],
                "company_address": default_company["address"],
                "company_emergency": default_company["emergency"],
                "recommended_use": self._get_recommended_use(chem.get("chemical_family", "")),
                "restricted_use": "禁止非授权使用"
            },
            "part2_hazard": {
                "emergency_overview": emergency_overview,
                "ghs_classifications": chem.get("ghs_classifications", []),
                "pictograms": chem.get("pictograms", []),
                "signal_word": chem.get("signal_word", "危险"),
                "hazard_codes": chem.get("hazard_statements", []),
                "hazard_codes_full": chem.get("hazard_codes_full", []),
                "precautionary_statements": self._get_p_statements(chem),
                "physical_hazards": self._gen_physical_hazard(chem, is_flammable),
                "health_hazards": self._gen_health_hazard(chem, is_corrosive, is_toxic),
                "environmental_hazards": "对水生生物有害。" if is_toxic else "无特殊环境危害。"
            },
            "part3_composition": {
                "substance_type": "物质",
                "components": [{
                    "name": chem.get("chemical_name_cn", ""),
                    "cas": chem.get("cas_number", ""),
                    "purity": ">=99.5%",
                    "chemical_family": chem.get("chemical_family", "")
                }]
            },
            "part4_first_aid": generate_first_aid_section(chem, is_corrosive, is_toxic, rag_context),
            "part5_firefighting": generate_firefighting_section(chem, is_flammable, is_corrosive, is_explosive, rag_context),
            "part6_spill": generate_spill_section(chem, is_flammable, is_corrosive, is_toxic, rag_context),
            "part7_handling": generate_handling_section(chem, is_flammable, is_corrosive, rag_context),
            "part8_exposure": self._gen_part8(chem),
            "part9_physical": self._gen_part9(chem),
            "part10_stability": generate_stability_section(chem, is_flammable, rag_context),
            "part11_toxicology": generate_toxicology_section(chem, rag_context),
            "part12_ecology": generate_ecology_section(chem, is_toxic, rag_context),
            "part13_disposal": generate_disposal_section(),
            "part14_transport": self._gen_part14(chem, is_flammable, is_corrosive, is_toxic),
            "part15_regulatory": generate_regulatory_section(),
            "part16_other": self._gen_part16(sds_number)
        }

    def _get_recommended_use(self, family: str) -> str:
        """根据化学类别返回推荐用途"""
        uses = {
            "酚类化合物": "消毒剂、防腐剂、抗氧化剂、医药中间体（由企业填写）",
            "醇类化合物": "溶剂、消毒剂、化学原料、燃料（由企业填写）",
            "酮类化合物": "溶剂、清洗剂、化学原料（由企业填写）",
            "腈类化合物": "有机合成原料、溶剂（由企业填写）",
            "烷烃化合物": "溶剂、化学原料、燃料（由企业填写）",
            "芳香烃": "溶剂、化学原料、燃料（由企业填写）",
            "无机碱": "工业清洗剂、化学原料（由企业填写）"
        }
        return uses.get(family, "工业用化学品（由企业填写）")

    def _get_p_statements(self, chem: Dict) -> Dict:
        """生成防范说明P码"""
        is_corrosive = any("腐蚀" in c for c in chem.get("ghs_classifications", []))
        is_flammable = any("易燃" in c for c in chem.get("ghs_classifications", []))

        prevention = [
            "P210 远离热源/火花/明火/热表面。禁止吸烟。",
            "P260 不要吸入蒸气。",
            "P280 戴防护手套/防护眼罩/防护服。"
        ]
        if is_flammable:
            prevention.extend([
                "P233 保持容器密闭。",
                "P240 容器和接收设备接地。"
            ])

        response = [
            "P302+P352 如皮肤沾染：用大量水冲洗。",
            "P305+P351+P338 如眼睛沾染：用水冲洗。",
            "P312 如感觉不适，呼叫中毒控制中心。"
        ]
        if is_corrosive:
            response.append("P363 沾染的衣物须彻底清洗后方可再次使用。")

        storage = [
            "P403+P233 存放在通风良好的地方。",
            "P405 存放在锁定的设施中。"
        ]

        disposal = [
            "P501 按法规处置。"
        ]

        return {
            "prevention": prevention,
            "response": response,
            "storage": storage,
            "disposal": disposal
        }

    def _gen_physical_hazard(self, chem: Dict, is_flammable: bool) -> str:
        hazards = []
        if is_flammable:
            fp = chem.get("flash_point", "未知")
            hazards.append(f"高度易燃液体，闪点{fp}。")
            hazards.append("蒸气与空气能形成爆炸性混合物。")
        if not hazards:
            hazards.append("无特殊物理危险性。")
        return "".join(hazards)

    def _gen_health_hazard(self, chem: Dict, is_corrosive: bool, is_toxic: bool) -> Dict:
        base = {
            "inhalation": "蒸气可能刺激呼吸道，高浓度引起头晕、恶心。",
            "skin_contact": "可能引起皮肤刺激。",
            "eye_contact": "可能引起眼睛刺激。",
            "ingestion": "误咽可能引起恶心、呕吐、腹痛。"
        }
        if is_corrosive:
            base["skin_contact"] = "造成严重皮肤灼伤和眼睛损伤。"
            base["eye_contact"] = "造成严重眼损伤，可能导致永久性视力损害。"
            base["ingestion"] = "造成消化道灼伤，禁止催吐，立即就医。"
        if is_toxic:
            base["inhalation"] = "吸入可能引起中毒，造成器官损害。"
        return base

    def _gen_part4(self, chem: Dict, is_corrosive: bool) -> Dict:
        ingestion = "如误咽，不得催吐。用水漱口。就医。" if not is_corrosive else "不要催吐。漱口。立即就医。"
        return {
            "inhalation": "立即撤离现场至空气新鲜处。保持呼吸道通畅。如呼吸困难，给氧。如呼吸停止，立即进行人工呼吸。就医。",
            "skin_contact": "立即脱去所有沾染的衣服。用大量清水持续冲洗至少15分钟。立即就医。" if is_corrosive else "立即脱去污染的衣着。用肥皂水和清水彻底冲洗皮肤至少15分钟。如有不适感，就医。",
            "eye_contact": "立即提起眼睑，用流动清水或生理盐水持续冲洗至少15分钟。隐形眼镜须取下并分开清洗。立即就医。",
            "ingestion": ingestion,
            "protection_for_rescuers": "救助人员应佩戴适当的呼吸防护和防化学手套。确保通风良好。",
            "notes_to_physician": "无特效解毒剂，采用支持治疗。如发生皮肤或眼睛灼伤，按烧伤处理。对症治疗。"
        }

    def _gen_part5(self, chem: Dict, is_flammable: bool, is_corrosive: bool, is_explosive: bool) -> Dict:
        hazard_chars = []
        extinguishing = []
        prohibited = []
        advice = []

        if is_explosive:
            hazard_chars.append("具有爆炸性。")
            extinguishing.append("大量水喷雾")
            prohibited.append("禁止使用干粉、CO2、泡沫灭火器")
            advice.append("撤离区域，单独处理。")

        if is_flammable:
            hazard_chars.append(f"高度易燃液体，闪点{chem.get('flash_point', '未知')}。")
            extinguishing.append("干粉灭火器、CO2、水喷雾、泡沫")
            prohibited.append("禁止使用直流水（可能使火势蔓延）")
            advice.append("在上风方向灭火，喷水冷却容器。")

        if is_corrosive:
            hazard_chars.append("具有腐蚀性。")
            advice.append("消防人员须穿戴防化学腐蚀防护装备。")

        if not hazard_chars:
            hazard_chars.append("未分类为危险化学品。")

        return {
            "hazard_characteristics": "".join(hazard_chars),
            "extinguishing_media": "、".join(extinguishing) if extinguishing else "待定",
            "extinguishing_prohibited": "；".join(prohibited) if prohibited else "无",
            "firefighting_advice": " ".join(advice) if advice else "遵循标准消防程序。"
        }

    def _gen_part6(self, chem: Dict, is_flammable: bool, is_corrosive: bool) -> Dict:
        personal = "确保通风。穿戴防护装备（呼吸防护、防化学手套、安全护目镜）。"
        emergency = "隔离泄漏区域至少50米。疏散人员至上风安全区域。禁止无关人员进入。"
        environmental = "防止泄漏物进入排水沟、下水道、地下室或密闭空间。如进入水体或土壤，通知当地环保部门。"
        containment = "小量：用惰性材料（如活性炭、砂土）吸收。大量：构筑围堤收容。"
        cleaning = "用清水冲洗污染区域。废液须按危险废物处理。"

        if is_corrosive:
            cleaning = "用大量清水冲洗。避免排放至下水道。"

        ppe = "正压呼吸器（紧急时）、防化学手套、安全护目镜、全面防护服。"

        return {
            "personal_precautions": personal,
            "emergency_response": emergency,
            "environmental_precautions": environmental,
            "containment_methods": containment,
            "cleaning_methods": cleaning,
            "ppe_for_cleanup": ppe
        }

    def _gen_part7(self, chem: Dict, is_flammable: bool, is_corrosive: bool) -> Dict:
        handling = "操作须在通风良好的地方进行。远离热源和火源。"
        if is_flammable:
            handling += "禁止吸烟。使用防爆设备和工具。容器须接地防止静电。"
        handling += "穿戴适当的防护装备。操作后彻底洗手。"

        storage = "储存于阴凉、干燥、通风良好的地方。远离热源和火源。容器须密闭。"
        if is_corrosive:
            storage += "储存于耐腐蚀容器中。"
        if is_flammable:
            storage += "与氧化剂分开存放。使用防爆电气设备。"

        incompatible = ["强氧化剂", "酸类", "碱类"]
        if is_corrosive:
            incompatible.extend(["铝", "锌"])

        return {
            "handling_precautions": handling,
            "storage_conditions": storage,
            "incompatible_materials": "、".join(incompatible)
        }

    def _gen_part8(self, chem: Dict) -> Dict:
        return {
            "occupational_limits": {
                "china_pc_twa": chem.get("pc_twa", "无资料"),
                "china_pc_stel": "无资料",
                "acgih_tlv_twa": "无资料"
            },
            "monitoring_method": "气相色谱法（GBZ/T 160.42）或对应检测方法",
            "engineering_controls": "使用局部通风或全面通风。提供安全淋浴和洗眼设备（距操作点10米以内）。",
            "respiratory_protection": "浓度超标时：配戴适合的呼吸防护具。紧急情况：正压呼吸器。",
            "eye_protection": "安全护目镜（防溅）或全面防护面罩。",
            "skin_protection": "防化学手套、防护服（防渗透）。",
            "hygiene_measures": "工作后彻底淋浴更衣。工作服须每日更换，被污染后立即更换。饭前须洗手。"
        }

    def _gen_part9(self, chem: Dict) -> Dict:
        return {
            "appearance": "无色至淡黄色液体或固体",
            "color": "无色至淡黄色",
            "odor": "特征性气味",
            "melting_point": "见实际数据",
            "boiling_point": "见实际数据",
            "flash_point": chem.get("flash_point", "无资料"),
            "autoignition_temp": "无资料",
            "explosion_limits": "无资料",
            "vapor_pressure": "无资料",
            "relative_density": "无资料",
            "solubility": "见实际数据",
            "viscosity": "无资料"
        }

    def _gen_part10(self, chem: Dict, is_flammable: bool) -> Dict:
        return {
            "stability": "在正常储存和操作条件下稳定。",
            "conditions_to_avoid": "高温、火源、静电、强氧化剂。" if is_flammable else "无特殊条件。",
            "incompatible_materials": "强氧化剂、酸类、碱类。",
            "hazardous_decomposition": "燃烧或高温分解时产生一氧化碳、二氧化碳、及其他有机裂解产物。",
            "polymerization_hazard": "不会发生聚合反应。"
        }

    def _gen_part11(self, chem: Dict) -> Dict:
        return {
            "acute_toxicity": {
                "oral_ld50": chem.get("ld50_oral", "无资料"),
                "dermal_ld50": "无资料",
                "inhalation_lc50": "无资料"
            },
            "skin_corrosion_irritation": "皮肤腐蚀/刺激。",
            "serious_eye_damage_irritation": "严重眼损伤/眼刺激。",
            "respiratory_skin_sensitization": "不致敏。",
            "carcinogenicity": "无资料",
            "reproductive_toxicity": "无资料",
            "stot_single_exposure": "高浓度可能引起呼吸道刺激或麻醉效应。",
            "stot_repeated_exposure": "长期接触可能对器官造成损害。"
        }

    def _gen_part12(self, chem: Dict) -> Dict:
        return {
            "ecotoxicity": {
                "fish_lc50": "无资料",
                "invertebrate_ec50": "无资料",
                "algae_ec50": "无资料"
            },
            "persistence_degradability": "具有一定的生物降解性。",
            "bioaccumulation": "BCF值低，生物富集潜力不大。",
            "mobility_in_soil": "可能在土壤中迁移。",
            "other_adverse_effects": "对水生生物有害。" if any("毒" in c for c in chem.get("ghs_classifications", [])) else "无特殊环境危害。"
        }

    def _gen_part13(self) -> Dict:
        return {
            "disposal_methods": "须委托有资质的危险废物处理商进行处置。不得直接排入下水道或土壤。",
            "container_handling": "空容器须彻底清洗后再处置。残留物可能具有危害性。",
            "disposal_precautions": "处置前应参阅国家和地方有关法规。遵守危险废物转移联单制度。"
        }

    def _gen_part14(self, chem: Dict, is_flammable: bool, is_corrosive: bool, is_toxic: bool) -> Dict:
        un = chem.get("un_number", "")
        if is_corrosive:
            transport_class, class_name = "8", "腐蚀性物质"
        elif is_flammable:
            transport_class, class_name = "3", "易燃液体"
        elif is_toxic:
            transport_class, class_name = "6.1", "有毒物质"
        else:
            transport_class, class_name = "3", "易燃液体"

        return {
            "un_number": f"UN {un}" if un else "待确定",
            "proper_shipping_name": chem.get("chemical_name_cn", ""),
            "transport_hazard_class": transport_class,
            "class_name": class_name,
            "packing_group": "II",
            "marine_pollutant": "否"
        }

    def _gen_part15(self) -> Dict:
        return {
            "china_regulations": [
                "《危险化学品安全管理条例》（国务院令第591号）",
                "《危险化学品目录》（2015版，含2026年调整）",
                "GB 30000系列《化学品分类和标签规范》",
                "GBZ 2.1-2019《工作场所有害因素职业接触限值 化学有害因素》"
            ],
            "international_regulations": [
                "《联合国危险货物运输建议书》（UN RTDG）",
                "《全球化学品统一分类和标签制度》（GHS Rev.10）",
                "《欧盟REACH法规》（(EC) No 1907/2006）",
                "《美国OSHA标准》（29 CFR 1910.1200）"
            ]
        }

    def _gen_part16(self, sds_number: str) -> Dict:
        return {
            "preparation_info": {
                "sds_number": sds_number,
                "version": "1.0.0",
                "revision_date": datetime.now().strftime("%Y-%m-%d"),
                "prepared_by": "HuaAnTong AI系统"
            },
            "training_requirements": "操作人员须经过专门培训，了解化学品的危险性和安全操作规程。",
            "references": [
                "GB/T 16483-2008《化学品安全技术说明书 内容和项目顺序》",
                "GB/T 17519-2013《化学品安全技术说明书编写指南》",
                "PubChem Chemical Database"
            ],
            "disclaimer": "本SDS仅供参考，使用前请务必阅读并理解标签。对于任何因使用或依赖本信息而造成的损害，我们不承担责任。"
        }

    def to_markdown(self, msds: Dict) -> str:
        """转换为完整16部分Markdown"""
        lines = []
        lines.append("# 化学品安全技术说明书（SDS）")
        lines.append("")
        lines.append(f"**SDS编号**: {msds['document_info']['sds_number']}")
        lines.append(f"**版本**: {msds['document_info']['version']}")
        lines.append(f"**修订日期**: {msds['document_info']['revision_date']}")
        lines.append(f"**数据来源**: {msds['document_info'].get('data_source', '')}")
        lines.append(f"**数据完整度**: {msds['document_info'].get('completeness', '')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 1
        p1 = msds["part1_identification"]
        lines.append("## 第一部分：化学品及企业标识")
        lines.append("")
        lines.append(f"| 项目 | 内容 |")
        lines.append("|------|------|")
        lines.append(f"| 化学品名称 | {p1['product_name_cn']} |")
        lines.append(f"| CAS号 | {p1['cas_number']} |")
        lines.append(f"| 分子式 | {p1['molecular_formula']} |")
        lines.append(f"| 分子量 | {p1['molecular_weight']} g/mol |")
        lines.append(f"| UN编号 | {p1['un_number']} |")
        lines.append(f"| IUPAC名称 | {p1.get('iupac_name', '无')} |")
        lines.append("")
        lines.append(f"**推荐用途**: {p1['recommended_use']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 2
        p2 = msds["part2_hazard"]
        lines.append("## 第二部分：危险性概述")
        lines.append("")
        lines.append(f"**紧急概述**: {p2['emergency_overview']}")
        lines.append("")
        lines.append(f"**GHS危险性类别**:")
        for c in p2['ghs_classifications']:
            lines.append(f"- {c}")
        lines.append(f"**象形图**: {', '.join(p2['pictograms'])}")
        lines.append(f"**信号词**: {p2['signal_word']}")
        lines.append("")
        lines.append("**危险性说明（H码）**:")
        for h in p2['hazard_codes']:
            lines.append(f"- {h}")
        lines.append("")
        lines.append("**防范说明（P码）**:")
        ps = p2['precautionary_statements']
        lines.append("**预防**: " + "； ".join(ps.get('prevention', [])))
        lines.append("**响应**: " + "； ".join(ps.get('response', [])))
        lines.append("**储存**: " + "； ".join(ps.get('storage', [])))
        lines.append("**废弃**: " + "； ".join(ps.get('disposal', [])))
        lines.append("")
        lines.append(f"**物理化学危险**: {p2['physical_hazards']}")
        hh = p2['health_hazards']
        lines.append("**健康危害**:")
        lines.append(f"- 吸入：{hh['inhalation']}")
        lines.append(f"- 皮肤：{hh['skin_contact']}")
        lines.append(f"- 眼睛：{hh['eye_contact']}")
        lines.append(f"- 食入：{hh['ingestion']}")
        lines.append(f"**环境危害**: {p2['environmental_hazards']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 3
        p3 = msds["part3_composition"]
        lines.append("## 第三部分：成分/组成信息")
        lines.append("")
        lines.append(f"| 项目 | 内容 |")
        lines.append("|------|------|")
        for comp in p3.get('components', []):
            lines.append(f"| 化学名称 | {comp['name']} |")
            lines.append(f"| CAS号 | {comp['cas']} |")
            lines.append(f"| 纯度 | {comp['purity']} |")
            lines.append(f"| 化学类别 | {comp['chemical_family']} |")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 4
        p4 = msds["part4_first_aid"]
        lines.append("## 第四部分：急救措施")
        lines.append("")
        lines.append(f"**吸入**: {p4.get('inhalation', '无资料')}")
        lines.append(f"**皮肤接触**: {p4.get('skin_contact', '无资料')}")
        lines.append(f"**眼睛接触**: {p4.get('eye_contact', '无资料')}")
        lines.append(f"**食入**: {p4.get('ingestion', '无资料')}")
        if 'protection_for_rescuers' in p4:
            lines.append(f"**救援人员防护**: {p4['protection_for_rescuers']}")
        if 'notes_to_physician' in p4:
            lines.append(f"**对医生提示**: {p4['notes_to_physician']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 5
        p5 = msds["part5_firefighting"]
        lines.append("## 第五部分：消防措施")
        lines.append("")
        lines.append(f"**危险特性**: {p5['hazard_characteristics']}")
        lines.append(f"**适用灭火剂**: {p5['extinguishing_media']}")
        lines.append(f"**禁止使用的灭火剂**: {p5['extinguishing_prohibited']}")
        lines.append(f"**消防建议**: {p5['firefighting_advice']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 6
        p6 = msds["part6_spill"]
        lines.append("## 第六部分：泄漏应急处理")
        lines.append("")
        lines.append(f"**人员防护**: {p6['personal_precautions']}")
        lines.append(f"**应急响应**: {p6['emergency_response']}")
        lines.append(f"**环境保护**: {p6['environmental_precautions']}")
        lines.append(f"**泄漏隔离**: {p6['containment_methods']}")
        lines.append(f"**清理方法**: {p6['cleaning_methods']}")
        lines.append(f"**应急人员防护装备**: {p6['ppe_for_cleanup']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 7
        p7 = msds["part7_handling"]
        lines.append("## 第七部分：操作处置与储存")
        lines.append("")
        lines.append(f"**操作注意事项**: {p7.get('operation_notes', p7.get('handling_precautions', '无资料'))}")
        lines.append(f"**储存条件**: {p7.get('storage_conditions', '无资料')}")
        lines.append(f"**禁配物**: {p7.get('incompatible_materials', '无资料')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 8
        p8 = msds["part8_exposure"]
        lines.append("## 第八部分：接触控制/个体防护")
        lines.append("")
        ol = p8['occupational_limits']
        lines.append("**职业接触限值**:")
        lines.append(f"- 中国PC-TWA: {ol['china_pc_twa']}")
        lines.append(f"- 中国PC-STEL: {ol['china_pc_stel']}")
        lines.append(f"- ACGIH TLV-TWA: {ol['acgih_tlv_twa']}")
        lines.append("")
        lines.append(f"**监测方法**: {p8['monitoring_method']}")
        lines.append(f"**工程控制**: {p8['engineering_controls']}")
        lines.append(f"**呼吸防护**: {p8['respiratory_protection']}")
        lines.append(f"**眼睛防护**: {p8['eye_protection']}")
        lines.append(f"**皮肤防护**: {p8['skin_protection']}")
        lines.append(f"**卫生措施**: {p8['hygiene_measures']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 9
        p9 = msds["part9_physical"]
        lines.append("## 第九部分：理化特性")
        lines.append("")
        lines.append(f"| 特性 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 外观 | {p9['appearance']} |")
        lines.append(f"| 熔点 | {p9['melting_point']} |")
        lines.append(f"| 沸点 | {p9['boiling_point']} |")
        lines.append(f"| 闪点 | {p9['flash_point']} |")
        lines.append(f"| 自燃温度 | {p9['autoignition_temp']} |")
        lines.append(f"| 爆炸极限 | {p9['explosion_limits']} |")
        lines.append(f"| 溶解性 | {p9['solubility']} |")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 10
        p10 = msds["part10_stability"]
        lines.append("## 第十部分：稳定性和反应性")
        lines.append("")
        lines.append(f"**稳定性**: {p10.get('stability', '无资料')}")
        lines.append(f"**应避免的条件**: {p10.get('conditions_to_avoid', '无资料')}")
        lines.append(f"**禁配物**: {p10.get('incompatible_materials', '无资料')}")
        lines.append(f"** hazardous分解产物**: {p10.get('hazardous_decomposition', '无资料')}")
        lines.append(f"**聚合危害**: {p10.get('polymerization_hazard', '无资料')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 11
        p11 = msds["part11_toxicology"]
        lines.append("## 第十一部分：毒理学信息")
        lines.append("")
        at = p11['acute_toxicity']
        lines.append("**急性毒性**:")
        lines.append(f"- 经口LD50: {at['oral_ld50']}")
        lines.append(f"- 经皮LD50: {at['dermal_ld50']}")
        lines.append(f"- 吸入LC50: {at['inhalation_lc50']}")
        lines.append("")
        lines.append(f"**皮肤腐蚀/刺激**: {p11['skin_corrosion_irritation']}")
        lines.append(f"**严重眼损伤/眼刺激**: {p11['serious_eye_damage_irritation']}")
        lines.append(f"**呼吸/皮肤致敏**: {p11['respiratory_skin_sensitization']}")
        lines.append(f"**致癌性**: {p11['carcinogenicity']}")
        lines.append(f"**生殖毒性**: {p11['reproductive_toxicity']}")
        lines.append(f"**单次接触STOT**: {p11['stot_single_exposure']}")
        lines.append(f"**反复接触STOT**: {p11['stot_repeated_exposure']}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 12
        p12 = msds["part12_ecology"]
        lines.append("## 第十二部分：生态学信息")
        lines.append("")
        ec = p12['ecotoxicity']
        lines.append("**生态毒性**:")
        lines.append(f"- 鱼类LC50: {ec['fish_lc50']}")
        lines.append(f"- 无脊椎动物EC50: {ec['invertebrate_ec50']}")
        lines.append(f"- 藻类EC50: {ec['algae_ec50']}")
        lines.append("")
        lines.append(f"**持久性和降解性**: {p12.get('persistence_degradability', '无资料')}")
        lines.append(f"**生物富集潜力**: {p12.get('bioaccumulation_potential', '无资料')}")
        lines.append(f"**土壤迁移性**: {p12.get('soil_mobility', '无资料')}")
        lines.append(f"**其他不良效应**: {p12.get('other_adverse_effects', '无资料')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 13
        p13 = msds["part13_disposal"]
        lines.append("## 第十三部分：废弃处置")
        lines.append("")
        lines.append(f"**处置方法**: {p13['disposal_methods']}")
        lines.append(f"**容器处理**: {p13['container_handling']}")
        lines.append(f"**注意事项**: {p13.get('notes', p13.get('disposal_precautions', '无资料'))}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 14
        p14 = msds["part14_transport"]
        lines.append("## 第十四部分：运输信息")
        lines.append("")
        lines.append(f"| 项目 | 内容 |")
        lines.append("|------|------|")
        lines.append(f"| UN编号 | {p14['un_number']} |")
        lines.append(f"| 正式运输名称 | {p14['proper_shipping_name']} |")
        lines.append(f"| 运输危险类别 | {p14['transport_hazard_class']} ({p14['class_name']}) |")
        lines.append(f"| 包装类别 | {p14['packing_group']} |")
        lines.append(f"| 海洋污染物 | {p14['marine_pollutant']} |")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 15
        p15 = msds["part15_regulatory"]
        lines.append("## 第十五部分：法规信息")
        lines.append("")
        lines.append("**中国法规**:")
        for r in p15.get('china_regulations', []):
            lines.append(f"- {r}")
        lines.append("")
        lines.append("**国际/地区法规**:")
        for r in p15.get('international_regulations', []):
            lines.append(f"- {r}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Part 16
        p16 = msds["part16_other"]
        lines.append("## 第十六部分：其他信息")
        lines.append("")
        pi = p16.get('preparation_info', {})
        lines.append(f"**SDS编号**: {pi.get('sds_number', 'N/A')}")
        lines.append(f"**版本**: {pi.get('version', 'N/A')}")
        lines.append(f"**修订日期**: {pi.get('revision_date', 'N/A')}")
        lines.append(f"**编制者**: {pi.get('prepared_by', 'HuaAnTong AI系统')}")
        lines.append("")
        lines.append("**培训要求**:")
        lines.append(p16.get('training_requirements', '操作人员须经过专门培训，了解化学品的危险性和安全操作规程。'))
        lines.append("")
        lines.append("**参考文献**:")
        for r in p16.get('references', []):
            lines.append(f"- {r}")
        lines.append("")
        lines.append("**免责说明**:")
        lines.append(p16.get('disclaimer', '本SDS仅供参考，使用前请务必阅读并理解标签。对于任何因使用或依赖本信息而造成的损害，我们不承担责任。'))
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append(f"*HuaAnTong AI MSDS自动生成系统*")

        return "\n".join(lines)


# ============================================================
# 主程序
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("用法: python msds_pipeline.py <CAS号或化学品名称>")
        print("示例: python msds_pipeline.py 106-44-5")
        print("      python msds_pipeline.py 67-64-1")
        print("      python msds_pipeline.py acetone")
        return

    cas_or_name = sys.argv[1]

    print("=" * 60)
    print("化安通 (HuaAnTong) - MSDS自动生成系统")
    print("=" * 60)

    generator = MSDSGenerator()
    msds = generator.generate(cas_or_name)

    if "error" in msds:
        print(f"\n[ERROR] {msds['error']}")
        return

    md = generator.to_markdown(msds)

    # 保存文件
    cas = cas_or_name.strip().replace("-", "_")
    output_file = OUTPUT_DIR / f"MSDS_{cas}_detailed.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n[OK] MSDS已生成: {output_file}")
    print(f"  大小: {len(md)} 字符")
    print(f"  数据来源: {msds['document_info'].get('data_source', '')}")

    # 自动创建化学品目录并移动文件
    chem_name = msds['part1_identification']['product_name_cn']
    if chem_name:
        chem_dir = OUTPUT_DIR / chem_name
        chem_dir.mkdir(exist_ok=True)
        new_file = chem_dir / f"MSDS_{chem_name}_detailed.md"
        import shutil
        shutil.copy(output_file, new_file)
        print(f"  [OK] 复制至: {new_file}")

    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    main()