"""
SDS/MSDS 模板化生成引擎
化安通 (HuaAnTong) MSDS自动生成系统 - 第五层

职责：
1. 接收标准化成分数据 + 分类结果 + 证据事实池
2. 按模板直填结构化字段
3. 低置信度字段标记 [待确认]
4. 输出完整16节SDS文档（Markdown）

不依赖LLM——纯规则驱动的模板引擎
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = PROJECT_ROOT / "db"


# ============================================================
# 数据类
# ============================================================

@dataclass
class FieldValue:
    """带来源标注的字段值"""
    value: Any
    source: str = ""           # kb / pubchem / ai / classification / template / input
    confidence: float = 1.0    # 0.0 - 1.0
    needs_review: bool = False


@dataclass
class SDSSection:
    """SDS章节"""
    id: int
    title_cn: str
    title_en: str
    fields: Dict[str, FieldValue] = field(default_factory=dict)
    raw_content: str = ""      # 生成的Markdown内容


@dataclass
class SDSDocument:
    """完整SDS文档"""
    sections: Dict[int, SDSSection] = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)
    review_flags: List[str] = field(default_factory=list)  # 需人工审核的项


# ============================================================
# 模板加载
# ============================================================

class TemplateLoader:
    """加载SDS模板和GHS映射"""

    def __init__(self):
        self.template = self._load_json("sds_template.json")
        self.ghs_mappings = self._load_json("ghs_mappings.json")

    def _load_json(self, filename: str) -> dict:
        path = DB_DIR / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def get_section_template(self, section_id: int) -> Optional[dict]:
        for s in self.template.get("sections", []):
            if s["id"] == section_id:
                return s
        return None

    def h_code_to_text(self, h_code: str) -> str:
        h_stmts = self.ghs_mappings.get("h_statements", {})
        return h_stmts.get(h_code, h_code)

    def p_code_to_text(self, p_code: str) -> str:
        p_stmts = self.ghs_mappings.get("p_statements", {})
        return p_stmts.get(p_code, p_code)

    def hazard_to_h_code(self, hazard_class: str) -> str:
        mapping = self.ghs_mappings.get("hazard_class_to_h", {})
        # 精确匹配
        if hazard_class in mapping:
            return mapping[hazard_class]
        # 模糊匹配: "易燃液体，类别2" → "易燃液体 Cat 2"
        normalized = self._normalize_hazard(hazard_class)
        if normalized in mapping:
            return mapping[normalized]
        # Split "/" compound names and try each part
        if "/" in hazard_class:
            cat_part = ""
            if "，" in hazard_class:
                cat_part = "，" + hazard_class.split("，", 1)[1]
            elif "," in hazard_class:
                cat_part = "," + hazard_class.split(",", 1)[1]
            for part in hazard_class.split("/")[1:]:  # skip first part (already tried)
                test = part.strip() + cat_part
                if test:
                    # try exact
                    if test in mapping:
                        return mapping[test]
                    # try normalized
                    norm = self._normalize_hazard(test)
                    if norm in mapping:
                        return mapping[norm]
        return ""

    def _normalize_hazard(self, hazard_class: str) -> str:
        """标准化GHS分类名称: '易燃液体，类别2' → '易燃液体 Cat 2'"""
        import re
        s = hazard_class.replace("，", " ").replace(",", " ")
        s = re.sub(r'类别\s*(\d+[A-Z]?)', r'Cat \1', s)
        s = re.sub(r'类别\s*（[^）]*）\s*(\d+[A-Z]?)', r'Cat \1', s)
        # 同义词: "一次接触" → "单次", "加压气体" → "高压气体"
        s = s.replace("一次接触", "单次")
        s = s.replace("加压气体", "高压气体")
        # Preserve known classification qualifiers (麻醉效应, 呼吸道刺激, etc.)
        # by converting （qualifier） to plain text before generic bracket removal
        qualifier_match = re.search(r'（([^）]+)）', s)
        qualifier_text = qualifier_match.group(1) if qualifier_match else ""
        s = re.sub(r'（[^）]*）', '', s)
        s = re.sub(r'\(\)', '', s)
        # Normalize spacing around hyphens: "气体 - 压缩" → "气体-压缩"
        s = re.sub(r'\s*-\s*', '-', s)
        s = s.strip()
        # Append qualifier after category if present
        if qualifier_text:
            cat_match = re.search(r'(Cat \d+[A-Z]?)\s*$', s)
            if cat_match:
                s = s[:cat_match.start()] + cat_match.group(1) + " " + qualifier_text
        return s.strip()

    def hazard_to_pictograms(self, hazard_class: str) -> List[str]:
        mapping = self.ghs_mappings.get("ghs_to_pictogram", {})
        if hazard_class in mapping:
            return mapping[hazard_class]
        normalized = self._normalize_hazard(hazard_class)
        if normalized in mapping:
            return mapping[normalized]
        # 提取Cat号用于精确匹配
        cat_match = re.search(r'Cat\s*(\d+[A-Za-z]*)', normalized)
        target_cat = cat_match.group(1) if cat_match else ""
        # 优先匹配Cat号一致的最长前缀
        best_match = None
        best_len = 0
        for key, val in mapping.items():
            prefix = key.split(" Cat")[0].split("，")[0]
            if prefix in hazard_class:
                key_cat_match = re.search(r'Cat\s*(\d+[A-Za-z]*)', key)
                key_cat = key_cat_match.group(1) if key_cat_match else ""
                if key_cat == target_cat and len(prefix) >= best_len:
                    best_match = val
                    best_len = len(prefix)
        if best_match:
            return best_match
        # Fallback: 最长前缀匹配（不要求Cat一致）
        for key, val in mapping.items():
            prefix = key.split(" Cat")[0].split("，")[0]
            if prefix in hazard_class and len(prefix) > best_len:
                best_match = val
                best_len = len(prefix)
        return best_match or []

    def hazard_to_signal_word(self, hazard_class: str) -> str:
        mapping = self.ghs_mappings.get("ghs_to_signal_word", {})
        if hazard_class in mapping:
            return mapping[hazard_class]
        normalized = self._normalize_hazard(hazard_class)
        if normalized in mapping:
            return mapping[normalized]
        # Fuzzy match: only match keys whose Cat number matches
        import re
        cat_match = re.search(r'Cat\s*(\d+[A-Za-z]*)', normalized)
        target_cat = cat_match.group(1) if cat_match else ""
        best_match = None
        best_len = 0
        cat_matched = False
        for key, val in mapping.items():
            prefix = key.split(" Cat")[0].split("，")[0]
            if prefix in hazard_class:
                key_cat_match = re.search(r'Cat\s*(\d+[A-Za-z]*)', key)
                key_cat = key_cat_match.group(1) if key_cat_match else ""
                if key_cat == target_cat and len(prefix) >= best_len:
                    best_match = val
                    best_len = len(prefix)
                    cat_matched = True
        # Fallback: if no Cat match, use longest prefix
        if not cat_matched:
            for key, val in mapping.items():
                prefix = key.split(" Cat")[0].split("，")[0]
                if prefix in hazard_class and len(prefix) > best_len:
                    best_match = val
                    best_len = len(prefix)
        return best_match or ""

    def hazard_to_p_codes(self, hazard_class: str) -> Dict[str, List[str]]:
        """获取某危害类别的P码（按预防/响应/储存/废弃分组）"""
        mapping = self.ghs_mappings.get("hazard_class_to_p_codes", {})
        # 先精确匹配
        if hazard_class in mapping:
            return mapping[hazard_class]
        # 再模糊匹配（如 "皮肤腐蚀 Cat 1A" → "皮肤腐蚀 Cat 1"）
        for key, val in mapping.items():
            if key in hazard_class or hazard_class.startswith(key):
                return val
        return {}


# ============================================================
# SDS生成引擎
# ============================================================

class SDSGenerator:
    """SDS文档模板化生成引擎"""

    def __init__(self, use_llm: bool = False):
        self.templates = TemplateLoader()
        self.document = SDSDocument()
        self.use_llm = use_llm
        self._init_sections()

    def _init_sections(self):
        """初始化16个章节"""
        for s in self.templates.template.get("sections", []):
            sec = SDSSection(id=s["id"], title_cn=s["title_cn"], title_en=s["title_en"])
            self.document.sections[s["id"]] = sec

    # ----------------------------------------------------------
    # 输入数据设置
    # ----------------------------------------------------------

    def set_chemical_data(self, data: dict):
        """设置化学品基础数据（来自KB或PubChem）"""
        self._kb_data = data
        # 第一部分：化学品标识
        s1 = self.document.sections[1]
        mappings = {
            "product_name_cn": ("chemical_name_cn", "kb"),
            "product_name_en": ("chemical_name_en", "kb"),
            "cas_number": ("cas_number", "kb"),
            "molecular_formula": ("molecular_formula", "kb"),
            "molecular_weight": ("molecular_weight", "kb"),
            "un_number": ("un_number", "kb"),
            "ec_number": ("ec_number", "kb"),
            "iupac_name": ("iupac_name", "kb"),
        }
        for field_key, (data_key, source) in mappings.items():
            val = data.get(data_key)
            if val:
                s1.fields[field_key] = FieldValue(value=val, source=source)

        # 第九部分：理化特性
        s9 = self.document.sections[9]
        phys_mappings = {
            "melting_point": "melting_point",
            "boiling_point": "boiling_point",
            "flash_point": "flash_point",
            "density": "density",
            "vapor_pressure": "vapor_pressure",
            "autoignition_temp": "autoignition_temp",
            "explosion_limits": "explosion_limits",
            "partition_coefficient": "partition_coefficient_n-octanol_water",
            "appearance": "appearance",
            "odor": "odor",
        }
        for field_key, data_key in phys_mappings.items():
            val = data.get(data_key)
            if val:
                s9.fields[field_key] = FieldValue(value=val, source="kb")

        # 特殊处理
        if data.get("solubility_details"):
            s9.fields["solubility"] = FieldValue(value=data["solubility_details"], source="kb")

        # 第十一部分：毒理学
        s11 = self.document.sections[11]
        tox_mappings = {
            "ld50_oral": "ld50_oral",
            "ld50_dermal": "ld50_dermal",
            "lc50_inhalation": "lc50_inhalation",
        }
        for field_key, data_key in tox_mappings.items():
            val = data.get(data_key)
            if val:
                s11.fields[field_key] = FieldValue(value=val, source="kb")

        # 其他毒理字段
        for key in ["skin_corrosion_category", "eye_damage_category", "skin_sensitization",
                     "mutagenicity", "carcinogenicity_ghs", "reproductive_toxicity_category",
                     "stot_single_exposure", "stot_repeated_exposure"]:
            if data.get(key):
                field_name = key
                s11.fields[field_name] = FieldValue(value=data[key], source="kb")

        # 第八部分：职业接触限值
        s8 = self.document.sections[8]
        oel_fields = ["pc_twa", "pc_stel", "acgih_tlv_twa", "acgih_tlv_stel"]
        oel_values = {}
        for f in oel_fields:
            if data.get(f):
                oel_values[f] = data[f]
        if oel_values:
            s8.fields["oel_table"] = FieldValue(value=oel_values, source="kb")

        # 第十四部分：运输
        s14 = self.document.sections[14]
        for key in ["un_number", "transport_class", "transport_class_name", "packing_group", "marine_pollutant"]:
            if data.get(key):
                target_key = key if key != "transport_class_name" else "proper_shipping_name"
                s14.fields[target_key] = FieldValue(value=data[key], source="kb")

        # 第十部分：反应性
        s10 = self.document.sections[10]
        for key in ["incompatible_materials", "hazardous_decomposition"]:
            val = data.get(key, "")
            if val:
                s10.fields[key] = FieldValue(value=val, source="kb")
        # 从GHS分类推导应避免条件
        ghs_list = data.get("ghs_classifications", [])
        ghs_text = " ".join(str(g) for g in ghs_list) if isinstance(ghs_list, list) else str(ghs_list)
        if "易燃" in ghs_text:
            s10.fields["conditions_to_avoid"] = FieldValue(value="明火、高热、静电、火花。", source="kb")
        elif "腐蚀" in ghs_text:
            s10.fields["conditions_to_avoid"] = FieldValue(value="潮湿环境、水。", source="kb")
        else:
            s10.fields["conditions_to_avoid"] = FieldValue(value="明火、高热。", source="kb")

        # 第四部分：急救注释
        s4 = self.document.sections[4]
        first_aid = data.get("first_aid_notes", {})
        if isinstance(first_aid, dict):
            for route in ["inhalation", "skin", "eye", "ingestion"]:
                note = first_aid.get(route, "")
                if note:
                    s4.fields[f"notes_{route}"] = FieldValue(value=note, source="kb")

        # 第五部分：消防注释
        s5 = self.document.sections[5]
        if data.get("firefighting_notes"):
            s5.fields["notes"] = FieldValue(value=data["firefighting_notes"], source="kb")
        if data.get("extinguishing_media_prohibited"):
            s5.fields["prohibited_media"] = FieldValue(value=data["extinguishing_media_prohibited"], source="kb")

        # 第十一部分：毒理注释
        tox_notes = data.get("toxicology_notes", {})
        if isinstance(tox_notes, dict):
            for key in ["acute_symptoms", "chronic_effects", "eye_effects", "iarc_group"]:
                note = tox_notes.get(key, "")
                if note:
                    s11.fields[f"notes_{key}"] = FieldValue(value=note, source="kb")

        # 第三部分：成分
        s3 = self.document.sections[3]

        # 第十二部分：生态
        s12 = self.document.sections[12]
        eco_mappings = {
            "ecotoxicity_fish_lc50": "ecotoxicity_fish_lc50",
            "ecotoxicity_daphnia_ec50": "ecotoxicity_daphnia_ec50",
            "ecotoxicity_algae_ec50": "ecotoxicity_algae_ec50",
            "persistence_degradability": "persistence_degradability",
            "bioaccumulation_bcf": "bioaccumulation_bcf",
            "bioaccumulation_log_bc": "bioaccumulation_log_bc",
        }
        for field_key, data_key in eco_mappings.items():
            val = data.get(data_key)
            if val:
                s12.fields[field_key] = FieldValue(value=val, source="kb")
        if data.get("mobility_in_soil"):
            s12.fields["mobility_in_soil"] = FieldValue(value=data["mobility_in_soil"], source="kb")

    def set_classification(self, classifications: List[dict]):
        """
        设置分类结果（来自mixture_calculator或单组分分类）

        classifications中每项: {
            "hazard": "易燃液体 Cat 2",
            "h_code": "H225",
            "signal": "危险",
            "pictograms": ["GHS02"],
            "reason": "...",
            ...
        }
        """
        self._classifications = classifications
        s2 = self.document.sections[2]

        # GHS分类列表
        ghs_classes = []
        h_codes = []
        signal_words = set()
        all_pictograms = []

        for cls in classifications:
            hazard = cls.get("hazard", "")
            ghs_classes.append(hazard)

            # H码
            h_code = cls.get("h_code", "")
            if h_code and h_code not in h_codes:
                h_codes.append(h_code)

            # 信号词
            sig = cls.get("signal", "")
            if sig:
                signal_words.add(sig)

            # 象形图（优先用分类结果的，否则从映射表查找，含中英文路由名兜底）
            picts = cls.get("pictograms") or []
            if not picts or picts == ["NONE"]:
                picts = self.templates.hazard_to_pictograms(hazard)
            if not picts:
                # mixture_calculator 用英文路由名(oral/dermal/inhalation)，映射表用中文(经口/经皮/吸入)
                cn_route = hazard
                for en, cn in [("oral", "经口"), ("dermal", "经皮"), ("inhalation", "吸入")]:
                    cn_route = cn_route.replace(en, cn)
                if cn_route != hazard:
                    picts = self.templates.hazard_to_pictograms(cn_route)
            for p in picts:
                if p not in all_pictograms:
                    all_pictograms.append(p)

        s2.fields["ghs_classifications"] = FieldValue(value=ghs_classes, source="classification")
        s2.fields["hazard_statements"] = FieldValue(value=h_codes, source="classification")
        # 信号词: 优先使用分类结果，fallback到KB数据
        sw = "危险" if "危险" in signal_words else ("警告" if "警告" in signal_words else "")
        if not sw:
            kb_sw = self._kb_data.get("signal_word", "")
            if kb_sw:
                sw = kb_sw
        s2.fields["signal_word"] = FieldValue(value=sw, source="classification")
        s2.fields["pictograms"] = FieldValue(value=all_pictograms, source="classification")

        # 生成P码
        all_p = {"prevention": [], "response": [], "storage": [], "disposal": []}
        for cls in classifications:
            hazard = cls.get("hazard", "")
            p_codes = cls.get("p_codes") or self.templates.hazard_to_p_codes(hazard)
            for group, codes in p_codes.items():
                if group in all_p:
                    for code in codes:
                        if code not in all_p[group]:
                            all_p[group].append(code)

        s2.fields["precautionary_statements"] = FieldValue(value=all_p, source="classification")

        # 分类也填充第11部分毒理相关
        s11 = self.document.sections[11]
        for cls in classifications:
            hazard = cls.get("hazard", "")
            if "急性毒性" in hazard and "经口" in hazard:
                s11.fields["acute_oral"] = FieldValue(value=hazard, source="classification")
            elif "皮肤腐蚀" in hazard:
                s11.fields["skin_corrosion_category"] = FieldValue(value=hazard, source="classification")
            elif "皮肤刺激" in hazard:
                s11.fields["skin_corrosion_category"] = FieldValue(value=hazard, source="classification")
            elif "眼损伤" in hazard:
                s11.fields["eye_damage_category"] = FieldValue(value=hazard, source="classification")
            elif "眼刺激" in hazard:
                s11.fields["eye_damage_category"] = FieldValue(value=hazard, source="classification")
            elif "STOT" in hazard or "靶器官" in hazard:
                if "单次" in hazard:
                    s11.fields["stot_single_exposure"] = FieldValue(value=hazard, source="classification")
                elif "反复" in hazard:
                    s11.fields["stot_repeated_exposure"] = FieldValue(value=hazard, source="classification")
            elif "吸入危害" in hazard:
                s11.fields["aspiration_hazard"] = FieldValue(value=hazard, source="classification")

    def set_components(self, components: List[dict], is_mixture: bool = False):
        """
        设置组分信息

        components: [{"name": "乙醇", "cas": "64-17-5", "concentration": 30, ...}]
        """
        s3 = self.document.sections[3]
        s3.fields["chemical_type"] = FieldValue(
            value="混合物" if is_mixture else "物质",
            source="input"
        )
        s3.fields["components"] = FieldValue(value=components, source="input")

    def set_input_info(self, product_name: str = "", recommended_use: str = "",
                       supplier: str = "", emergency_phone: str = "",
                       version: str = "1.0", revision_date: str = "",
                       revision_log: list = None):
        """设置用户输入信息"""
        s1 = self.document.sections[1]
        if product_name:
            s1.fields["product_name_cn"] = FieldValue(value=product_name, source="input")
        if recommended_use:
            s1.fields["recommended_use"] = FieldValue(value=recommended_use, source="input")
        if supplier:
            s1.fields["supplier_info"] = FieldValue(value=supplier, source="input")
        if emergency_phone:
            s1.fields["emergency_phone"] = FieldValue(value=emergency_phone, source="input")
        # 版本管理
        self.document.metadata["version"] = version
        self.document.metadata["revision_date"] = revision_date
        self.document.metadata["revision_log"] = revision_log or []

    # ----------------------------------------------------------
    # 混合物危害聚合器（无需LLM，纯规则驱动）
    # ----------------------------------------------------------

    class MixtureHazardAggregator:
        """从所有组分中聚合危害信息，用于生成化学特异性内容"""

        TARGET_ORGAN_FIRST_AID = {
            "血液": {"ingestion": "注意溶血风险。监测血液参数（红细胞计数、血红蛋白）。",
                     "skin": "注意皮肤吸收导致的血液毒性风险。"},
            "中枢神经": {"inhalation": "可能导致头晕、嗜睡。保持患者清醒。"},
            "神经": {"inhalation": "可能导致神经损伤。长期暴露需监测神经系统功能。"},
            "肝": {"ingestion": "监测肝功能指标（ALT、AST）。"},
            "肾": {"ingestion": "监测肾功能指标。保持充足液体摄入。"},
            "呼吸": {"inhalation": "可能引起呼吸道刺激或肺水肿。延迟观察至少48小时。"},
        }

        TARGET_ORGAN_SPILL = {
            "血液": "泄漏物可能通过皮肤吸收导致血液毒性。加强皮肤防护。",
            "中枢神经": "蒸气可引起嗜睡和眩晕。确保充分通风。",
        }

        DECOMPOSITION_HAZARDS = {
            "氰": "燃烧可能产生剧毒氰化氢(HCN)气体。",
            "氯": "燃烧可能产生有毒氯气。",
            "氮": "燃烧可能产生有毒氮氧化物。",
            "硫": "燃烧可能产生有毒二氧化硫。",
        }

        def __init__(self, components_data: List[dict]):
            self.components = components_data
            self._all_target_organs = set()
            self._all_hazard_keywords = set()
            self._aggregate()

        def _aggregate(self):
            for comp in self.components:
                ghs_list = comp.get("ghs_classifications", [])
                if isinstance(ghs_list, list):
                    for ghs in ghs_list:
                        self._all_hazard_keywords.add(str(ghs))
                        if "靶器官" in str(ghs):
                            organ = self._extract_target_organ(str(ghs))
                            if organ:
                                self._all_target_organs.add(organ)

        def _extract_target_organ(self, ghs_str: str) -> str:
            match = re.search(r'[（(]\s*([^)）]+)\s*[)）]', ghs_str)
            if match:
                organ_text = match.group(1)
                for key in self.TARGET_ORGAN_FIRST_AID:
                    if key in organ_text:
                        return key
            return ""

        def get_first_aid_notes(self) -> Dict[str, List[str]]:
            result = {"inhalation": [], "skin": [], "eye": [], "ingestion": []}
            # 聚合各组分的KB急救注释
            for comp in self.components:
                notes = comp.get("first_aid_notes", {})
                if isinstance(notes, dict):
                    name = comp.get("chemical_name_cn", comp.get("name", ""))
                    for route in result:
                        note = notes.get(route, "")
                        if note:
                            result[route].append(f"[{name}] {note}")
            # 基于靶器官添加特异性建议
            for organ in self._all_target_organs:
                advice = self.TARGET_ORGAN_FIRST_AID.get(organ, {})
                for route, text in advice.items():
                    if text and text not in result.get(route, []):
                        result[route].append(text)
            return result

        def get_firefighting_notes(self) -> List[str]:
            notes = []
            for comp in self.components:
                ff = comp.get("firefighting_notes", "")
                if ff:
                    name = comp.get("chemical_name_cn", comp.get("name", ""))
                    notes.append(f"[{name}] {ff}")
            # 分解产物危害
            for comp in self.components:
                decomp = str(comp.get("hazardous_decomposition", ""))
                for key, warning in self.DECOMPOSITION_HAZARDS.items():
                    if key in decomp and warning not in notes:
                        notes.append(warning)
            return notes

        def get_spill_notes(self) -> List[str]:
            notes = []
            for organ in self._all_target_organs:
                advice = self.TARGET_ORGAN_SPILL.get(organ, "")
                if advice:
                    notes.append(advice)
            return notes

        def get_target_organs_summary(self) -> str:
            if not self._all_target_organs:
                return ""
            return "、".join(sorted(self._all_target_organs))

        def get_all_hazard_keywords(self) -> set:
            return self._all_hazard_keywords

    # ----------------------------------------------------------
    # 模板化生成各章节
    # ----------------------------------------------------------

    def _fv(self, value, source="template", confidence=1.0, needs_review=False) -> FieldValue:
        return FieldValue(value=value, source=source, confidence=confidence, needs_review=needs_review)

    def _val(self, section_id: int, field_key: str, default: str = "无可用数据") -> str:
        """获取字段值，无数据时标记[待确认]，有来源时追加HTML注释"""
        sec = self.document.sections.get(section_id)
        if sec and field_key in sec.fields:
            fv = sec.fields[field_key]
            v = fv.value
            if v is not None and v != "" and v != []:
                val_str = str(v)
                # 字段来源渲染（HTML注释，不影响Markdown显示）
                if fv.source and fv.source not in ("template", "input") and fv.confidence >= 0.7:
                    val_str += f" <!-- src:{fv.source} conf:{fv.confidence:.1f} -->"
                return val_str
        self.document.review_flags.append(f"第{section_id}部分-{field_key}: 缺少数据")
        if "[待确认]" in default:
            return default
        return f"{default} [待确认]"

    def _strip_unit(self, value: str) -> str:
        """去除KB值中已有的单位，防止模板追加时重复"""
        # 提取HTML注释
        comment = ''
        comment_match = re.search(r'(<!--.*?-->)\s*$', str(value))
        if comment_match:
            comment = ' ' + comment_match.group(1)
        main_val = re.sub(r'\s*<!--.*?-->\s*$', '', str(value))
        # 去除温度单位（可能在值中间，如"-20℃（闭杯）"）
        main_val = re.sub(r'[°℃][Cc]?', '', main_val)
        # 去除压力/密度单位
        main_val = re.sub(r'\s*kPa\b', '', main_val, flags=re.IGNORECASE)
        main_val = re.sub(r'\s*g/cm[³3]\b', '', main_val)
        main_val = re.sub(r'\s*g/mL\b', '', main_val)
        return main_val.strip() + comment

    def _has_classification(self, keyword: str) -> bool:
        """检查分类中是否包含某关键词"""
        for cls in getattr(self, '_classifications', []):
            if keyword in cls.get("hazard", ""):
                return True
        return False

    def _get_chemical_types(self) -> List[str]:
        """根据GHS分类+物性推断化学品类型标签列表"""
        types = set()
        classifications = getattr(self, '_classifications', [])
        ghs_text = " ".join(c.get("hazard", "") for c in classifications)
        kb = getattr(self, '_kb_data', {})

        # 易燃液体（闪点<60°C）
        if "易燃液体" in ghs_text:
            types.add("flammable_liquid")
        # 腐蚀性酸/碱
        if "皮肤腐蚀" in ghs_text or "金属腐蚀" in ghs_text:
            # 通过pH或成分区分酸/碱
            formula = str(kb.get("molecular_formula", ""))
            name = str(kb.get("chemical_name_cn", ""))
            acid_hints = ["HCl", "H2SO4", "HNO3", "H3PO4", "HF", "酸"]
            base_hints = ["NaOH", "KOH", "Ca(OH)2", "NH3", "碱", "氢氧化"]
            if any(h in formula or h in name for h in acid_hints):
                types.add("corrosive_acid")
            elif any(h in formula or h in name for h in base_hints):
                types.add("corrosive_alkali")
            else:
                types.add("corrosive_acid")  # 默认按酸处理
        # 急性毒性
        if "急性毒性" in ghs_text:
            types.add("toxic")
        # 氧化性
        if "氧化性" in ghs_text:
            types.add("oxidizer")
        # 易燃固体
        if "易燃固体" in ghs_text:
            types.add("flammable_solid")
        # 自反应/爆炸
        if "自反应" in ghs_text or "爆炸" in ghs_text:
            types.add("explosive")
        # 高压气体
        if "高压气体" in ghs_text or "加压气体" in ghs_text or "液化气体" in ghs_text:
            types.add("compressed_gas")
        # 重金属
        formula = str(kb.get("molecular_formula", ""))
        heavy_metals = ["Pb", "Hg", "Cd", "Cr", "As", "Cu", "Zn", "Ni", "Co"]
        if any(el in formula for el in heavy_metals):
            types.add("heavy_metal")
        # 有机溶剂（含碳 + 易燃）
        if "C" in formula and "flammable_liquid" in types:
            types.add("organic_solvent")
        # 吸入危害
        if "吸入危害" in ghs_text:
            types.add("aspiration_hazard")

        return list(types) if types else ["general"]

    def _is_chemical_type(self, type_name: str) -> bool:
        """快速判断是否属于某种化学品类型"""
        return type_name in self._get_chemical_types()

    def _try_llm_enhance(self, section_id: int, template_content: str) -> str:
        """尝试用LLM增强章节内容，失败时返回原始模板内容"""
        if not self.use_llm:
            return template_content
        try:
            sys_path = str(Path(__file__).resolve().parent)
            if sys_path not in sys.path:
                sys.path.insert(0, sys_path)
            from msds_llm_client import (
                generate_first_aid_section, generate_firefighting_section,
                generate_spill_section, generate_handling_section,
            )
            chem_data = getattr(self, '_kb_data', {})
            is_flammable = self._has_classification("易燃")
            is_corrosive = self._has_classification("腐蚀")
            is_toxic = self._has_classification("毒性") or self._has_classification("有毒")

            if section_id == 4:
                result = generate_first_aid_section(chem_data, is_corrosive, is_toxic)
                if result and isinstance(result, dict):
                    parts = []
                    for key in ["inhalation", "skin", "eye", "ingestion"]:
                        if result.get(key):
                            parts.append(f"**{key}**: {result[key]}")
                    if parts:
                        return "# 第四部分：急救措施\n\n" + "\n\n".join(parts) + "\n\n---"
            elif section_id == 5:
                result = generate_firefighting_section(chem_data, is_flammable, is_corrosive, is_explosive=False)
                if result and isinstance(result, dict):
                    parts = []
                    for key, label in [("extinguishing_media", "适用灭火剂"), ("prohibited_media", "禁止使用灭火剂"), ("specific_hazards", "特殊危险"), ("protective_equipment", "防护建议")]:
                        if result.get(key):
                            parts.append(f"**{label}**: {result[key]}")
                    if parts:
                        return "# 第五部分：消防措施\n\n" + "\n\n".join(parts) + "\n\n---"
            elif section_id == 6:
                result = generate_spill_section(chem_data, is_flammable, is_corrosive, is_toxic)
                if result and isinstance(result, dict):
                    parts = []
                    for key, label in [("personal_protection", "人员防护"), ("emergency_response", "应急响应"), ("environmental_protection", "环境保护"), ("cleanup_method", "清理方法")]:
                        if result.get(key):
                            parts.append(f"**{label}**: {result[key]}")
                    if parts:
                        return "# 第六部分：泄漏应急处理\n\n" + "\n\n".join(parts) + "\n\n---"
            elif section_id == 7:
                result = generate_handling_section(chem_data, is_flammable, is_corrosive)
                if result and isinstance(result, dict):
                    parts = []
                    for key, label in [("handling_precautions", "操作注意事项"), ("storage_conditions", "储存条件"), ("incompatible_materials", "禁配物")]:
                        if result.get(key):
                            parts.append(f"**{label}**: {result[key]}")
                    if parts:
                        return "# 第七部分：操作处置与储存\n\n" + "\n\n".join(parts) + "\n\n---"
        except Exception:
            pass  # LLM增强失败，静默回退到模板
        return template_content

    def generate_section_1(self) -> str:
        """第一部分：化学品及企业标识"""
        return (
            f"# 第一部分：化学品及企业标识\n\n"
            f"| 项目 | 内容 |\n|------|------|\n"
            f"| 化学品名称 | {self._val(1, 'product_name_cn')} |\n"
            f"| 英文名称 | {self._val(1, 'product_name_en')} |\n"
            f"| CAS号 | {self._val(1, 'cas_number')} |\n"
            f"| 分子式 | {self._val(1, 'molecular_formula')} |\n"
            f"| 分子量 | {self._val(1, 'molecular_weight')} g/mol |\n"
            f"| UN编号 | {self._val(1, 'un_number')} |\n"
            f"| EC号 | {self._val(1, 'ec_number', '不适用')} |\n"
            f"| IUPAC名称 | {self._val(1, 'iupac_name')} |\n"
            f"| 推荐用途 | {self._val(1, 'recommended_use', '请咨询供应商')} |\n"
            f"| 供应商 | {self._val(1, 'supplier_info', '请咨询供应商')} |\n"
            f"| 应急电话 | {self._val(1, 'emergency_phone', '请咨询供应商')} |"
        )

    def generate_section_2(self) -> str:
        """第二部分：危险性概述"""
        s2 = self.document.sections[2]

        # GHS分类
        ghs_classes = self._val(2, 'ghs_classifications')
        if isinstance(s2.fields.get('ghs_classifications'), FieldValue):
            ghs_list = s2.fields['ghs_classifications'].value
            ghs_text = "\n".join(f"- {g}" for g in ghs_list) if isinstance(ghs_list, list) else ghs_classes
        else:
            ghs_text = ghs_classes

        # 信号词
        signal = self._val(2, 'signal_word')

        # H码
        h_text = ""
        if isinstance(s2.fields.get('hazard_statements'), FieldValue):
            h_codes = s2.fields['hazard_statements'].value
            if isinstance(h_codes, list):
                lines = []
                for code in h_codes:
                    desc = self.templates.h_code_to_text(code)
                    lines.append(f"- {code} {desc}")
                h_text = "\n".join(lines)

        # P码
        p_text = ""
        if isinstance(s2.fields.get('precautionary_statements'), FieldValue):
            p_data = s2.fields['precautionary_statements'].value
            if isinstance(p_data, dict):
                sections = []
                for group, label in [("prevention", "预防措施"), ("response", "事故响应"),
                                      ("storage", "安全储存"), ("disposal", "废弃处置")]:
                    codes = p_data.get(group, [])
                    if codes:
                        lines = []
                        for code in codes:
                            desc = self.templates.p_code_to_text(code)
                            lines.append(f"  - {code} {desc}")
                        sections.append(f"**{label}**:\n" + "\n".join(lines))
                p_text = "\n\n".join(sections)

        # 象形图
        pict_text = ""
        if isinstance(s2.fields.get('pictograms'), FieldValue):
            picts = s2.fields['pictograms'].value
            if isinstance(picts, list) and picts:
                pict_info = self.templates.ghs_mappings.get("pictogram_info", {})
                pict_text = ", ".join(
                    f"{p} ({pict_info.get(p, {}).get('name_cn', p)})"
                    for p in picts
                )

        return (
            f"# 第二部分：危险性概述\n\n"
            f"**GHS分类**:\n{ghs_text}\n\n"
            f"**信号词**: {signal}\n\n"
            f"**象形图**: {pict_text if pict_text else '无适用象形图 [待确认]'}\n\n"
            f"**危险性说明**:\n{h_text if h_text else '无可用数据 [待确认]'}\n\n"
            f"**防范说明**:\n\n{p_text if p_text else '无可用数据 [待确认]'}"
        )

    def generate_section_3(self) -> str:
        """第三部分：成分/组成信息"""
        s3 = self.document.sections[3]
        chem_type = self._val(3, 'chemical_type')

        if isinstance(s3.fields.get('components'), FieldValue):
            comps = s3.fields['components'].value
            if isinstance(comps, list) and comps:
                header = "| 成分名称 | CAS号 | 浓度(%) | 危险性分类 |"
                sep = "|----------|-------|---------|-----------|"
                rows = []
                for c in comps:
                    name = c.get("name", "")
                    cas = c.get("cas", "")
                    conc = c.get("concentration", "")
                    ghs = c.get("ghs_classifications", "")
                    if isinstance(ghs, list):
                        ghs = ", ".join(ghs)
                    rows.append(f"| {name} | {cas} | {conc} | {ghs} |")
                table = "\n".join([header, sep] + rows)
                return f"# 第三部分：成分/组成信息\n\n**类型**: {chem_type}\n\n{table}"

        return f"# 第三部分：成分/组成信息\n\n**类型**: {chem_type}\n\n{self._val(3, 'components', '无可用数据 [待确认]')}"

    # 急救知识库：按化学品类型提供特异性急救建议
    _FIRST_AID_KB = {
        "corrosive_acid": {
            "inhalation": "立即将患者移至空气新鲜处。如呼吸困难，给予吸氧。如呼吸停止，进行人工呼吸（注意：施救者勿口对口接触腐蚀性气体）。立即就医。",
            "skin": "立即脱去被污染的衣物。用大量流动清水冲洗至少30分钟。不可使用化学中和剂。冲洗时注意不要将化学品扩散到未受影响的皮肤。立即就医。",
            "eye": "立即翻开上下眼睑，用大量流动清水或生理盐水冲洗至少30分钟。如戴隐形眼镜且易取下，先取下再继续冲洗。不可揉眼睛。立即送往眼科就医。",
            "ingestion": "不要催吐（腐蚀性物质催吐可造成食道二次损伤）。不要经口给任何物质。立即就医。如患者意识清醒，可用水漱口。",
            "rescuer": "救援人员必须佩戴防酸碱面罩、穿耐酸碱防护服、戴橡胶手套。避免直接接触污染物。",
            "physician": "如误食，考虑内窥镜检查以评估食道和胃的损伤程度。避免洗胃。注意监测酸碱平衡和电解质。",
        },
        "corrosive_alkali": {
            "inhalation": "立即将患者移至空气新鲜处。保持安静、保暖。如呼吸困难，给予吸氧。如呼吸停止，进行人工呼吸。立即就医。",
            "skin": "立即脱去被污染的衣物。用大量流动清水冲洗至少60分钟。碱腐蚀比酸腐蚀更深，冲洗时间必须更长。不可使用化学中和剂。立即就医。",
            "eye": "这是眼科急症。立即翻开上下眼睑，用大量流动清水或生理盐水持续冲洗至少60分钟。碱灼伤可致永久失明。立即送往眼科就医。",
            "ingestion": "绝对不要催吐。不要经口给任何物质。碱液可造成食道深层坏死。立即就医。",
            "rescuer": "救援人员必须佩戴防碱面罩、穿耐碱防护服、戴橡胶手套。避免吸入碱雾。",
            "physician": "碱灼伤比酸灼伤更具侵蚀性，可能造成深层组织坏死。眼部碱灼伤需持续冲洗并请眼科会诊。如误食，考虑内窥镜检查。",
        },
        "flammable_liquid": {
            "inhalation": "将患者移至空气新鲜处。保持安静、保暖。如呼吸困难，给予吸氧。如呼吸停止，进行人工呼吸（注意：施救者勿吸入蒸气）。如出现中毒症状就医。",
            "skin": "立即脱去被污染的衣物。用大量肥皂水和清水彻底冲洗皮肤。被污染的衣物须彻底清洗后方可重新使用。如刺激持续，就医。",
            "eye": "立即用大量清水冲洗几分钟。如戴隐形眼镜且易取下，取下后继续冲洗。如持续刺激或疼痛，就医。",
            "ingestion": "不要催吐（有吸入性肺炎风险）。如患者意识清醒，用水漱口。给200-300mL水稀释（在意识清醒情况下）。禁止给失去意识者经口任何物质。立即就医。",
            "rescuer": "救援人员应佩戴适当的防护装备。注意远离火源。避免吸入蒸气。",
            "physician": "注意吸入性肺炎风险。如大量吞咽，考虑洗胃（仅在专业人员操作下）。对症支持治疗。",
        },
        "toxic": {
            "inhalation": "立即将患者移至空气新鲜处。保持安静、保暖。如呼吸困难，给予吸氧。如呼吸停止，进行人工呼吸（注意：避免口对口人工呼吸，应使用器械通气）。立即就医。",
            "skin": "立即脱去被污染的衣物。用大量肥皂水和清水冲洗皮肤。被污染的衣物须彻底清洗后方可重新使用。立即就医。",
            "eye": "立即用大量清水冲洗至少15分钟，提起上下眼睑确保彻底冲洗。如戴隐形眼镜且易取下，先取下再继续冲洗。立即就医。",
            "ingestion": "不要催吐。如患者意识清醒，用水漱口。禁止给失去意识者经口任何物质。立即呼叫中毒控制中心或就医。",
            "rescuer": "救援人员必须佩戴适当的呼吸防护和化学防护装备。避免直接接触。确保自身安全后再进行施救。",
            "physician": "本品的毒性作用可能延迟出现。至少观察24-48小时。根据暴露途径和剂量进行对症治疗。",
        },
        "heavy_metal": {
            "inhalation": "立即将患者移至空气新鲜处。保持安静、保暖。如呼吸困难，给予吸氧。立即就医。告知医生可能的金属暴露。",
            "skin": "立即脱去被污染的衣物。用大量清水和肥皂冲洗。立即就医。",
            "eye": "立即用大量清水冲洗至少15分钟。立即就医。",
            "ingestion": "不要催吐。如患者意识清醒，用水漱口。给活性炭（如适用）。立即就医。告知医生具体的金属种类。",
            "rescuer": "救援人员应佩戴防尘面具、化学防护服和手套。避免吸入粉尘和蒸气。",
            "physician": "监测重金属血/尿浓度。考虑使用螯合剂（如DMSA、EDTA等，需根据具体金属选择）。注意肝肾功能损害。",
        },
        "compressed_gas": {
            "inhalation": "立即将患者移至空气新鲜处。保持安静、保暖。如呼吸困难，给予吸氧。如呼吸停止，进行人工呼吸。立即就医。冻伤部位用温水缓慢复温，不要揉搓。",
            "skin": "如发生冻伤，将患部浸入温水（不超过40°C）中。不要揉搓冻伤部位。立即就医。",
            "eye": "如接触液化气体导致冻伤，用大量温水冲洗眼睛。立即就医。",
            "ingestion": "不适用（气体物质）。",
            "rescuer": "救援人员应佩戴自给式呼吸器。注意高压气体喷射危险。防止气体在低洼处聚集。",
            "physician": "注意冻伤和窒息风险。高压气体可能造成气栓。对症支持治疗。",
        },
        "oxidizer": {
            "inhalation": "将患者移至空气新鲜处。如呼吸困难，给予吸氧。如持续不适，就医。",
            "skin": "立即用大量清水冲洗。脱去被污染的衣物。如刺激持续，就医。",
            "eye": "立即用大量清水冲洗几分钟。如持续刺激，就医。",
            "ingestion": "漱口。给水稀释。不要催吐。立即就医。",
            "rescuer": "救援人员应穿着适当的防护装备。注意氧化性物质接触有机物可能引发火灾。",
            "physician": "注意氧化性物质对粘膜的刺激作用。对症治疗。",
        },
        "flammable_solid": {
            "inhalation": "将患者移至空气新鲜处。如呼吸困难，给予吸氧。如呼吸停止，进行人工呼吸。立即就医。注意粉尘吸入。",
            "skin": "用大量水和肥皂冲洗。如有刺激或烧伤，就医。如皮肤粘有熔融物，不要强行撕脱，用冷水冲洗。",
            "eye": "用大量水冲洗几分钟。如持续刺激，就医。注意粉尘对眼睛的刺激。",
            "ingestion": "漱口。给水稀释。不要催吐。如感觉不适，就医。",
            "rescuer": "救援人员应佩戴防护装备，远离火源。避免吸入粉尘。",
            "physician": "对症治疗。注意粉尘吸入对呼吸道的影响。",
        },
        "general": {
            "inhalation": "将患者移至空气新鲜处。如呼吸困难，给予吸氧。如呼吸停止，进行人工呼吸。如持续不适，就医。",
            "skin": "用大量水和肥皂冲洗。如有刺激，就医。",
            "eye": "用大量水冲洗几分钟。如持续刺激，就医。",
            "ingestion": "漱口。给水稀释。如感觉不适，就医。",
            "rescuer": "救援人员应佩戴适当的防护装备。避免直接接触。",
            "physician": "无特效解毒剂。对症治疗。",
        },
    }

    def generate_section_4(self) -> str:
        """第四部分：急救措施（基于化学品类型的特异性建议）"""
        chem_types = self._get_chemical_types()

        # 从最严重的类型选择急救方案（优先级：腐蚀碱 > 腐蚀酸 > 毒性 > 重金属 > 压缩气体 > 氧化 > 易燃 > 通用）
        type_priority = ["corrosive_alkali", "corrosive_acid", "toxic", "heavy_metal",
                         "compressed_gas", "oxidizer", "flammable_liquid", "flammable_solid", "general"]
        primary_type = "general"
        for t in type_priority:
            if t in chem_types:
                primary_type = t
                break

        kb = self._FIRST_AID_KB.get(primary_type, self._FIRST_AID_KB["general"])

        # 混合物模式：聚合所有组分的特异性注释和靶器官建议
        mixture_notes = {"inhalation": [], "skin": [], "eye": [], "ingestion": []}
        if getattr(self, '_is_mixture', False):
            agg = getattr(self, '_mixture_aggregator', None)
            if agg:
                mixture_notes = agg.get_first_aid_notes()

        # 注入KB特异性注释（纯物质模式用单组分KB，混合物模式用聚合结果）
        route_map = {}
        for route in ["inhalation", "skin", "eye", "ingestion"]:
            base = kb.get(route, self._FIRST_AID_KB["general"][route])
            extra_lines = []
            agg_notes = mixture_notes.get(route, [])
            if agg_notes:
                extra_lines.extend(agg_notes)
            if not agg_notes:
                note = self._val(4, f'notes_{route}', "")
                if note and "待确认" not in note:
                    extra_lines.append(note)
            if extra_lines:
                route_map[route] = base + "\n\n" + "\n".join(f"- {n}" for n in extra_lines)
            else:
                route_map[route] = base

        rescuer = kb.get("rescuer", self._FIRST_AID_KB["general"]["rescuer"])
        physician = kb.get("physician", self._FIRST_AID_KB["general"]["physician"])

        # 靶器官摘要（混合物模式）
        if getattr(self, '_is_mixture', False):
            agg = getattr(self, '_mixture_aggregator', None)
            if agg:
                organs = agg.get_target_organs_summary()
                if organs:
                    physician = f"本品含特异性靶器官毒性组分（{organs}）。注意监测相关器官功能。" + \
                               ("无特效解毒剂。对症治疗。" if "解毒" not in physician else "")

        # 急性中毒症状（从KB毒理注释提取）
        symptoms = self._val(11, 'notes_acute_symptoms', '')
        symptoms_line = ""
        if symptoms and "待确认" not in symptoms:
            symptoms_line = f"\n\n**急性中毒症状**: {symptoms}"

        return (
            f"# 第四部分：急救措施\n\n"
            f"**吸入**: {route_map['inhalation']}\n\n"
            f"**皮肤接触**: {route_map['skin']}\n\n"
            f"**眼睛接触**: {route_map['eye']}\n\n"
            f"**食入**: {route_map['ingestion']}\n"
            f"{symptoms_line}\n\n"
            f"**救援人员防护**: {rescuer}\n\n"
            f"**对医生的提示**: {physician}"
        )

    # 消防知识库：按化学品类型提供特异性消防建议
    _FIREFIGHTING_KB = {
        "flammable_liquid": {
            "hazard": "极易燃。其蒸气与空气可形成爆炸性混合物。蒸气比空气重，能沿地面扩散至远处，遇火源可能引起回燃。容器在火中可能破裂或爆炸。",
            "media": "干粉、二氧化碳、泡沫、水雾。",
            "prohibited": "禁止使用直流水（可能扩大火势和化学品扩散范围）。",
            "advice": "消防人员必须佩戴自给式正压呼吸器，穿全身防火防毒服。尽可能将容器从火场移至空旷处。喷水保持火场容器冷却，直至灭火结束。处在火场中的容器若已变色或发出异常声响，必须马上撤离。",
        },
        "flammable_solid": {
            "hazard": "遇明火、高热可燃。粉尘与空气可形成爆炸性混合物。",
            "media": "干粉、干砂、二氧化碳。",
            "prohibited": "禁止用水和泡沫灭火。",
            "advice": "消防人员必须佩戴自给式呼吸器，穿全身防火服。禁止使用直流水。尽可能将容器从火场移至空旷处。",
        },
        "corrosive_acid": {
            "hazard": "不燃。与金属反应可产生易燃的氢气。受热或遇水分解放出腐蚀性气体。容器在火中可能破裂。",
            "media": "干粉、二氧化碳、干砂。",
            "prohibited": "禁止用水直接喷射（可能导致酸液飞溅和扩散）。",
            "advice": "消防人员必须佩戴自给式正压呼吸器，穿耐酸碱消防服。注意酸液飞溅。尽可能将容器从火场移至空旷处。",
        },
        "corrosive_alkali": {
            "hazard": "不燃。遇水放出大量热。与酸类剧烈反应。受热分解产生腐蚀性烟雾。",
            "media": "干粉、二氧化碳、干砂。",
            "prohibited": "禁止用水直接喷射（可能剧烈放热和飞溅）。",
            "advice": "消防人员必须佩戴自给式正压呼吸器，穿耐碱消防防护服。防止碱性溶液接触皮肤和眼睛。",
        },
        "oxidizer": {
            "hazard": "强氧化剂。与可燃物接触可能引起燃烧。受热分解放出氧气，可加剧燃烧。容器在火中可能发生爆炸。",
            "media": "大量水。",
            "prohibited": "禁止使用干粉、泡沫（有机物成分可能与氧化剂反应）。",
            "advice": "消防人员应佩戴自给式正压呼吸器，穿全身化学防护服。不要让氧化剂与可燃物接触。大量用水冷却容器。",
        },
        "compressed_gas": {
            "hazard": "受热容器可能爆炸。泄漏气体可能造成窒息。某些气体可燃。",
            "media": "适用周围火源的灭火剂。用水冷却容器。",
            "prohibited": "禁止将水直接喷向泄漏源。",
            "advice": "消防人员必须佩戴自给式正压呼吸器。如有可能，切断气源。如无法切断，让其燃尽。用水冷却周围容器。如在安全距离内感到容器震动或发出异常声响，立即撤离。",
        },
        "toxic": {
            "hazard": "燃烧产生有毒气体。火灾产生的有毒燃烧产物可能危害消防人员和周围人群。",
            "media": "干粉、二氧化碳、泡沫、水雾。",
            "prohibited": "禁止使用直流水（可能扩大有毒物质扩散范围）。",
            "advice": "消防人员必须佩戴自给式正压呼吸器，穿全身化学防护服。从上风方向灭火。防止灭火废水流入水体。火灾现场应设置警戒线。",
        },
        "heavy_metal": {
            "hazard": "不燃。受热产生有毒金属烟雾。金属粉末可能形成爆炸性粉尘。",
            "media": "干粉、干砂、二氧化碳。金属火灾使用D类灭火器或干燥砂土覆盖。",
            "prohibited": "禁止用水（某些金属遇水反应）、禁止使用泡沫和CO2（对金属火灾无效）。",
            "advice": "消防人员必须佩戴自给式正压呼吸器，穿全身隔热防火服。注意有毒金属烟雾。不要让灭火废水流入水体。收集受污染的灭火用水。",
        },
        "general": {
            "hazard": "参见具体化学品特性。",
            "media": "干粉、二氧化碳、泡沫、砂土。",
            "prohibited": "无特殊禁止要求。",
            "advice": "消防人员必须佩戴防毒面具，穿全身消防服。尽可能将容器从火场移至空旷处。喷水保持火场容器冷却。",
        },
    }

    def generate_section_5(self) -> str:
        """第五部分：消防措施（基于化学品类型的特异性建议，支持多类型综合）"""
        chem_types = self._get_chemical_types()

        # 综合多类型的消防建议（不再只选一种）
        hazard_parts = []
        media_parts = []
        prohibited_parts = []
        advice_parts = []

        # 按危险优先级收集各类型的消防建议
        type_order = ["flammable_liquid", "flammable_solid", "oxidizer", "compressed_gas",
                      "toxic", "corrosive_acid", "corrosive_alkali", "heavy_metal"]
        for t in type_order:
            if t in chem_types and t in self._FIREFIGHTING_KB:
                kb = self._FIREFIGHTING_KB[t]
                if kb["hazard"] not in hazard_parts:
                    hazard_parts.append(kb["hazard"])
                if kb["media"] not in media_parts:
                    media_parts.append(kb["media"])
                if kb["prohibited"] not in prohibited_parts:
                    prohibited_parts.append(kb["prohibited"])
                if kb["advice"] not in advice_parts:
                    advice_parts.append(kb["advice"])

        if not hazard_parts:
            kb = self._FIREFIGHTING_KB["general"]
            hazard_parts = [kb["hazard"]]
            media_parts = [kb["media"]]
            prohibited_parts = [kb["prohibited"]]
            advice_parts = [kb["advice"]]

        # 组合：第一条完整展示，后续类型只展示额外要点
        if len(hazard_parts) > 1:
            hazard = hazard_parts[0]
            for extra in hazard_parts[1:]:
                # 提取关键差异（去掉"不燃"等与第一条矛盾的描述）
                if "不燃" in extra:
                    extra = extra.replace("不燃。", "").replace("不燃", "")
                if extra.strip():
                    hazard += " " + extra.strip()
        else:
            hazard = hazard_parts[0]

        media = "；".join(media_parts) if media_parts else "干粉、二氧化碳、泡沫、砂土。"
        prohibited = prohibited_parts[0] if prohibited_parts else "无特殊禁止要求。"
        # 取最严格的消防建议
        advice = advice_parts[0] if advice_parts else ""

        # 混合物模式：聚合所有组分的消防注释和分解产物危害
        extra_hazard_lines = []
        if getattr(self, '_is_mixture', False):
            agg = getattr(self, '_mixture_aggregator', None)
            if agg:
                ff_notes = agg.get_firefighting_notes()
                extra_hazard_lines.extend(ff_notes)
        else:
            ff_notes = self._val(5, 'notes', '')
            if ff_notes and "待确认" not in ff_notes:
                extra_hazard_lines.append(ff_notes)

        if extra_hazard_lines:
            hazard += "\n" + "\n".join(f"- {n}" for n in extra_hazard_lines)

        # KB数据覆盖
        kb_prohibited = self._val(5, 'prohibited_media', '')
        if kb_prohibited and "待确认" not in kb_prohibited:
            prohibited = kb_prohibited

        # 分解产物
        decomp = self._val(10, 'hazardous_decomposition', '')
        decomp_line = ""
        if decomp and "待确认" not in decomp:
            decomp_line = f"\n\n**燃烧/分解产物**: {decomp}"

        return (
            f"# 第五部分：消防措施\n\n"
            f"**危险特性**: {hazard}\n\n"
            f"**适用灭火剂**: {media}\n\n"
            f"**禁止使用的灭火剂**: {prohibited}\n\n"
            f"**消防建议**: {advice}"
            f"{decomp_line}"
        )

    def generate_section_6(self) -> str:
        """第六部分：泄漏应急处理（含气体/固体/液体差异）"""
        is_flammable = self._has_classification("易燃")
        is_toxic = self._has_classification("急性毒性")
        is_corrosive = self._has_classification("腐蚀")

        # 检测化学品类型
        kb_data = getattr(self, '_kb_data', {})
        bp = kb_data.get("boiling_point", "")
        formula = kb_data.get("molecular_formula", "")
        is_gas = False
        is_solid_metal = False
        try:
            bp_match = re.search(r'-?[\d.]+', str(bp))
            if bp_match:
                bp_num = float(bp_match.group())
                if bp_num < 0:
                    is_gas = True
        except (ValueError, IndexError):
            pass
        # 金属元素或熔点>100的固体
        mp = kb_data.get("melting_point", "")
        if any(el in formula for el in ["Na", "K", "Ca", "Al", "Cu", "Fe", "Zn", "Mg"]):
            if "C" not in formula or formula in ["NaOH", "KOH", "CaO", "Cu", "Al", "Fe", "Zn"]:
                is_solid_metal = True
        try:
            mp_match = re.search(r'-?[\d.]+', str(mp))
            if mp_match:
                mp_num = float(mp_match.group())
                if mp_num > 100 and not is_gas:
                    is_solid_metal = True
        except (ValueError, IndexError):
            pass

        personal = "佩戴防护手套、护目镜。"
        if is_gas:
            personal += "避免吸入气体。确保通风。"
        else:
            personal += "避免吸入蒸气。"
        if is_flammable:
            personal += "消除所有火源。"
        if is_corrosive:
            personal += "穿戴防酸碱防护服。"

        environmental = "防止进入排水沟、下水道、水体和土壤。如泄漏物进入水体，立即通知相关部门。"

        if is_gas:
            cleanup = "撤离泄漏污染区人员至上风处。隔离泄漏区。切断火源。"
        elif is_solid_metal:
            cleanup = "收集泄漏物。回收利用。避免产生粉尘。"
        else:
            cleanup = "用惰性吸收材料（砂土、蛭石等）吸收泄漏物。收集于适当的废弃物容器中。"
        if is_flammable and not is_gas:
            cleanup += "通风。"

        # 混合物模式：追加靶器官特异性泄漏建议
        spill_extra = []
        if getattr(self, '_is_mixture', False):
            agg = getattr(self, '_mixture_aggregator', None)
            if agg:
                spill_extra = agg.get_spill_notes()
        if spill_extra:
            personal += "\n" + "\n".join(f"- {n}" for n in spill_extra)

        return (
            f"# 第六部分：泄漏应急处理\n\n"
            f"**人员防护措施**: {personal}\n\n"
            f"**环境保护措施**: {environmental}\n\n"
            f"**收容与清除方法**: {cleanup}\n\n"
            f"**参考**: 参见第八部分和第十三部分。"
        )

    # 操作储存知识库
    _HANDLING_KB = {
        "flammable_liquid": {
            "handling": "密闭操作，全面通风。操作人员必须经过专门培训，严格遵守操作规程。建议操作人员佩戴过滤式防毒面具（半面罩），戴化学安全防护眼镜，穿防静电工作服，戴橡胶耐油手套。远离火种、热源，工作场所严禁吸烟。使用防爆型的通风系统和设备。防止蒸气泄漏到工作场所空气中。避免与氧化剂、酸类、碱金属接触。灌装时应控制流速，且有接地装置，防止静电积聚。搬运时轻装轻卸，防止包装及容器损坏。配备相应品种和数量的消防器材及泄漏应急处理设备。",
            "storage": "储存于阴凉、通风的专用库房内。远离火种、热源。库温不宜超过37°C，相对湿度不超过80%。保持容器密封。应与氧化剂、还原剂、碱类、食用化学品分开存放，切忌混储。采用防爆型照明、通风设施。禁止使用易产生火花的机械设备和工具。储存区应备有泄漏应急处理设备和合适的收容材料。",
        },
        "corrosive_acid": {
            "handling": "密闭操作，注意通风。操作尽可能机械化、自动化。操作人员必须经过专门培训，严格遵守操作规程。建议操作人员佩戴头罩型电动送风过滤式防尘呼吸器，穿橡胶耐酸碱服，戴橡胶耐酸碱手套。远离易燃、可燃物。避免产生酸雾。防止蒸气释放到工作场所空气中。避免与碱类、胺类、碱金属接触。搬运时要轻装轻卸，防止包装及容器损坏。配备泄漏应急处理设备。倒空的容器可能残留有害物。",
            "storage": "储存于阴凉、通风的库房。库温不超过30°C，相对湿度不超过85%。保持容器密封。应与碱类、胺类、碱金属、易燃物、可燃物分开存放，切忌混储。储区应备有泄漏应急处理设备和合适的收容材料。耐酸地坪。",
        },
        "corrosive_alkali": {
            "handling": "密闭操作。操作人员必须经过专门培训，严格遵守操作规程。建议操作人员佩戴头罩型电动送风过滤式防尘呼吸器，穿橡胶耐酸碱服，戴橡胶耐酸碱手套。避免产生粉尘和气溶胶。避免与酸类接触。搬运时要轻装轻卸，防止包装及容器损坏。配备泄漏应急处理设备。注意防止包装破损。倒空的容器可能残留有害物。",
            "storage": "储存于阴凉、干燥、通风良好的库房。远离火种、热源。包装必须密封，切勿受潮。应与易燃物、可燃物、酸类等分开存放，切忌混储。储区应备有合适的收容材料。",
        },
        "toxic": {
            "handling": "严加密闭，提供充分的局部排风和全面通风。操作人员必须经过专门培训，严格遵守操作规程。建议操作人员佩戴过滤式防毒面具（全面罩），穿胶布防毒衣，戴橡胶手套。远离火种、热源，工作场所严禁吸烟。使用防爆型的通风系统和设备。防止蒸气泄漏到工作场所空气中。避免与氧化剂、酸类、碱类接触。搬运时要轻装轻卸，防止包装及容器损坏。配备泄漏应急处理设备。",
            "storage": "储存于阴凉、通风的库房内。远离火种、热源。保持容器密封。应与氧化剂、酸类、碱类、食用化学品分开存放，切忌混储。采用防爆型照明。禁止使用易产生火花的机械设备和工具。储区应备有泄漏应急处理设备和合适的收容材料。",
        },
        "compressed_gas": {
            "handling": "密闭操作，提供良好的自然通风条件。操作人员必须经过专门培训，严格遵守操作规程。远离火种、热源，工作场所严禁吸烟。搬运时轻装轻卸，防止钢瓶及附件破损。配备泄漏应急处理设备。",
            "storage": "储存于阴凉、通风的库房。远离火种、热源。库温不宜超过30°C。应与易燃物、可燃物分开存放。储区应备有泄漏应急处理设备。气瓶应直立放置，固定牢靠。",
        },
        "oxidizer": {
            "handling": "密闭操作，加强通风。操作人员必须经过专门培训，严格遵守操作规程。远离火种、热源，工作场所严禁吸烟。远离易燃、可燃物。避免产生粉尘。避免与还原剂、酸类、金属粉末接触。搬运时要轻装轻卸，防止包装及容器损坏。注意防止包装破损。",
            "storage": "储存于阴凉、通风的库房。远离火种、热源。库温不超过30°C，相对湿度不超过80%。包装密封。应与易燃物、可燃物、还原剂、酸类、金属粉末等分开存放，切忌混储。储区应备有合适的收容材料。禁止使用易产生火花的机械设备和工具。",
        },
        "general": {
            "handling": "密闭操作，注意通风。操作人员必须经过专门培训，严格遵守操作规程。建议操作人员佩戴防护眼镜和手套。避免吸入蒸气。避免与皮肤和眼睛接触。",
            "storage": "储存于阴凉、通风的库房内。远离火种、热源。保持容器密封。应与氧化剂分开存放，切忌混储。",
        },
    }

    def generate_section_7(self) -> str:
        """第七部分：操作处置与储存（基于化学品类型的特异性建议）"""
        chem_types = self._get_chemical_types()

        type_priority = ["corrosive_alkali", "corrosive_acid", "toxic", "compressed_gas",
                         "oxidizer", "flammable_liquid", "general"]
        primary_type = "general"
        for t in type_priority:
            if t in chem_types:
                primary_type = t
                break

        kb = self._HANDLING_KB.get(primary_type, self._HANDLING_KB["general"])
        handling = kb["handling"]
        storage = kb["storage"]
        incompatibles = self._val(10, 'incompatible_materials', '强氧化剂、强酸、强碱 [待确认]')

        return (
            f"# 第七部分：操作处置与储存\n\n"
            f"**操作注意事项**: {handling}\n\n"
            f"**储存条件**: {storage}\n\n"
            f"**禁配物**: {incompatibles}"
        )

    def generate_section_8(self) -> str:
        """第八部分：接触控制/个体防护"""
        s8 = self.document.sections[8]
        is_corrosive = self._has_classification("腐蚀")
        is_toxic = self._has_classification("急性毒性")
        is_flammable = self._has_classification("易燃")

        # 职业接触限值
        oel_text = ""
        if isinstance(s8.fields.get('oel_table'), FieldValue):
            oel = s8.fields['oel_table'].value
            if isinstance(oel, dict):
                oel_text = "| 标准 | 限值类型 | 数值 |\n|------|---------|------|\n"
                for key, val in oel.items():
                    oel_text += f"| {key} | - | {val} |\n"

        if not oel_text:
            oel_text = "无可用数据 [待确认]"

        engineering = "密闭操作。提供良好的自然通风条件。工作场所应安装紧急洗眼装置和淋浴设备。"
        respiratory = "浓度超标时佩戴防毒面具。" + ("紧急事态下佩戴正压式呼吸器。" if is_toxic else "")
        eye = "化学安全防护眼镜。" + ("必要时戴面罩。" if is_corrosive else "")
        skin = "穿防静电工作服。" if is_flammable else \
               "穿防酸碱工作服。戴橡胶手套。" if is_corrosive else \
               "穿一般工作服。戴防护手套。"
        hygiene = "工作现场禁止吸烟、进食和饮水。工作后淋浴更衣。"

        return (
            f"# 第八部分：接触控制/个体防护\n\n"
            f"**职业接触限值**:\n\n{oel_text}\n\n"
            f"**工程控制**: {engineering}\n\n"
            f"**呼吸防护**: {respiratory}\n\n"
            f"**眼睛防护**: {eye}\n\n"
            f"**皮肤防护**: {skin}\n\n"
            f"**卫生措施**: {hygiene}"
        )

    def generate_section_9(self) -> str:
        """第九部分：理化特性"""
        # 获取原始值并去除已有单位，避免与模板追加的单位重复
        def _s9(field_key, default='无可用数据 [待确认]'):
            raw = self._val(9, field_key, default)
            if '[待确认]' in raw:
                return raw
            return self._strip_unit(raw)

        return (
            f"# 第九部分：理化特性\n\n"
            f"| 特性 | 数值 |\n|------|------|\n"
            f"| 外观 | {self._val(9, 'appearance', '无可用数据 [待确认]')} |\n"
            f"| 气味 | {self._val(9, 'odor', '无可用数据 [待确认]')} |\n"
            f"| 熔点 | {_s9('melting_point')} °C |\n"
            f"| 沸点 | {_s9('boiling_point')} °C |\n"
            f"| 闪点 | {_s9('flash_point')} °C |\n"
            f"| 密度 | {_s9('density')} g/cm³ |\n"
            f"| 蒸气压 | {_s9('vapor_pressure')} kPa |\n"
            f"| 溶解性 | {self._val(9, 'solubility', '无可用数据 [待确认]')} |\n"
            f"| 自燃温度 | {_s9('autoignition_temp')} °C |\n"
            f"| 爆炸极限 | {self._val(9, 'explosion_limits', '无可用数据 [待确认]')} |\n"
            f"| 辛醇/水分配系数 | {self._val(9, 'partition_coefficient', '无可用数据 [待确认]')} |"
        )

    def _infer_decomposition_products(self) -> str:
        """从分子式推断可能的危险分解产物"""
        formula = str(getattr(self, '_kb_data', {}).get("molecular_formula", ""))
        products = []
        if not formula:
            return ""

        elements = set()
        # 简单元素检测（处理常见化学式）
        if "C" in formula and "H" in formula:
            elements.add("碳氢")
        if "N" in formula:
            elements.add("氮")
        if "S" in formula:
            elements.add("硫")
        if "Cl" in formula:
            elements.add("氯")
        if "F" in formula:
            elements.add("氟")
        if "Br" in formula:
            elements.add("溴")
        if "CN" in formula or (formula.count("C") >= 1 and "N" in formula):
            elements.add("氰")
        if "P" in formula and "O" in formula:
            elements.add("磷")
        # 金属
        for metal in ["Pb", "Hg", "Cd", "Cr", "Cu", "Zn", "Ni", "Al", "Fe", "Na", "K", "Ca", "Mg"]:
            if metal in formula:
                elements.add("金属")
                break

        if "碳氢" in elements:
            products.append("一氧化碳")
            products.append("二氧化碳")
        if "氮" in elements:
            products.append("氮氧化物")
        if "硫" in elements:
            products.append("二氧化硫")
        if "氯" in elements:
            products.append("氯化氢")
        if "氟" in elements:
            products.append("氟化氢")
        if "溴" in elements:
            products.append("溴化氢")
        if "氰" in elements and "碳氢" not in elements:
            products.append("氰化氢")
        if "磷" in elements:
            products.append("磷氧化物")
        if "金属" in elements:
            products.append("金属氧化物")

        if products:
            return "、".join(products)
        return ""

    def generate_section_10(self) -> str:
        """第十部分：稳定性和反应性"""
        # 稳定性：检查是否有不稳定分类
        stability = "在正常储存和操作条件下稳定。"
        if self._has_classification("自反应") or self._has_classification("爆炸"):
            stability = "不稳定，受热、摩擦或撞击可能发生分解。"

        # 应避免的条件
        conditions = self._val(10, 'conditions_to_avoid', '明火、高热。 [待确认]')

        # 禁配物
        incompatibles = self._val(10, 'incompatible_materials', '强氧化剂、强酸、强碱 [待确认]')

        # 危险分解产物：优先KB数据，否则从分子式推断
        decomp = self._val(10, 'hazardous_decomposition', '')
        if not decomp or "待确认" in decomp:
            inferred = self._infer_decomposition_products()
            if inferred:
                decomp = f"{inferred}（推断值）"
            else:
                decomp = "无可用数据 [待确认]"

        # 聚合危害
        polymerization = "不会发生危险的聚合反应。"
        if self._has_classification("自反应") or self._has_classification("有机过氧化物"):
            polymerization = "可能发生危险的聚合反应。"

        return (
            f"# 第十部分：稳定性和反应性\n\n"
            f"**稳定性**: {stability}\n\n"
            f"**应避免的条件**: {conditions}\n\n"
            f"**禁配物**: {incompatibles}\n\n"
            f"**危险分解产物**: {decomp}\n\n"
            f"**聚合危害**: {polymerization}"
        )

    # 毒理学症状知识库：基于GHS分类自动推断主要症状
    _TOX_SYMPTOMS_KB = {
        "急性毒性-经口": "误食可引起恶心、呕吐、腹痛。严重时可导致意识障碍、呼吸困难、器官损伤。",
        "急性毒性-经皮": "皮肤接触可引起刺激、红肿。大面积接触可导致系统性中毒。",
        "急性毒性-吸入": "吸入蒸气或雾可引起呼吸道刺激、咳嗽、呼吸困难。高浓度暴露可导致头晕、头痛、恶心，严重时可引起意识丧失。",
        "皮肤腐蚀": "接触可引起皮肤严重灼伤和坏死。疼痛剧烈，愈合缓慢，可能留疤。",
        "皮肤刺激": "接触可引起皮肤红斑、瘙痒、脱脂。反复接触可引起皮肤干燥、皲裂。",
        "严重眼损伤": "接触可引起严重的角膜损伤，可能造成不可逆的视力损害甚至失明。",
        "眼刺激": "接触可引起眼睛发红、疼痛、流泪。蒸气也可引起刺激。",
        "致突变": "根据现有数据，该物质可能引起遗传物质损伤。",
        "致癌": "根据现有数据，该物质怀疑或确认具有致癌性。",
        "生殖毒性": "根据现有数据，该物质可能对生育能力或胎儿造成损害。",
        "STOT-单次-麻醉": "可引起嗜睡、眩晕、反应迟钝。高浓度暴露可导致意识丧失。",
        "STOT-单次-呼吸道": "可引起呼吸道刺激、咳嗽、呼吸困难。可能引起肺水肿（延迟发作）。",
        "STOT-反复-肝": "长期或反复接触可引起肝脏损害。表现为肝功能异常、黄疸等。",
        "STOT-反复-肾": "长期或反复接触可引起肾脏损害。表现为肾功能异常、蛋白尿等。",
        "STOT-反复-血液": "长期或反复接触可引起血液系统损害。表现为贫血、白细胞减少等。",
        "STOT-反复-神经": "长期或反复接触可引起神经系统损害。表现为感觉异常、运动障碍等。",
        "吸入危害": "低粘度液体如误吸进入呼吸道，可引起化学性肺炎，严重时可致命。",
        "致敏": "接触可引起皮肤过敏反应。致敏后，极少量接触也可引发过敏反应。",
    }

    def generate_section_11(self) -> str:
        """第十一部分：毒理学信息"""
        s11 = self.document.sections[11]

        def tox_field(key, label):
            val = self._val(11, key, "无可用数据 [待确认]")
            return f"**{label}**: {val}"

        # 基于GHS分类自动推断症状描述
        symptom_lines = []
        for cls in getattr(self, '_classifications', []):
            hazard = cls.get("hazard", "")
            for key, desc in self._TOX_SYMPTOMS_KB.items():
                # 模糊匹配分类名
                key_parts = key.replace("STOT-", "").replace("单次", "").replace("反复", "").split("-")
                if any(kp in hazard for kp in key_parts if len(kp) > 1):
                    if desc not in symptom_lines:
                        symptom_lines.append(desc)
                    break

        # KB毒理注释
        notes_lines = []
        for note_key, label in [("notes_acute_symptoms", "急性中毒症状"),
                                  ("notes_chronic_effects", "慢性影响"),
                                  ("notes_eye_effects", "眼睛影响"),
                                  ("notes_iarc_group", "致癌性详情")]:
            note_val = self._val(11, note_key, "")
            if note_val and "待确认" not in note_val:
                notes_lines.append(f"**{label}**: {note_val}")

        # 自动推断的吸入危害
        aspiration = self._val(11, 'aspiration_hazard', '')
        if "待确认" in aspiration:
            # 低粘度有机液体自动标注
            kb = getattr(self, '_kb_data', {})
            formula = str(kb.get("molecular_formula", ""))
            bp = str(kb.get("boiling_point", ""))
            if "C" in formula and "H" in formula:
                try:
                    bp_num = float(re.search(r'-?[\d.]+', bp).group())
                    if bp_num > 0 and bp_num < 300:  # 低沸点有机液体
                        aspiration = "低粘度有机液体，误吸可引起化学性肺炎。（推断值）"
                except (ValueError, AttributeError):
                    pass

        symptoms_text = ""
        if symptom_lines:
            symptoms_text = f"**可能的主要症状和影响**:\n" + "\n".join(f"- {s}" for s in symptom_lines) + "\n\n"

        notes_text = ("\n\n".join(notes_lines) + "\n\n") if notes_lines else ""

        return (
            f"# 第十一部分：毒理学信息\n\n"
            f"{tox_field('ld50_oral', 'LD50经口')}\n\n"
            f"{tox_field('ld50_dermal', 'LD50经皮')}\n\n"
            f"{tox_field('lc50_inhalation', 'LC50吸入')}\n\n"
            f"{tox_field('skin_corrosion_category', '皮肤腐蚀/刺激')}\n\n"
            f"{tox_field('eye_damage_category', '严重眼损伤/眼刺激')}\n\n"
            f"{tox_field('mutagenicity', '致突变性')}\n\n"
            f"{tox_field('carcinogenicity_ghs', '致癌性')}\n\n"
            f"{tox_field('reproductive_toxicity_category', '生殖毒性')}\n\n"
            f"{tox_field('stot_single_exposure', '特异性靶器官毒性-单次接触')}\n\n"
            f"{tox_field('stot_repeated_exposure', '特异性靶器官毒性-反复接触')}\n\n"
            f"**吸入危害**: {aspiration if aspiration else self._val(11, 'aspiration_hazard')}\n\n"
            f"{symptoms_text}"
            f"{notes_text}"
        )

    def generate_section_12(self) -> str:
        """第十二部分：生态学信息"""
        s12 = self.document.sections[12]

        # 生态毒性：优先使用聚合字段，否则组合单项
        eco_text = self._val(12, 'ecotoxicity', '')
        if not eco_text or "无可用" in eco_text:
            fish = self._val(12, 'ecotoxicity_fish_lc50')
            daphnia = self._val(12, 'ecotoxicity_daphnia_ec50')
            algae = self._val(12, 'ecotoxicity_algae_ec50')
            parts = []
            if "待确认" not in fish:
                parts.append(f"鱼类LC50: {fish}")
            if "待确认" not in daphnia:
                parts.append(f"水蚤EC50: {daphnia}")
            if "待确认" not in algae:
                parts.append(f"藻类EC50: {algae}")
            eco_text = "；".join(parts) if parts else "无可用数据 [待确认]"

        # 持久性和降解性
        persistence = self._val(12, 'persistence_degradability')

        # 生物富集
        bioaccum_text = self._val(12, 'bioaccumulation_potential', '')
        if not bioaccum_text or "无可用" in bioaccum_text:
            bcf = self._val(12, 'bioaccumulation_bcf')
            log_bc = self._val(12, 'bioaccumulation_log_bc')
            if "待确认" not in bcf or "待确认" not in log_bc:
                bioaccum_text = f"BCF: {bcf}; LogBC: {log_bc}"
            else:
                bioaccum_text = "无可用数据 [待确认]"

        # 土壤迁移性
        soil = self._val(12, 'mobility_in_soil')

        return (
            f"# 第十二部分：生态学信息\n\n"
            f"**生态毒性**: {eco_text}\n\n"
            f"**持久性和降解性**: {persistence}\n\n"
            f"**生物富集潜力**: {bioaccum_text}\n\n"
            f"**土壤中的迁移性**: {soil}"
        )

    # 废弃处置知识库
    _DISPOSAL_KB = {
        "flammable_liquid": {
            "method": "焚烧处理。焚烧炉应配备洗涤器和粉尘捕集装置，确保尾气达标排放。严禁倒入下水道。委托有资质的危险废物处理单位处理。",
            "container": "将废弃容器交由有资质的危险废物处理单位处理。容器倒空后可能仍有残留液体和易燃蒸气，应保持通风，远离火源。不得切割、焊接空容器。",
            "regulation": "《国家危险废物名录》HW06（有机溶剂废物）或HW42（废有机溶剂）。",
            "note": "处置过程中应遵守《危险废物转移联单管理办法》。防止废物与不相容物质混合。",
        },
        "corrosive_acid": {
            "method": "缓慢加入大量水中，用碱中和至pH 6-9后排入废水系统（须取得环保部门许可）。或交由有资质的危险废物处理单位处理。严禁直接排放。",
            "container": "空容器应用水彻底清洗三次以上，清洗液按废液处理。中和后可回收利用或按相关规定处置。不得将废酸倒入金属容器中。",
            "regulation": "《国家危险废物名录》HW34（废酸）。",
            "note": "中和处理应缓慢进行，避免剧烈反应产生大量热量。操作人员应穿戴防护装备。",
        },
        "corrosive_alkali": {
            "method": "缓慢加入大量水中，用酸中和至pH 6-9后排入废水系统（须取得环保部门许可）。或交由有资质的危险废物处理单位处理。严禁直接排放。",
            "container": "空容器应用水彻底清洗三次以上，清洗液按废液处理。中和后可回收利用或按相关规定处置。",
            "regulation": "《国家危险废物名录》HW35（废碱）。",
            "note": "中和处理应缓慢进行，避免剧烈放热。操作人员应穿戴防护装备。",
        },
        "toxic": {
            "method": "用焚烧法或化学法处理。含卤素有机物焚烧需配备高效洗涤器。不得与一般废物混合。委托有资质的危险废物处理单位处理。",
            "container": "废弃容器按危险废物管理，交由有资质单位处理。不得作为普通废金属回收。容器上应保持危险废物标签。",
            "regulation": "按具体成分确定危险废物类别。须执行《危险废物转移联单管理办法》。",
            "note": "处置过程中应防止有毒物质扩散。操作人员必须穿戴适当的防护装备。",
        },
        "heavy_metal": {
            "method": "不得焚烧（会造成重金属大气污染）。应进行稳定化/固化处理后安全填埋。含重金属废液应先沉淀处理，上清液达标后排放，沉淀物按危险废物处置。",
            "container": "容器不可回收利用。按危险废物处置。残留物中含有重金属，不得随意丢弃。",
            "regulation": "《国家危险废物名录》HW48（含铜废物）/HW49（含铅废物）/HW50（含汞废物）等，按实际成分确定。",
            "note": "含重金属废物属于持久性污染物，必须确保最终处置安全。禁止稀释排放。",
        },
        "oxidizer": {
            "method": "根据化学品性质，可选择化学还原处理后按一般废物处置，或交由有资质的危险废物处理单位处理。禁止与还原剂、可燃物混合处置。",
            "container": "彻底清洗后回收利用或按相关规定处置。清洗液需经处理达标后排放。",
            "regulation": "按具体成分确定危险废物类别。",
            "note": "处置时注意氧化性物质与有机物的反应风险。",
        },
        "compressed_gas": {
            "method": "残气应通过安全方式（如通风橱）缓慢排放至大气中，或用适当溶液吸收后处理。钢瓶返回供应商或交由有资质单位处理。",
            "container": "钢瓶返回供应商。不得随意切割或破坏钢瓶。",
            "regulation": "按气体具体成分确定废物类别。",
            "note": "排放前确认气体性质，确保安全。有毒气体不得直接排放至大气中。",
        },
        "flammable_solid": {
            "method": "焚烧处理。或在安全条件下燃烧处理。委托有资质的危险废物处理单位处理。",
            "container": "废弃容器交由有资质单位处理。彻底清洁后方可回收利用。容器内不得有残留物。",
            "regulation": "《国家危险废物名录》按具体成分确定废物类别。",
            "note": "处理过程中应远离火源。防止粉尘飞扬形成爆炸性混合物。",
        },
        "general": {
            "method": "按照国家和地方相关法规要求进行处置。委托有资质的危险废物处理单位处理。",
            "container": "废弃容器应用水彻底清洗后回收或按相关规定处置。",
            "regulation": "按照《中华人民共和国固体废物污染环境防治法》执行。",
            "note": "处置过程中应遵守相关环保法规，防止环境污染。",
        },
    }

    def generate_section_13(self) -> str:
        """第十三部分：废弃处置（基于化学品类型的特异性建议）"""
        chem_types = self._get_chemical_types()

        type_priority = ["heavy_metal", "corrosive_alkali", "corrosive_acid", "toxic",
                         "oxidizer", "compressed_gas", "flammable_liquid", "general"]
        primary_type = "general"
        for t in type_priority:
            if t in chem_types:
                primary_type = t
                break

        kb = self._DISPOSAL_KB.get(primary_type, self._DISPOSAL_KB["general"])

        return (
            f"# 第十三部分：废弃处置\n\n"
            f"**处置方法**: {kb['method']}\n\n"
            f"**容器处理**: {kb['container']}\n\n"
            f"**适用的法规**: {kb['regulation']}\n\n"
            f"**注意事项**: {kb['note']}"
        )

    def generate_section_14(self) -> str:
        """第十四部分：运输信息"""
        s14 = self.document.sections[14]

        # 运输类别：优先KB数据，fallback从GHS分类推导
        transport_class = self._val(14, 'transport_class', '')
        if not transport_class or "待确认" in transport_class:
            transport_class = self._infer_transport_class()
        if not transport_class:
            transport_class = "无可用数据 [待确认]"

        # 运输名称：优先KB，fallback按类别推导
        shipping_name = self._val(14, 'proper_shipping_name', '')
        if not shipping_name or "待确认" in shipping_name:
            tc = transport_class if "待确认" not in transport_class else ""
            if tc == "3":
                shipping_name = "易燃液体"
            elif tc == "8":
                shipping_name = "腐蚀性物质"
            elif tc == "2.1" or tc == "2.2" or tc == "2.3":
                shipping_name = "气体"
            elif tc == "4.1":
                shipping_name = "易燃固体"
            elif tc == "5.1":
                shipping_name = "氧化性物质"
            elif tc == "6.1":
                shipping_name = "毒性物质"
            elif tc == "9":
                shipping_name = "环境危害物质"
            else:
                shipping_name = "无可用数据 [待确认]"

        return (
            f"# 第十四部分：运输信息\n\n"
            f"| 项目 | 内容 |\n|------|------|\n"
            f"| UN编号 | {self._val(14, 'un_number', '无可用数据 [待确认]')} |\n"
            f"| 正式运输名称 | {shipping_name} |\n"
            f"| 运输危险类别 | {transport_class} |\n"
            f"| 包装类别 | {self._val(14, 'packing_group', '无可用数据 [待确认]')} |\n"
            f"| 海洋污染物 | {self._val(14, 'marine_pollutant', '否 [待确认]')} |"
        )

    def _infer_transport_class(self) -> str:
        """从GHS分类推导运输类别"""
        ghs_list = []
        s2 = self.document.sections.get(2)
        if s2 and isinstance(s2.fields.get('ghs_classifications'), FieldValue):
            ghs_list = s2.fields['ghs_classifications'].value
        if not isinstance(ghs_list, list):
            ghs_list = []
        ghs_text = " ".join(str(g) for g in ghs_list)

        # 按优先级匹配（腐蚀>毒性>易燃>气体>氧化>环境）
        # 按主危险优先级匹配（易燃液体优先于腐蚀）
        if "易燃液体" in ghs_text:
            return "3"
        if "易燃固体" in ghs_text or "自热" in ghs_text:
            return "4.1"
        if "加压气体" in ghs_text or ("气体" in ghs_text and "液化" not in ghs_text):
            return "2.2"
        if "氧化性" in ghs_text:
            return "5.1"
        if "急性毒性" in ghs_text:
            return "6.1"
        if "腐蚀" in ghs_text:
            return "8"
        if "水生环境" in ghs_text or "环境" in ghs_text:
            return "9"
        return ""

    def generate_section_15(self) -> str:
        """第十五部分：法规信息"""
        s15_template = self.templates.get_section_template(15)
        defaults = s15_template.get("defaults", {}) if s15_template else {}
        cn_regs = defaults.get("cn_regulations", [])

        return (
            f"# 第十五部分：法规信息\n\n"
            f"**中国法规**:\n" +
            "\n".join(f"- {r}" for r in cn_regs) +
            f"\n\n**国际法规**: 参见相关国际运输法规（ADR/IMDG/IATA-DGR）。"
        )

    def generate_section_16(self) -> str:
        """第十六部分：其他信息"""
        now = datetime.now().strftime("%Y-%m-%d")
        version = self.document.metadata.get("version", "1.0")
        rev_date = self.document.metadata.get("revision_date", "") or now
        rev_log = self.document.metadata.get("revision_log", [])

        sources = ["PubChem数据库", "GHS分类规则", "SDS模板"]
        if hasattr(self, '_kb_data'):
            sources.append("本地知识库")

        disclaimer = (
            "本安全技术说明书中的信息基于我们目前所掌握的知识和经验，"
            "不保证其中所含信息在任何特定情况下的准确性和完整性。"
            "本文件中的信息仅供参考，使用者应根据实际应用场景进行独立判断。"
        )

        # 修订日志
        rev_log_text = ""
        if rev_log:
            rev_log_text = "\n**修订记录**:\n"
            for entry in rev_log:
                rev_log_text += f"| {entry.get('date', '-')} | {entry.get('version', '-')} | {entry.get('description', '-')} |\n"
            if rev_log:
                rev_log_text = "\n| 日期 | 版本 | 修订内容 |\n|------|------|----------|\n" + rev_log_text.split("\n**修订记录**:\n")[1]

        return (
            f"# 第十六部分：其他信息\n\n"
            f"| 项目 | 内容 |\n|------|------|\n"
            f"| SDS编号 | AUTO-{datetime.now().strftime('%Y%m%d%H%M%S')} |\n"
            f"| 版本号 | {version} |\n"
            f"| 编制日期 | {now} |\n"
            f"| 修订日期 | {rev_date} |\n\n"
            f"**数据来源**: {', '.join(sources)}\n\n"
            f"{rev_log_text}"
            f"**免责声明**: {disclaimer}\n\n"
            f"---\n\n"
            f"*本文档由化安通(HuaAnTong)智能MSDS系统自动生成，标记[待确认]的字段需人工审核补充。*"
        )

    # ----------------------------------------------------------
    # 完整文档生成
    # ----------------------------------------------------------

    def generate(self) -> str:
        """生成完整16节SDS文档"""
        generators = {
            1: self.generate_section_1,
            2: self.generate_section_2,
            3: self.generate_section_3,
            4: self.generate_section_4,
            5: self.generate_section_5,
            6: self.generate_section_6,
            7: self.generate_section_7,
            8: self.generate_section_8,
            9: self.generate_section_9,
            10: self.generate_section_10,
            11: self.generate_section_11,
            12: self.generate_section_12,
            13: self.generate_section_13,
            14: self.generate_section_14,
            15: self.generate_section_15,
            16: self.generate_section_16,
        }

        sections = []
        for i in range(1, 17):
            gen = generators.get(i)
            if gen:
                content = gen()
                # LLM增强（仅第4-7节）
                if i in (4, 5, 6, 7):
                    content = self._try_llm_enhance(i, content)
                self.document.sections[i].raw_content = content
                sections.append(content)

        return "\n\n---\n\n".join(sections)

    def get_review_flags(self) -> List[str]:
        """获取需要人工审核的项目"""
        return self.document.review_flags


# ============================================================
# 便捷函数
# ============================================================

def generate_pure_sds(kb_data: dict, product_name: str = "",
                      use_llm: bool = False, version: str = "1.0",
                      revision_date: str = "", revision_log: list = None) -> tuple:
    """
    生成纯净物SDS

    Args:
        kb_data: 知识库中的化学品数据
        product_name: 产品名称
        use_llm: 是否使用LLM增强
        version: 版本号
        revision_date: 修订日期
        revision_log: 修订记录列表

    Returns:
        (markdown_content, review_flags)
    """
    gen = SDSGenerator(use_llm=use_llm)
    gen.set_chemical_data(kb_data)
    gen.set_input_info(product_name=product_name,
                       version=version, revision_date=revision_date,
                       revision_log=revision_log)

    # 从KB数据的GHS分类构建分类结果
    ghs_list = kb_data.get("ghs_classifications", [])
    if isinstance(ghs_list, list) and ghs_list:
        classifications = []
        for ghs_cls in ghs_list:
            h_code = gen.templates.hazard_to_h_code(ghs_cls)
            signal = gen.templates.hazard_to_signal_word(ghs_cls)
            picts = gen.templates.hazard_to_pictograms(ghs_cls)
            classifications.append({
                "hazard": ghs_cls,
                "h_code": h_code,
                "signal": signal,
                "pictograms": picts,
            })
        gen.set_classification(classifications)

    # 成分
    gen.set_components([{
        "name": kb_data.get("chemical_name_cn", product_name),
        "cas": kb_data.get("cas_number", ""),
        "concentration": "≥99.0%",
        "ghs_classifications": ghs_list,
    }])

    content = gen.generate()
    return content, gen.get_review_flags()


def generate_mixture_sds(components_data: List[dict],
                          mixture_classifications: List[dict],
                          product_name: str = "",
                          use_llm: bool = False, version: str = "1.0",
                          revision_date: str = "", revision_log: list = None) -> tuple:
    """
    生成混合物SDS

    Args:
        components_data: 各组分KB数据列表
        mixture_classifications: 混合物分类结果
        product_name: 产品名称
        use_llm: 是否使用LLM增强
        version: 版本号
        revision_date: 修订日期
        revision_log: 修订记录列表

    Returns:
        (markdown_content, review_flags)
    """
    gen = SDSGenerator(use_llm=use_llm)
    gen.set_input_info(product_name=product_name,
                       version=version, revision_date=revision_date,
                       revision_log=revision_log)

    # 混合物危害聚合器：从所有组分聚合靶器官和特异性建议
    gen._is_mixture = True
    gen._components_data = components_data
    gen._mixture_aggregator = SDSGenerator.MixtureHazardAggregator(components_data)

    # 用第一个有数据的组分作为内部参考（毒理、运输等），但不清空到S1/S9
    for comp in components_data:
        if comp:
            gen.set_chemical_data(comp)
            break

    # 关键：设置混合物分类结果 → 填充S2（GHS分类、H码、P码、象形图、信号词）
    if mixture_classifications:
        gen.set_classification(mixture_classifications)

    # S3：设置混合物组分表
    s3 = gen.document.sections[3]
    s3.fields["chemical_type"] = FieldValue(value="混合物", source="template")
    comp_table = []
    for comp in components_data:
        name = comp.get("chemical_name_cn", comp.get("name", ""))
        cas = comp.get("cas_number", comp.get("cas", ""))
        conc = comp.get("concentration", "")
        ghs_raw = comp.get("ghs_classifications", "")
        if isinstance(ghs_raw, list):
            ghs = ", ".join(str(g) for g in ghs_raw)
        else:
            ghs = str(ghs_raw) if ghs_raw else ""
        comp_table.append({
            "name": name, "cas": cas,
            "concentration": conc, "ghs_classifications": ghs,
        })
    s3.fields["components"] = FieldValue(value=comp_table, source="input")

    # 混合物模式：清空S1（化学品标识）— 混合物没有单一CAS/分子式，标记"不适用"
    s1 = gen.document.sections[1]
    for key in ["cas_number", "molecular_formula", "molecular_weight",
                "ec_number", "iupac_name"]:
        s1.fields[key] = FieldValue(value="不适用", source="template")
    s1.fields["un_number"] = FieldValue(value="不适用", source="template")
    if not s1.fields.get("product_name_en"):
        s1.fields["product_name_en"] = FieldValue(value="不适用", source="template")
    if product_name:
        s1.fields["product_name_cn"] = FieldValue(value=product_name, source="input")
    else:
        s1.fields.pop("product_name_cn", None)

    # 混合物模式：S9理化特性从组分数据聚合推导
    s9 = gen.document.sections[9]
    s9.fields.clear()
    # 聚合理化特性
    flash_points = []
    boiling_points = []
    densities = []
    appearances = []
    solubilities = []
    for comp in components_data:
        try:
            fp = str(comp.get("flash_point", ""))
            fp_match = re.search(r'-?[\d.]+', fp)
            if fp_match:
                flash_points.append(float(fp_match.group()))
        except:
            pass
        try:
            bp = str(comp.get("boiling_point", ""))
            bp_match = re.search(r'-?[\d.]+', bp)
            if bp_match:
                boiling_points.append(float(bp_match.group()))
        except:
            pass
        try:
            d = str(comp.get("density", ""))
            d_match = re.search(r'[\d.]+', d)
            if d_match:
                densities.append(float(d_match.group()))
        except:
            pass
        app = str(comp.get("appearance", ""))
        if app and "无可用" not in app:
            appearances.append(app)
        sol = str(comp.get("solubility_details", comp.get("solubility", "")))
        if sol and "无可用" not in sol:
            solubilities.append(sol)

    if flash_points:
        # 混合物闪点取最低值（最危险）
        min_fp = min(flash_points)
        s9.fields["flash_point"] = FieldValue(value=f"{min_fp:.0f}（最低组分值）", source="aggregation")
    if boiling_points:
        bp_min = min(boiling_points)
        bp_max = max(boiling_points)
        if bp_min == bp_max:
            s9.fields["boiling_point"] = FieldValue(value=f"{bp_min:.0f}", source="aggregation")
        else:
            s9.fields["boiling_point"] = FieldValue(value=f"{bp_min:.0f}~{bp_max:.0f}", source="aggregation")
    if densities:
        # 密度取加权平均（按浓度）
        total_conc = sum(float(str(c.get("concentration", "0")).replace("%", "")) for c in components_data)
        if total_conc > 0:
            avg_density = sum(d * float(str(components_data[i].get("concentration", "0")).replace("%", "")) / total_conc
                             for i, d in enumerate(densities))
            s9.fields["density"] = FieldValue(value=f"{avg_density:.2f}（加权平均）", source="aggregation")
    if appearances:
        unique_apps = list(dict.fromkeys(appearances))[:3]  # 去重，最多3个
        s9.fields["appearance"] = FieldValue(value="；".join(unique_apps), source="aggregation")
    else:
        # 推断外观：含有易燃液体组分 → 液体
        s9.fields["appearance"] = FieldValue(value="液体（根据组分推断）", source="inference")
    s9.fields["odor"] = FieldValue(value="有特殊气味（含有机溶剂组分）", source="inference")
    # 熔点聚合
    melting_points = []
    for comp in components_data:
        try:
            mp = str(comp.get("melting_point", ""))
            mp_match = re.search(r'-?[\d.]+', mp)
            if mp_match:
                melting_points.append(float(mp_match.group()))
        except:
            pass
    if melting_points:
        mp_min = min(melting_points)
        mp_max = max(melting_points)
        if mp_min == mp_max:
            s9.fields["melting_point"] = FieldValue(value=f"{mp_min:.0f}", source="aggregation")
        else:
            s9.fields["melting_point"] = FieldValue(value=f"{mp_min:.0f}~{mp_max:.0f}", source="aggregation")
    # 溶解性聚合（从KB的solubility字段）
    sol_values = []
    for comp in components_data:
        sol = str(comp.get("solubility", comp.get("solubility_details", "")))
        if sol and "无可用" not in sol:
            sol_values.append(sol)
    if sol_values:
        unique_sol = list(dict.fromkeys(sol_values))[:4]
        s9.fields["solubility"] = FieldValue(value="；".join(unique_sol), source="aggregation")
    else:
        # 推断：含有机溶剂组分
        s9.fields["solubility"] = FieldValue(value="溶解性因组分而异，参见第三部分各组分数据", source="inference")

    # 蒸气压聚合
    vapor_pressures = []
    for comp in components_data:
        vp = str(comp.get("vapor_pressure", ""))
        vp_match = re.search(r'[\d.]+', vp)
        if vp_match:
            vapor_pressures.append(float(vp_match.group()))
    if vapor_pressures:
        vp_min = min(vapor_pressures)
        vp_max = max(vapor_pressures)
        if vp_min == vp_max:
            s9.fields["vapor_pressure"] = FieldValue(value=f"{vp_min:.1f}", source="aggregation")
        else:
            s9.fields["vapor_pressure"] = FieldValue(value=f"{vp_min:.1f}~{vp_max:.1f}", source="aggregation")
    else:
        # 推断：含低沸点有机溶剂，蒸气压较高
        if boiling_points and min(boiling_points) < 100:
            s9.fields["vapor_pressure"] = FieldValue(value="含低沸点组分，室温下蒸气压较高（推断）", source="inference")

    # 自燃温度聚合
    autoign_temps = []
    for comp in components_data:
        ai = str(comp.get("autoignition_temp", ""))
        ai_match = re.search(r'[\d.]+', ai)
        if ai_match:
            autoign_temps.append(float(ai_match.group()))
    if autoign_temps:
        s9.fields["autoignition_temp"] = FieldValue(value=f"{min(autoign_temps):.0f}（最低组分值）", source="aggregation")

    # 爆炸极限聚合
    expl_limits = []
    for comp in components_data:
        el = str(comp.get("explosion_limits", ""))
        if el and "无可用" not in el:
            expl_limits.append(el)
    if expl_limits:
        s9.fields["explosion_limits"] = FieldValue(value="；".join(list(dict.fromkeys(expl_limits))[:3]), source="aggregation")

    # 辛醇/水分配系数（xlogp聚合）
    xlogp_values = []
    for comp in components_data:
        xlp = str(comp.get("xlogp", comp.get("partition_coefficient_n-octanol_water", "")))
        xlp_match = re.search(r'-?[\d.]+', xlp)
        if xlp_match:
            xlogp_values.append(float(xlp_match.group()))
    if xlogp_values:
        s9.fields["partition_coefficient"] = FieldValue(
            value=f"各组分LogP范围: {min(xlogp_values):.1f}~{max(xlogp_values):.1f}", source="aggregation")

    # 混合物S8接触限值：从组分聚合
    s8 = gen.document.sections[8]
    oel_combined = {}
    for comp in components_data:
        for key in ["pc_twa", "pc_stel", "acgih_tlv_twa", "acgih_tlv_stel"]:
            val = comp.get(key)
            if val and str(val) not in ("", "无可用数据", "不适用"):
                name = comp.get("chemical_name_cn", comp.get("name", ""))
                oel_combined[f"{key}[{name}]"] = val
    if oel_combined:
        s8.fields["oel_table"] = FieldValue(value=oel_combined, source="aggregation")

    # 混合物S11毒理：从分类结果填充缺失字段
    s11 = gen.document.sections[11]
    for cls_item in mixture_classifications:
        hazard = cls_item.get("hazard", "")
        ate_val = cls_item.get("ate")
        if ate_val:
            if "oral" in hazard:
                s11.fields["ld50_oral"] = FieldValue(
                    value=f"ATE = {ate_val:.0f} mg/kg（混合物计算值）",
                    source="classification")
            elif "dermal" in hazard:
                s11.fields["ld50_dermal"] = FieldValue(
                    value=f"ATE = {ate_val:.0f} mg/kg（混合物计算值）",
                    source="classification")
            elif "inhalation" in hazard:
                s11.fields["lc50_inhalation"] = FieldValue(
                    value=f"ATE = {ate_val:.1f} mg/L（混合物计算值）",
                    source="classification")

    # 混合物S11毒理：从组分GHS分类反填（皮肤/眼/致癌/生殖/STOT等）
    # 扫描所有组分的ghs_classifications，聚合各危害类别
    all_comp_ghs = []
    for comp in components_data:
        ghs_raw = comp.get("ghs_classifications", "")
        if isinstance(ghs_raw, list):
            all_comp_ghs.extend(ghs_raw)
        elif ghs_raw:
            all_comp_ghs.append(str(ghs_raw))
    all_ghs_text = " ".join(str(g) for g in all_comp_ghs)

    # 皮肤腐蚀/刺激
    if any(kw in all_ghs_text for kw in ["皮肤腐蚀", "皮肤刺激"]):
        skin_cats = [g for g in all_comp_ghs if "皮肤腐蚀" in str(g) or "皮肤刺激" in str(g)]
        s11.fields["skin_corrosion_category"] = FieldValue(
            value=", ".join(str(c) for c in set(skin_cats)), source="classification")
    # 严重眼损伤/眼刺激
    if any(kw in all_ghs_text for kw in ["眼损伤", "眼刺激"]):
        eye_cats = [g for g in all_comp_ghs if "眼损伤" in str(g) or "眼刺激" in str(g)]
        s11.fields["eye_damage_category"] = FieldValue(
            value=", ".join(str(c) for c in set(eye_cats)), source="classification")
    # 致突变性
    if "致突变" in all_ghs_text:
        s11.fields["mutagenicity"] = FieldValue(value="根据组分分类推断", source="classification")
    # 致癌性 — 混合物分类中已有
    for cls_item in mixture_classifications:
        hazard = cls_item.get("hazard", "")
        if "致癌" in hazard:
            if "carcinogenicity_ghs" not in s11.fields or "待确认" in str(s11.fields.get("carcinogenicity_ghs", "")):
                s11.fields["carcinogenicity_ghs"] = FieldValue(value=hazard, source="classification")
    # 生殖毒性 — 混合物分类中已有
    for cls_item in mixture_classifications:
        hazard = cls_item.get("hazard", "")
        if "生殖" in hazard:
            if "reproductive_toxicity_category" not in s11.fields or "待确认" in str(s11.fields.get("reproductive_toxicity_category", "")):
                s11.fields["reproductive_toxicity_category"] = FieldValue(value=hazard, source="classification")
    # 特异性靶器官毒性
    stot_se = [g for g in all_comp_ghs if "靶器官" in str(g) and "单次" in str(g)]
    if stot_se:
        s11.fields["stot_single_exposure"] = FieldValue(
            value=", ".join(str(c) for c in set(stot_se)), source="classification")
    stot_re = [g for g in all_comp_ghs if "靶器官" in str(g) and "反复" in str(g)]
    if stot_re:
        s11.fields["stot_repeated_exposure"] = FieldValue(
            value=", ".join(str(c) for c in set(stot_re)), source="classification")
    # 吸入危害
    if any(kw in all_ghs_text for kw in ["吸入危害", "吸入危险"]):
        s11.fields["aspiration_hazard"] = FieldValue(value="含低粘度有机液体组分，存在吸入危害", source="classification")
    # 致敏
    if "致敏" in all_ghs_text:
        s11.fields.setdefault("skin_sensitization", FieldValue(value="根据组分分类推断", source="classification"))

    # 混合物S12生态学：从组分聚合生态数据
    s12 = gen.document.sections[12]
    eco_tox = []
    eco_degrad = []
    eco_bcf = []
    eco_soil = []
    for comp in components_data:
        name = comp.get("chemical_name_cn", comp.get("name", ""))
        # 生态毒性
        for fish_key in ["ecotoxicity_fish_lc50", "ecotoxicity_daphnia_ec50", "ecotoxicity_algae_ec50"]:
            val = comp.get(fish_key)
            if val and "无可用" not in str(val):
                eco_tox.append(f"{name}: {val}")
        # 持久性和降解性
        degrad = comp.get("persistence_degradability", "")
        if degrad and "无可用" not in str(degrad):
            eco_degrad.append(f"{name}: {degrad}")
        # 生物富集
        bcf = comp.get("bioaccumulation_bcf", "")
        if bcf and "无可用" not in str(bcf):
            eco_bcf.append(f"{name}: {bcf}")
        # 土壤迁移性
        soil = comp.get("mobility_in_soil", "")
        if soil and "无可用" not in str(soil):
            eco_soil.append(f"{name}: {soil}")
    # 从GHS分类推断水生毒性
    aquatic_hazards = [g for g in all_comp_ghs if "水生" in str(g)]
    if aquatic_hazards and not eco_tox:
        eco_tox.append(f"根据组分分类，含对水生环境有害组分: {', '.join(set(str(h) for h in aquatic_hazards[:5]))}")
    if eco_tox:
        s12.fields["ecotoxicity"] = FieldValue(value="；".join(eco_tox[:6]), source="aggregation")
    if eco_degrad:
        s12.fields["persistence_degradability"] = FieldValue(value="；".join(eco_degrad[:6]), source="aggregation")
    elif any("芳香烃" in str(c.get("chemical_family", "")) for c in components_data):
        s12.fields["persistence_degradability"] = FieldValue(value="含芳香烃组分，可生物降解但需较长时间", source="inference")
    if eco_bcf:
        s12.fields["bioaccumulation_potential"] = FieldValue(value="；".join(eco_bcf[:6]), source="aggregation")
    if eco_soil:
        s12.fields["mobility_in_soil"] = FieldValue(value="；".join(eco_soil[:6]), source="aggregation")

    # 混合物S14运输：推导运输类别、UN编号、包装类别和海洋污染物
    s14 = gen.document.sections[14]
    # 推导运输类别
    ghs_text_for_transport = " ".join(c.get("hazard", "") for c in mixture_classifications)
    if "易燃液体" in ghs_text_for_transport:
        s14.fields["transport_class"] = FieldValue(value="3", source="classification")
        s14.fields["un_number"] = FieldValue(value="UN 1993", source="classification")
        s14.fields["proper_shipping_name"] = FieldValue(value="易燃液体，未另作规定的", source="classification")
    elif "易燃固体" in ghs_text_for_transport:
        s14.fields["transport_class"] = FieldValue(value="4.1", source="classification")
    elif "急性毒性" in ghs_text_for_transport:
        s14.fields["transport_class"] = FieldValue(value="6.1", source="classification")
    elif "腐蚀" in ghs_text_for_transport:
        s14.fields["transport_class"] = FieldValue(value="8", source="classification")
    # 从分类推导包装类别
    has_cat1_or_2 = any("Cat 1" in c.get("hazard", "") or "Cat 2" in c.get("hazard", "") for c in mixture_classifications)
    if "packing_group" not in s14.fields or "待确认" in str(s14.fields.get("packing_group", "")):
        if has_cat1_or_2:
            s14.fields["packing_group"] = FieldValue(value="II", source="classification")
        else:
            s14.fields["packing_group"] = FieldValue(value="III", source="classification")
    # 海洋污染物：检查组分是否含水生毒性
    has_aquatic = any("水生" in c.get("hazard", "") or "水生环境" in str(comp.get("ghs_classifications", ""))
                      for c in mixture_classifications for comp in components_data)
    if has_aquatic:
        s14.fields["marine_pollutant"] = FieldValue(value="是（含对水生环境有害组分）", source="classification")
    else:
        s14.fields["marine_pollutant"] = FieldValue(value="否", source="classification")

    # 混合物S10禁配物和分解产物：从组分聚合
    s10 = gen.document.sections[10]
    all_incompatibles = set()
    all_decomp = set()
    for comp in components_data:
        inc = str(comp.get("incompatible_materials", ""))
        if inc and "无可用" not in inc:
            # 去除 [待确认] 标记后聚合
            clean_inc = inc.replace(" [待确认]", "").replace("[待确认]", "")
            for item in re.split(r'[、,，;；]', clean_inc):
                item = item.strip()
                if item:
                    all_incompatibles.add(item)
        dec = str(comp.get("hazardous_decomposition", ""))
        if dec and "无可用" not in dec:
            clean_dec = dec.replace(" [待确认]", "").replace("[待确认]", "")
            all_decomp.add(clean_dec)
    # 如果组分的禁配物都被过滤了，从组分类型推断
    if not all_incompatibles:
        # 检查是否含有易燃液体组分
        has_flammable = any("易燃" in str(c.get("ghs_classifications", "")) for c in components_data)
        if has_flammable:
            all_incompatibles = {"强氧化剂", "强酸", "强碱", "热源"}
    if all_incompatibles:
        s10.fields["incompatible_materials"] = FieldValue(value="、".join(sorted(all_incompatibles)), source="aggregation")
    # 分解产物：如果组分的分解产物为空，从分子式推断
    if not all_decomp:
        # 有机溶剂混合物默认分解产物
        all_decomp.add("一氧化碳、二氧化碳")
    if all_decomp:
        s10.fields["hazardous_decomposition"] = FieldValue(value="；".join(sorted(all_decomp)) + "（推断值）", source="inference")

    content = gen.generate()
    return content, gen.get_review_flags()


# ============================================================
# CLI入口
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python sds_generator.py --cas <CAS号> [--name <名称>]")
        print("      python sds_generator.py --demo")
        sys.exit(1)

    if "--demo" in sys.argv:
        # 演示：用KB中的乙醇数据
        kb_file = DB_DIR / "chemical_db.json"
        with open(kb_file, "r", encoding="utf-8") as f:
            kb = json.load(f)

        ethanol = kb.get("64-17-5")
        if ethanol:
            content, flags = generate_pure_sds(ethanol, "乙醇")
            print(content)
            if flags:
                print(f"\n\n===== 需人工审核 ({len(flags)}项) =====")
                for f_item in flags:
                    print(f"  - {f_item}")
        else:
            print("未找到乙醇数据，请先运行 kb_manager.py 添加数据")
