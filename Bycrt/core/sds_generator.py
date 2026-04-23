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

            # 象形图
            picts = cls.get("pictograms", self.templates.hazard_to_pictograms(hazard))
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

    def _has_classification(self, keyword: str) -> bool:
        """检查分类中是否包含某关键词"""
        for cls in getattr(self, '_classifications', []):
            if keyword in cls.get("hazard", ""):
                return True
        return False

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

    def generate_section_4(self) -> str:
        """第四部分：急救措施（基于分类规则 + KB特异性注释）"""
        is_corrosive = self._has_classification("皮肤腐蚀") or self._has_classification("腐蚀")
        is_toxic = self._has_classification("急性毒性")

        inhalation = "将患者移至空气新鲜处。如呼吸困难，给予吸氧。如呼吸停止，进行人工呼吸。立即就医。"
        skin = "立即用大量流动水冲洗至少15分钟。脱去被污染的衣物。就医。" if is_corrosive else \
               "用大量水和肥皂冲洗。如有刺激，就医。"
        eye = "立即用大量水冲洗至少15分钟，提起上下眼睑。如戴隐形眼镜且易取下，取下。立即就医。" if is_corrosive else \
              "用大量水冲洗几分钟。如持续刺激，就医。"
        ingestion = "漱口。不要催吐。给少量水稀释。立即就医。" if is_corrosive or is_toxic else \
                    "漱口。给水稀释。如感觉不适，就医。"

        # 注入KB特异性注释
        for route, base_text in [("inhalation", inhalation), ("skin", skin),
                                  ("eye", eye), ("ingestion", ingestion)]:
            note = self._val(4, f'notes_{route}', "")
            if note and "待确认" not in note:
                # 找到对应变量并追加注释
                if route == "inhalation":
                    inhalation = f"{inhalation}\n注意：{note}"
                elif route == "skin":
                    skin = f"{skin}\n注意：{note}"
                elif route == "eye":
                    eye = f"{eye}\n注意：{note}"
                elif route == "ingestion":
                    ingestion = f"{ingestion}\n注意：{note}"

        rescuer = "救援人员应佩戴适当的防护装备。避免直接接触。"
        physician = "无特效解毒剂。对症治疗。"

        return (
            f"# 第四部分：急救措施\n\n"
            f"**吸入**: {inhalation}\n\n"
            f"**皮肤接触**: {skin}\n\n"
            f"**眼睛接触**: {eye}\n\n"
            f"**食入**: {ingestion}\n\n"
            f"**救援人员防护**: {rescuer}\n\n"
            f"**对医生的提示**: {physician}"
        )

    def generate_section_5(self) -> str:
        """第五部分：消防措施"""
        is_flammable = self._has_classification("易燃")
        is_oxidizer = self._has_classification("氧化")
        is_corrosive = self._has_classification("腐蚀")

        hazard = "遇明火、高热可燃。" if is_flammable else \
                 "强氧化剂，与可燃物接触可引起燃烧。" if is_oxidizer else \
                 "不燃烧，但与金属反应可产生易燃气体。" if is_corrosive else \
                 "参见具体化学品特性。 [待确认]"

        # 注入KB消防注释
        ff_notes = self._val(5, 'notes', '')
        if ff_notes and "待确认" not in ff_notes:
            hazard = f"{hazard}\n{ff_notes}"

        media = "干粉、二氧化碳、泡沫、砂土。"
        prohibited = self._val(5, 'prohibited_media', '')
        if prohibited and "待确认" not in prohibited:
            pass  # use KB value
        elif is_flammable and self._has_classification("金属"):
            prohibited = "严禁用水。"
        else:
            prohibited = "无特殊禁止要求。"

        advice = "消防人员必须佩戴防毒面具，穿全身消防服。尽可能将容器从火场移至空旷处。喷水保持火场容器冷却。"

        return (
            f"# 第五部分：消防措施\n\n"
            f"**危险特性**: {hazard}\n\n"
            f"**适用灭火剂**: {media}\n\n"
            f"**禁止使用的灭火剂**: {prohibited}\n\n"
            f"**消防建议**: {advice}"
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

        return (
            f"# 第六部分：泄漏应急处理\n\n"
            f"**人员防护措施**: {personal}\n\n"
            f"**环境保护措施**: {environmental}\n\n"
            f"**收容与清除方法**: {cleanup}\n\n"
            f"**参考**: 参见第八部分和第十三部分。"
        )

    def generate_section_7(self) -> str:
        """第七部分：操作处置与储存"""
        is_flammable = self._has_classification("易燃")
        is_corrosive = self._has_classification("腐蚀")
        is_toxic = self._has_classification("急性毒性")

        handling = "密闭操作，局部排风。" + \
                   ("远离火源和热源。使用防爆设备。" if is_flammable else "") + \
                   ("避免接触皮肤和眼睛。" if is_corrosive else "") + \
                   ("操作人员必须经过专门培训，严格遵守操作规程。" if is_toxic else "")

        storage = "储存于阴凉、干燥、通风良好的地方。保持容器密闭。" + \
                  ("远离火源和热源。与氧化剂分开存放。" if is_flammable else "") + \
                  ("储存于耐腐蚀容器中。" if is_corrosive else "")

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
        return (
            f"# 第九部分：理化特性\n\n"
            f"| 特性 | 数值 |\n|------|------|\n"
            f"| 外观 | {self._val(9, 'appearance', '无可用数据 [待确认]')} |\n"
            f"| 气味 | {self._val(9, 'odor', '无可用数据 [待确认]')} |\n"
            f"| 熔点 | {self._val(9, 'melting_point', '无可用数据 [待确认]')} °C |\n"
            f"| 沸点 | {self._val(9, 'boiling_point', '无可用数据 [待确认]')} °C |\n"
            f"| 闪点 | {self._val(9, 'flash_point', '无可用数据 [待确认]')} °C |\n"
            f"| 密度 | {self._val(9, 'density', '无可用数据 [待确认]')} g/cm³ |\n"
            f"| 蒸气压 | {self._val(9, 'vapor_pressure', '无可用数据 [待确认]')} kPa |\n"
            f"| 溶解性 | {self._val(9, 'solubility', '无可用数据 [待确认]')} |\n"
            f"| 自燃温度 | {self._val(9, 'autoignition_temp', '无可用数据 [待确认]')} °C |\n"
            f"| 爆炸极限 | {self._val(9, 'explosion_limits', '无可用数据 [待确认]')} |\n"
            f"| 辛醇/水分配系数 | {self._val(9, 'partition_coefficient', '无可用数据 [待确认]')} |"
        )

    def generate_section_10(self) -> str:
        """第十部分：稳定性和反应性"""
        decomp = self._val(10, 'hazardous_decomposition', '一氧化碳、二氧化碳及其他有害气体。 [待确认]')
        return (
            f"# 第十部分：稳定性和反应性\n\n"
            f"**稳定性**: 在正常储存和操作条件下稳定。\n\n"
            f"**应避免的条件**: {self._val(10, 'conditions_to_avoid', '明火、高热。 [待确认]')}\n\n"
            f"**禁配物**: {self._val(10, 'incompatible_materials', '强氧化剂、强酸、强碱 [待确认]')}\n\n"
            f"**危险分解产物**: {decomp}"
        )

    def generate_section_11(self) -> str:
        """第十一部分：毒理学信息"""
        s11 = self.document.sections[11]

        def tox_field(key, label):
            val = self._val(11, key, "无可用数据 [待确认]")
            return f"**{label}**: {val}"

        # 毒理定性注释
        notes_lines = []
        for note_key, label in [("notes_acute_symptoms", "急性中毒症状"),
                                  ("notes_chronic_effects", "慢性影响"),
                                  ("notes_eye_effects", "眼睛影响"),
                                  ("notes_iarc_group", "致癌性详情")]:
            note_val = self._val(11, note_key, "")
            if note_val and "待确认" not in note_val:
                notes_lines.append(f"**{label}**: {note_val}")

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
            f"{tox_field('aspiration_hazard', '吸入危害')}\n\n"
            f"{notes_text}"
        )

    def generate_section_12(self) -> str:
        """第十二部分：生态学信息"""
        fish = self._val(12, 'ecotoxicity_fish_lc50')
        daphnia = self._val(12, 'ecotoxicity_daphnia_ec50')
        algae = self._val(12, 'ecotoxicity_algae_ec50')
        persistence = self._val(12, 'persistence_degradability')
        bcf = self._val(12, 'bioaccumulation_bcf')
        log_bc = self._val(12, 'bioaccumulation_log_bc')

        eco_text = ""
        if fish != "无可用数据 [待确认]" or daphnia != "无可用数据 [待确认]" or algae != "无可用数据 [待确认]":
            eco_text = f"鱼类LC50: {fish}; 水蚤EC50: {daphnia}; 藻类EC50: {algae}"
        else:
            eco_text = "无可用数据 [待确认]"

        bio_text = ""
        if bcf != "无可用数据 [待确认]" or log_bc != "无可用数据 [待确认]":
            bio_text = f"BCF: {bcf}; LogBC: {log_bc}"
        else:
            bio_text = "无可用数据 [待确认]"

        return (
            f"# 第十二部分：生态学信息\n\n"
            f"**生态毒性**: {eco_text}\n\n"
            f"**持久性和降解性**: {persistence}\n\n"
            f"**生物富集潜力**: {bio_text}\n\n"
            f"**土壤中的迁移性**: {self._val(12, 'mobility_in_soil', '无可用数据 [待确认]')}"
        )

    def generate_section_13(self) -> str:
        """第十三部分：废弃处置"""
        return (
            f"# 第十三部分：废弃处置\n\n"
            f"**处置方法**: 按照国家和地方相关法规要求进行处置。委托有资质的危险废物处理单位处理。\n\n"
            f"**容器处理**: 废弃容器应用水彻底清洗后回收或按相关规定处置。\n\n"
            f"**注意事项**: 处置过程中应遵守相关环保法规，防止环境污染。"
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

    # 用第一个有数据的组分作为主数据源（用于理化特性等）
    for comp in components_data:
        if comp:
            gen.set_chemical_data(comp)
            break

    gen.set_classification(mixture_classifications)
    gen.set_components(components_data, is_mixture=True)

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
