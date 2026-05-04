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
        self.safety_kb = self._load_json("safety_knowledge.json")
        self.type_rules = self._load_json("chemical_type_rules.json")

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
        # DEF-002: 去除限定符后重试（如 "特异性靶器官毒性-单次 Cat 1 呼吸道" → "特异性靶器官毒性-单次 Cat 1"）
        import re
        base_match = re.match(r'^(.+?\s+Cat\s+\d+[A-Z]?)\s', normalized)
        if base_match:
            base = base_match.group(1)
            if base in mapping:
                return mapping[base]
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

    # DEF-002: PubChem分类名称 → ghs_mappings.json标准名称 的别名表
    _HAZARD_NAME_ALIASES = {
        "对水生环境有害-急性危害": "危害水生环境-急性",
        "对水生环境有害-长期危害": "危害水生环境-长期",
        "对水生环境有害 -急性危害": "危害水生环境-急性",
        "对水生环境有害 -长期危害": "危害水生环境-长期",
        "吸入危险": "吸入危害",
        "危害水生环境-急性危害": "危害水生环境-急性",
        "危害水生环境-长期危害": "危害水生环境-长期",
    }

    def _normalize_hazard(self, hazard_class: str) -> str:
        """标准化GHS分类名称: '易燃液体，类别2' → '易燃液体 Cat 2'"""
        import re
        s = hazard_class.replace("，", " ").replace(",", " ")
        s = re.sub(r'类别\s*(\d+[A-Z]?)', r'Cat \1', s)
        s = re.sub(r'类别\s*（[^）]*）\s*(\d+[A-Z]?)', r'Cat \1', s)
        # 同义词: "一次接触" → "单次", "加压气体" → "高压气体"
        s = s.replace("一次接触", "单次")
        s = s.replace("单次接触", "单次")
        s = s.replace("反复接触", "反复")
        s = s.replace("加压气体", "高压气体")
        # DEF-002: 应用分类名称别名（在去除括号和连字符之前）
        for alias, standard in self._HAZARD_NAME_ALIASES.items():
            if alias in s:
                s = s.replace(alias, standard)
        # Preserve known classification qualifiers (麻醉效应, 呼吸道刺激, etc.)
        # by converting （qualifier） to plain text before generic bracket removal
        qualifier_match = re.search(r'（([^）]+)）', s)
        qualifier_text = qualifier_match.group(1) if qualifier_match else ""
        s = re.sub(r'（[^）]*）', '', s)
        s = re.sub(r'\(\)', '', s)
        # Normalize spacing around hyphens: "气体 - 压缩" → "气体-压缩"
        s = re.sub(r'\s*-\s*', '-', s)
        # DEF-002: 合并多个连续空格为单个空格
        s = re.sub(r'\s+', ' ', s)
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
        import re
        mapping = self.ghs_mappings.get("hazard_class_to_p_codes", {})
        # 标准化：将中文分类名转为映射key格式
        # "皮肤腐蚀/刺激，类别1A" → "皮肤腐蚀 Cat 1A"
        norm = hazard_class
        norm = re.sub(r'[，、/]', ' ', norm)
        norm = re.sub(r'\s+', ' ', norm).strip()
        norm = re.sub(r'类别\s*(\d+[A-Za-z]*)', r'Cat \1', norm)
        # 去掉"/刺激"等后缀以匹配映射key
        norm = re.sub(r'\s*/\s*刺激', '', norm)

        # 精确匹配
        if norm in mapping:
            return mapping[norm]
        # 匹配去掉子类别后缀: "Cat 1A" → "Cat 1"
        norm_base = re.sub(r'Cat\s*\d+([A-Za-z])', r'Cat \g<0>'.split('Cat ')[-1].rstrip('ABab') if 'Cat ' in norm else norm, norm)
        # 简化: 尝试截断 Cat 后缀
        base_key = re.sub(r'\s*Cat\s+\d+[A-Za-z]*$', '', norm)
        for suffix in [' Cat 1', ' Cat 2', ' Cat 3']:
            test_key = base_key + suffix
            if test_key in mapping:
                return mapping[test_key]
        # 模糊匹配：key中的核心词在hazard中出现
        for key, val in mapping.items():
            # 提取key的核心词（去掉Cat部分）
            key_core = re.sub(r'\s*Cat\s+\d+[A-Za-z]*$', '', key)
            if key_core and key_core in norm and len(key_core) >= 3:
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

    # === 外部化知识库访问 ===
    # 所有KB从 safety_knowledge.json 和 chemical_type_rules.json 读取
    # 保留类常量作为fallback（JSON为空时使用）

    @property
    def _kb(self):
        return self.templates.safety_kb

    @property
    def FIRST_AID_KB(self):
        return self._kb.get("first_aid", self._FIRST_AID_KB_FALLBACK)

    @property
    def FIREFIGHTING_KB(self):
        return self._kb.get("firefighting", self._FIREFIGHTING_KB_FALLBACK)

    @property
    def HANDLING_KB(self):
        return self._kb.get("handling_storage", self._HANDLING_KB_FALLBACK)

    @property
    def DISPOSAL_KB(self):
        return self._kb.get("disposal", self._DISPOSAL_KB_FALLBACK)

    @property
    def TOX_SYMPTOMS_KB(self):
        return self._kb.get("tox_symptoms", self._TOX_SYMPTOMS_KB_FALLBACK)

    @property
    def TYPE_PRIORITY(self):
        return self._kb.get("type_priority", {})

    @property
    def TYPE_RULES(self):
        return self.templates.type_rules

    @property
    def TARGET_ORGAN_FIRST_AID(self):
        return self._kb.get("target_organ_first_aid", {})

    @property
    def TARGET_ORGAN_SPILL(self):
        return self._kb.get("target_organ_spill", {})

    @property
    def DECOMPOSITION_HAZARDS(self):
        return self._kb.get("decomposition_hazards", {})

    # ----------------------------------------------------------
    # 输入数据设置
    # ----------------------------------------------------------

    # 中文key→英文key 的 fallback 映射（DEF-001 修复）
    _CN_KEY_ALIASES = {
        "皮肤腐蚀类别": "skin_corrosion_category",
        "眼损伤类别": "eye_damage_category",
        "IARC致癌分类": "carcinogenicity_iarc",
        "生物降解性": "persistence_degradability",
        "BCF生物富集系数": "bioaccumulation_bcf",
        "Koc土壤迁移系数": "mobility_in_soil",
        "partition_coefficient_log_kow": "partition_coefficient_n-octanol_water",
    }

    def _get_data_value(self, data: dict, key: str, fallback_cn_keys: list = None):
        """从data中取值，支持中文key fallback"""
        val = data.get(key)
        if val:
            return val
        # 尝试中文别名
        cn_alias = self._CN_KEY_ALIASES.get(key)
        if cn_alias:
            val = data.get(cn_alias)
            if val:
                return val
        # 尝试额外的fallback keys
        if fallback_cn_keys:
            for fk in fallback_cn_keys:
                val = data.get(fk)
                if val:
                    return val
        return None

    def set_chemical_data(self, data: dict):
        """设置化学品基础数据（来自KB或PubChem）"""
        self._kb_data = data
        # 传播数据冲突信息到review_flags
        if "_data_conflicts" in data:
            for conflict_msg in data["_data_conflicts"]:
                self.document.review_flags.append(f"数据冲突: {conflict_msg}")
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
            "ph_value": "ph_value",
            "decomposition_temperature": "decomposition_temperature",
            "solubility": "solubility_details",
        }
        for field_key, data_key in phys_mappings.items():
            val = self._get_data_value(data, data_key, [data_key])
            if val:
                s9.fields[field_key] = FieldValue(value=val, source="kb")

        # 溶解性 fallback：Tier 2 使用 "solubility" 而非 "solubility_details"
        if "solubility" not in s9.fields or not s9.fields["solubility"].value:
            sol_val = data.get("solubility_details") or data.get("solubility")
            if sol_val:
                s9.fields["solubility"] = FieldValue(value=sol_val, source="kb")

        # 辛醇/水分配系数 fallback：xlogp → partition_coefficient
        if "partition_coefficient" not in s9.fields or not s9.fields["partition_coefficient"].value or s9.fields["partition_coefficient"].value == '无可用数据 [待确认]':
            xlogp_val = data.get("xlogp") or data.get("partition_coefficient_log_kow")
            if xlogp_val:
                try:
                    xlogp_num = float(str(xlogp_val).strip())
                    s9.fields["partition_coefficient"] = FieldValue(
                        value=f"Log Kow = {xlogp_num:.1f}", source="kb")
                except (ValueError, TypeError):
                    pass

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

        # 其他毒理字段（支持中文key fallback）
        tox_key_aliases = {
            "skin_corrosion_category": ["皮肤腐蚀类别"],
            "eye_damage_category": ["眼损伤类别"],
            "carcinogenicity_iarc": ["IARC致癌分类"],
        }
        for key in ["skin_corrosion_category", "eye_damage_category", "skin_sensitization",
                     "mutagenicity", "carcinogenicity_ghs", "reproductive_toxicity_category",
                     "stot_single_exposure", "stot_repeated_exposure", "carcinogenicity_iarc"]:
            fallback = tox_key_aliases.get(key, [])
            val = self._get_data_value(data, key, fallback)
            if val:
                s11.fields[key] = FieldValue(value=val, source="kb")

        # 第八部分：职业接触限值
        s8 = self.document.sections[8]
        oel_fields = ["pc_twa", "pc_stel", "mac", "acgih_tlv_twa", "acgih_tlv_stel"]
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
        # 检查是否有Cat 1腐蚀（需在每条分类中单独判断，避免跨分类误匹配）
        _has_cat1_corrosion_s10 = any(
            ("皮肤腐蚀" in str(g) and ("类别1" in str(g) or "Cat 1" in str(g))) or "金属腐蚀" in str(g)
            for g in (ghs_list if isinstance(ghs_list, list) else [ghs_list])
        )
        if "易燃" in ghs_text:
            s10.fields["conditions_to_avoid"] = FieldValue(value="明火、高热、静电、火花。", source="kb")
        elif "氧化" in ghs_text:
            s10.fields["conditions_to_avoid"] = FieldValue(value="热源、污染、可燃物、还原剂、金属粉末。", source="kb")
        elif _has_cat1_corrosion_s10:
            # 浓酸/浓碱遇水剧烈放热，应建议避免与水接触
            _acid_hints_s10ca = ["酸", "HCl", "H2SO4", "HNO3", "H3PO4", "HF"]
            _alkali_hints_s10ca = ["碱", "NaOH", "KOH", "Ca(OH)2", "氢氧化", "次氯酸钠", "NaClO"]
            name_str = str(data.get("chemical_name_cn", ""))
            formula_str = str(data.get("molecular_formula", ""))
            _is_acid_s10ca = any(h in name_str or h in formula_str for h in _acid_hints_s10ca)
            _is_alkali_s10ca = any(h in name_str or h in formula_str for h in _alkali_hints_s10ca)
            if _is_acid_s10ca:
                s10.fields["conditions_to_avoid"] = FieldValue(value="高温、明火。避免与水接触（遇水剧烈放热）。", source="kb")
            elif _is_alkali_s10ca:
                s10.fields["conditions_to_avoid"] = FieldValue(value="高温、明火。避免与水接触（遇水放热）。", source="kb")
            else:
                # 腐蚀品但非酸非碱（如有机腐蚀品），不盲目建议避水
                s10.fields["conditions_to_avoid"] = FieldValue(value="高温、明火、不相容物质。", source="kb")
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

        # 第十二部分：生态（支持中文key fallback）
        s12 = self.document.sections[12]
        eco_key_aliases = {
            "persistence_degradability": ["生物降解性"],
            "bioaccumulation_bcf": ["BCF生物富集系数"],
            "mobility_in_soil": ["Koc土壤迁移系数"],
        }
        eco_mappings = {
            "ecotoxicity_fish_lc50": "ecotoxicity_fish_lc50",
            "ecotoxicity_daphnia_ec50": "ecotoxicity_daphnia_ec50",
            "ecotoxicity_algae_ec50": "ecotoxicity_algae_ec50",
            "persistence_degradability": "persistence_degradability",
            "bioaccumulation_bcf": "bioaccumulation_bcf",
            "bioaccumulation_log_bc": "bioaccumulation_log_bc",
        }
        for field_key, data_key in eco_mappings.items():
            fallback = eco_key_aliases.get(data_key, [])
            val = self._get_data_value(data, data_key, fallback)
            if val:
                s12.fields[field_key] = FieldValue(value=val, source="kb")
        mob_val = self._get_data_value(data, "mobility_in_soil", ["Koc土壤迁移系数"])
        if mob_val:
            s12.fields["mobility_in_soil"] = FieldValue(value=mob_val, source="kb")

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
        # 信号词: 优先使用分类结果，fallback到KB数据，最终fallback到"警告"
        sw = "危险" if "危险" in signal_words else ("警告" if "警告" in signal_words else "")
        if not sw:
            kb_sw = self._kb_data.get("signal_word", "")
            if kb_sw:
                sw = kb_sw
        if not sw:
            sw = "警告 [待确认]"
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
                # 低置信度标记（confidence < 0.7 时加 [待确认]）
                if fv.confidence < 0.7 and "[待确认]" not in val_str:
                    val_str += " [待确认]"
                    fv.needs_review = True
                    self.document.review_flags.append(
                        f"第{section_id}部分-{field_key}: 低置信度({fv.confidence:.1f})需核实"
                    )
                # 字段来源渲染（HTML注释，不影响Markdown显示）
                if fv.source and fv.source not in ("template", "input"):
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

    def _has_classification(self, keyword: str, require_cat1: bool = False) -> bool:
        """检查分类中是否包含某关键词。
        require_cat1=True时，对"皮肤腐蚀/刺激"类仅匹配Cat 1（真正的腐蚀），排除Cat 2（仅刺激）"""
        for cls in getattr(self, '_classifications', []):
            hazard = cls.get("hazard", "")
            if require_cat1 and keyword == "腐蚀":
                # 区分真正的皮肤腐蚀(Cat 1)和皮肤刺激(Cat 2)
                if "皮肤腐蚀" in hazard and ("类别1" in hazard or "Cat 1" in hazard):
                    return True
                if "金属腐蚀" in hazard:
                    return True
                continue
            if keyword in hazard:
                return True
        return False

    def _get_flammability_text(self) -> str:
        """根据GHS分类生成S9易燃性字段文本"""
        # 优先检查混合物分类中的易燃性
        for cls in getattr(self, '_classifications', []):
            hazard = cls.get("hazard", "")
            if "易燃" in hazard:
                h_code = cls.get("h_code", "")
                h_stmts = self.templates.ghs_mappings.get("h_statements", {})
                return h_stmts.get(h_code, hazard)

        # NEW-111: 混合物模式 — 即使混合物分类无易燃，检查组分是否有易燃液体分类
        # FIX-S9-flammability: 必须与S2分类一致，遵守水溶液豁免规则
        if getattr(self, '_is_mixture', False):
            components = getattr(self, '_components_data', [])
            total_flammable = 0.0
            total_water = 0.0
            for comp in components:
                ghs_raw = comp.get("ghs_classifications", "")
                if isinstance(ghs_raw, list):
                    ghs_text = " ".join(str(g) for g in ghs_raw)
                else:
                    ghs_text = str(ghs_raw) if ghs_raw else ""
                if "易燃液体" in ghs_text or "易燃" in ghs_text:
                    try:
                        conc_str = str(comp.get("concentration", "0")).replace("%", "")
                        total_flammable += float(conc_str)
                    except (ValueError, TypeError):
                        pass
                if "水" in str(comp.get("chemical_name_cn", "")) or "水" in str(comp.get("name", "")):
                    try:
                        conc_str = str(comp.get("concentration", "0")).replace("%", "")
                        total_water += float(conc_str)
                    except (ValueError, TypeError):
                        pass
            # 水溶液豁免：水>60%且易燃<20%，与check_flammability一致
            if total_water > 60 and total_flammable < 20:
                return "不适用（水溶液中低浓度有机物）"
            if total_flammable >= 10:
                return f"含易燃组分（易燃组分总浓度约{total_flammable:.0f}%）"

        return "不适用"

    def _get_oxidizer_text(self) -> str:
        """FIX-oxidizer: 根据GHS分类生成S9氧化性字段文本"""
        for cls in getattr(self, '_classifications', []):
            hazard = cls.get("hazard", "")
            if "氧化" in hazard:
                return hazard
        # 检查组分是否有氧化性分类
        if getattr(self, '_is_mixture', False):
            for comp in getattr(self, '_components_data', []):
                ghs_raw = comp.get("ghs_classifications", "")
                if isinstance(ghs_raw, list):
                    ghs_text = " ".join(str(g) for g in ghs_raw)
                else:
                    ghs_text = str(ghs_raw) if ghs_raw else ""
                if "氧化" in ghs_text:
                    return "含氧化性组分"
        return "此物质或混合物不被分类为氧化剂。"

    def _get_chemical_types(self) -> List[str]:
        """根据GHS分类+物性推断化学品类型标签列表（从JSON规则驱动）"""
        types = set()
        classifications = getattr(self, '_classifications', [])
        ghs_text = " ".join(c.get("hazard", "") for c in classifications)
        kb = getattr(self, '_kb_data', {})
        formula = str(kb.get("molecular_formula", ""))
        name = str(kb.get("chemical_name_cn", ""))

        # 从 chemical_type_rules.json 读取检测规则
        type_rules = self.TYPE_RULES

        # 预先提取酸/碱的hints用于区分
        acid_formula_hints = []
        acid_name_hints = []
        alkali_formula_hints = []
        alkali_name_hints = []
        for rule in type_rules.get("type_detection", []):
            if rule["tag"] == "corrosive_acid":
                acid_formula_hints = rule.get("formula_hints", [])
                acid_name_hints = rule.get("name_hints", [])
            elif rule["tag"] == "corrosive_alkali":
                alkali_formula_hints = rule.get("formula_hints", [])
                alkali_name_hints = rule.get("name_hints", [])

        is_acid_hint = any(h in formula or h in name for h in acid_formula_hints + acid_name_hints)
        is_alkali_hint = any(h in formula or h in name for h in alkali_formula_hints + alkali_name_hints)
        # 检测是否有氧化性分类（氧化剂不应被默认归类为酸）
        has_oxidizer_class = any("氧化" in c.get("hazard", "") for c in classifications)

        for rule in type_rules.get("type_detection", []):
            tag = rule["tag"]
            ghs_kw = rule.get("ghs_keywords", [])
            # 检查GHS关键词
            if not any(kw in ghs_text for kw in ghs_kw):
                continue
            # 氧化剂优先：有氧化性分类时不使用酸碱默认匹配
            if tag == "corrosive_acid":
                if is_acid_hint and not is_alkali_hint:
                    types.add(tag)
                elif rule.get("default_if_no_base_match") and not is_alkali_hint and not has_oxidizer_class:
                    types.add(tag)
            elif tag == "corrosive_alkali":
                if is_alkali_hint and not is_acid_hint:
                    types.add(tag)
            else:
                types.add(tag)

        # 重金属检测（从规则读取元素列表）
        heavy_metals = type_rules.get("heavy_metals", ["Pb","Hg","Cd","Cr","As","Cu","Zn","Ni","Co"])
        if any(el in formula for el in heavy_metals):
            types.add("heavy_metal")
        # 有机溶剂
        if "C" in formula and "flammable_liquid" in types:
            types.add("organic_solvent")

        return list(types) if types else ["general"]

    def _is_chemical_type(self, type_name: str) -> bool:
        """快速判断是否属于某种化学品类型"""
        return type_name in self._get_chemical_types()

    def _validate_llm_first_aid(self, result: dict, is_corrosive: bool, is_toxic: bool) -> list:
        """校验LLM生成的急救内容，返回警告列表并修正危险建议"""
        warnings = []
        for key in ["inhalation", "skin", "eye", "ingestion"]:
            text = result.get(key, "")
            if not text:
                continue
            # 腐蚀性物质禁止催吐
            if is_corrosive and "催吐" in text:
                text = text.replace("催吐", "**禁止催吐**（腐蚀性物质催吐可造成食道二次损伤）")
                result[key] = text
                warnings.append(f"{key}: 自动修正了腐蚀性物质的催吐建议")
        return warnings

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
            is_corrosive = self._has_classification("腐蚀", require_cat1=True)
            is_toxic = self._has_classification("毒性") or self._has_classification("有毒")

            if section_id == 4:
                result = generate_first_aid_section(chem_data, is_corrosive, is_toxic)
                if result and isinstance(result, dict):
                    # 安全校验
                    warnings = self._validate_llm_first_aid(result, is_corrosive, is_toxic)
                    for w in warnings:
                        self.document.review_flags.append(f"S4-LLM校验: {w}")
                    parts = []
                    for key in ["inhalation", "skin", "eye", "ingestion"]:
                        if result.get(key):
                            parts.append(f"**{key}**: {result[key]}")
                    if parts:
                        disclaimer = "\n\n> **[AI生成-待医疗专业人员审核]** 以上急救措施由AI辅助生成，使用前须经有资质的医务人员确认。"
                        return "# 第四部分：急救措施\n\n" + "\n\n".join(parts) + disclaimer + "\n\n---"
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
        except (RuntimeError, ValueError, OSError):
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
            f"| 推荐用途 | {self._val(1, 'recommended_use', '工业用化学品')} |\n"
            f"| 供应商 | {self._val(1, 'supplier_info', '[待确认]')} |\n"
            f"| 应急电话 | {self._val(1, 'emergency_phone', '[待确认]')} |"
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

        # 紧急概述：基于GHS分类生成简要危害描述
        _h_codes_for_overview = []
        if isinstance(s2.fields.get('hazard_statements'), FieldValue):
            _h_codes_for_overview = s2.fields['hazard_statements'].value or []
        emergency_overview = self._build_emergency_overview(ghs_text, _h_codes_for_overview)

        # 物理/化学危险、健康危害、环境危害子段落
        phys_chem_hazard = ""
        health_hazard_summary = ""
        env_hazard_summary = ""
        other_hazard = ""
        ghs_lower = ghs_text.lower() if ghs_text else ""
        # 物理化学危险
        if "易燃" in ghs_text:
            phys_chem_hazard = "可燃液体。" if "类别 4" in ghs_text or "类别4" in ghs_text else "极易燃液体和蒸气。"
        elif "氧化" in ghs_text:
            phys_chem_hazard = "可加剧燃烧。"
        elif self._has_classification("腐蚀", require_cat1=True):
            phys_chem_hazard = "具腐蚀性。"
        elif "加压" in ghs_text:
            phys_chem_hazard = "含加压气体。"
        elif "爆炸" in ghs_text:
            phys_chem_hazard = "具爆炸危险。"
        if not phys_chem_hazard:
            phys_chem_hazard = "根据现有信息无需进行分类。"
        # 健康危害
        health_keywords = ["急性毒性", "皮肤腐蚀", "皮肤刺激", "眼损伤", "眼刺激",
                          "致癌", "生殖", "靶器官", "致敏", "吸入危害", "麻醉"]
        if any(kw in ghs_text for kw in health_keywords):
            health_parts = []
            if "急性毒性" in ghs_text:
                health_parts.append("具急性毒性")
            if self._has_classification("腐蚀", require_cat1=True):
                health_parts.append("引起皮肤灼伤")
            elif "皮肤刺激" in ghs_text or "皮肤腐蚀/刺激" in ghs_text:
                health_parts.append("可引起皮肤刺激")
            if "眼损伤" in ghs_text:
                health_parts.append("可引起严重眼损伤")
            if "眼刺激" in ghs_text:
                health_parts.append("可引起眼刺激")
            if "致癌" in ghs_text:
                health_parts.append("怀疑或确认致癌")
            if "生殖" in ghs_text:
                health_parts.append("可能损害生育力或胎儿")
            if "靶器官" in ghs_text:
                health_parts.append("可造成特异性靶器官损害")
            if "致敏" in ghs_text:
                health_parts.append("可引起致敏反应")
            if "吸入危害" in ghs_text:
                health_parts.append("具吸入危害")
            health_hazard_summary = "、".join(health_parts) + "。" if health_parts else "根据现有信息无需进行分类。"
        else:
            health_hazard_summary = "根据现有信息无需进行分类。"
        # 环境危害
        if "水生" in ghs_text or "环境" in ghs_text or "臭氧" in ghs_text:
            env_hazard_summary = "对水生环境有害。"
        else:
            env_hazard_summary = "根据现有信息无需进行分类。"
        # 其它危害
        other_hazard = "无数据资料 [待确认]。"

        return (
            f"# 第二部分：危险性概述\n\n"
            f"**紧急概述**: {emergency_overview}\n\n"
            f"**GHS分类**:\n{ghs_text}\n\n"
            f"**信号词**: {signal}\n\n"
            f"**象形图**: {pict_text if pict_text else '无适用象形图 [待确认]'}\n\n"
            f"**危险性说明**:\n{h_text if h_text else '无可用数据 [待确认]'}\n\n"
            f"**防范说明**:\n\n{p_text if p_text else '无可用数据 [待确认]'}\n\n"
            f"**物理和化学危险**: {phys_chem_hazard}\n\n"
            f"**健康危害**: {health_hazard_summary}\n\n"
            f"**环境危害**: {env_hazard_summary}\n\n"
            f"**其它危害**: {other_hazard}"
        )

    def _build_emergency_overview(self, ghs_text: str, h_codes: list = None) -> str:
        """基于GHS分类生成紧急概述段落"""
        parts = []
        # 外观描述（从S9获取外观和气味信息）
        appearance = self._val(9, 'appearance', '')
        odor = self._val(9, 'odor', '')
        appearance_desc = ""
        if appearance and "待确认" not in appearance:
            appearance_desc = appearance
            if "待确认" not in odor:
                appearance_desc += f"，{odor}"
            # 不在此处加句号，由最后的join统一添加

        # 物理状态推断
        state = ""
        if any(k in ghs_text for k in ["易燃液体", "液体"]):
            state = "液体。"
        elif any(k in ghs_text for k in ["易燃固体", "金属腐蚀", "固体"]):
            state = "固体。"
        elif "气体" in ghs_text:
            state = "气体。"

        # 先输出外观描述
        if appearance_desc:
            parts.append(appearance_desc)
        elif state:
            parts.append(state)

        # 物理化学危险
        if "易燃液体" in ghs_text or "易燃固体" in ghs_text:
            if not appearance_desc:
                parts.append(state + "极易燃烧，蒸气与空气可形成爆炸性混合物")
            else:
                parts.append("极易燃烧，蒸气与空气可形成爆炸性混合物")
        elif "易燃" in ghs_text:
            if not appearance_desc:
                parts.append(state + "具易燃性")
            else:
                parts.append("具易燃性")
        if "氧化性" in ghs_text:
            parts.append("可加剧燃烧")
        if "加压气体" in ghs_text:
            parts.append("含加压气体，受热容器可能破裂")
        if "金属腐蚀" in ghs_text:
            parts.append("可腐蚀金属")
        # 健康危害
        health = []
        if "急性毒性" in ghs_text:
            health.append("具急性毒性")
        if self._has_classification("腐蚀", require_cat1=True):
            health.append("引起皮肤灼伤")
        elif "皮肤刺激" in ghs_text or "皮肤腐蚀/刺激" in ghs_text:
            health.append("可引起皮肤刺激")
        if "金属腐蚀" in ghs_text:
            health.append("具腐蚀性")
        if "眼损伤" in ghs_text:
            health.append("有严重损害眼睛的危险")
        elif "眼刺激" in ghs_text:
            health.append("可引起眼刺激")
        if "致癌" in ghs_text:
            health.append("怀疑或确认致癌")
        if "生殖" in ghs_text:
            health.append("可能损害生育力或胎儿")
        if "靶器官" in ghs_text:
            health.append("可造成特异性靶器官损害")
        if health:
            parts.append("健康危害：" + "、".join(health))
        # 环境危害
        if "水生" in ghs_text or "环境" in ghs_text:
            parts.append("对水生环境有害")
        if not parts:
            return "请参阅下述详细分类信息。"
        return "。".join(parts) + "。具体分类详见下文。"

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
    _FIRST_AID_KB_FALLBACK = {
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
        """第四部分：急救措施（聚合所有适用化学品类型的特异性建议）"""
        chem_types = self._get_chemical_types()

        # 优先级：腐蚀碱 > 腐蚀酸 > 毒性 > 重金属 > 压缩气体 > 氧化 > 易燃 > 通用
        type_priority = ["corrosive_alkali", "corrosive_acid", "toxic", "heavy_metal",
                         "compressed_gas", "oxidizer", "flammable_liquid", "flammable_solid", "general"]
        primary_type = "general"
        for t in type_priority:
            if t in chem_types:
                primary_type = t
                break

        kb_primary = self.FIRST_AID_KB.get(primary_type, self.FIRST_AID_KB["general"])

        # 收集所有适用化学品类型的补充建议（而非仅用 primary_type）
        extra_by_route = {"inhalation": [], "skin": [], "eye": [], "ingestion": []}
        for t in type_priority:
            if t == primary_type or t not in chem_types:
                continue
            kb_t = self.FIRST_AID_KB.get(t)
            if not kb_t:
                continue
            for route in ["inhalation", "skin", "eye", "ingestion"]:
                primary_text = kb_primary.get(route, "")
                alt_text = kb_t.get(route, "")
                # 仅当替代类型的建议有主类型缺少的关键内容时才追加
                if alt_text and alt_text != primary_text:
                    # 提取关键差异部分（简化：直接追加标注来源类型）
                    extra_by_route[route].append(alt_text)

        # 混合物模式：聚合所有组分的特异性注释和靶器官建议
        mixture_notes = {"inhalation": [], "skin": [], "eye": [], "ingestion": []}
        if getattr(self, '_is_mixture', False):
            agg = getattr(self, '_mixture_aggregator', None)
            if agg:
                mixture_notes = agg.get_first_aid_notes()

        # 注入KB特异性注释
        route_map = {}
        for route in ["inhalation", "skin", "eye", "ingestion"]:
            base = kb_primary.get(route, self.FIRST_AID_KB["general"][route])
            extra_lines = []
            # 多类型聚合的补充建议
            extra_lines.extend(extra_by_route.get(route, []))
            # 混合物聚合器注释
            agg_notes = mixture_notes.get(route, [])
            if agg_notes:
                extra_lines.extend(agg_notes)
            if not agg_notes and not extra_lines:
                note = self._val(4, f'notes_{route}', "")
                if note and "待确认" not in note:
                    extra_lines.append(note)
            if extra_lines:
                route_map[route] = base + "\n\n" + "\n".join(f"- {n}" for n in extra_lines)
            else:
                route_map[route] = base

        rescuer = kb_primary.get("rescuer", self.FIRST_AID_KB["general"]["rescuer"])
        physician = kb_primary.get("physician", self.FIRST_AID_KB["general"]["physician"])

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
    _FIREFIGHTING_KB_FALLBACK = {
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
            if t in chem_types and t in self.FIREFIGHTING_KB:
                kb = self.FIREFIGHTING_KB[t]
                if kb["hazard"] not in hazard_parts:
                    hazard_parts.append(kb["hazard"])
                if kb["media"] not in media_parts:
                    media_parts.append(kb["media"])
                if kb["prohibited"] not in prohibited_parts:
                    prohibited_parts.append(kb["prohibited"])
                if kb["advice"] not in advice_parts:
                    advice_parts.append(kb["advice"])

        if not hazard_parts:
            kb = self.FIREFIGHTING_KB["general"]
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
        # 去重合并灭火剂（避免"干粉、二氧化碳、泡沫、水雾。；干粉、二氧化碳、干砂。"）
        media_items = re.split(r'[；;]', media)
        all_items = set()
        unique_items = []
        for item in media_items:
            item = item.strip().rstrip('。')
            for sub in item.split('、'):
                sub = sub.strip()
                if sub and sub not in all_items:
                    all_items.add(sub)
                    unique_items.append(sub)
        if unique_items:
            media = '、'.join(unique_items) + '。'
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
        # 补充含卤素有机物的光气警告
        if not decomp_line:
            inferred = self._infer_decomposition_products()
            if inferred:
                decomp_line = f"\n\n**燃烧/分解产物**: {inferred}（推断值）"
        # 检查是否含卤素组分
        s5_comps = getattr(self, '_components_data', [])
        s5_cas_list = [str(c.get("cas_number", c.get("cas", ""))) for c in s5_comps]
        s5_names = [str(c.get("chemical_name_cn", c.get("name", ""))) for c in s5_comps]
        _chlorinated_cas = self.TYPE_RULES.get("chlorinated_cas", ["75-09-2", "67-66-3", "71-55-6", "127-18-4"])
        s5_has_chlorinated = any(cas in s5_cas_list for cas in _chlorinated_cas) or \
                             any("二氯" in n or "三氯" in n or "氯仿" in n for n in s5_names)
        kb5 = getattr(self, '_kb_data', {})
        formula = str(kb5.get("molecular_formula", ""))
        # DEF-003: 只有含C+Cl的有机物才需要光气警告，无机氯化物（如HCl）不需要
        is_chlorinated_organic = ("Cl" in formula and "C" in formula) or s5_has_chlorinated
        if is_chlorinated_organic:
            if "光气" not in decomp_line and "氯化氢" not in decomp_line:
                decomp_line += "。含氯有机物不完全燃烧可产生光气（碳酰氯）和氯化氢等剧毒气体"

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
        is_corrosive = self._has_classification("腐蚀", require_cat1=True)

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
        # 腐蚀品中和处理
        if is_corrosive and not is_gas and not is_solid_metal:
            chem_types_s6 = self._get_chemical_types()
            if "corrosive_acid" in chem_types_s6:
                cleanup += "用石灰石、苏打灰或石灰中和酸液后再行清理。"
            elif "corrosive_alkali" in chem_types_s6:
                cleanup += "用弱酸（如稀醋酸）中和碱液后再行清理。"
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
    _HANDLING_KB_FALLBACK = {
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

        kb = self.HANDLING_KB.get(primary_type, self.HANDLING_KB["general"])
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
        is_corrosive = self._has_classification("腐蚀", require_cat1=True)
        is_toxic = self._has_classification("急性毒性")
        is_flammable = self._has_classification("易燃")

        # 职业接触限值（DEF-108: 中文标签+单位）
        _oel_label_map = {
            "pc_twa": "PC-TWA",
            "pc_stel": "PC-STEL",
            "acgih_tlv_twa": "ACGIH TLV-TWA",
            "acgih_tlv_stel": "ACGIH TLV-STEL",
            "mac": "MAC",
        }
        oel_text = ""
        if isinstance(s8.fields.get('oel_table'), FieldValue):
            oel = s8.fields['oel_table'].value
            if isinstance(oel, dict):
                oel_text = "| 限值类型 | 数值 |\n|---------|------|\n"
                for key, val in oel.items():
                    # 将内部key转为中文标签
                    label = key
                    # NEW-112: 提取混合物组分名（键格式如 "pc_twa[氢氧化钠]"）
                    comp_name = ""
                    bracket_match = re.search(r'\[(.+)\]$', key)
                    if bracket_match:
                        comp_name = bracket_match.group(1)
                    for pattern, cn_label in _oel_label_map.items():
                        if pattern in key:
                            label = f"{cn_label}（{comp_name}）" if comp_name else cn_label
                            break
                    # 格式化数值：如果纯数字则追加 mg/m³
                    val_str = str(val)
                    if re.match(r'^[\d.]+$', val_str.strip()):
                        val_str = f"{val_str.strip()} mg/m³"
                    oel_text += f"| {label} | {val_str} |\n"

        if not oel_text:
            oel_text = "无可用数据 [待确认]"

        engineering = "密闭操作。提供良好的自然通风条件。工作场所应安装紧急洗眼装置和淋浴设备。"
        respiratory = "浓度超标时佩戴防毒面具。" + ("紧急事态下佩戴正压式呼吸器。" if is_toxic else "")
        eye = "化学安全防护眼镜。" + ("必要时戴面罩。" if is_corrosive else "")
        skin = ""
        if is_corrosive and is_flammable:
            skin = "穿防酸碱工作服和防静电内衣。戴耐酸碱橡胶手套。"
        elif is_corrosive:
            skin = "穿防酸碱工作服。戴橡胶手套。"
        elif is_flammable:
            skin = "穿防静电工作服。"
        else:
            skin = "穿一般工作服。戴防护手套。"
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

        # pH值（有值时插入在外观/气味之后）
        ph_row = ""
        ph_val = self._val(9, 'ph_value', '')
        if not ph_val or '[待确认]' in ph_val or ph_val == '无可用数据':
            # FIX-pH: 混合物优先使用组分酸碱性推断，避免单组分类型检测误判
            kb_s9 = getattr(self, '_kb_data', {})
            formula_s9 = str(kb_s9.get("molecular_formula", ""))
            if getattr(self, '_is_mixture', False):
                # 混合物：根据组分的实际酸碱性和浓度判断pH
                # FIX-pH: 只有含强酸/强碱组分且浓度>1%时才推断酸碱性
                _has_acid = False
                _has_alkali = False
                for comp in getattr(self, '_components_data', []):
                    comp_ghs = comp.get("ghs_classifications", [])
                    if isinstance(comp_ghs, str):
                        comp_ghs = [comp_ghs]
                    comp_ghs_text = " ".join(str(g) for g in comp_ghs)
                    comp_formula = str(comp.get("molecular_formula", ""))
                    comp_conc_str = str(comp.get("concentration", "0")).replace("%", "")
                    try:
                        comp_conc = float(comp_conc_str)
                    except (ValueError, TypeError):
                        comp_conc = 0
                    if comp_conc < 1.0:
                        continue  # 浓度<1%的组分对pH影响可忽略
                    # 检测酸：无机酸或有机酸
                    acid_formulas = ["HCl", "H2SO4", "HNO3", "H3PO4", "HF", "HCOOH", "CH3COOH"]
                    alkali_formulas = ["NaOH", "KOH", "Ca(OH)2", "NH3", "NaClO"]
                    acid_names = ["酸"]
                    alkali_names = ["氢氧化", "碱", "次氯酸钠"]
                    if (any(f in comp_formula for f in acid_formulas)
                        or any(n in str(comp.get("chemical_name_cn", "")) for n in acid_names)):
                        _has_acid = True
                    if (any(f in comp_formula for f in alkali_formulas)
                        or any(n in str(comp.get("chemical_name_cn", "")) for n in alkali_names)):
                        _has_alkali = True
                if _has_acid and _has_alkali:
                    ph_val = "取决于配比（需实测） [待确认]"
                elif _has_acid:
                    ph_val = "酸性（需实测） [待确认]"
                elif _has_alkali:
                    ph_val = "碱性（需实测） [待确认]"
                else:
                    ph_val = "不适用（有机溶剂混合物） [待确认]"
            else:
                # 纯物质：根据化学品类型推断pH
                chem_types_s9 = self._get_chemical_types()
                if "corrosive_acid" in chem_types_s9:
                    ph_val = "<1 (强酸性) [待确认]"
                elif "corrosive_alkali" in chem_types_s9:
                    ph_val = ">13 (强碱性) [待确认]"
                else:
                    # 水溶性有机物（乙醇、丙酮等）pH约7；非水溶性有机溶剂pH不适用
                    water_miscible = ["C2H6O", "C3H6O", "CH4O", "CH2O2", "C2H4O2",
                                      "C2H6O2", "C3H8O2", "C3H8O3"]
                    organic_types = {"flammable_liquid", "organic_solvent"}
                    if formula_s9 in water_miscible:
                        ph_val = "约7 (中性)"
                    elif organic_types & set(chem_types_s9):
                        ph_val = "不适用（有机溶剂，非水溶性） [待确认]"
                    else:
                        ph_val = "需实测 [待确认]"
        if ph_val and ph_val != '无可用数据 [待确认]':
            ph_row = f"| pH值 | {ph_val} |\n"

        # 补充缺失行：嗅觉阈值、pH、凝固点、蒸发速率、相对蒸气密度、分解温度、动态粘度、爆炸特性、氧化性、分子量
        # 使用KB数据或默认"无可用数据"
        def _s9_row(label, field_key, unit='', default='无可用数据'):
            val = self._val(9, field_key, '')
            if not val or '待确认' in val:
                val = default
            if unit and val != default:
                val = self._strip_unit(val)
            return f"| {label} | {val} {unit} |\n"

        # 蒸气压：自动检测单位并转kPa
        # KB裸数值常见单位为mmHg(托)，1 mmHg = 0.133322 kPa
        # 少数来源用hPa，1 hPa = 0.1 kPa
        # 策略：裸数值统一按mmHg处理（化学品数据库最常用单位）
        def _normalize_vp(vp_str):
            if not vp_str or '待确认' in vp_str or '不适用' in vp_str or '无可用' in vp_str:
                return vp_str
            vp_str = str(vp_str).strip()
            # 先移除HTML注释（来源标注）
            vp_str = re.sub(r'\s*<!--.*?-->\s*', '', vp_str).strip()
            if 'kPa' in vp_str:
                return vp_str.replace('kPa', '').strip()
            if 'mmHg' in vp_str or 'Torr' in vp_str:
                # mmHg → kPa
                m = re.search(r'([\d.]+)', vp_str)
                if m:
                    return f"{float(m.group(1)) * 0.133322:.1f}"
                return vp_str
            if 'hPa' in vp_str:
                m = re.search(r'([\d.]+)', vp_str)
                if m:
                    return f"{float(m.group(1)) / 10:.1f}"
                return vp_str
            if 'atm' in vp_str:
                m = re.search(r'([\d.]+)', vp_str)
                if m:
                    return f"{float(m.group(1)) * 101.325:.1f}"
                return vp_str
            # 纯数值：按mmHg处理（化学品数据库最常用单位）
            try:
                val = float(vp_str)
                kpa_val = val * 0.133322
                return f"{kpa_val:.1f}"
            except (ValueError, TypeError):
                return vp_str

        vp_display = _normalize_vp(_s9('vapor_pressure'))
        _expl_raw = self._val(9, 'explosion_limits', '')
        _lel, _uel = '无可用数据', '无可用数据'
        if _expl_raw and '待确认' not in _expl_raw and '无可用' not in _expl_raw:
            # 支持 "3.3%~19.0%", "3.3%-19.0%", "2.5 ~ 13.0 (vol%)" 等格式
            _m = re.search(r'([\d.]+)\s*%?\s*[~〜\-—–]\s*%?\s*([\d.]+)', _expl_raw)
            if _m:
                _lel, _uel = _m.group(1) + '%', _m.group(2) + '%'
            else:
                _lel = _expl_raw
        return (
            f"# 第九部分：理化特性\n\n"
            f"| 特性 | 数值 |\n|------|------|\n"
            f"| 外观 | {self._val(9, 'appearance', '无可用数据 [待确认]')} |\n"
            f"| 气味 | {self._val(9, 'odor', '无可用数据 [待确认]')} |\n"
            f"| 嗅觉阈值 | 无可用数据 |\n"
            f"{ph_row}"
            f"| 熔点 | {_s9('melting_point')} °C |\n"
            f"| 凝固点 | 无可用数据 |\n"
            f"| 沸点 | {_s9('boiling_point')} °C |\n"
            f"| 闪点 | {_s9('flash_point')} °C |\n"
            f"| 蒸发速率 | 无可用数据 |\n"
            f"| 易燃性 | {self._get_flammability_text()} |\n"
            f"| 爆炸下限 | {_lel} |\n"
            f"| 爆炸上限 | {_uel} |\n"
            f"| 蒸气压 | {vp_display}{' kPa' if vp_display and '无可用' not in str(vp_display) and '不适用' not in str(vp_display) else ''} |\n"
            f"| 相对蒸气密度 | 无可用数据 |\n"
            f"| 密度 | {_s9('density')} g/cm³ |\n"
            f"| 溶解性 | {self._val(9, 'solubility', '无可用数据 [待确认]')} |\n"
            f"| 辛醇/水分配系数 | {self._val(9, 'partition_coefficient', '无可用数据 [待确认]')} |\n"
            f"| 自燃温度 | {_s9('autoignition_temp')} °C |\n"
            f"| 分解温度 | {_s9('decomposition_temperature', '无可用数据')} |\n"
            f"| 动态粘度 | 无可用数据 |\n"
            f"| 爆炸特性 | {'具爆炸性 [待确认]' if self._has_classification('爆炸') or self._has_classification('自反应') or self._has_classification('有机过氧化物') else '无爆炸性'} |\n"
            f"| 氧化性 | {self._get_oxidizer_text()} |"
        )

    def _infer_decomposition_products(self) -> str:
        """从分子式推断可能的危险分解产物（规则从 chemical_type_rules.json 读取）"""
        formula = str(getattr(self, '_kb_data', {}).get("molecular_formula", ""))
        products = []
        if not formula:
            return ""

        type_rules = self.TYPE_RULES
        decomposition_rules = type_rules.get("decomposition_rules", [])
        decomposition_metals = type_rules.get("decomposition_metals",
            ["Pb", "Hg", "Cd", "Cr", "Cu", "Zn", "Ni", "Al", "Fe", "Na", "K", "Ca", "Mg"])
        has_carbon_hydrogen = "C" in formula and "H" in formula

        matched_elements = set()
        for rule in decomposition_rules:
            elems = rule.get("elements", [])
            exclude = rule.get("exclude_elements", [])
            if all(e in formula for e in elems):
                if exclude and has_carbon_hydrogen and all(e in formula for e in exclude):
                    continue
                matched_elements.update(elems)
                for p in rule.get("products", []):
                    if p not in products:
                        products.append(p)

        # 金属氧化物
        for metal in decomposition_metals:
            if metal in formula:
                if "金属氧化物" not in products:
                    products.append("金属氧化物")
                break

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

        # 危险反应：含卤素有机物的特殊警告
        hazard_reaction = ""
        comps = getattr(self, '_components_data', [])
        all_ghs_s10 = ""
        comp_names = []
        comp_cas = []
        for comp in comps:
            cg = comp.get("ghs_classifications", "")
            if isinstance(cg, list):
                all_ghs_s10 += " " + " ".join(str(g) for g in cg)
            elif cg:
                all_ghs_s10 += " " + str(cg)
            comp_names.append(str(comp.get("chemical_name_cn", comp.get("name", ""))))
            comp_cas.append(str(comp.get("cas_number", comp.get("cas", ""))))

        kb10 = getattr(self, '_kb_data', {})
        formula10 = str(kb10.get("molecular_formula", ""))
        # 检查是否含氯组分（通过CAS号或名称判断）
        _chlorinated_cas_s10 = self.TYPE_RULES.get("chlorinated_cas", ["75-09-2", "67-66-3", "71-55-6", "127-18-4"])
        has_chlorinated = any(cas in comp_cas for cas in _chlorinated_cas_s10) or \
                          any("二氯" in n or "三氯" in n or "氯仿" in n or "氯乙烯" in n for n in comp_names)
        # 纯物质模式：检查分子式是否含有机C和Cl（排除无机物如HCl、NaCl）
        if not has_chlorinated and formula10:
            has_standalone_c = bool(re.search(r'C(?!l|a|o|u|r)', formula10))
            has_chlorinated = "Cl" in formula10 and has_standalone_c
        reaction_notes = []
        # 腐蚀品与酸类/水等剧烈反应
        incompat_lower = incompatibles.lower() if incompatibles else ""
        chem_types_s10 = self._get_chemical_types()
        is_acid = "corrosive_acid" in chem_types_s10
        is_alkali = "corrosive_alkali" in chem_types_s10
        if "酸" in incompat_lower:
            if is_acid:
                reaction_notes.append("与碱类接触可发生剧烈反应。")
            else:
                reaction_notes.append("与酸类接触可发生剧烈反应。")
        if "水" in incompat_lower and ("腐蚀" in all_ghs_s10 or "碱" in str(comp_names)):
            # 检查是否有高浓度碱/酸组分（>20%才算浓溶液，稀溶液遇水不剧烈放热）
            has_concentrated_corrosive = False
            for cd in (getattr(self, '_components_data', []) or []):
                conc_str = str(cd.get("concentration", "0")).replace("%", "")
                try:
                    conc_val = float(conc_str)
                except (ValueError, TypeError):
                    conc_val = 0
                cn = str(cd.get("chemical_name_cn", ""))
                if conc_val > 20 and ("氢氧化" in cn or "酸" in cn or "碱" in cn):
                    has_concentrated_corrosive = True
                    break
            if has_concentrated_corrosive:
                reaction_notes.append("遇水剧烈放热，可能引起飞溅。")
        if has_chlorinated:
            reaction_notes.append("含卤素有机物与活泼金属（铝、镁、锌）反应可产生有毒气体。含氯有机物在紫外线或高温下可分解产生光气（碳酰氯），应避免阳光直射。")
        if "易燃" in all_ghs_s10 and ("氧化" in all_ghs_s10 or "过氧化" in all_ghs_s10):
            reaction_notes.append("与强氧化剂剧烈反应，有火灾和爆炸危险。")
        # FIX-incompat: 检测配方内部组分间不相容性（氧化剂+有机物）
        if getattr(self, '_is_mixture', False) and comps:
            has_oxidizer_comp = False
            has_organic_flammable = False
            oxidizer_names = []
            organic_names = []
            # 已知氧化剂：GHS分类不含"氧化"但实际具强氧化性的物质
            known_oxidizer_formulas = ["NaClO", "Ca(ClO)2", "ClNaO", "KClO3", "NaClO3", "KMnO4"]
            known_oxidizer_names = ["次氯酸钠", "次氯酸钙", "氯酸钠", "高锰酸钾", "双氧水", "过氧化氢"]
            for comp in comps:
                cn = str(comp.get("chemical_name_cn", comp.get("name", "")))
                formula = str(comp.get("molecular_formula", ""))
                cg = comp.get("ghs_classifications", "")
                if isinstance(cg, list):
                    cg_text = " ".join(str(g) for g in cg)
                else:
                    cg_text = str(cg) if cg else ""
                is_oxidizer = ("氧化" in cg_text or "过氧化" in cg_text
                               or formula in known_oxidizer_formulas
                               or any(n in cn for n in known_oxidizer_names))
                if is_oxidizer:
                    has_oxidizer_comp = True
                    oxidizer_names.append(cn)
                if ("易燃" in cg_text or ("C" in formula and "H" in formula)) and not is_oxidizer:
                    has_organic_flammable = True
                    organic_names.append(cn)
            if has_oxidizer_comp and has_organic_flammable:
                reaction_notes.append(
                    f"⚠ 配方内部不相容警告：含氧化性组分（{', '.join(oxidizer_names)}）"
                    f"与可燃有机物（{', '.join(organic_names[:3])}）混合，"
                    f"可能自发放热甚至导致爆炸。应评估配方的化学稳定性。")
        if reaction_notes:
            hazard_reaction = "\n\n**危险反应**: " + " ".join(reaction_notes)

        # 对分解产物补充光气警告
        decomp_warning = ""
        if has_chlorinated:
            if "光气" not in decomp and "氯化氢" not in decomp:
                decomp_warning = "。含氯有机物不完全燃烧可产生光气（碳酰氯）和氯化氢等剧毒气体"

        # 反应性评估
        reactivity = "未被分类为反应性危害。"
        if self._has_classification("自反应") or self._has_classification("有机过氧化物"):
            reactivity = "具有反应性危害。"
        elif has_chlorinated:
            reactivity = "未被分类为反应性危害，但含卤素组分与活泼金属可发生反应。"

        # 危险反应字段：生成通用内容（即使无特殊reaction_notes也输出基本描述）
        if not hazard_reaction:
            # 生成基于禁配物的危险反应描述
            basic_reactions = []
            if "酸" in incompat_lower:
                if is_acid:
                    basic_reactions.append("与碱类接触可发生剧烈反应。")
                else:
                    basic_reactions.append("与酸类接触可发生剧烈反应。")
            if "碱" in incompat_lower:
                if is_alkali:
                    basic_reactions.append("与酸类接触可发生剧烈反应。")
                else:
                    basic_reactions.append("与碱类接触可发生反应。")
            if "氧化" in incompat_lower:
                basic_reactions.append("与强氧化剂接触可发生剧烈反应，有火灾和爆炸危险。")
            if "水" in incompat_lower:
                basic_reactions.append("遇水剧烈反应。")
            if basic_reactions:
                hazard_reaction = "\n\n**危险反应**: " + " ".join(basic_reactions)
            elif incompatibles and "待确认" not in incompatibles:
                hazard_reaction = f"\n\n**危险反应**: 与禁配物接触可发生反应。"

        return (
            f"# 第十部分：稳定性和反应性\n\n"
            f"**反应性**: {reactivity}\n\n"
            f"**稳定性**: {stability}\n\n"
            f"**危险反应的可能性**: 与禁配物接触可能发生危险反应。{hazard_reaction.replace(chr(10) + chr(10) + '**危险反应**: ', '') if hazard_reaction else ''}\n\n"
            f"**应避免的条件**: {conditions}\n\n"
            f"**禁配物**: {incompatibles}\n\n"
            f"**危险分解产物**: {decomp}{decomp_warning}\n\n"
            f"**聚合危害**: {polymerization}"
        )

    # 毒理学症状知识库：基于GHS分类自动推断主要症状
    _TOX_SYMPTOMS_KB_FALLBACK = {
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

        # NEW-118: 皮肤腐蚀/刺激字段与S2 GHS分类一致性校验
        # 当S2分类中无皮肤腐蚀/刺激时，不应在S11显示KB的皮肤数据
        s2_ghs_classes = self.document.sections[2].fields.get("ghs_classifications")
        s2_has_skin = False
        if s2_ghs_classes:
            ghs_list = s2_ghs_classes.value if s2_ghs_classes else []
            s2_has_skin = any(
                "皮肤腐蚀" in str(c) or "皮肤刺激" in str(c)
                for c in ghs_list
            )
        if not s2_has_skin and "skin_corrosion_category" in s11.fields:
            # 检查来源：如果是classification则保留（由分类系统设置），否则删除
            src = s11.fields["skin_corrosion_category"].source
            if src != "classification":
                del s11.fields["skin_corrosion_category"]

        # NEW-118: 严重眼损伤/眼刺激同理
        s2_has_eye = False
        if s2_ghs_classes:
            ghs_list = s2_ghs_classes.value if s2_ghs_classes else []
            s2_has_eye = any(
                "眼损伤" in str(c) or "眼刺激" in str(c)
                for c in ghs_list
            )
        if not s2_has_eye and "eye_damage_category" in s11.fields:
            src = s11.fields["eye_damage_category"].source
            if src != "classification":
                del s11.fields["eye_damage_category"]

        def tox_field(key, label):
            val = self._val(11, key, "")
            # 字段不存在于S11（被NEW-118一致性检查删除）且S2无此分类 → "无需进行分类"
            is_no_class = not val or val.strip() == "[待确认]" or val.strip() == "" or "待确认" in val
            if is_no_class and key in ("skin_corrosion_category", "eye_damage_category"):
                val = "根据现有信息无需进行分类。"
            elif is_no_class:
                val = "无可用数据 [待确认]"
            # DEF-109: 自动追加单位（裸数值时补充mg/kg或mg/L）
            if "无可用数据" not in val and "待确认" not in val and "无需进行分类" not in val:
                # 移除来源注释后检查
                clean = re.sub(r'\s*<!--.*?-->\s*', '', str(val)).strip()
                has_unit = any(u in clean for u in ["mg/kg", "mg/L", "ppm", "g/kg"])
                if not has_unit and clean and clean != "不适用":
                    if "ld50" in key.lower() or "oral" in key or "dermal" in key:
                        val = val.rstrip() + " mg/kg"
                    elif "lc50" in key.lower() or "inhalation" in key:
                        val = val.rstrip() + " mg/L"
            return f"**{label}**: {val}"

        # 检测是否为混合物模式
        is_mixture = bool(getattr(self, '_components_data', []))

        # 基于GHS分类自动推断症状描述
        symptom_lines = []
        for cls in getattr(self, '_classifications', []):
            hazard = cls.get("hazard", "")
            h_code = cls.get("h_code", "")
            # 区分眼损伤Cat1和眼刺激Cat2A：避免Cat2A使用Cat1的严重描述
            if "眼损伤" in hazard or "眼刺激" in hazard:
                cat_val = cls.get("category", "")
                cat_str = str(cat_val) + hazard
                if "Cat 1" in cat_str or "类别1" in cat_str or "类别 1" in cat_str:
                    desc = self.TOX_SYMPTOMS_KB.get("严重眼损伤", "")
                else:
                    # Cat2A/2B → 眼刺激描述
                    desc = self.TOX_SYMPTOMS_KB.get("眼刺激", "")
                if desc and desc not in symptom_lines:
                    symptom_lines.append(desc)
                continue
            for key, desc in self.TOX_SYMPTOMS_KB.items():
                if key in ("严重眼损伤", "眼刺激"):
                    continue  # 已在上面单独处理
                # 皮肤腐蚀：区分Cat 1（真正腐蚀）和Cat 2（仅刺激）
                if key == "皮肤腐蚀":
                    if "皮肤腐蚀" in hazard and ("类别1" in hazard or "Cat 1" in hazard):
                        if desc not in symptom_lines:
                            symptom_lines.append(desc)
                    elif "皮肤腐蚀/刺激" in hazard and ("类别2" in hazard or "Cat 2" in hazard):
                        # Cat 2 用刺激描述
                        irritant_desc = self.TOX_SYMPTOMS_KB.get("皮肤刺激", desc)
                        if irritant_desc not in symptom_lines:
                            symptom_lines.append(irritant_desc)
                    continue
                # 精确匹配分类名（完整关键词匹配，而非拆分片段）
                _key_normalized = key.replace("STOT-", "靶器官毒性-").replace("单次", "").replace("反复", "")
                if _key_normalized in hazard or key in hazard:
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

        # 自动推断的吸入危害（DEF-003: 增加化学品类型检查，无机物不使用有机液体模板）
        aspiration = self._val(11, 'aspiration_hazard', '')
        if "待确认" in aspiration:
            kb = getattr(self, '_kb_data', {})
            formula = str(kb.get("molecular_formula", ""))
            bp = str(kb.get("boiling_point", ""))
            name_cn = str(kb.get("chemical_name_cn", ""))
            # 判断是否为有机物：需含C且含H，且不是无机酸/碱/盐
            is_organic = ("C" in formula and "H" in formula)
            inorganic_hints = ["酸", "碱", "盐", "氧化钙", "次氯酸", "氯酸钠"]
            is_inorganic = any(h in name_cn for h in inorganic_hints)
            if is_organic and not is_inorganic:
                try:
                    bp_num = float(re.search(r'-?[\d.]+', bp).group())
                    if bp_num > 0 and bp_num < 300:  # 低沸点有机液体
                        aspiration = "低粘度有机液体，误吸可引起化学性肺炎。（推断值）"
                except (ValueError, AttributeError):
                    pass
            elif is_inorganic:
                aspiration = ""  # 无机物不标注吸入危害（待人工确认）

        symptoms_text = ""
        if symptom_lines:
            symptoms_text = f"**可能的主要症状和影响**:\n" + "\n".join(f"- {s}" for s in symptom_lines) + "\n\n"

        notes_text = ("\n\n".join(notes_lines) + "\n\n") if notes_lines else ""

        # 核心毒理学字段（纯物质和混合物共用）
        core_tox = (
            f"{tox_field('ld50_oral', 'LD50经口')}\n\n"
            f"{tox_field('ld50_dermal', 'LD50经皮')}\n\n"
            f"{tox_field('lc50_inhalation', 'LC50吸入')}\n\n"
            f"{tox_field('skin_corrosion_category', '皮肤腐蚀/刺激')}\n\n"
            f"{tox_field('eye_damage_category', '严重眼损伤/眼刺激')}\n\n"
            f"**皮肤致敏**: {self._val(11, 'skin_sensitization', '无可用数据 [待确认]')}\n\n"
            f"**呼吸致敏**: {self._val(11, 'respiratory_sensitization', '无可用数据 [待确认]')}\n\n"
            f"{tox_field('mutagenicity', '致突变性')}\n\n"
            f"{tox_field('carcinogenicity_ghs', '致癌性')}\n\n"
            f"**致畸性**: {self._val(11, 'developmental_toxicity', '无可用数据 [待确认]')}\n\n"
            f"{tox_field('reproductive_toxicity_category', '生殖毒性')}\n\n"
            f"{tox_field('stot_single_exposure', '特异性靶器官毒性-单次接触')}\n\n"
            f"{tox_field('stot_repeated_exposure', '特异性靶器官毒性-反复接触')}\n\n"
            f"**吸入危害**: {aspiration if aspiration else self._val(11, 'aspiration_hazard')}\n\n"
        )

        # 混合物模式：添加各组分组分详细信息
        component_tox = ""
        if is_mixture:
            comps = getattr(self, '_components_data', [])
            comp_tox_parts = []
            for comp in comps:
                comp_name = comp.get("chemical_name_cn", comp.get("name", ""))
                comp_cas = comp.get("cas_number", comp.get("cas", ""))
                comp_data = comp.get("_kb_data", {})

                comp_lines = []
                # 急性毒性
                ld50 = comp_data.get("ld50_oral", "")
                if ld50 and "无" not in ld50:
                    comp_lines.append(f"  - LD50经口: {ld50}")
                ld50_d = comp_data.get("ld50_dermal", "")
                if ld50_d and "无" not in ld50_d:
                    comp_lines.append(f"  - LD50经皮: {ld50_d}")
                lc50 = comp_data.get("lc50_inhalation", "")
                if lc50 and "无" not in lc50:
                    comp_lines.append(f"  - LC50吸入: {lc50}")
                # 皮肤/眼
                skin = comp_data.get("skin_corrosion_category", "")
                if skin and "无" not in skin:
                    comp_lines.append(f"  - 皮肤腐蚀/刺激: {skin}")
                eye = comp_data.get("eye_damage_category", "")
                if eye and "无" not in eye:
                    comp_lines.append(f"  - 严重眼损伤/眼刺激: {eye}")

                if comp_lines:
                    comp_tox_parts.append(f"**{comp_name}** ({comp_cas}):\n" + "\n".join(comp_lines))

            if comp_tox_parts:
                component_tox = "\n**各组分毒理学详细信息**:\n\n" + "\n\n".join(comp_tox_parts) + "\n\n"

        return (
            f"# 第十一部分：毒理学信息\n\n"
            f"{core_tox}"
            f"{symptoms_text}"
            f"{component_tox}"
            f"{notes_text}"
        )

    def generate_section_12(self) -> str:
        """第十二部分：生态学信息"""
        s12 = self.document.sections[12]

        # 生态毒性：优先使用聚合字段，否则组合单项
        eco_text = self._val(12, 'ecotoxicity', '')
        if not eco_text or "无可用" in eco_text or "待确认" in eco_text:
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

        # 生物富集（DEF-008: 修复条件逻辑，任一字段有效即显示）
        bioaccum_text = self._val(12, 'bioaccumulation_potential', '')
        if not bioaccum_text or "无可用" in bioaccum_text or "待确认" in bioaccum_text:
            bcf = self._val(12, 'bioaccumulation_bcf')
            log_bc = self._val(12, 'bioaccumulation_log_bc')
            bcf_valid = bcf and "待确认" not in bcf and "无可用" not in bcf and "不适用" not in bcf
            log_bc_valid = log_bc and "待确认" not in log_bc and "无可用" not in log_bc
            if bcf_valid or log_bc_valid:
                parts = []
                if bcf_valid:
                    parts.append(f"BCF: {bcf}")
                if log_bc_valid:
                    parts.append(f"LogBC: {log_bc}")
                bioaccum_text = "；".join(parts)
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
    _DISPOSAL_KB_FALLBACK = {
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
            "method": "用焚烧法或化学法处理。含卤素有机物焚烧温度不低于1200°C，停留时间不小于2秒，确保完全分解防止产生二噁英。焚烧需配备高效洗涤器和除尘装置。不得与一般废物混合。委托有资质的危险废物处理单位处理。",
            "container": "废弃容器按危险废物管理，交由有资质单位处理。不得作为普通废金属回收。容器上应保持危险废物标签。空容器可能残留有害蒸气，不得切割、焊接。",
            "regulation": "按具体成分确定危险废物类别（HW06有机溶剂废物、HW42废有机溶剂，含卤素废物属HW39）。须执行《危险废物转移联单管理办法》。",
            "note": "处置过程中应防止有毒物质扩散。操作人员必须穿戴适当的防护装备。严禁直接排入下水道。",
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

        kb = self.DISPOSAL_KB.get(primary_type, self.DISPOSAL_KB["general"])

        # NEW-113: 混合物模式 — 基于组分GHS分类生成组分特异性废物类别
        extra_waste_notes = ""
        if getattr(self, '_is_mixture', False):
            components = getattr(self, '_components_data', [])
            waste_codes = []
            has_aquatic_toxicity = False
            for comp in components:
                ghs_raw = comp.get("ghs_classifications", "")
                if isinstance(ghs_raw, list):
                    ghs_text = " ".join(str(g) for g in ghs_raw)
                else:
                    ghs_text = str(ghs_raw) if ghs_raw else ""
                # 碱类 → HW35（仅Cat 1腐蚀或金属腐蚀）
                cn_name = str(comp.get("chemical_name_cn", ""))
                _comp_has_cat1_corrosion = any("皮肤腐蚀" in str(g) and ("类别1" in str(g) or "Cat 1" in str(g)) for g in (ghs_raw if isinstance(ghs_raw, list) else [ghs_raw]))
                if _comp_has_cat1_corrosion or "金属腐蚀" in ghs_text:
                    if any(h in cn_name for h in ["氢氧化", "氢氧化钠", "氢氧化钾", "氢氧化钙"]):
                        if "HW35（废碱）" not in waste_codes:
                            waste_codes.append("HW35（废碱）")
                # 酸类 → HW34（仅Cat 1腐蚀或金属腐蚀）
                formula = str(comp.get("molecular_formula", ""))
                if (_comp_has_cat1_corrosion or "金属腐蚀" in ghs_text) and \
                   any(h in formula for h in ["HCl", "H2SO4", "HNO3", "HF"]):
                    if "HW34（废酸）" not in waste_codes:
                        waste_codes.append("HW34（废酸）")
                # 有机溶剂 → HW06
                if ("C" in formula and "H" in formula) and \
                   any(kw in ghs_text for kw in ["易燃液体", "易燃"]):
                    if "HW06（有机溶剂废物）" not in waste_codes:
                        waste_codes.append("HW06（有机溶剂废物）")
                # 水生毒性
                if "水生" in ghs_text:
                    has_aquatic_toxicity = True
            # 去重
            waste_codes = list(dict.fromkeys(waste_codes))
            if waste_codes:
                extra_waste_notes = "\n\n**废物类别（根据组分推断）**: " + "、".join(waste_codes) + \
                    "\n\n**注意**: 混合物废弃物应按照各组分对应的最高危险废物类别进行管理。"
            if has_aquatic_toxicity:
                extra_waste_notes += "\n\n**环境警示**: 本品含对水生环境有害组分，废弃处置时应防止进入水体和下水道。"

        return (
            f"# 第十三部分：废弃处置\n\n"
            f"**处置方法**: {kb['method']}\n\n"
            f"**容器处理**: {kb['container']}\n\n"
            f"**适用的法规**: {kb['regulation']}\n\n"
            f"**注意事项**: {kb['note']}"
            f"{extra_waste_notes}"
        )

    def generate_section_14(self) -> str:
        """第十四部分：运输信息（DEF-111: 支持多重危险性）"""
        s14 = self.document.sections[14]

        # 从GHS分类推导运输信息（含多重危险）
        transport_info = self._infer_transport_info()

        # 运输类别：优先KB数据，fallback推导结果
        kb_transport_class = self._val(14, 'transport_class', '')
        if kb_transport_class and "待确认" not in kb_transport_class:
            transport_class = kb_transport_class
        elif transport_info["primary"]:
            if transport_info["multi_hazard"] and transport_info["secondary"]:
                transport_class = f"{transport_info['primary']}（主要），{transport_info['secondary']}（次要）"
            else:
                transport_class = transport_info["primary"]
        else:
            transport_class = "无可用数据 [待确认]"

        # UN编号：优先KB，fallback多重危险UN号
        un_number = self._val(14, 'un_number', '')
        if (not un_number or "待确认" in un_number) and transport_info["un_number"]:
            un_number = f"UN {transport_info['un_number']}"

        # 运输名称：优先KB，fallback推导结果
        shipping_name = self._val(14, 'proper_shipping_name', '')
        if not shipping_name or "待确认" in shipping_name:
            if transport_info["shipping_name"]:
                shipping_name = transport_info["shipping_name"]
            else:
                tc = transport_info["primary"]
                name_map = {
                    "3": "易燃液体，未另作规定的", "8": "腐蚀性物质",
                    "2.2": "气体", "4.1": "易燃固体",
                    "5.1": "氧化性物质", "6.1": "毒性物质",
                    "9": "环境危害物质"
                }
                shipping_name = name_map.get(tc, "无可用数据 [待确认]")

        # 基本信息表格
        basic_table = (
            f"| 项目 | 内容 |\n|------|------|\n"
            f"| UN编号 | {un_number if un_number else '无可用数据 [待确认]'} |\n"
            f"| 正式运输名称 | {shipping_name} |\n"
            f"| 运输危险类别 | {transport_class} |\n"
            f"| 包装类别 | {self._val(14, 'packing_group', '无可用数据 [待确认]')} |\n"
            f"| 海洋污染物 | {self._val(14, 'marine_pollutant', '否 [待确认]')} |"
        )

        # 运输方式分段
        # 优先使用推断的primary，若推断失败则看KB的transport_class
        primary_class = transport_info["primary"] or re.sub(r'\s*<!--.*?-->\s*', '', str(transport_class)).strip()
        is_regulated = "待确认" not in transport_class and primary_class
        un_clean = un_number.replace("UN ", "").replace("UN", "") if un_number else ""
        if is_regulated:
            if transport_info["multi_hazard"] and transport_info["secondary"]:
                hazard_desc = f"主要危险类别 {transport_info['primary']}，次要危险类别 {transport_info['secondary']}"
            else:
                hazard_desc = f"危险类别 {transport_class}"
            road_rail = f"{hazard_desc}，{shipping_name}。"
            sea = f"IMDG: {hazard_desc}，UN {un_clean}，{shipping_name}。"
            air = f"IATA/ICAO: {hazard_desc}，UN {un_clean}，{shipping_name}。"
        else:
            road_rail = "不受危险货物规则限制。"
            sea = "不受海运危险货物规则限制 (Not regulated for transport)。"
            air = "不受空运危险货物规则限制 (Not regulated for transport)。"

        return (
            f"# 第十四部分：运输信息\n\n"
            f"{basic_table}\n\n"
            f"**公路和铁路运输**:\n{road_rail}\n\n"
            f"**海运分类(IMO-IMDG)**:\n{sea}\n\n"
            f"**空运分类(IATA/ICAO)**:\n{air}\n\n"
            f"*此信息未计划传达所有关于此产品的特殊法规或操作要求。运输分类可能因容器体积和地区法规而不同。*"
        )

    def _infer_transport_info(self) -> dict:
        """从GHS分类推导运输信息，支持多重危险性（DEF-111）

        Returns:
            dict: {
                "primary": "8",          # 主要危险类别
                "secondary": "3",        # 次要危险类别（无则为""）
                "un_number": "2924",     # UN编号
                "shipping_name": "...",  # 正式运输名称
                "multi_hazard": True     # 是否多重危险
            }
        """
        ghs_list = []
        s2 = self.document.sections.get(2)
        if s2 and isinstance(s2.fields.get('ghs_classifications'), FieldValue):
            ghs_list = s2.fields['ghs_classifications'].value
        if not isinstance(ghs_list, list):
            ghs_list = []
        ghs_text = " ".join(str(g) for g in ghs_list)

        # 收集所有匹配的运输类别
        transport_mapping = self.TYPE_RULES.get("transport_class_mapping", [])
        matched_classes = []
        for rule in transport_mapping:
            keywords = rule.get("ghs_keywords", [])
            if any(kw in ghs_text for kw in keywords):
                cls = rule.get("class", "")
                if cls and cls not in matched_classes:
                    matched_classes.append(cls)

        # 检查多重危险组合
        multi_hazard_rules = self.TYPE_RULES.get("transport_multi_hazard", [])
        for rule in multi_hazard_rules:
            if set(rule["classes"]).issubset(set(matched_classes)):
                return {
                    "primary": rule["primary"],
                    "secondary": rule.get("secondary", ""),
                    "un_number": rule["un_number"],
                    "shipping_name": rule["shipping_name"],
                    "multi_hazard": True
                }

        # 单一危险：返回首个匹配
        if matched_classes:
            primary_cls = matched_classes[0]
            shipping = ""
            for rule in transport_mapping:
                if rule.get("class") == primary_cls:
                    shipping = rule.get("shipping_name", "")
                    break
            return {
                "primary": primary_cls,
                "secondary": "",
                "un_number": "",
                "shipping_name": shipping,
                "multi_hazard": False
            }

        return {"primary": "", "secondary": "", "un_number": "",
                "shipping_name": "", "multi_hazard": False}

    def generate_section_15(self) -> str:
        """第十五部分：法规信息（DEF-115: 按危害类型动态匹配法规）"""
        s15_template = self.templates.get_section_template(15)
        defaults = s15_template.get("defaults", {}) if s15_template else {}
        cn_regs = defaults.get("cn_regulations", [])

        # 基于GHS分类动态匹配专项法规
        ghs_text = " ".join(
            c.get("hazard", "") for c in getattr(self, '_classifications', [])
        )
        extra_regs = []
        if "易燃" in ghs_text:
            extra_regs.append("《危险化学品安全管理条例》（国务院令第591号）")
            extra_regs.append("《易制毒化学品管理条例》（针对特定有机溶剂）")
        if self._has_classification("腐蚀", require_cat1=True):
            extra_regs.append("《危险化学品安全管理条例》（国务院令第591号）")
        if "致癌" in ghs_text or "致突变" in ghs_text:
            extra_regs.append("《职业病防治法》— 致癌物职业接触管理")
        if "急性毒性" in ghs_text:
            extra_regs.append("《剧毒化学品购买和公路运输许可证件管理办法》")
        if "水生" in ghs_text or "环境" in ghs_text:
            extra_regs.append("《水污染防治法》— 环境危害物质排放管理")

        # NEW-117: 易制毒化学品管理条例 — 按CAS号匹配
        _YZD_CAS = {
            "7647-01-0": "盐酸",
            "7664-93-9": "硫酸",
            "67-64-1": "丙酮",
            "108-94-1": "环己酮",
            "74-89-5": "甲胺",
            "79-03-3": "溴代丙酮",
            "109-99-9": "四氢呋喃",
            "78-93-3": "丁酮",
            "141-78-6": "乙酸乙酯",
        }
        cas_yzd = getattr(self, '_kb_data', {}).get("cas_number", "")
        if cas_yzd in _YZD_CAS:
            reg_yzd = f"《易制毒化学品管理条例》— {_YZD_CAS[cas_yzd]}属于易制毒化学品"
            if reg_yzd not in extra_regs:
                extra_regs.append(reg_yzd)
        # 混合物：检查组分CAS
        if getattr(self, '_is_mixture', False):
            for comp in getattr(self, '_components_data', []):
                comp_cas = comp.get("cas_number", "")
                if comp_cas in _YZD_CAS:
                    reg_yzd = f"《易制毒化学品管理条例》— 含{_YZD_CAS[comp_cas]}(易制毒化学品)"
                    if reg_yzd not in extra_regs:
                        extra_regs.append(reg_yzd)

        # 国际法规（按危害类型）
        intl_regs = [
            "联合国《全球化学品统一分类和标签制度》（GHS Rev.9）",
            "ADR/RID（《国际公路/铁路危险货物运输协定》）",
            "IMDG Code（《国际海运危险货物规则》）",
            "IATA-DGR（《国际空运危险货物规则》）",
        ]
        if "易燃" in ghs_text:
            intl_regs.append("GB 50016《建筑设计防火规范》")
        if self._has_classification("腐蚀", require_cat1=True):
            intl_regs.append("GB 30000.2-2013《化学品分类和标签规范 第2部分：爆炸物》等系列标准")

        all_cn = list(cn_regs) + [r for r in extra_regs if r not in cn_regs]

        return (
            f"# 第十五部分：法规信息\n\n"
            f"**中国法规**:\n" +
            "\n".join(f"- {r}" for r in all_cn) +
            f"\n\n**国际法规**:\n" +
            "\n".join(f"- {r}" for r in intl_regs)
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
            f"| SDS编号 | AUTO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{hash(str(getattr(self, '_kb_data', {}).get('cas_number', ''))) % 10000:04d} |\n"
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

    # 加载企业信息配置
    company_info = {}
    try:
        _ci_path = DB_DIR / "company_info.json"
        if _ci_path.exists():
            with open(_ci_path, "r", encoding="utf-8") as _f:
                company_info = json.load(_f)
    except (OSError, json.JSONDecodeError):
        pass
    _supplier = company_info.get("company_name", "")
    if company_info.get("company_address"):
        _supplier += f"，{company_info['company_address']}"
    if company_info.get("company_phone"):
        _supplier += f"，电话：{company_info['company_phone']}"
    if company_info.get("email"):
        _supplier += f"，邮箱：{company_info['email']}"
    # 占位符检测：企业信息未配置时加 [待确认]
    _has_placeholder = any(
        v.startswith("[") and v.endswith("]")
        for v in [_supplier, company_info.get("emergency_phone", "")]
    )
    if _has_placeholder:
        _supplier += " [待确认]"

    gen.set_input_info(product_name=product_name,
                       recommended_use=company_info.get("recommended_use", ""),
                       supplier=_supplier,
                       emergency_phone=company_info.get("emergency_phone", "") + (" [待确认]" if _has_placeholder else ""),
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

    # 成分（DEF-007: 根据化学品类型设置合理浓度）
    cas = kb_data.get("cas_number", "")
    formula = kb_data.get("molecular_formula", "")
    name_cn = kb_data.get("chemical_name_cn", product_name)
    # 常见水溶液的典型浓度（从 chemical_type_rules.json 读取，带回退）
    _sol_conc_rules = {}
    try:
        import os, json as _json
        _rules_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'chemical_type_rules.json')
        with open(_rules_path, 'r', encoding='utf-8') as _f:
            _sol_conc_rules = _json.load(_f).get("solution_concentrations", {})
    except (OSError, ValueError):
        _sol_conc_rules = {
            "7647-01-0": "36-38%", "7664-93-9": "95-98%", "7697-37-2": "65-70%",
            "7664-38-2": "≥85%", "7681-52-9": "10-15%", "7722-84-1": "30-50%", "64-19-7": "≥99.0%",
        }
    concentration = _sol_conc_rules.get(cas, "≥99.0%")
    gen.set_components([{
        "name": name_cn,
        "cas": cas,
        "concentration": concentration,
        "ghs_classifications": ghs_list,
    }])

    content = gen.generate()
    # 清除来源注释（HTML注释不写入最终输出）
    content = re.sub(r'\s*<!--\s*src:[^>]*-->', '', content)
    return content, gen.get_review_flags()


def generate_mixture_sds(components_data: List[dict],
                          mixture_classifications: List[dict],
                          product_name: str = "",
                          use_llm: bool = False, version: str = "1.0",
                          revision_date: str = "", revision_log: list = None,
                          calc_result=None) -> tuple:
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

    # 加载企业信息配置
    company_info = {}
    try:
        _ci_path = DB_DIR / "company_info.json"
        if _ci_path.exists():
            with open(_ci_path, "r", encoding="utf-8") as _f:
                company_info = json.load(_f)
    except (OSError, json.JSONDecodeError):
        pass
    _supplier = company_info.get("company_name", "")
    if company_info.get("company_address"):
        _supplier += f"，{company_info['company_address']}"
    if company_info.get("company_phone"):
        _supplier += f"，电话：{company_info['company_phone']}"
    if company_info.get("email"):
        _supplier += f"，邮箱：{company_info['email']}"
    # 占位符检测：企业信息未配置时加 [待确认]
    _has_placeholder = any(
        v.startswith("[") and v.endswith("]")
        for v in [_supplier, company_info.get("emergency_phone", "")]
    )
    if _has_placeholder:
        _supplier += " [待确认]"

    gen.set_input_info(product_name=product_name,
                       recommended_use=company_info.get("recommended_use", ""),
                       supplier=_supplier,
                       emergency_phone=company_info.get("emergency_phone", "") + (" [待确认]" if _has_placeholder else ""),
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
            # 标准化每条分类格式: " - 类别 X" → "，类别X"
            normalized = []
            for g in ghs_raw:
                g_str = str(g)
                g_str = re.sub(r'\s*-\s*类别\s*', '，类别', g_str)
                g_str = re.sub(r'\s*-\s*Cat\s*', '，Cat ', g_str)
                normalized.append(g_str)
            ghs = ", ".join(normalized)
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
        s1.fields[key] = FieldValue(value="不适用（混合物，见第三部分成分表）", source="template")
    s1.fields["un_number"] = FieldValue(value="见第十四部分", source="template")
    # NEW-109: 混合物英文名称使用产品名 + " mixture"，而非第一个组分名
    if product_name:
        s1.fields["product_name_en"] = FieldValue(value=f"{product_name} mixture", source="template")
        s1.fields["product_name_cn"] = FieldValue(value=product_name, source="input")
    else:
        s1.fields["product_name_en"] = FieldValue(value="Mixture", source="template")
        s1.fields.pop("product_name_cn", None)

    # 混合物模式：S9理化特性从组分数据聚合推导（DEF-110: 改进聚合策略）
    s9 = gen.document.sections[9]
    s9.fields.clear()

    # 预处理：按浓度排序，识别主组分
    comp_with_conc = []
    for comp in components_data:
        conc_str = str(comp.get("concentration", "0")).replace("%", "")
        try:
            conc = float(conc_str)
        except (ValueError, TypeError):
            conc = 0
        comp_with_conc.append((comp, conc))
    comp_with_conc.sort(key=lambda x: x[1], reverse=True)
    main_comp = comp_with_conc[0][0] if comp_with_conc else {}

    # 聚合理化特性
    flash_points = []
    boiling_points = []
    densities = []
    appearances = []
    solubilities = []
    for comp, conc in comp_with_conc:
        try:
            fp = str(comp.get("flash_point", ""))
            fp_match = re.search(r'-?[\d.]+', fp)
            if fp_match:
                flash_points.append(float(fp_match.group()))
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            bp = str(comp.get("boiling_point", ""))
            bp_match = re.search(r'-?[\d.]+', bp)
            if bp_match:
                bp_val = float(bp_match.group())
                # 仅取挥发性组分（沸点<300°C），排除NaOH等不挥发溶质
                if bp_val < 300:
                    boiling_points.append(bp_val)
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            d = str(comp.get("density", ""))
            d_match = re.search(r'[\d.]+', d)
            if d_match:
                densities.append(float(d_match.group()))
        except (ValueError, TypeError, AttributeError):
            pass
        app = str(comp.get("appearance", ""))
        if app and "无可用" not in app:
            appearances.append(app)
        sol = str(comp.get("solubility_details", comp.get("solubility", "")))
        if sol and "无可用" not in sol:
            solubilities.append(sol)

    if flash_points:
        # FIX-flashpoint: 水溶液中低浓度有机溶剂的闪点不等于纯品闪点
        # 检测水含量：如果水>60%，易燃有机物<20%，闪点可能>60°C
        water_conc = 0.0
        flammable_organic_conc = 0.0
        for comp, conc in comp_with_conc:
            cn = str(comp.get("chemical_name_cn", ""))
            formula = str(comp.get("molecular_formula", ""))
            if cn == "水" or formula == "H2O":
                water_conc += conc
            ghs_raw = comp.get("ghs_classifications", "")
            if isinstance(ghs_raw, list):
                ghs_text = " ".join(str(g) for g in ghs_raw)
            else:
                ghs_text = str(ghs_raw) if ghs_raw else ""
            if "易燃" in ghs_text and "C" in formula:
                flammable_organic_conc += conc
        if water_conc > 60 and flammable_organic_conc < 20:
            s9.fields["flash_point"] = FieldValue(
                value="不适用（水溶液中有机物浓度低，实际闪点>60°C）", source="aggregation")
        else:
            # 混合物闪点取最低值（最危险）
            min_fp = min(flash_points)
            s9.fields["flash_point"] = FieldValue(value=f"{min_fp:.0f}（最低组分值）", source="aggregation")
    if boiling_points:
        bp_min = min(boiling_points)
        bp_max = max(boiling_points)
        if bp_min == bp_max:
            s9.fields["boiling_point"] = FieldValue(value=f"{bp_min:.0f}", source="aggregation")
        else:
            s9.fields["boiling_point"] = FieldValue(value=f"{bp_min:.0f}~{bp_max:.0f}（挥发性组分范围）", source="aggregation")
    if densities:
        # 密度取加权平均（按浓度）
        total_conc = sum(conc for _, conc in comp_with_conc)
        if total_conc > 0:
            avg_density = sum(d * comp_with_conc[i][1] / total_conc
                             for i, d in enumerate(densities))
            s9.fields["density"] = FieldValue(value=f"{avg_density:.2f}（加权平均估算值）", source="aggregation")
    if appearances:
        # NEW-108: 判断液体组分是否主导（>50%浓度）
        _solid_keywords = ["固体", "粉末", "片状", "颗粒", "结晶"]
        total_conc_all = sum(conc for _, conc in comp_with_conc)
        liquid_conc = 0.0
        for comp, conc in comp_with_conc:
            app_check = str(comp.get("appearance", ""))
            is_solid = any(kw in app_check for kw in _solid_keywords)
            if not is_solid:
                liquid_conc += conc
        liquid_dominant = total_conc_all > 0 and (liquid_conc / total_conc_all) > 0.5

        # DEF-110: 取主组分外观而非拼接所有（避免"白色固体；无色液体"矛盾）
        main_app = str(main_comp.get("appearance", ""))
        if main_app and "无可用" not in main_app:
            # NEW-108: 若液体主导且主组分外观为固体，则过滤为液体描述
            if liquid_dominant and any(kw in main_app for kw in _solid_keywords):
                main_app = "液体（根据组分推断）"
            s9.fields["appearance"] = FieldValue(value=main_app, source="aggregation")
        else:
            # fallback: 去重后最多2个，过滤固体描述（当液体主导时）
            filtered_apps = list(dict.fromkeys(appearances))[:2]
            if liquid_dominant:
                filtered_apps = [a for a in filtered_apps if not any(kw in a for kw in _solid_keywords)]
            if filtered_apps:
                s9.fields["appearance"] = FieldValue(value="；".join(filtered_apps), source="aggregation")
            else:
                s9.fields["appearance"] = FieldValue(value="液体（根据组分推断）", source="inference")
    else:
        # 推断外观：根据主组分浓度和物态
        s9.fields["appearance"] = FieldValue(value="液体（根据组分推断）", source="inference")
    s9.fields["odor"] = FieldValue(value="有特殊气味（含有机溶剂组分）", source="inference")
    # 熔点聚合（DEF-110: 仅取挥发性组分的熔点范围）
    melting_points = []
    for comp, conc in comp_with_conc:
        try:
            mp = str(comp.get("melting_point", ""))
            mp_match = re.search(r'-?[\d.]+', mp)
            if mp_match:
                mp_val = float(mp_match.group())
                if mp_val < 100:  # 排除溶质的高熔点
                    melting_points.append(mp_val)
        except (ValueError, TypeError, AttributeError):
            pass
    if melting_points:
        mp_min = min(melting_points)
        mp_max = max(melting_points)
        if mp_min == mp_max:
            s9.fields["melting_point"] = FieldValue(value=f"{mp_min:.0f}", source="aggregation")
        else:
            s9.fields["melting_point"] = FieldValue(value=f"{mp_min:.0f}~{mp_max:.0f}", source="aggregation")
    # 溶解性聚合（DEF-006: 语义融合替代直接拼接）
    sol_values = []
    for comp in components_data:
        sol = str(comp.get("solubility", comp.get("solubility_details", "")))
        if sol and "无可用" not in sol:
            sol_values.append(sol)
    if sol_values:
        # 分类归纳溶解性
        water_soluble = []    # 与水混溶
        partial_soluble = []  # 微溶于水
        organic_soluble = []  # 溶于有机溶剂
        for sol in sol_values:
            if "与水混溶" in sol or "与水完全互溶" in sol or "易溶于水" in sol:
                water_soluble.append(sol)
            elif "微溶于水" in sol or "难溶于水" in sol or "不溶于水" in sol:
                partial_soluble.append(sol)
            if "有机溶剂" in sol:
                organic_soluble.append(sol)
        # 生成融合描述
        sol_parts = []
        if water_soluble and partial_soluble:
            sol_parts.append("部分组分与水混溶，部分组分微溶或难溶于水")
        elif water_soluble:
            sol_parts.append("各组分均与水混溶")
        elif partial_soluble:
            sol_parts.append("各组分微溶或难溶于水")
        if organic_soluble:
            sol_parts.append("各组分均易溶于常见有机溶剂（乙醇、乙醚、丙酮等）")
        if sol_parts:
            s9.fields["solubility"] = FieldValue(value="；".join(sol_parts), source="aggregation")
        else:
            # fallback: 去重后拼接（限制4条）
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
            if "经口" in hazard or "oral" in hazard.lower():
                s11.fields["ld50_oral"] = FieldValue(
                    value=f"ATE = {ate_val:.0f} mg/kg（混合物计算值）",
                    source="classification")
            elif "经皮" in hazard or "dermal" in hazard.lower():
                s11.fields["ld50_dermal"] = FieldValue(
                    value=f"ATE = {ate_val:.0f} mg/kg（混合物计算值）",
                    source="classification")
            elif "吸入" in hazard or "inhalation" in hazard.lower():
                s11.fields["lc50_inhalation"] = FieldValue(
                    value=f"ATE = {ate_val:.1f} mg/L（混合物计算值）",
                    source="classification")

    # 即使ATE不分类（>5000），也用ATE计算值替换纯物质LD50，避免误导
    if calc_result and getattr(calc_result, 'ate_oral', None):
        s11.fields["ld50_oral"] = FieldValue(
            value=f"ATE ≈ {calc_result.ate_oral:.0f} mg/kg（混合物估算值）",
            source="classification")
    if calc_result and getattr(calc_result, 'ate_dermal', None):
        s11.fields["ld50_dermal"] = FieldValue(
            value=f"ATE ≈ {calc_result.ate_dermal:.0f} mg/kg（混合物估算值）",
            source="classification")

    # R-09: 混合物为液体时，若LC50吸入显示"不适用（固体）"，替换为"无可用数据"
    lc50_val = s11.fields.get("lc50_inhalation")
    if lc50_val and "固体" in str(lc50_val.value):
        s11.fields["lc50_inhalation"] = FieldValue(value="无可用数据", source="classification")

    # 混合物S11毒理：从组分GHS分类反填（致癌/生殖/STOT等）
    # 扫描所有组分的ghs_classifications，聚合各危害类别
    all_comp_ghs = []
    for comp in components_data:
        ghs_raw = comp.get("ghs_classifications", "")
        if isinstance(ghs_raw, list):
            all_comp_ghs.extend(ghs_raw)
        elif ghs_raw:
            all_comp_ghs.append(str(ghs_raw))
    all_ghs_text = " ".join(str(g) for g in all_comp_ghs)

    # 皮肤腐蚀/刺激 — FIX-S2S11: 优先从混合物分类结果(S2)取，确保一致性
    skin_from_mixture = [c for c in mixture_classifications
                         if "皮肤腐蚀" in c.get("hazard", "") or "皮肤刺激" in c.get("hazard", "")]
    if skin_from_mixture:
        # 取最严重等级（Cat1 > Cat2）
        best_skin = skin_from_mixture[0]
        for c in skin_from_mixture:
            if "类别1" in c.get("hazard", "") or "Cat 1" in c.get("hazard", ""):
                best_skin = c
                break
        s11.fields["skin_corrosion_category"] = FieldValue(
            value=best_skin["hazard"], source="classification")
    elif any(kw in all_ghs_text for kw in ["皮肤腐蚀", "皮肤刺激"]):
        # fallback: 从组分取（仅当混合物分类中无此分类时）
        skin_cats = [g for g in all_comp_ghs if "皮肤腐蚀" in str(g) or "皮肤刺激" in str(g)]
        has_corrosion = any("皮肤腐蚀" in str(c) and ("Cat 1" in str(c) or "类别1" in str(c)) for c in skin_cats)
        if has_corrosion:
            best = next(c for c in skin_cats if "皮肤腐蚀" in str(c) and ("Cat 1" in str(c) or "类别1" in str(c)))
        elif any("皮肤腐蚀" in str(c) for c in skin_cats):
            best = next(c for c in skin_cats if "皮肤腐蚀" in str(c))
        else:
            best = skin_cats[0]
        s11.fields["skin_corrosion_category"] = FieldValue(
            value=str(best), source="classification")
    # 严重眼损伤/眼刺激 — FIX-S2S11: 优先从混合物分类结果(S2)取
    eye_from_mixture = [c for c in mixture_classifications
                        if "眼损伤" in c.get("hazard", "") or "眼刺激" in c.get("hazard", "")]
    if eye_from_mixture:
        best_eye = eye_from_mixture[0]
        for c in eye_from_mixture:
            if "类别1" in c.get("hazard", "") or "Cat 1" in c.get("hazard", ""):
                best_eye = c
                break
        s11.fields["eye_damage_category"] = FieldValue(
            value=best_eye["hazard"], source="classification")
    elif any(kw in all_ghs_text for kw in ["眼损伤", "眼刺激"]):
        # fallback: 从组分取
        eye_cats = [g for g in all_comp_ghs if "眼损伤" in str(g) or "眼刺激" in str(g)]
        has_severe = any("眼损伤" in str(c) and ("Cat 1" in str(c) or "类别1" in str(c) or "类别 1" in str(c)) for c in eye_cats)
        if has_severe:
            best = next(c for c in eye_cats if "眼损伤" in str(c) and ("Cat 1" in str(c) or "类别1" in str(c) or "类别 1" in str(c)))
        elif any("眼损伤" in str(c) for c in eye_cats):
            best = next(c for c in eye_cats if "眼损伤" in str(c))
        else:
            best = eye_cats[0]
        s11.fields["eye_damage_category"] = FieldValue(
            value=str(best), source="classification")
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
    # 特异性靶器官毒性 — 归并去重，按Cat等级排序
    stot_se = [str(g) for g in all_comp_ghs if "靶器官" in str(g) and "单次" in str(g)]
    if stot_se:
        # 去重：标准化格式后取唯一
        seen_targets = set()
        unique_se = []
        for s in stot_se:
            # 提取靶器官关键词
            targets = re.findall(r'[\(（]([^)）]+)[\)）]|(\w+[器官系统])', s)
            target_key = "".join("".join(t) for t in targets) if targets else s
            if target_key not in seen_targets:
                seen_targets.add(target_key)
                unique_se.append(s)
        s11.fields["stot_single_exposure"] = FieldValue(
            value="；".join(unique_se), source="classification")
    stot_re = [str(g) for g in all_comp_ghs if "靶器官" in str(g) and "反复" in str(g)]
    if stot_re:
        # 优先Cat1，按靶器官去重
        cat1_items = [s for s in stot_re if "Cat 1" in s or "类别1" in s or "类别 1" in s]
        cat2_items = [s for s in stot_re if "Cat 2" in s or "类别2" in s or "类别 2" in s]
        seen_targets = set()
        unique_re = []
        for s in (cat1_items + cat2_items):
            targets = re.findall(r'[\(（]([^)）]+)[\)）]|(\w+[器官系统经液])', s)
            target_key = "".join("".join(t) for t in targets) if targets else s
            if target_key not in seen_targets:
                seen_targets.add(target_key)
                unique_re.append(s)
        s11.fields["stot_repeated_exposure"] = FieldValue(
            value="；".join(unique_re), source="classification")
    # 吸入危害（DEF-003: 根据组分类型判断描述）
    if any(kw in all_ghs_text for kw in ["吸入危害", "吸入危险"]):
        # 检查是否含有机液体组分
        has_organic_comp = False
        for c_data in components_data:
            formula = str(c_data.get("molecular_formula", ""))
            if "C" in formula and "H" in formula:
                has_organic_comp = True
                break
        if has_organic_comp:
            s11.fields["aspiration_hazard"] = FieldValue(value="含低粘度有机液体组分，存在吸入危害", source="classification")
        else:
            s11.fields["aspiration_hazard"] = FieldValue(value="根据分类，存在吸入危害", source="classification")
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

    # 混合物S14运输：推导运输类别、UN编号、包装类别和海洋污染物（DEF-111: 多重危险）
    s14 = gen.document.sections[14]
    ghs_text_for_transport = " ".join(c.get("hazard", "") for c in mixture_classifications)
    # 收集所有匹配的运输类别
    transport_mapping = gen.TYPE_RULES.get("transport_class_mapping", [])
    matched_transport_classes = []
    for rule in transport_mapping:
        keywords = rule.get("ghs_keywords", [])
        if any(kw in ghs_text_for_transport for kw in keywords):
            cls = rule.get("class", "")
            if cls and cls not in matched_transport_classes:
                matched_transport_classes.append(cls)
    # 检查多重危险组合
    multi_hazard_rules = gen.TYPE_RULES.get("transport_multi_hazard", [])
    multi_matched = None
    for rule in multi_hazard_rules:
        if set(rule["classes"]).issubset(set(matched_transport_classes)):
            multi_matched = rule
            break
    if multi_matched:
        s14.fields["transport_class"] = FieldValue(
            value=f"{multi_matched['primary']}（主要），{multi_matched['secondary']}（次要）",
            source="classification")
        s14.fields["un_number"] = FieldValue(
            value=f"UN {multi_matched['un_number']}", source="classification")
        s14.fields["proper_shipping_name"] = FieldValue(
            value=multi_matched["shipping_name"], source="classification")
    elif matched_transport_classes:
        primary_cls = matched_transport_classes[0]
        s14.fields["transport_class"] = FieldValue(value=primary_cls, source="classification")
        for rule in transport_mapping:
            if rule.get("class") == primary_cls:
                s14.fields["proper_shipping_name"] = FieldValue(
                    value=rule.get("shipping_name", ""), source="classification")
                break
        un_defaults = {"3": "UN 1993", "4.1": "UN 1325", "6.1": "UN 2810",
                       "8": "UN 1760", "5.1": "UN 1479", "9": "UN 3082"}
        if primary_cls in un_defaults:
            s14.fields["un_number"] = FieldValue(value=un_defaults[primary_cls], source="classification")
    # 从分类推导包装类别（同时匹配中文"类别"和英文"Cat"格式）
    has_cat1_or_2 = any(
        "Cat 1" in c.get("hazard", "") or "类别1" in c.get("hazard", "") or
        "Cat 2" in c.get("hazard", "") or "类别2" in c.get("hazard", "")
        for c in mixture_classifications)
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
    # 清除来源注释（HTML注释不写入最终输出）
    content = re.sub(r'\s*<!--\s*src:[^>]*-->', '', content)
    return content, gen.get_review_flags()
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
