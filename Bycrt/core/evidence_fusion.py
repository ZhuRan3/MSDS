"""
证据检索与融合层
化安通 (HuaAnTong) MSDS自动生成系统 - 第三层

职责：
1. 多源自动检索（本地KB + PubChem API + LLM推断）
2. 字段级来源标注
3. 冲突检测
4. 置信度评估
5. 优先级排序
6. 输出统一的字段事实池

优先级：
  法规权威规则 > 官方数据库 > 厂商SDS > 公共数据库 > 模型推断
"""

import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = PROJECT_ROOT / "db"


class SourcePriority(Enum):
    """数据源优先级"""
    REGULATION = 100       # 法规权威
    OFFICIAL_DB = 80       # PubChem等官方数据库
    VENDOR_SDS = 60        # 厂商SDS样本
    LOCAL_KB = 70          # 本地知识库（通常来自PubChem+LLM）
    PUBLIC_DB = 50         # 公共数据库
    LLM_INFERENCE = 30     # LLM推断
    TEMPLATE_DEFAULT = 10  # 模板默认值


class ConfidenceLevel(Enum):
    """置信度等级"""
    HIGH = 0.9      # 多源一致
    MEDIUM = 0.7    # 单一来源，权威
    LOW = 0.5       # 模型推断
    UNVERIFIED = 0.3  # 未验证


@dataclass
class Evidence:
    """单个证据条目"""
    field_name: str              # 字段名
    value: Any                   # 值
    source: str                  # 来源标识
    source_type: SourcePriority  # 来源类型
    confidence: float = 0.7      # 置信度 0-1
    conflict: bool = False       # 是否存在冲突
    notes: str = ""              # 备注
    selection_reason: str = ""   # 选择理由


@dataclass
class FactPool:
    """字段事实池 - 融合后的统一结果"""
    cas: str = ""
    name_cn: str = ""
    name_en: str = ""
    evidences: Dict[str, List[Evidence]] = field(default_factory=dict)
    conflicts: List[Dict] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)

    def add_evidence(self, field_name: str, evidence: Evidence):
        if field_name not in self.evidences:
            self.evidences[field_name] = []
        self.evidences[field_name].append(evidence)

    def get_best(self, field_name: str) -> Optional[Evidence]:
        """获取某字段的最佳证据（最高优先级+置信度）"""
        evs = self.evidences.get(field_name, [])
        if not evs:
            return None
        return max(evs, key=lambda e: (e.source_type.value, e.confidence))

    def get_value(self, field_name: str, default: str = "") -> Any:
        best = self.get_best(field_name)
        return best.value if best else default

    def to_dict(self) -> Dict[str, Any]:
        """导出为扁平字典（最佳值），用于 SDSGenerator.set_chemical_data()"""
        result = {}
        for field_name in self.evidences:
            best = self.get_best(field_name)
            if best and best.value is not None:
                result[field_name] = best.value
        return result

    def get_source_summary(self) -> Dict[str, str]:
        """导出字段来源摘要 {field_name: 'source (confidence)'}"""
        summary = {}
        for field_name in self.evidences:
            best = self.get_best(field_name)
            if best:
                summary[field_name] = f"{best.source} (conf={best.confidence:.1f})"
        return summary


class EvidenceRetriever:
    """多源证据检索器"""

    def __init__(self):
        self.kb = self._load_kb()
        self.ghs = self._load_ghs()
        self.val_samples = self._load_val_samples()

    def _load_kb(self) -> dict:
        path = DB_DIR / "chemical_db.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_ghs(self) -> dict:
        path = DB_DIR / "ghs_mappings.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_val_samples(self) -> dict:
        """加载val/目录下的真实SDS样本作为证据源"""
        val_dir = PROJECT_ROOT / "val"
        samples = {}
        if not val_dir.exists():
            return samples
        import os
        for fname in os.listdir(val_dir):
            if not fname.endswith(".md") or fname.startswith("README") or "指南" in fname:
                continue
            fpath = val_dir / fname
            try:
                content = fpath.read_text(encoding="utf-8")
            except Exception:
                continue
            # 从文件名解析化学品名和CAS
            base = fname.replace(".md", "")
            parts = base.split("_")
            name = parts[0] if parts else ""
            cas = parts[1] if len(parts) > 1 else ""
            # 从内容提取关键字段
            data = {"_source_file": str(fpath), "chemical_name_cn": name, "cas_number": cas}
            # 提取闪点
            fp_match = re.search(r'闪点[：:]\s*([-\d.]+)\s*°C', content)
            if fp_match:
                data["flash_point"] = f"{fp_match.group(1)}°C"
            # 提取沸点
            bp_match = re.search(r'沸点[：:]\s*([-\d.]+)\s*°C', content)
            if bp_match:
                data["boiling_point"] = f"{bp_match.group(1)}°C"
            # 提取密度
            den_match = re.search(r'相对密度[^\d]*([-\d.]+)', content)
            if den_match:
                data["density"] = den_match.group(1)
            # 提取LD50
            ld50_match = re.search(r'LD50[^\d]*([\d,]+)\s*mg/kg', content)
            if ld50_match:
                data["ld50_oral"] = f"{ld50_match.group(1)} mg/kg"
            # 提取溶解性
            sol_match = re.search(r'溶解性[：:]\s*(.+?)(?:\n|$)', content)
            if sol_match:
                data["solubility_details"] = sol_match.group(1).strip()
            if cas:
                samples[cas] = data
            if name:
                samples[name] = data
        return samples

    def retrieve(self, query: str, query_type: str = "auto") -> FactPool:
        """
        执行多源检索

        Args:
            query: CAS号或化学品名称
            query_type: "cas", "name", or "auto"
        """
        pool = FactPool()

        # 确定查询类型
        if query_type == "auto":
            if re.match(r'\d{2,7}-\d{2}-\d', query):
                query_type = "cas"
            else:
                query_type = "name"

        # 来源1：本地知识库
        kb_data = self._search_kb(query, query_type)
        if kb_data:
            self._extract_kb_evidence(kb_data, pool)

        # 来源2：PubChem API
        if not kb_data:
            pubchem_data = self._fetch_pubchem(query, query_type)
            if pubchem_data:
                self._extract_kb_evidence(pubchem_data, pool)
                # 标记为OFFICIAL_DB优先级
                for field_name, evs in pool.evidences.items():
                    for ev in evs:
                        if ev.source == "local_kb" and ev.source_type == SourcePriority.LOCAL_KB:
                            ev.source = "pubchem_api"
                            ev.source_type = SourcePriority.OFFICIAL_DB

        # 来源3：真实SDS样本（val/目录，低优先级，不覆盖已有数据）
        val_data = self._search_val_samples(query, query_type)
        if val_data:
            for key, value in val_data.items():
                if key.startswith("_") or key in ("chemical_name_cn", "cas_number"):
                    continue
                if not pool.evidences.get(key):  # 仅填充缺失字段
                    pool.add_evidence(key, Evidence(
                        field_name=key,
                        value=value,
                        source="val_sample",
                        source_type=SourcePriority.VENDOR_SDS,
                        confidence=0.6,
                        notes="来自真实SDS样本",
                    ))

        # 冲突检测
        self._detect_conflicts(pool)

        # 缺失字段识别
        self._identify_missing(pool)

        return pool

    def _search_kb(self, query: str, query_type: str) -> Optional[dict]:
        """在本地知识库中搜索"""
        if query_type == "cas":
            # CAS精确匹配（去除连字符）
            cas_clean = query.replace("-", "")
            for cas, data in self.kb.items():
                if cas == query or cas.replace("-", "") == cas_clean:
                    return data
        else:
            # 名称匹配：精确匹配优先，然后子串匹配（短名优先避免"甲苯"匹配"三硝基甲苯"）
            query_lower = query.lower()

            # 第一轮：精确匹配
            for cas, data in self.kb.items():
                name_cn = data.get("chemical_name_cn", "").lower()
                name_en = data.get("chemical_name_en", "").lower()
                synonyms = data.get("synonyms", [])
                if query_lower == name_cn or query_lower == name_en:
                    return data
                if isinstance(synonyms, list):
                    for syn in synonyms:
                        if query_lower == str(syn).lower():
                            return data

            # 第二轮：子串匹配，按名称长度升序排列（短名优先）
            candidates = []
            for cas, data in self.kb.items():
                name_cn = data.get("chemical_name_cn", "").lower()
                name_en = data.get("chemical_name_en", "").lower()
                synonyms = data.get("synonyms", [])
                matched = False
                if query_lower in name_cn or query_lower in name_en:
                    matched = True
                elif isinstance(synonyms, list):
                    for syn in synonyms:
                        if query_lower in str(syn).lower():
                            matched = True
                            break
                if matched:
                    candidates.append((len(name_cn), data))
            if candidates:
                candidates.sort(key=lambda x: x[0])
                return candidates[0][1]
        return None

    def _search_val_samples(self, query: str, query_type: str) -> Optional[dict]:
        """在val/真实SDS样本中搜索"""
        query_lower = query.lower().replace("-", "")
        for key, data in self.val_samples.items():
            key_lower = key.lower().replace("-", "")
            if query_lower == key_lower or query_lower in key_lower:
                return data
        # 按名称匹配
        for key, data in self.val_samples.items():
            name = data.get("chemical_name_cn", "").lower()
            if query_lower in name or name in query_lower:
                return data
        return None

    def _fetch_pubchem(self, query: str, query_type: str) -> Optional[dict]:
        """从PubChem API获取化学品数据（通过kb_manager）"""
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from kb_manager import PubChemFetcher
            fetcher = PubChemFetcher()
            cas = query if query_type == "cas" else ""
            name = query if query_type == "name" else ""
            data = fetcher.get_all_data(cas or name, alt_name=name)
            return data
        except Exception:
            return None

    def _extract_kb_evidence(self, data: dict, pool: FactPool):
        """从KB数据中提取证据"""
        pool.cas = data.get("cas_number", "")
        pool.name_cn = data.get("chemical_name_cn", "")
        pool.name_en = data.get("chemical_name_en", "")

        # 基础身份字段
        identity_fields = [
            ("cas_number", "cas_number"),
            ("chemical_name_cn", "chemical_name_cn"),
            ("chemical_name_en", "chemical_name_en"),
            ("molecular_formula", "molecular_formula"),
            ("molecular_weight", "molecular_weight"),
            ("un_number", "un_number"),
            ("ec_number", "ec_number"),
            ("iupac_name", "iupac_name"),
        ]

        for data_key, field_name in identity_fields:
            val = data.get(data_key)
            if val:
                pool.add_evidence(field_name, Evidence(
                    field_name=field_name,
                    value=val,
                    source="local_kb",
                    source_type=SourcePriority.LOCAL_KB,
                    confidence=0.8,
                ))

        # 理化性质字段（含KB别名映射）
        phys_field_aliases = [
            ("flash_point", "flash_point"),
            ("boiling_point", "boiling_point"),
            ("melting_point", "melting_point"),
            ("density", "density"),
            ("vapor_pressure", "vapor_pressure"),
            ("autoignition_temp", "autoignition_temp"),
            ("explosion_limits", "explosion_limits"),
            ("solubility_details", "solubility_details"),
            ("solubility", "solubility"),            # KB直接存solubility
            ("partition_coefficient_n-octanol_water", "partition_coefficient_n-octanol_water"),
            ("partition_coefficient_log_kow", "partition_coefficient_n-octanol_water"),  # DEF-001: LLM推算别名
            ("xlogp", "xlogp"),                       # KB存xlogp (辛醇水分配系数)
            ("appearance", "appearance"),
            ("odor", "odor"),
            ("ph_value", "ph_value"),
            ("decomposition_temperature", "decomposition_temperature"),
        ]
        for data_key, field_name in phys_field_aliases:
            val = data.get(data_key)
            if val:
                pool.add_evidence(field_name, Evidence(
                    field_name=field_name,
                    value=val,
                    source="local_kb",
                    source_type=SourcePriority.LOCAL_KB,
                    confidence=0.75,
                ))

        # 毒理学字段（含KB中文别名）
        tox_field_aliases = [
            ("ld50_oral", "ld50_oral"),
            ("ld50_dermal", "ld50_dermal"),
            ("lc50_inhalation", "lc50_inhalation"),
            ("skin_corrosion_category", "skin_corrosion_category"),
            ("皮肤腐蚀类别", "skin_corrosion_category"),     # KB中文别名
            ("eye_damage_category", "eye_damage_category"),
            ("眼损伤类别", "eye_damage_category"),            # KB中文别名
            ("skin_sensitization", "skin_sensitization"),
            ("mutagenicity", "mutagenicity"),
            ("carcinogenicity_ghs", "carcinogenicity_ghs"),
            ("reproductive_toxicity_category", "reproductive_toxicity_category"),
            ("stot_single_exposure", "stot_single_exposure"),
            ("stot_repeated_exposure", "stot_repeated_exposure"),
            ("IARC致癌分类", "carcinogenicity_iarc"),          # KB中文别名
            ("carcinogenicity_iarc", "carcinogenicity_iarc"),   # 英文标准key
        ]
        for data_key, field_name in tox_field_aliases:
            val = data.get(data_key)
            if val:
                pool.add_evidence(field_name, Evidence(
                    field_name=field_name,
                    value=val,
                    source="local_kb",
                    source_type=SourcePriority.LOCAL_KB,
                    confidence=0.7,
                ))

        # 职业接触限值
        oel_fields = ["pc_twa", "pc_stel", "acgih_tlv_twa", "acgih_tlv_stel"]
        for f in oel_fields:
            val = data.get(f)
            if val:
                pool.add_evidence(f, Evidence(
                    field_name=f,
                    value=val,
                    source="local_kb",
                    source_type=SourcePriority.LOCAL_KB,
                    confidence=0.8,
                ))

        # GHS分类
        ghs = data.get("ghs_classifications", [])
        if isinstance(ghs, list) and ghs:
            pool.add_evidence("ghs_classifications", Evidence(
                field_name="ghs_classifications",
                value=ghs,
                source="local_kb",
                source_type=SourcePriority.LOCAL_KB,
                confidence=0.8,
            ))

        # 信号词
        signal = data.get("signal_word")
        if signal:
            pool.add_evidence("signal_word", Evidence(
                field_name="signal_word",
                value=signal,
                source="local_kb",
                source_type=SourcePriority.LOCAL_KB,
                confidence=0.85,
            ))

        # H码
        h_codes = data.get("hazard_statements", [])
        if isinstance(h_codes, list) and h_codes:
            pool.add_evidence("hazard_statements", Evidence(
                field_name="hazard_statements",
                value=h_codes,
                source="local_kb",
                source_type=SourcePriority.LOCAL_KB,
                confidence=0.8,
            ))

        # 运输信息
        transport_fields = [
            "transport_class", "transport_class_name",
            "packing_group", "marine_pollutant",
        ]
        for f in transport_fields:
            val = data.get(f)
            if val:
                pool.add_evidence(f, Evidence(
                    field_name=f,
                    value=val,
                    source="local_kb",
                    source_type=SourcePriority.LOCAL_KB,
                    confidence=0.75,
                ))

        # 生态信息（含KB中文别名）
        eco_field_aliases = [
            ("ecotoxicity_fish_lc50", "ecotoxicity_fish_lc50"),
            ("ecotoxicity_daphnia_ec50", "ecotoxicity_daphnia_ec50"),
            ("ecotoxicity_algae_ec50", "ecotoxicity_algae_ec50"),
            ("persistence_degradability", "persistence_degradability"),
            ("生物降解性", "persistence_degradability"),        # KB中文别名
            ("bioaccumulation_bcf", "bioaccumulation_bcf"),
            ("BCF生物富集系数", "bioaccumulation_bcf"),         # KB中文别名
            ("bioaccumulation_log_bc", "bioaccumulation_log_bc"),
            ("mobility_in_soil", "mobility_in_soil"),
            ("Koc土壤迁移系数", "mobility_in_soil"),            # KB中文别名
        ]
        for data_key, field_name in eco_field_aliases:
            val = data.get(data_key)
            if val:
                pool.add_evidence(field_name, Evidence(
                    field_name=field_name,
                    value=val,
                    source="local_kb",
                    source_type=SourcePriority.LOCAL_KB,
                    confidence=0.7,
                ))

        # 理化辅助字段 — 已合并到phys_field_aliases中，此处保留appearance/odor的独立提取以防遗漏
        # (已在上方phys_field_aliases中包含)

        # 反应性与安全
        reactive_fields = [
            "incompatible_materials", "hazardous_decomposition",
            "firefighting_notes", "extinguishing_media_prohibited",
        ]
        for f in reactive_fields:
            val = data.get(f)
            if val:
                pool.add_evidence(f, Evidence(
                    field_name=f,
                    value=val,
                    source="local_kb",
                    source_type=SourcePriority.LOCAL_KB,
                    confidence=0.75,
                ))

        # 复合字段（字典类型）
        for dict_field in ["first_aid_notes", "toxicology_notes"]:
            val = data.get(dict_field)
            if val and isinstance(val, dict):
                pool.add_evidence(dict_field, Evidence(
                    field_name=dict_field,
                    value=val,
                    source="local_kb",
                    source_type=SourcePriority.LOCAL_KB,
                    confidence=0.75,
                ))

        # P码（完整版）
        p_codes = data.get("precautionary_codes_full")
        if p_codes and isinstance(p_codes, dict):
            pool.add_evidence("precautionary_codes_full", Evidence(
                field_name="precautionary_codes_full",
                value=p_codes,
                source="local_kb",
                source_type=SourcePriority.LOCAL_KB,
                confidence=0.8,
            ))

    def _detect_conflicts(self, pool: FactPool):
        """检测字段冲突"""
        for field_name, evs in pool.evidences.items():
            if len(evs) <= 1:
                continue

            # 检查值是否一致
            values = set()
            for ev in evs:
                val_str = str(ev.value).strip()
                # 标准化数值比较
                numeric = re.search(r'[\d.]+', val_str)
                if numeric:
                    values.add(numeric.group())
                else:
                    values.add(val_str)

            if len(values) > 1:
                for ev in evs:
                    ev.conflict = True
                pool.conflicts.append({
                    "field": field_name,
                    "values": [(ev.value, ev.source) for ev in evs],
                    "resolution": "取最高优先级来源",
                })

    def _identify_missing(self, pool: FactPool):
        """识别缺失的关键字段"""
        required_fields = [
            "cas_number", "chemical_name_cn", "molecular_formula",
            "molecular_weight", "ghs_classifications", "flash_point",
            "boiling_point", "ld50_oral", "un_number",
        ]
        for f in required_fields:
            if not pool.evidences.get(f):
                pool.missing_fields.append(f)

    def get_coverage(self, pool: FactPool) -> float:
        """计算数据覆盖率"""
        required = [
            "cas_number", "chemical_name_cn", "molecular_formula",
            "molecular_weight", "ghs_classifications", "flash_point",
            "boiling_point", "ld50_oral", "un_number",
            "density", "melting_point", "autoignition_temp",
        ]
        filled = sum(1 for f in required if pool.evidences.get(f))
        return filled / len(required) if required else 0.0


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python evidence_fusion.py <CAS号或化学名>")
        sys.exit(1)

    query = sys.argv[1]
    retriever = EvidenceRetriever()
    pool = retriever.retrieve(query)

    print(f"检索结果: {pool.name_cn} ({pool.name_en}) CAS:{pool.cas}")
    print(f"字段覆盖: {len(pool.evidences)} 个字段")
    print(f"覆盖率: {retriever.get_coverage(pool)*100:.0f}%")
    print(f"冲突: {len(pool.conflicts)}")
    print(f"缺失: {pool.missing_fields}")

    if pool.conflicts:
        print("\n冲突字段:")
        for c in pool.conflicts:
            print(f"  {c['field']}: {c['values']}")

    print(f"\n证据详情:")
    for field, evs in pool.evidences.items():
        best = pool.get_best(field)
        conf = "HIGH" if best.confidence >= 0.8 else ("MED" if best.confidence >= 0.6 else "LOW")
        src = best.source
        print(f"  [{conf}] {field}: {best.value} (from {src})")
