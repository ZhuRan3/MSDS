"""
混合物GHS分类计算器
化安通 (HuaAnTong) MSDS自动生成系统

功能：
1. ATE加和公式计算混合物急性毒性
2. 浓度限值/切割值判断（皮肤腐蚀、眼损伤等）
3. GHS分类换算表
4. 未知毒性成分处理
5. 桥接原则辅助判断

数据来源：UN GHS紫皮书、ECHA、OSHA、GB 30000系列

用法：
python mixture_calculator.py --input mixture.json
python mixture_calculator.py --components "乙醇:64-17-5:30" "甲醇:67-56-1:30" "丙酮:67-64-1:15" "丙三醇:56-81-5:25"
"""

import json
import sys
import math
import re
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

# ============================================================
# GHS分类常量表
# ============================================================

# 急性毒性分类换算表（口服/经皮/吸入）
# 当只知道GHS分类不知道具体LD50时，用此表换算ATE值
ACUTE_TOXITY_CONVERSION = {
    "oral": {
        1: {"ld50_range": (0, 5), "ate": 0.5, "h_code": "H300", "signal": "危险"},
        2: {"ld50_range": (5, 50), "ate": 5, "h_code": "H300", "signal": "危险"},
        3: {"ld50_range": (50, 300), "ate": 100, "h_code": "H301", "signal": "危险"},
        4: {"ld50_range": (300, 2000), "ate": 500, "h_code": "H302", "signal": "警告"},
        5: {"ld50_range": (2000, 5000), "ate": 2500, "h_code": "H303", "signal": "警告"},
    },
    "dermal": {
        1: {"ld50_range": (0, 50), "ate": 5, "h_code": "H310", "signal": "危险"},
        2: {"ld50_range": (50, 200), "ate": 50, "h_code": "H310", "signal": "危险"},
        3: {"ld50_range": (200, 1000), "ate": 300, "h_code": "H311", "signal": "危险"},
        4: {"ld50_range": (1000, 2000), "ate": 1100, "h_code": "H312", "signal": "警告"},
        5: {"ld50_range": (2000, 5000), "ate": 2500, "h_code": "H313", "signal": "警告"},
    },
    "inhalation_gas": {
        1: {"lc50_range": (0, 100), "ate": 10, "h_code": "H330", "signal": "危险"},
        2: {"lc50_range": (100, 500), "ate": 100, "h_code": "H330", "signal": "危险"},
        3: {"lc50_range": (500, 2500), "ate": 700, "h_code": "H331", "signal": "危险"},
        4: {"lc50_range": (2500, 20000), "ate": 4500, "h_code": "H332", "signal": "警告"},
        5: {"lc50_range": (20000, 50000), "ate": 25000, "h_code": "H333", "signal": "警告"},
    },
    "inhalation_vapor": {
        1: {"lc50_range": (0, 0.5), "ate": 0.05, "h_code": "H330", "signal": "危险"},
        2: {"lc50_range": (0.5, 2.0), "ate": 0.5, "h_code": "H330", "signal": "危险"},
        3: {"lc50_range": (2.0, 10.0), "ate": 3, "h_code": "H331", "signal": "危险"},
        4: {"lc50_range": (10.0, 20.0), "ate": 11, "h_code": "H332", "signal": "警告"},
        5: {"lc50_range": (20.0, 50.0), "ate": 25, "h_code": "H333", "signal": "警告"},
    },
    "inhalation_dust": {
        1: {"lc50_range": (0, 0.05), "ate": 0.005, "h_code": "H330", "signal": "危险"},
        2: {"lc50_range": (0.05, 0.5), "ate": 0.05, "h_code": "H330", "signal": "危险"},
        3: {"lc50_range": (0.5, 1.0), "ate": 0.5, "h_code": "H331", "signal": "危险"},
        4: {"lc50_range": (1.0, 5.0), "ate": 1.5, "h_code": "H332", "signal": "警告"},
        5: {"lc50_range": (5.0, 10.0), "ate": 5, "h_code": "H333", "signal": "警告"},
    },
}

# 急性毒性分类阈值（根据计算出的ATE值判断混合物分类）
ACUTE_TOXITY_THRESHOLDS = {
    "oral": [(5, 1), (50, 2), (300, 3), (2000, 4), (5000, 5)],
    "dermal": [(50, 1), (200, 2), (1000, 3), (2000, 4), (5000, 5)],
    "inhalation_gas": [(100, 1), (500, 2), (2500, 3), (20000, 4)],
    "inhalation_vapor": [(0.5, 1), (2.0, 2), (10.0, 3), (20.0, 4)],
    "inhalation_dust": [(0.05, 1), (0.5, 2), (1.0, 3), (5.0, 4)],
}

# 浓度限值表 - 皮肤腐蚀/刺激
SKIN_CORROSION_LIMITS = [
    {"component_class": "皮肤腐蚀 Cat 1A", "threshold": 5.0, "mixture_class": "皮肤腐蚀 Cat 1"},
    {"component_class": "皮肤腐蚀 Cat 1B", "threshold": 5.0, "mixture_class": "皮肤腐蚀 Cat 1"},
    {"component_class": "皮肤腐蚀 Cat 1C", "threshold": 5.0, "mixture_class": "皮肤腐蚀 Cat 1"},
    {"component_class": "皮肤腐蚀 Cat 1A", "threshold": 1.0, "mixture_class": "皮肤刺激 Cat 2", "note": "≥1%但<5%"},
    {"component_class": "皮肤腐蚀 Cat 1B", "threshold": 1.0, "mixture_class": "皮肤刺激 Cat 2", "note": "≥1%但<5%"},
    {"component_class": "皮肤腐蚀 Cat 1C", "threshold": 1.0, "mixture_class": "皮肤刺激 Cat 2", "note": "≥1%但<5%"},
    {"component_class": "皮肤刺激 Cat 2", "threshold": 10.0, "mixture_class": "皮肤刺激 Cat 2"},
    {"component_class": "皮肤刺激 Cat 2", "threshold": 1.0, "mixture_class": "考虑分类", "note": "≥1%但<10%"},
]

# 浓度限值表 - 严重眼损伤/眼刺激
EYE_DAMAGE_LIMITS = [
    {"component_class": "严重眼损伤 Cat 1", "threshold": 3.0, "mixture_class": "严重眼损伤 Cat 1"},
    {"component_class": "眼刺激 Cat 2A", "threshold": 10.0, "mixture_class": "眼刺激 Cat 2A"},
    {"component_class": "眼刺激 Cat 2A", "threshold": 1.0, "mixture_class": "考虑分类", "note": "≥1%但<10%"},
]

# 非加和危害类别及其浓度限值通用规则（SCL未指定时使用通用切割值0.1%）
NON_ADDITIVE_HAZARDS = {
    "呼吸致敏 Cat 1": {"generic_cut_off": 0.1, "h_code": "H334"},
    "皮肤致敏 Cat 1": {"generic_cut_off": 0.1, "h_code": "H317"},
    "生殖细胞致突变 Cat 1A": {"generic_cut_off": 0.1, "h_code": "H340"},
    "生殖细胞致突变 Cat 1B": {"generic_cut_off": 0.1, "h_code": "H340"},
    "生殖细胞致突变 Cat 2": {"generic_cut_off": 1.0, "h_code": "H341"},
    "致癌性 Cat 1A": {"generic_cut_off": 0.1, "h_code": "H350"},
    "致癌性 Cat 1B": {"generic_cut_off": 0.1, "h_code": "H350"},
    "致癌性 Cat 2": {"generic_cut_off": 1.0, "h_code": "H351"},
    "生殖毒性 Cat 1A": {"generic_cut_off": 0.1, "h_code": "H360"},
    "生殖毒性 Cat 1B": {"generic_cut_off": 0.1, "h_code": "H360"},
    "生殖毒性 Cat 2": {"generic_cut_off": 0.3, "h_code": "H361"},
    "STOT-单次 Cat 1": {"generic_cut_off": 1.0, "h_code": "H370"},
    "STOT-单次 Cat 2": {"generic_cut_off": 1.0, "h_code": "H371"},
    "STOT-反复 Cat 1": {"generic_cut_off": 1.0, "h_code": "H372"},
    "STOT-反复 Cat 2": {"generic_cut_off": 1.0, "h_code": "H373"},
    "吸入危害 Cat 1": {"generic_cut_off": 1.0, "h_code": "H304"},
}


# ============================================================
# 数据类
# ============================================================

@dataclass
class Component:
    """混合物组分"""
    name: str                # 中文名
    name_en: str = ""        # 英文名
    cas: str = ""            # CAS号
    concentration: float = 0.0  # 浓度(%)
    # 毒性数据（优先使用实验值）
    ld50_oral: Optional[float] = None      # 经口LD50 (mg/kg)
    ld50_dermal: Optional[float] = None    # 经皮LD50 (mg/kg)
    lc50_inhalation: Optional[float] = None  # 吸入LC50 (mg/L 或 ppm)
    # GHS分类（当无实验值时用于换算ATE）
    ghs_classifications: List[str] = field(default_factory=list)
    # 其他属性
    flash_point: Optional[float] = None    # 闪点 (°C)
    boiling_point: Optional[float] = None  # 沸点 (°C)
    initial_boiling_point: Optional[float] = None  # 初沸点 (°C)
    is_unknown_toxicity: bool = False      # 是否未知毒性


@dataclass
class MixtureResult:
    """混合物计算结果"""
    # ATE计算结果
    ate_oral: Optional[float] = None
    ate_dermal: Optional[float] = None
    ate_inhalation: Optional[float] = None
    # GHS分类结果
    classifications: List[Dict] = field(default_factory=list)
    # H码汇总
    h_codes: List[str] = field(default_factory=list)
    # 信号词
    signal_word: str = ""
    # 易燃性
    flammability_class: str = ""
    # 未知毒性比例
    unknown_percentage: float = 0.0
    # P码
    p_codes: Dict[str, List[str]] = field(default_factory=dict)
    # 计算过程记录
    calculation_log: List[str] = field(default_factory=list)


# ============================================================
# 核心计算引擎
# ============================================================

class MixtureCalculator:
    """混合物GHS分类计算器"""

    def __init__(self, components: List[Component]):
        self.components = components
        self.result = MixtureResult()
        self._validate_components()

    def _validate_components(self):
        """验证组分数据有效性"""
        total = sum(c.concentration for c in self.components)
        if abs(total - 100.0) > 1.0:
            self.result.calculation_log.append(
                f"⚠ 浓度总和为{total:.1f}%，不等于100%，请检查"
            )
        for c in self.components:
            if c.concentration <= 0:
                raise ValueError(f"组分 {c.name} 浓度必须>0")

    @staticmethod
    def _infer_inhalation_form(component: Component) -> str:
        """根据组分物理属性推断吸入形式: gas/vapor/dust"""
        bp = component.boiling_point or component.initial_boiling_point
        # 气体: 沸点很低(通常 < -10°C)
        if bp is not None and bp < -10:
            return "inhalation_gas"
        # 蒸汽: 液体(有沸点且 > -10°C) 或有闪点(液态易燃)
        if bp is not None and bp >= -10:
            return "inhalation_vapor"
        if component.flash_point is not None:
            return "inhalation_vapor"
        # 检查外观描述
        appearance = getattr(component, 'appearance', '') or ''
        if any(kw in appearance for kw in ['气体', '气态']):
            return "inhalation_gas"
        if any(kw in appearance for kw in ['固体', '粉末', '结晶', '颗粒']):
            return "inhalation_dust"
        if any(kw in appearance for kw in ['液体', '溶液']):
            return "inhalation_vapor"
        # 默认: 蒸汽(最常见场景)
        return "inhalation_vapor"

    def _get_ate(self, component: Component, route: str) -> Optional[float]:
        """获取组分的ATE值（优先实验值，其次GHS分类换算）"""
        # 优先使用实验值
        if route == "oral" and component.ld50_oral:
            return component.ld50_oral
        if route == "dermal" and component.ld50_dermal:
            return component.ld50_dermal
        if route == "inhalation" and component.lc50_inhalation:
            return component.lc50_inhalation

        # 从GHS分类换算
        conversion_map = {
            "oral": "急性毒性-经口",
            "dermal": "急性毒性-经皮",
            "inhalation": "急性毒性-吸入",
        }
        target_prefix = conversion_map.get(route, "")

        for cls_str in component.ghs_classifications:
            if target_prefix in cls_str:
                # 提取分类号，支持 "Cat 4" 和 "类别4" 两种格式
                try:
                    cat_str = cls_str
                    # 先尝试 Cat 格式
                    if "Cat" in cat_str:
                        cat_num = int(cat_str.split("Cat")[-1].strip().split()[0])
                    elif "类别" in cat_str:
                        cat_num = int(re.search(r'类别\s*(\d+)', cat_str).group(1))
                    else:
                        continue
                    if route == "inhalation":
                        table_key = self._infer_inhalation_form(component)
                    else:
                        table_key = route
                    table = ACUTE_TOXITY_CONVERSION.get(table_key, {})
                    if cat_num in table:
                        ate = table[cat_num]["ate"]
                        self.result.calculation_log.append(
                            f"  {component.name}: 无实验值，从'{cls_str}'换算ATE={ate} (形式: {table_key})"
                        )
                        return ate
                except (ValueError, IndexError, AttributeError):
                    continue

        return None

    def calculate_ate(self, route: str = "oral") -> Optional[float]:
        """
        计算混合物ATE值（加和公式）
        1/ATE_mix = Σ(Ci/ATEi)
        """
        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append(f"ATE加和公式计算 - {route}")
        self.result.calculation_log.append(f"{'='*60}")

        unknown_total = sum(c.concentration for c in self.components if c.is_unknown_toxicity)
        self.result.unknown_percentage = unknown_total

        sum_reciprocal = 0.0
        contributing = []

        for c in self.components:
            if c.is_unknown_toxicity:
                self.result.calculation_log.append(
                    f"  {c.name}({c.concentration}%): 未知毒性，跳过"
                )
                continue

            ate = self._get_ate(c, route)
            if ate is None:
                self.result.calculation_log.append(
                    f"  {c.name}({c.concentration}%): 无ATE数据，跳过"
                )
                continue

            ci = c.concentration / 100.0
            reciprocal = ci / ate
            sum_reciprocal += reciprocal
            contributing.append((c.name, c.concentration, ate, reciprocal))
            self.result.calculation_log.append(
                f"  {c.name}: {c.concentration}%/{ate} = {ci}/{ate} = {reciprocal:.6f}"
            )

        if not contributing:
            self.result.calculation_log.append("  无有效组分数据，无法计算")
            return None

        # 未知毒性>10%时使用修正公式
        if unknown_total > 10.0:
            self.result.calculation_log.append(
                f"\n  未知毒性成分={unknown_total}% > 10%，使用修正公式"
            )
            correction = 1.0 / (1.0 - unknown_total / 100.0)
            sum_reciprocal *= correction
            self.result.calculation_log.append(
                f"  修正系数: 1/(1-{unknown_total/100:.2f}) = {correction:.4f}"
            )

        if sum_reciprocal <= 0:
            return None

        ate_mix = 1.0 / sum_reciprocal

        self.result.calculation_log.append(f"\n  Σ(Ci/ATEi) = {sum_reciprocal:.6f}")
        self.result.calculation_log.append(f"  ATE_mix = 1/{sum_reciprocal:.6f} = {ate_mix:.1f} mg/kg")

        return ate_mix

    def classify_acute_toxicity(self, ate: float, route: str,
                                  inhalation_form: str = "") -> Optional[Dict]:
        """根据ATE值判断急性毒性分类"""
        if route == "inhalation" and inhalation_form:
            threshold_key = inhalation_form
        elif route == "inhalation":
            threshold_key = "inhalation_vapor"  # 默认蒸汽
        else:
            threshold_key = route
        thresholds = ACUTE_TOXITY_THRESHOLDS.get(threshold_key, [])
        for threshold, cat in thresholds:
            if ate <= threshold:
                table = ACUTE_TOXITY_CONVERSION.get(threshold_key, {})
                info = table.get(cat, {})
                # 计算置信度: ATE距阈值越远置信度越高
                confidence = min(0.95, 0.7 + 0.25 * (1.0 - ate / threshold))
                basis = {
                    "method": "ate_formula",
                    "rule_reference": "UN GHS 3.1.3",
                    "ate_value": round(ate, 2),
                    "threshold": threshold,
                    "route": route,
                }
                # 路由名称中文映射
                _route_cn = {"oral": "经口", "dermal": "经皮", "inhalation": "吸入"}
                route_cn = _route_cn.get(route, route)
                return {
                    "hazard": f"急性毒性-{route_cn}，类别{cat}",
                    "category": cat,
                    "h_code": info.get("h_code", ""),
                    "signal": info.get("signal", "警告"),
                    "ate": ate,
                    "route": route,
                    "classification_confidence": round(confidence, 2),
                    "classification_basis": basis,
                }
        # ATE > 5000，不分类
        return None

    def check_skin_corrosion(self) -> List[Dict]:
        """检查皮肤腐蚀/刺激（浓度限值法）"""
        results = []
        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append("皮肤腐蚀/刺激浓度限值检查")
        self.result.calculation_log.append(f"{'='*60}")

        cat1_conc = 0.0  # 皮肤腐蚀Cat1组分总浓度
        cat2_conc = 0.0  # 皮肤刺激Cat2组分总浓度

        for c in self.components:
            for cls_str in c.ghs_classifications:
                if "皮肤腐蚀" in cls_str and "Cat 1" in cls_str:
                    cat1_conc += c.concentration
                    self.result.calculation_log.append(
                        f"  {c.name}({c.concentration}%): {cls_str}"
                    )
                elif "皮肤刺激" in cls_str and "Cat 2" in cls_str:
                    cat2_conc += c.concentration
                    self.result.calculation_log.append(
                        f"  {c.name}({c.concentration}%): {cls_str}"
                    )

        if cat1_conc >= 5.0:
            results.append({
                "hazard": "皮肤腐蚀/刺激，类别1",
                "h_code": "H314",
                "signal": "危险",
                "reason": f"皮肤腐蚀Cat1组分总浓度{cat1_conc:.1f}%≥5%",
                "classification_confidence": 0.9,
                "classification_basis": {"method": "concentration_limit", "rule_reference": "UN GHS 3.2.3", "threshold": 5.0, "actual": round(cat1_conc, 1)},
            })
            self.result.calculation_log.append(f"  → 皮肤腐蚀Cat1组分总浓度{cat1_conc:.1f}%≥5% → Cat 1")
        elif cat1_conc >= 1.0:
            results.append({
                "hazard": "皮肤腐蚀/刺激，类别2",
                "h_code": "H315",
                "signal": "警告",
                "reason": f"皮肤腐蚀Cat1组分总浓度{cat1_conc:.1f}%≥1%但<5%",
                "classification_confidence": 0.7,
                "classification_basis": {"method": "concentration_limit", "rule_reference": "UN GHS 3.2.3", "threshold": 1.0, "actual": round(cat1_conc, 1)},
            })
            self.result.calculation_log.append(f"  → 皮肤腐蚀Cat1组分总浓度{cat1_conc:.1f}%，≥1%但<5% → Cat 2")

        if cat2_conc >= 10.0:
            results.append({
                "hazard": "皮肤腐蚀/刺激，类别2",
                "h_code": "H315",
                "signal": "警告",
                "reason": f"皮肤刺激Cat2组分总浓度{cat2_conc:.1f}%≥10%",
                "classification_confidence": 0.9,
                "classification_basis": {"method": "concentration_limit", "rule_reference": "UN GHS 3.2.3", "threshold": 10.0, "actual": round(cat2_conc, 1)},
            })
            self.result.calculation_log.append(f"  → 皮肤刺激Cat2组分总浓度{cat2_conc:.1f}%≥10% → Cat 2")

        if not results:
            self.result.calculation_log.append("  → 无触发")

        return results

    def check_eye_damage(self) -> List[Dict]:
        """检查严重眼损伤/眼刺激（浓度限值法）"""
        results = []
        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append("严重眼损伤/眼刺激浓度限值检查")
        self.result.calculation_log.append(f"{'='*60}")

        cat1_conc = 0.0
        cat2a_conc = 0.0

        for c in self.components:
            for cls_str in c.ghs_classifications:
                if "严重眼损伤" in cls_str and "Cat 1" in cls_str and "眼刺激" not in cls_str:
                    cat1_conc += c.concentration
                    self.result.calculation_log.append(
                        f"  {c.name}({c.concentration}%): {cls_str}"
                    )
                elif "眼损伤" in cls_str and "Cat 1" in cls_str:
                    cat1_conc += c.concentration
                    self.result.calculation_log.append(
                        f"  {c.name}({c.concentration}%): {cls_str}"
                    )
                elif "眼刺激" in cls_str and ("Cat 2A" in cls_str or "Cat 2" in cls_str):
                    cat2a_conc += c.concentration
                    self.result.calculation_log.append(
                        f"  {c.name}({c.concentration}%): {cls_str}"
                    )

        if cat1_conc >= 3.0:
            results.append({
                "hazard": "严重眼损伤/眼刺激，类别1",
                "h_code": "H318",
                "signal": "危险",
                "reason": f"严重眼损伤Cat1组分总浓度{cat1_conc:.1f}%≥3%",
                "classification_confidence": 0.9,
                "classification_basis": {"method": "concentration_limit", "rule_reference": "UN GHS 3.3.3", "threshold": 3.0, "actual": round(cat1_conc, 1)},
            })
            self.result.calculation_log.append(f"  → 严重眼损伤Cat1组分总浓度{cat1_conc:.1f}%≥3% → Cat 1")

        if cat2a_conc >= 10.0:
            results.append({
                "hazard": "严重眼损伤/眼刺激，类别2A",
                "h_code": "H319",
                "signal": "警告",
                "reason": f"眼刺激Cat2A组分总浓度{cat2a_conc:.1f}%≥10%",
                "classification_confidence": 0.9,
                "classification_basis": {"method": "concentration_limit", "rule_reference": "UN GHS 3.3.3", "threshold": 10.0, "actual": round(cat2a_conc, 1)},
            })
            self.result.calculation_log.append(f"  → 眼刺激Cat2A组分总浓度{cat2a_conc:.1f}%≥10% → Cat 2A")
        elif cat2a_conc >= 1.0 and not results:
            results.append({
                "hazard": "严重眼损伤/眼刺激，类别2A（考虑分类）",
                "h_code": "H319",
                "signal": "警告",
                "reason": f"眼刺激Cat2A组分总浓度{cat2a_conc:.1f}%≥1%但<10%，需进一步评估",
                "classification_confidence": 0.6,
                "classification_basis": {"method": "concentration_limit", "rule_reference": "UN GHS 3.3.3", "threshold": 1.0, "actual": round(cat2a_conc, 1)},
            })
            self.result.calculation_log.append(f"  → 眼刺激Cat2A组分总浓度{cat2a_conc:.1f}%，≥1%但<10% → 考虑分类")

        if not results:
            self.result.calculation_log.append("  → 无触发")

        return results

    def check_non_additive_hazards(self) -> List[Dict]:
        """检查非加和危害（浓度限值法）"""
        results = []
        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append("非加和危害浓度限值检查")
        self.result.calculation_log.append(f"{'='*60}")

        for hazard_type, info in NON_ADDITIVE_HAZARDS.items():
            cut_off = info["generic_cut_off"]
            h_code = info["h_code"]
            total_conc = 0.0
            triggering = []

            for c in self.components:
                for cls_str in c.ghs_classifications:
                    if hazard_type in cls_str or self._hazard_match(cls_str, hazard_type):
                        total_conc += c.concentration
                        triggering.append(f"{c.name}({c.concentration}%)")

            if total_conc >= cut_off:
                # 标准化hazard名称为中文GHS格式
                display_name = hazard_type
                display_name = display_name.replace(" Cat ", "，类别")
                display_name = display_name.replace("STOT-单次", "特异性靶器官毒性-一次接触")
                display_name = display_name.replace("STOT-反复", "特异性靶器官毒性-反复接触")
                results.append({
                    "hazard": display_name,
                    "h_code": h_code,
                    "signal": "危险" if "Cat 1" in hazard_type else "警告",
                    "reason": f"总浓度{total_conc:.1f}%≥{cut_off}% (触发组分: {', '.join(triggering)})",
                    "classification_confidence": 0.6,
                    "classification_basis": {"method": "generic_cutoff", "rule_reference": "UN GHS 1.3.3", "cut_off": cut_off, "actual": round(total_conc, 1)},
                })
                self.result.calculation_log.append(
                    f"  {hazard_type}: 总浓度{total_conc:.1f}%≥{cut_off}% → 触发"
                )
            elif total_conc > 0:
                self.result.calculation_log.append(
                    f"  {hazard_type}: 总浓度{total_conc:.1f}%<{cut_off}% → 未触发"
                )

        return results

    def _hazard_match(self, cls_str: str, hazard_type: str) -> bool:
        """模糊匹配危害分类 — 支持中英文双格式"""
        # 标准化后直接子串匹配
        normalized = _normalize_ghs_for_matching(cls_str)
        if hazard_type in normalized:
            return True
        # 关键词匹配
        keywords = hazard_type.replace(" Cat", "").split()
        if all(kw in normalized for kw in keywords):
            return True
        return False

    def check_flammability(self) -> Optional[Dict]:
        """检查易燃性"""
        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append("易燃性检查")
        self.result.calculation_log.append(f"{'='*60}")

        flammable_conc = 0.0
        flash_points = []

        for c in self.components:
            for cls_str in c.ghs_classifications:
                if "易燃" in cls_str:
                    flammable_conc += c.concentration
                    self.result.calculation_log.append(
                        f"  {c.name}({c.concentration}%): {cls_str}"
                    )
                    break
            if c.flash_point is not None:
                flash_points.append((c.name, c.flash_point))

        if flammable_conc < 10.0:
            self.result.calculation_log.append(f"  → 易燃组分总浓度{flammable_conc:.1f}%<10%，不分类")
            return None

        # FIX-flashpoint: 水溶液中低浓度有机物不应分类为易燃
        water_conc = sum(c.concentration for c in self.components
                        if c.name == "水" or "水" in c.name)
        if water_conc > 60 and flammable_conc < 20:
            self.result.calculation_log.append(
                f"  → 水溶液中有机物浓度低(易燃{flammable_conc:.0f}%/水{water_conc:.0f}%)，"
                f"实际闪点>60°C，不分类为易燃")
            return None

        # 取最低闪点为混合物闪点参考，同时取最低初沸点
        if flash_points:
            min_fp = min(flash_points, key=lambda x: x[1])
            # 获取最低初沸点
            initial_bps = [(c.name, c.initial_boiling_point) for c in self.components if c.initial_boiling_point is not None]
            min_ibp = min(initial_bps, key=lambda x: x[1]) if initial_bps else None
            ibp_val = min_ibp[1] if min_ibp else None

            self.result.calculation_log.append(
                f"  → 易燃组分总浓度{flammable_conc:.1f}%≥10%"
            )
            self.result.calculation_log.append(
                f"  → 最低闪点组分: {min_fp[0]} ({min_fp[1]}°C)"
            )
            if ibp_val is not None:
                self.result.calculation_log.append(
                    f"  → 最低初沸点组分: {min_ibp[0]} ({ibp_val}°C)"
                )

            if min_fp[1] < 23:
                # Cat 1: 闪点<23°C 且 初沸点<=35°C (H224)
                # Cat 2: 闪点<23°C 且 初沸点>35°C  (H225)
                if ibp_val is not None and ibp_val <= 35:
                    classification = "易燃液体，类别1"
                    h_code = "H224"
                    ibp_note = f"，初沸点{ibp_val}°C<=35°C"
                else:
                    classification = "易燃液体，类别2"
                    h_code = "H225"
                    ibp_note = (f"，初沸点{ibp_val}°C>35°C" if ibp_val is not None
                                else "，初沸点数据缺失，默认Cat2")
            elif min_fp[1] < 60:
                classification = "易燃液体，类别3"
                h_code = "H226"
                ibp_note = ""
            else:
                classification = "易燃液体，类别4" if min_fp[1] <= 93 else ""
                h_code = "H227" if min_fp[1] <= 93 else ""
                ibp_note = ""

            if classification:
                confidence = 0.9 if (ibp_val is not None and min_fp[1] < 23) else 0.75
                return {
                    "hazard": classification,
                    "h_code": h_code,
                    "signal": "危险",
                    "reason": f"易燃组分总浓度{flammable_conc:.1f}%，最低闪点参考{min_fp[1]}°C{ibp_note}",
                    "flash_point_ref": min_fp[1],
                    "initial_boiling_point_ref": ibp_val,
                    "classification_confidence": confidence,
                    "classification_basis": {"method": "flash_point_based", "rule_reference": "UN GHS 2.6", "flash_point": min_fp[1], "initial_boiling_point": ibp_val},
                }

        # 有易燃组分但无闪点数据
        return {
            "hazard": "易燃液体（需进一步确认分类）",  # noqa: 保留待确认标记
            "h_code": "H225/H226",
            "signal": "危险",
            "reason": f"易燃组分总浓度{flammable_conc:.1f}%≥10%，但缺少闪点数据",
            "classification_confidence": 0.5,
            "classification_basis": {"method": "flash_point_based", "rule_reference": "UN GHS 2.6", "note": "缺少闪点数据"},
        }

    def check_oxidizer(self) -> Optional[Dict]:
        """检查氧化性（GB/T 30000.14 / UN GHS 2.13）"""
        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append("氧化性检查")
        self.result.calculation_log.append(f"{'='*60}")

        oxidizer_conc = 0.0
        oxidizer_names = []

        for c in self.components:
            for cls_str in c.ghs_classifications:
                if "氧化" in cls_str:
                    oxidizer_conc += c.concentration
                    oxidizer_names.append(c.name)
                    self.result.calculation_log.append(
                        f"  {c.name}({c.concentration}%): {cls_str}"
                    )
                    break

        if oxidizer_conc < 1.0:
            self.result.calculation_log.append(
                f"  → 氧化性组分总浓度{oxidizer_conc:.1f}%<1%，不分类")
            return None

        # 确定氧化性类别（取最高类别组分）— 同时匹配中文"类别X"和英文"Cat X"
        best_cat = 3  # 默认最低
        for c in self.components:
            for cls_str in c.ghs_classifications:
                if "氧化" in cls_str:
                    if "类别1" in cls_str or "Cat 1" in cls_str:
                        best_cat = min(best_cat, 1)
                    elif "类别2" in cls_str or "Cat 2" in cls_str:
                        best_cat = min(best_cat, 2)
                    elif "类别3" in cls_str or "Cat 3" in cls_str:
                        best_cat = min(best_cat, 3)

        cat_label = f"类别{best_cat}"
        # GHS H码: Cat1→H271, Cat2→H272, Cat3→H272（GHS无H273）
        h_code_map = {1: "H271", 2: "H272", 3: "H272"}
        h_code = h_code_map[best_cat]
        is_liquid = any("液体" in cls for c in self.components for cls in c.ghs_classifications if "氧化" in cls)
        medium = "液体" if is_liquid else "固体"
        classification = f"氧化性{medium}，{cat_label}"

        self.result.calculation_log.append(
            f"  → 氧化性组分总浓度{oxidizer_conc:.1f}%≥1%: {classification}")

        return {
            "hazard": classification,
            "h_code": h_code,
            "signal": "危险" if best_cat <= 2 else "警告",
            "reason": f"氧化性组分总浓度{oxidizer_conc:.1f}%≥1%",
            "classification_confidence": 0.85,
            "classification_basis": {
                "method": "oxidizer_concentration",
                "rule_reference": "UN GHS 2.13",
                "oxidizer_concentration": oxidizer_conc,
                "oxidizer_components": oxidizer_names,
            },
        }

    def calculate_all(self) -> MixtureResult:
        """执行全部计算"""
        self.result.calculation_log.append("=" * 60)
        self.result.calculation_log.append("混合物GHS分类计算报告")
        self.result.calculation_log.append("=" * 60)
        self.result.calculation_log.append("组分列表:")
        for c in self.components:
            self.result.calculation_log.append(
                f"  {c.name} ({c.cas}): {c.concentration}%"
                + (f", LD50经口={c.ld50_oral}" if c.ld50_oral else "")
                + (f", 未知毒性" if c.is_unknown_toxicity else "")
            )

        # 1. 急性毒性 - 经口
        ate_oral = self.calculate_ate("oral")
        if ate_oral:
            self.result.ate_oral = ate_oral
            cls = self.classify_acute_toxicity(ate_oral, "oral")
            if cls:
                self.result.classifications.append(cls)
                self.result.calculation_log.append(
                    f"  → 分类结果: {cls['hazard']}, {cls['h_code']}, {cls['ate']:.1f} mg/kg"
                )
            else:
                self.result.calculation_log.append(f"  → ATE={ate_oral:.1f} mg/kg > 5000，不分类")

        # 2. 急性毒性 - 经皮
        ate_dermal = self.calculate_ate("dermal")
        if ate_dermal:
            self.result.ate_dermal = ate_dermal
            cls = self.classify_acute_toxicity(ate_dermal, "dermal")
            if cls:
                self.result.classifications.append(cls)

        # 3. 急性毒性 - 吸入（根据主要组分推断物理形式）
        ate_inhalation = self.calculate_ate("inhalation")
        if ate_inhalation:
            self.result.ate_inhalation = ate_inhalation
            # 确定主要吸入形式（取浓度最高的组分的物理形式）
            best_form = "inhalation_vapor"
            max_conc = 0.0
            for c in self.components:
                if not c.is_unknown_toxicity and c.concentration > max_conc:
                    form = self._infer_inhalation_form(c)
                    max_conc = c.concentration
                    best_form = form
            cls = self.classify_acute_toxicity(ate_inhalation, "inhalation",
                                                inhalation_form=best_form)
            if cls:
                self.result.classifications.append(cls)
                self.result.calculation_log.append(
                    f"  → 吸入分类({best_form}): {cls['hazard']}, ATE={cls['ate']:.2f} mg/L"
                )
            else:
                self.result.calculation_log.append(
                    f"  → 吸入ATE={ate_inhalation:.2f}，不分类 (形式: {best_form})"
                )

        # 4. 皮肤腐蚀/刺激
        skin_results = self.check_skin_corrosion()
        self.result.classifications.extend(skin_results)

        # 4. 眼损伤
        eye_results = self.check_eye_damage()
        self.result.classifications.extend(eye_results)

        # 5. 非加和危害
        non_additive_results = self.check_non_additive_hazards()
        self.result.classifications.extend(non_additive_results)

        # 6. 易燃性
        flam_result = self.check_flammability()
        if flam_result:
            self.result.classifications.append(flam_result)
            self.result.flammability_class = flam_result["hazard"]

        # 7. 氧化性
        oxidizer_result = self.check_oxidizer()
        if oxidizer_result:
            self.result.classifications.append(oxidizer_result)

        # 8. 水生环境危害
        aquatic_results = self.check_aquatic_toxicity()
        self.result.classifications.extend(aquatic_results)

        # 9. 金属腐蚀
        corrosion_result = self.check_metal_corrosion()
        if corrosion_result:
            self.result.classifications.append(corrosion_result)

        # 10. 桥接原则评估
        bridging = self.check_bridging_principles()
        if bridging:
            self.result.calculation_log.append(f"\n{'='*60}")
            self.result.calculation_log.append("桥接原则评估")
            self.result.calculation_log.append(f"{'='*60}")
            for bp in bridging:
                self.result.calculation_log.append(
                    f"  {bp['principle']}: 适用={bp['applicable']}, {bp.get('note', '')}"
                )

        # GHS分类覆盖规则：高等级覆盖低等级
        # Cat1覆盖Cat2A（眼损伤），Cat1覆盖Cat2（皮肤腐蚀）
        self._apply_classification_hierarchy()

        # 汇总
        self._summarize()

        return self.result

    def check_aquatic_toxicity(self) -> List[Dict]:
        """检查水生环境危害（M因子加权求和法，UN GHS 4.1.3）"""
        results = []
        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append("水生环境危害检查（M因子求和法）")
        self.result.calculation_log.append(f"{'='*60}")

        # 收集水生危害组分及其分类
        aquatic_components = []
        for c in self.components:
            for cls_str in c.ghs_classifications:
                if "水生" in cls_str or "水环境" in cls_str:
                    cat = ""
                    if "急性" in cls_str and "Cat 1" in cls_str:
                        cat = "急性1"
                    elif "急性" in cls_str and "Cat 2" in cls_str:
                        cat = "急性2"
                    elif "长期" in cls_str and "Cat 1" in cls_str:
                        cat = "长期1"
                    elif "长期" in cls_str and "Cat 2" in cls_str:
                        cat = "长期2"
                    elif "长期" in cls_str and "Cat 3" in cls_str:
                        cat = "长期3"

                    if cat:
                        # M因子：默认为1，从组分属性读取（如果有）
                        m_factor = getattr(c, 'm_factor', 1) or 1
                        aquatic_components.append({
                            "name": c.name,
                            "conc": c.concentration,
                            "cat": cat,
                            "m": m_factor,
                            "cls": cls_str,
                        })
                        self.result.calculation_log.append(
                            f"  {c.name}({c.concentration}%): {cls_str}, M={m_factor}"
                        )

        if not aquatic_components:
            self.result.calculation_log.append("  -> 无水生危害组分")
            return results

        # M因子加权求和法（UN GHS 4.1.3）
        # Σ(Ci × Mi) / 100
        # 长期Cat1: Σ(C×M)/100 >= 0.1 → 长期Cat1; >= 0.01 → 长期Cat2
        # 长期Cat2: Σ(C×M)/100 >= 0.25 → 长期Cat2
        # 急性Cat1: Σ(C×M)/100 >= 0.25 → 急性Cat1; >= 0.025 → 急性Cat2

        long_cat1_sum = sum(a["conc"] * a["m"] for a in aquatic_components if "长期1" in a["cat"]) / 100
        long_cat2_sum = sum(a["conc"] * a["m"] for a in aquatic_components if "长期2" in a["cat"]) / 100
        acute_cat1_sum = sum(a["conc"] * a["m"] for a in aquatic_components if "急性1" in a["cat"]) / 100

        self.result.calculation_log.append(f"  长期Cat1 Σ(Ci×Mi)/100 = {long_cat1_sum:.4f}")
        self.result.calculation_log.append(f"  长期Cat2 Σ(Ci×Mi)/100 = {long_cat2_sum:.4f}")
        self.result.calculation_log.append(f"  急性Cat1 Σ(Ci×Mi)/100 = {acute_cat1_sum:.4f}")

        # 长期危害判定
        if long_cat1_sum >= 0.1:
            results.append({
                "hazard": "危害水生环境-长期危害，类别1",
                "h_code": "H410",
                "signal": "警告",
                "reason": f"Σ(Ci×Mi)/100={long_cat1_sum:.3f}>=0.1",
                "classification_confidence": 0.8,
                "classification_basis": {"method": "M-factor_summation", "rule_reference": "UN GHS 4.1.3",
                                          "cat1_weighted_sum": round(long_cat1_sum, 4)},
            })
            self.result.calculation_log.append(f"  -> 长期Cat1 (Σ={long_cat1_sum:.3f}>=0.1)")
        elif long_cat1_sum >= 0.01 or long_cat2_sum >= 0.25:
            results.append({
                "hazard": "危害水生环境-长期危害，类别2",
                "h_code": "H411",
                "signal": "警告",
                "reason": f"Cat1加权Σ={long_cat1_sum:.3f}，Cat2加权Σ={long_cat2_sum:.3f}",
                "classification_confidence": 0.7,
                "classification_basis": {"method": "M-factor_summation", "rule_reference": "UN GHS 4.1.3",
                                          "cat1_weighted_sum": round(long_cat1_sum, 4),
                                          "cat2_weighted_sum": round(long_cat2_sum, 4)},
            })
            self.result.calculation_log.append(f"  -> 长期Cat2")

        # 急性危害判定
        if acute_cat1_sum >= 0.25:
            results.append({
                "hazard": "危害水生环境-急性危害，类别1",
                "h_code": "H400",
                "signal": "警告",
                "reason": f"Σ(Ci×Mi)/100={acute_cat1_sum:.3f}>=0.25",
                "classification_confidence": 0.8,
                "classification_basis": {"method": "M-factor_summation", "rule_reference": "UN GHS 4.1.3",
                                          "acute_weighted_sum": round(acute_cat1_sum, 4)},
            })
            self.result.calculation_log.append(f"  -> 急性Cat1")

        if not results:
            self.result.calculation_log.append("  -> 各组分加权浓度未达触发阈值")

        return results

    def check_bridging_principles(self) -> List[Dict]:
        """
        桥接原则评估（简化实现）

        桥接原则用于当混合物整体数据不可用时，利用已知相关混合物的分类结果推断。
        参考: UN GHS 第1.4章 桥接原则
        """
        results = []

        # 稀释原则: 如果已分类混合物被低危害稀释剂稀释，分类不变或降级
        non_hazardous = []
        hazardous = []
        for c in self.components:
            has_hazard = bool(c.ghs_classifications) or c.flash_point is not None
            if has_hazard:
                hazardous.append(c)
            else:
                non_hazardous.append(c)

        if non_hazardous and hazardous:
            non_hz_conc = sum(c.concentration for c in non_hazardous)
            results.append({
                "principle": "稀释原则",
                "applicable": True,
                "note": f"含{len(non_hazardous)}种非危害成分(总{non_hz_conc:.1f}%)，可考虑稀释效应",
                "confidence": 0.6,
                "basis": {"method": "dilution", "rule_reference": "UN GHS 1.4.2.1",
                          "non_hazardous_pct": round(non_hz_conc, 1)},
            })
        else:
            results.append({
                "principle": "稀释原则",
                "applicable": False,
                "note": "无非危害稀释成分",
                "confidence": 0.0,
            })

        # 批次原则: 标记为可复用（需要外部提供历史批次信息）
        results.append({
            "principle": "批次原则",
            "applicable": False,
            "note": "需外部提供历史批次分类数据方可应用",
            "confidence": 0.0,
            "basis": {"method": "batching", "rule_reference": "UN GHS 1.4.3"},
        })

        # 插值原则: 需要两个已分类混合物A和B，当前混合物C介于两者之间
        results.append({
            "principle": "插值原则",
            "applicable": False,
            "note": "需外部提供已分类的参照混合物数据方可应用",
            "confidence": 0.0,
            "basis": {"method": "interpolation", "rule_reference": "UN GHS 1.4.4"},
        })

        # 气雾剂原则: 如果非气雾形式已分类，气雾形式可等同
        # 检测组分中是否有推进剂
        propellant_keywords = ["丙烷", "丁烷", "异丁烷", "二氧化碳", "氮气", "氩气"]
        has_propellant = any(
            any(kw in c.name for kw in propellant_keywords)
            for c in self.components
        )
        if has_propellant:
            results.append({
                "principle": "气雾剂原则",
                "applicable": True,
                "note": "含推进剂成分，气雾形式分类可等同非气雾形式",
                "confidence": 0.7,
                "basis": {"method": "aerosol", "rule_reference": "UN GHS 1.4.7"},
            })

        return results

    def check_metal_corrosion(self) -> Optional[Dict]:
        """检查金属腐蚀"""
        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append("金属腐蚀检查")
        self.result.calculation_log.append(f"{'='*60}")

        for c in self.components:
            for cls_str in c.ghs_classifications:
                if "金属腐蚀" in cls_str or "腐蚀金属" in cls_str:
                    self.result.calculation_log.append(
                        f"  {c.name}({c.concentration}%): {cls_str}"
                    )
                    return {
                        "hazard": "金属腐蚀物，类别1",
                        "h_code": "H290",
                        "signal": "警告",
                        "reason": f"含金属腐蚀组分: {c.name}",
                        "classification_confidence": 0.8,
                        "classification_basis": {"method": "generic_cutoff", "rule_reference": "UN GHS 2.14", "component": c.name},
                    }

        self.result.calculation_log.append("  -> 无触发")
        return None

    def generate_p_codes(self) -> Dict[str, List[str]]:
        """根据所有分类结果生成P码"""
        ghs_path = Path(__file__).resolve().parent.parent / "db" / "ghs_mappings.json"
        p_mapping = {}
        if ghs_path.exists():
            with open(ghs_path, "r", encoding="utf-8") as f:
                ghs_data = json.load(f)
            p_mapping = ghs_data.get("hazard_class_to_p_codes", {})

        all_p = {"prevention": [], "response": [], "storage": [], "disposal": []}

        for cls in self.result.classifications:
            hazard = cls.get("hazard", "")
            # 精确匹配
            p_codes = p_mapping.get(hazard, {})

            # 模糊匹配
            if not p_codes:
                for key, val in p_mapping.items():
                    if key in hazard or any(kw in hazard for kw in key.split()):
                        p_codes = val
                        break

            for group in ["prevention", "response", "storage", "disposal"]:
                for code in p_codes.get(group, []):
                    if code not in all_p[group]:
                        all_p[group].append(code)

        return all_p

    def _apply_classification_hierarchy(self):
        """GHS分类覆盖规则：高等级覆盖低等级"""
        to_remove = set()
        hazards = [c.get("hazard", "") for c in self.result.classifications]

        # 眼损伤Cat1覆盖眼刺激Cat2A
        has_eye_cat1 = any("眼损伤" in h and ("类别1" in h or "Cat 1" in h) for h in hazards)
        if has_eye_cat1:
            for i, c in enumerate(self.result.classifications):
                h = c.get("hazard", "")
                if "眼刺激" in h and ("类别2A" in h or "Cat 2A" in h):
                    to_remove.add(i)

        # 皮肤腐蚀Cat1覆盖皮肤刺激Cat2
        has_skin_cat1 = any("皮肤腐蚀" in h and ("类别1" in h or "Cat 1" in h) for h in hazards)
        if has_skin_cat1:
            for i, c in enumerate(self.result.classifications):
                h = c.get("hazard", "")
                if "皮肤刺激" in h and ("类别2" in h or "Cat 2" in h) and "腐蚀" not in h:
                    to_remove.add(i)

        # STOT-反复Cat1覆盖Cat2（同一靶器官）
        stot_re_cat1_organs = set()
        for c in self.result.classifications:
            h = c.get("hazard", "")
            if "反复" in h and ("类别1" in h or "Cat 1" in h):
                # 提取靶器官
                organs = re.findall(r'[\(（]([^)）]+)[\)）]', h)
                for organ in organs:
                    stot_re_cat1_organs.update(organ.replace("，", ",").replace("、", ",").split(","))
        if stot_re_cat1_organs:
            for i, c in enumerate(self.result.classifications):
                h = c.get("hazard", "")
                if "反复" in h and ("类别2" in h or "Cat 2" in h):
                    cat2_organs = re.findall(r'[\(（]([^)）]+)[\)）]', h)
                    cat2_organ_set = set()
                    for organ in cat2_organs:
                        cat2_organ_set.update(organ.replace("，", ",").replace("、", ",").split(","))
                    if cat2_organ_set & stot_re_cat1_organs:
                        to_remove.add(i)

        if to_remove:
            self.result.classifications = [
                c for i, c in enumerate(self.result.classifications) if i not in to_remove
            ]
            self.result.calculation_log.append(
                f"  [覆盖规则] 移除{len(to_remove)}项被高等级覆盖的分类"
            )

    def _summarize(self):
        """汇总结果"""
        h_codes = []
        has_danger = False

        for cls in self.result.classifications:
            if cls.get("h_code"):
                # 去重
                code = cls["h_code"]
                if code not in h_codes:
                    h_codes.append(code)
            if cls.get("signal") == "危险":
                has_danger = True

        self.result.h_codes = h_codes
        self.result.signal_word = "危险" if has_danger else "警告"

        # 生成P码
        p_codes = self.generate_p_codes()
        if p_codes:
            # 把P码注入每个分类结果
            for cls in self.result.classifications:
                cls["p_codes"] = p_codes

        self.result.calculation_log.append(f"\n{'='*60}")
        self.result.calculation_log.append("分类汇总")
        self.result.calculation_log.append(f"{'='*60}")
        for cls in self.result.classifications:
            self.result.calculation_log.append(
                f"  • {cls['hazard']} | {cls.get('h_code', '')} | {cls.get('signal', '')}"
            )
            if cls.get("reason"):
                self.result.calculation_log.append(f"    原因: {cls['reason']}")
        self.result.calculation_log.append(f"\n信号词: {self.result.signal_word}")
        self.result.calculation_log.append(f"H码: {', '.join(self.result.h_codes)}")

    def to_json(self) -> str:
        """输出JSON格式结果"""
        return json.dumps(asdict(self.result), ensure_ascii=False, indent=2)

    def print_report(self):
        """打印文本格式报告"""
        for line in self.result.calculation_log:
            safe_line = line.replace('\u2022', '-').replace('\u26a0', '[!]').replace('\u2192', '->').replace('\u2265', '>=').replace('\u2264', '<=')
            try:
                print(safe_line)
            except UnicodeEncodeError:
                print(safe_line.encode('gbk', errors='replace').decode('gbk'))


# ============================================================
# 从知识库加载组分数据
# ============================================================

def load_component_from_kb(cas: str, name: str = "") -> Optional[Dict]:
    """从本地知识库加载化学品数据"""
    project_root = Path(__file__).resolve().parent.parent
    kb_file = project_root / "db" / "chemical_db.json"
    if not kb_file.exists():
        return None

    with open(kb_file, "r", encoding="utf-8") as f:
        kb = json.load(f)

    # KB是dict，key为CAS号
    if isinstance(kb, dict):
        if cas in kb:
            return kb[cas]
        # 按CAS号字段查找
        for key, entry in kb.items():
            if entry.get("cas_number") == cas:
                return entry
        # 按名称模糊查找（精确匹配优先，子串匹配其次）
        for key, entry in kb.items():
            cn = entry.get("chemical_name_cn", "")
            en = entry.get("chemical_name_en", "")
            if name and (name == cn or name == en):
                return entry
        for key, entry in kb.items():
            cn = entry.get("chemical_name_cn", "")
            en = entry.get("chemical_name_en", "")
            syns = entry.get("synonyms", [])
            if name and (name in cn or name in en):
                return entry
            if isinstance(syns, list) and name:
                for s in syns:
                    if name in str(s):
                        return entry
    elif isinstance(kb, list):
        for entry in kb:
            if entry.get("cas") == cas or entry.get("cas_number") == cas:
                return entry
            cn = entry.get("chemical_name_cn", "")
            en = entry.get("chemical_name_en", "")
            if name and (name in cn or name in en):
                return entry

    return None


def _parse_numeric(value) -> Optional[float]:
    """从字符串中提取数值，如 '7060 mg/kg（大鼠）' → 7060.0
    FIX-ATE: 优先提取mg/kg或mg/L前的数值（LD50/LC50场景），
    避免'LD50'中的数字'50'被误提取。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in ("-", "无数据", "无", "不适用"):
        return None
    import re
    s_clean = s.replace(',', '')
    # 优先匹配 mg/kg 或 mg/L 前面的数值
    m = re.search(r'([\d.]+)\s*mg/[kL]', s_clean)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    # 其次匹配范围值：取中间值（如 "1600-2000" → 1800）
    m = re.search(r'([\d.]+)\s*[-–—~～]\s*([\d.]+)', s_clean)
    if m:
        try:
            low, high = float(m.group(1)), float(m.group(2))
            return round((low + high) / 2, 1)
        except ValueError:
            pass
    # 最后：提取第一个独立的数值（跳过LD50/LC50中的数字）
    # 先移除LD50/LC50等标识符中的数字
    s_no_ld = re.sub(r'(?:LD|LC|EC)\d+', '', s_clean, flags=re.IGNORECASE)
    match = re.search(r'[\d.]+', s_no_ld)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def _normalize_ghs_for_matching(cls_str: str) -> str:
    """标准化GHS分类字符串，使中文格式匹配计算器内部检查格式。

    KB存储格式: "皮肤刺激 (类别 2)", "特异性靶器官毒性-反复接触 (类别 2, 肝脏)"
    计算器匹配: "皮肤刺激 Cat 2", "STOT-反复 Cat 2"
    """
    import re
    s = cls_str
    # 先提取括号内的类别编号并放到括号外，再移除括号
    # 处理 "皮肤腐蚀/刺激（类别1B）" → "皮肤腐蚀/刺激 类别1B"
    s = re.sub(r'[（(]\s*类别\s*(\d+[A-Za-z]?)\s*[）)]', r' Cat \1', s)
    # 处理剩余括号（器官限定符等）: "(呼吸道)" → 移除
    s = re.sub(r'[（(][^）)]*[）)]', '', s)
    # 标点统一：中文逗号→空格
    s = s.replace("，", " ").replace(",", " ")
    # "类别 2" / "类别2" / "类别 2A" → "Cat 2" / "Cat 2A"（处理不在括号中的情况）
    s = re.sub(r'类别\s*(\d+[A-Za-z]?)', r'Cat \1', s)
    # 中文全称 → 计算器缩写（DEF-002: 补充PubChem格式的别名）
    aliases = [
        ("特异性靶器官毒性-反复接触", "STOT-反复"),
        ("特异性靶器官毒性-单次接触", "STOT-单次"),
        ("特异性靶器官毒性-一次接触", "STOT-单次"),
        ("吸入危险", "吸入危害"),
        ("危害水生环境-急性危害", "水生环境-急性"),
        ("危害水生环境-长期危害", "水生环境-长期"),
        ("对水生环境有害-急性危害", "水生环境-急性"),
        ("对水生环境有害-长期危害", "水生环境-长期"),
        ("金属腐蚀物", "金属腐蚀"),
    ]
    for old, new in aliases:
        s = s.replace(old, new)
    s = re.sub(r'\s+', ' ', s)
    s = s.strip()
    return s


def build_component(name: str, cas: str, concentration: float) -> Component:
    """构建组分对象，尝试从知识库加载数据"""
    comp = Component(name=name, cas=cas, concentration=concentration)

    kb_data = load_component_from_kb(cas, name)
    if kb_data:
        comp.name_en = kb_data.get("chemical_name_en", "")
        comp.ld50_oral = _parse_numeric(kb_data.get("ld50_oral"))
        comp.ld50_dermal = _parse_numeric(kb_data.get("ld50_dermal"))
        comp.lc50_inhalation = _parse_numeric(kb_data.get("lc50_inhalation"))
        comp.flash_point = _parse_numeric(kb_data.get("flash_point"))
        comp.boiling_point = _parse_numeric(kb_data.get("boiling_point"))
        # 初沸点优先使用initial_boiling_point字段，否则用boiling_point近似
        comp.initial_boiling_point = _parse_numeric(kb_data.get("initial_boiling_point"))
        if comp.initial_boiling_point is None and comp.boiling_point is not None:
            comp.initial_boiling_point = comp.boiling_point

        # GHS分类列表 — 标准化为计算器匹配格式
        ghs = kb_data.get("ghs_classifications", [])
        if isinstance(ghs, list):
            comp.ghs_classifications = [_normalize_ghs_for_matching(str(g)) for g in ghs if g]
        elif isinstance(ghs, str):
            comp.ghs_classifications = [_normalize_ghs_for_matching(ghs)]

    return comp


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="混合物GHS分类计算器")
    parser.add_argument(
        "--components", nargs="+",
        help='组分列表，格式: "名称:CAS:浓度" (如 "乙醇:64-17-5:30")'
    )
    parser.add_argument(
        "--input", type=str,
        help="JSON输入文件路径"
    )
    parser.add_argument(
        "--output", type=str,
        help="JSON输出文件路径（可选）"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以JSON格式输出结果"
    )

    args = parser.parse_args()

    components = []

    if args.input:
        # 从JSON文件读取
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("components", []):
            comp = build_component(
                name=item.get("name", ""),
                cas=item.get("cas", ""),
                concentration=item.get("concentration", 0),
            )
            # JSON中可直接指定毒性数据
            if item.get("ld50_oral"):
                comp.ld50_oral = item["ld50_oral"]
            if item.get("ld50_dermal"):
                comp.ld50_dermal = item["ld50_dermal"]
            if item.get("flash_point"):
                comp.flash_point = item["flash_point"]
            if item.get("ghs_classifications"):
                comp.ghs_classifications = item["ghs_classifications"]
            if item.get("is_unknown_toxicity"):
                comp.is_unknown_toxicity = True
            components.append(comp)

    elif args.components:
        # 从命令行参数读取
        for comp_str in args.components:
            parts = comp_str.split(":")
            if len(parts) >= 3:
                comp = build_component(
                    name=parts[0],
                    cas=parts[1],
                    concentration=float(parts[2]),
                )
                # 可选: 第四个参数为LD50
                if len(parts) >= 4:
                    try:
                        comp.ld50_oral = float(parts[3])
                    except ValueError:
                        pass
                components.append(comp)
            else:
                print(f"⚠ 无法解析: {comp_str}，格式应为 名称:CAS:浓度")

    else:
        # 演示模式
        print("混合物GHS分类计算器 - 演示模式")
        print("示例: 乙醇30% + 甲醇30% + 丙酮15% + 丙三醇25%\n")
        components = [
            build_component("乙醇", "64-17-5", 30),
            build_component("甲醇", "67-56-1", 30),
            build_component("丙酮", "67-64-1", 15),
            build_component("丙三醇", "56-81-5", 25),
        ]

    if not components:
        print("错误: 未提供任何组分数据")
        sys.exit(1)

    # 计算
    calculator = MixtureCalculator(components)
    result = calculator.calculate_all()

    # 输出
    if args.json:
        output = calculator.to_json()
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"结果已保存到 {args.output}")
        else:
            print(output)
    else:
        calculator.print_report()
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(calculator.to_json())
            print(f"\nJSON结果已保存到 {args.output}")


if __name__ == "__main__":
    main()
