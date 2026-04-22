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
                # 提取分类号，如 "急性毒性-经口 Cat 4" → 4
                try:
                    cat_num = int(cls_str.split("Cat")[-1].strip().split()[0])
                    table = ACUTE_TOXITY_CONVERSION.get(f"{route}" if route != "inhalation" else "inhalation_vapor", {})
                    if cat_num in table:
                        ate = table[cat_num]["ate"]
                        self.result.calculation_log.append(
                            f"  {component.name}: 无实验值，从'{cls_str}'换算ATE={ate} mg/kg"
                        )
                        return ate
                except (ValueError, IndexError):
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

    def classify_acute_toxicity(self, ate: float, route: str) -> Optional[Dict]:
        """根据ATE值判断急性毒性分类"""
        thresholds = ACUTE_TOXITY_THRESHOLDS.get(route, [])
        for threshold, cat in thresholds:
            if ate <= threshold:
                table = ACUTE_TOXITY_CONVERSION.get(
                    route if route != "inhalation" else "inhalation_vapor", {}
                )
                info = table.get(cat, {})
                return {
                    "hazard": f"急性毒性-{route} Cat {cat}",
                    "category": cat,
                    "h_code": info.get("h_code", ""),
                    "signal": info.get("signal", "警告"),
                    "ate": ate,
                    "route": route,
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
                "hazard": "皮肤腐蚀 Cat 1",
                "h_code": "H314",
                "signal": "危险",
                "reason": f"皮肤腐蚀Cat1组分总浓度{cat1_conc:.1f}%≥5%",
            })
            self.result.calculation_log.append(f"  → 皮肤腐蚀Cat1组分总浓度{cat1_conc:.1f}%≥5% → Cat 1")
        elif cat1_conc >= 1.0:
            results.append({
                "hazard": "皮肤刺激 Cat 2",
                "h_code": "H315",
                "signal": "警告",
                "reason": f"皮肤腐蚀Cat1组分总浓度{cat1_conc:.1f}%≥1%但<5%",
            })
            self.result.calculation_log.append(f"  → 皮肤腐蚀Cat1组分总浓度{cat1_conc:.1f}%，≥1%但<5% → Cat 2")

        if cat2_conc >= 10.0:
            results.append({
                "hazard": "皮肤刺激 Cat 2",
                "h_code": "H315",
                "signal": "警告",
                "reason": f"皮肤刺激Cat2组分总浓度{cat2_conc:.1f}%≥10%",
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
                "hazard": "严重眼损伤 Cat 1",
                "h_code": "H318",
                "signal": "危险",
                "reason": f"严重眼损伤Cat1组分总浓度{cat1_conc:.1f}%≥3%",
            })
            self.result.calculation_log.append(f"  → 严重眼损伤Cat1组分总浓度{cat1_conc:.1f}%≥3% → Cat 1")

        if cat2a_conc >= 10.0:
            results.append({
                "hazard": "眼刺激 Cat 2A",
                "h_code": "H319",
                "signal": "警告",
                "reason": f"眼刺激Cat2A组分总浓度{cat2a_conc:.1f}%≥10%",
            })
            self.result.calculation_log.append(f"  → 眼刺激Cat2A组分总浓度{cat2a_conc:.1f}%≥10% → Cat 2A")
        elif cat2a_conc >= 1.0 and not results:
            results.append({
                "hazard": "眼刺激 Cat 2A（考虑分类）",
                "h_code": "H319",
                "signal": "警告",
                "reason": f"眼刺激Cat2A组分总浓度{cat2a_conc:.1f}%≥1%但<10%，需进一步评估",
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
                results.append({
                    "hazard": hazard_type,
                    "h_code": h_code,
                    "signal": "危险" if "Cat 1" in hazard_type else "警告",
                    "reason": f"总浓度{total_conc:.1f}%≥{cut_off}% (触发组分: {', '.join(triggering)})",
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
        """模糊匹配危害分类"""
        # 简单包含匹配
        keywords = hazard_type.replace(" Cat", "").split()
        return all(kw in cls_str for kw in keywords)

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

        # 取最低闪点为混合物闪点参考
        if flash_points:
            min_fp = min(flash_points, key=lambda x: x[1])
            self.result.calculation_log.append(
                f"  → 易燃组分总浓度{flammable_conc:.1f}%≥10%"
            )
            self.result.calculation_log.append(
                f"  → 最低闪点组分: {min_fp[0]} ({min_fp[1]}°C)"
            )

            if min_fp[1] < 23:
                if flammable_conc >= 50:  # 初沸点≤35°C假设不满足时
                    classification = "易燃液体 Cat 2"
                    h_code = "H225"
                else:
                    classification = "易燃液体 Cat 2"
                    h_code = "H225"
            elif min_fp[1] < 60:
                classification = "易燃液体 Cat 3"
                h_code = "H226"
            else:
                classification = "易燃液体 Cat 4" if min_fp[1] <= 93 else ""
                h_code = "H227" if min_fp[1] <= 93 else ""

            if classification:
                return {
                    "hazard": classification,
                    "h_code": h_code,
                    "signal": "危险",
                    "reason": f"易燃组分总浓度{flammable_conc:.1f}%，最低闪点参考{min_fp[1]}°C",
                    "flash_point_ref": min_fp[1],
                }

        # 有易燃组分但无闪点数据
        return {
            "hazard": "易燃液体（需进一步确认分类）",
            "h_code": "H225/H226",
            "signal": "危险",
            "reason": f"易燃组分总浓度{flammable_conc:.1f}%≥10%，但缺少闪点数据",
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

        # 3. 皮肤腐蚀/刺激
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

        # 汇总
        self._summarize()

        return self.result

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
        # 按名称模糊查找
        for key, entry in kb.items():
            if name and (name in entry.get("name_cn", "") or name in entry.get("name_en", "")):
                return entry
    elif isinstance(kb, list):
        for entry in kb:
            if entry.get("cas") == cas:
                return entry
            if name and (name in entry.get("name_cn", "") or name in entry.get("name_en", "")):
                return entry

    return None


def _parse_numeric(value) -> Optional[float]:
    """从字符串中提取数值，如 '7060 mg/kg（大鼠）' → 7060.0"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in ("-", "无数据", "无", "不适用"):
        return None
    import re
    match = re.search(r'[\d.]+', s.replace(',', ''))
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


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

        # GHS分类列表
        ghs = kb_data.get("ghs_classifications", [])
        if isinstance(ghs, list):
            comp.ghs_classifications = [str(g) for g in ghs if g]
        elif isinstance(ghs, str):
            comp.ghs_classifications = [ghs]

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
