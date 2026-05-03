"""
MSDS审查器 - 化安通(HuaAnTong) MSDS质量审查
功能：审查生成的MSDS是否完整、准确、符合标准

用法：
python msds_reviewer.py --input "./Bycrt/phenol/MSDS_phenol_detailed.md"
"""

import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

# ============================================================
# MSDS审查规则
# ============================================================

class MSDSReviewer:
    """MSDS审查器"""

    @staticmethod
    def _load_h_codes_from_mappings():
        """DEF-005: 从ghs_mappings.json动态加载H-code映射"""
        mapping_path = Path(__file__).parent.parent / "db" / "ghs_mappings.json"
        if mapping_path.exists():
            with open(mapping_path, "r", encoding="utf-8") as f:
                mappings = json.load(f)
            # 将 hazard_class_to_h 反转为 h_code → [classification_names]
            h_to_class = {}
            for cls_name, h_code in mappings.get("hazard_class_to_h", {}).items():
                if h_code not in h_to_class:
                    h_to_class[h_code] = []
                h_to_class[h_code].append(cls_name)
            return h_to_class
        # fallback: 返回空映射
        return {}

    # 必须包含的16个部分
    REQUIRED_PARTS = [
        "第一部分：化学品及企业标识",
        "第二部分：危险性概述",
        "第三部分：成分/组成信息",
        "第四部分：急救措施",
        "第五部分：消防措施",
        "第六部分：泄漏应急处理",
        "第七部分：操作处置与储存",
        "第八部分：接触控制/个体防护",
        "第九部分：理化特性",
        "第十部分：稳定性和反应性",
        "第十一部分：毒理学信息",
        "第十二部分：生态学信息",
        "第十三部分：废弃处置",
        "第十四部分：运输信息",
        "第十五部分：法规信息",
        "第十六部分：其他信息"
    ]

    # GHS象形图对应关系
    GHS_PICTOGRAMS = {
        "火焰": "GHS02",
        "腐蚀": "GHS05",
        "感叹号": "GHS07",
        "健康危害": "GHS08",
        "爆炸": "GHS01",
        "氧化剂": "GHS03",
        "气瓶": "GHS04",
        "环境": "GHS09"
    }

    # H码验证规则（DEF-005: 动态从ghs_mappings.json加载）
    # 使用函数加载，避免staticmethod在类定义体中不可调用
    def _build_h_codes():
        mapping_path = Path(__file__).parent.parent / "db" / "ghs_mappings.json"
        if mapping_path.exists():
            with open(mapping_path, "r", encoding="utf-8") as f:
                mappings = json.load(f)
            h_to_class = {}
            for cls_name, h_code in mappings.get("hazard_class_to_h", {}).items():
                if h_code not in h_to_class:
                    h_to_class[h_code] = []
                h_to_class[h_code].append(cls_name)
            return h_to_class
        return {}
    H_CODES = _build_h_codes()

    def __init__(self, file_path: str = "", content: str = ""):
        self.file_path = Path(file_path) if file_path else Path("")
        self.content = content
        self.issues = []
        self.warnings = []

    @classmethod
    def from_content(cls, content: str) -> "MSDSReviewer":
        """从内存字符串创建审查器"""
        return cls(content=content)

    def review(self) -> Dict:
        """执行完整审查"""
        print(f"\n{'='*60}")
        print(f"化安通 MSDS审查")
        print(f"{'='*60}")

        # 如果已有content（from_content模式），跳过文件读取
        if not self.content:
            if self.file_path and self.file_path.exists():
                print(f"文件: {self.file_path}")
                self.content = self.file_path.read_text(encoding='utf-8')
            else:
                return {"status": "ERROR", "message": f"无审查内容"}

        if not self.content.strip():
            return {"status": "ERROR", "message": "内容为空"}

        results = {
            "status": "PASS",
            "completeness": self._check_completeness(),
            "ghs_consistency": self._check_ghs_consistency(),
            "data_consistency": self._check_data_consistency(),
            "format_compliance": self._check_format_compliance(),
            "professional_check": self._check_professional_knowledge(),
            "cross_section_consistency": self._check_cross_section_consistency(),
            "risk_assessment": self._check_risk_assessment(),
            "source_traceability": self._check_source_traceability(),
            "conflict_fields": self._check_conflict_fields(),
            "issues": self.issues,
            "warnings": self.warnings
        }

        # 综合判定
        failed_checks = []
        for key in ["completeness", "ghs_consistency", "data_consistency", "format_compliance",
                     "professional_check", "cross_section_consistency", "source_traceability"]:
            if results[key]["status"] == "FAIL":
                failed_checks.append(key)

        if failed_checks:
            results["status"] = "FAIL"
            results["failed_checks"] = failed_checks

        return results

    def _check_completeness(self) -> Dict:
        """检查16部分完整性"""
        print(f"\n[1/5] 检查完整性...")

        missing_parts = []
        for part in self.REQUIRED_PARTS:
            if part not in self.content:
                missing_parts.append(part)

        if missing_parts:
            self.issues.append(f"缺少部分: {', '.join(missing_parts)}")
            return {"status": "FAIL", "missing": missing_parts}

        return {"status": "PASS", "message": "16部分齐全"}

    def _check_ghs_consistency(self) -> Dict:
        """检查GHS分类一致性"""
        print(f"[2/5] 检查GHS一致性...")

        issues = []

        # 检查是否有GHS分类
        if "GHS" not in self.content and "象形图" not in self.content:
            issues.append("缺少GHS分类信息")

        # 检查H码与分类是否匹配
        hazard_section = self._extract_section("第二部分：危险性概述")
        if hazard_section:
            # 提取GHS分类（DEF-005: 扩展正则表达式支持更多格式）
            ghs_matches = re.findall(
                r'[\u4e00-\u9fa5/\-]+'                  # 中文名（含/和-）
                r'[，,\s]*'                               # 分隔符
                r'(?:类别|Cat\.?\s*)'                     # "类别" 或 "Cat" 或 "Cat."
                r'\d+[A-Z]?',                             # 类别号
                hazard_section
            )
            h_codes_found = re.findall(r'H\d{3}', hazard_section)

            # 验证H码存在
            if not h_codes_found:
                issues.append("缺少H码（危险说明）")

            # 验证象形图存在
            if "象形图" in hazard_section:
                pictogram_match = re.search(r'象形图[：:]\s*(.+?)(?:\n|$)', hazard_section)
                if pictogram_match:
                    pictograms = pictogram_match.group(1)
            else:
                issues.append("缺少象形图信息")

            # 验证H码与分类是否匹配
            for h_code, expected_classes in self.H_CODES.items():
                if h_code in hazard_section:
                    has_match = any(cls in hazard_section for cls in expected_classes)
                    if not has_match:
                        issues.append(f"H码{h_code}存在但未找到对应GHS分类: {expected_classes[0]}")
            # DEF-005: 标记未在映射中找到的H-code
            for h_code in h_codes_found:
                if h_code not in self.H_CODES:
                    self.warnings.append(f"H码{h_code}未在ghs_mappings.json中找到映射，需人工确认")

            # 检查P码存在性
            p_codes_found = re.findall(r'P\d{3}', self.content)
            if not p_codes_found:
                issues.append("缺少P码（防范说明）")

        if issues:
            self.issues.append(f"GHS问题: {'; '.join(issues)}")
            return {"status": "FAIL", "issues": issues}

        return {"status": "PASS", "message": "GHS分类一致"}

    def _check_data_consistency(self) -> Dict:
        """检查数据一致性"""
        print(f"[3/5] 检查数据一致性...")

        issues = []

        # 提取CAS号
        cas_matches = re.findall(r'CAS[号#]*[:：]?\s*(\d{2,3}-\d{2,7}(?:-\d+)?)', self.content)
        if cas_matches:
            unique_cas = set(cas_matches)
            if len(unique_cas) > 1:
                issues.append(f"CAS号不一致: {unique_cas}")

        # 检查分子式格式
        formula_matches = re.findall(r'分子式[：:]\s*([A-Za-z0-9]+)', self.content)
        for formula in formula_matches:
            if not re.match(r'^[A-Z][A-Z0-9]*$', formula):
                issues.append(f"分子式格式可疑: {formula}")

        # 检查UN编号格式
        un_matches = re.findall(r'UN\s*(\d{4})', self.content)
        if un_matches:
            for un in un_matches:
                if len(un) != 4:
                    issues.append(f"UN编号格式错误: {un}")

        if issues:
            self.issues.append(f"数据一致性问题: {'; '.join(issues)}")
            return {"status": "FAIL", "issues": issues}

        return {"status": "PASS", "message": "数据一致"}

    def _check_format_compliance(self) -> Dict:
        """检查格式规范性"""
        print(f"[4/5] 检查格式规范性...")

        issues = []

        # 检查标题格式
        expected_headers = [
            "## 第一部分：",
            "## 第二部分：",
            # ... 其他部分
        ]

        # 检查是否有SDS编号
        if "SDS编号" not in self.content:
            issues.append("缺少SDS编号")

        # 检查是否有版本信息
        if "版本" not in self.content:
            issues.append("缺少版本信息")

        # 检查是否有修订日期
        if "修订日期" not in self.content:
            issues.append("缺少修订日期")

        # 检查表格格式
        table_count = self.content.count("|")
        if table_count < 10:
            issues.append("表格数量过少，可能格式不规范")

        if issues:
            self.warnings.append(f"格式问题: {'; '.join(issues)}")
            return {"status": "WARN", "issues": issues}

        return {"status": "PASS", "message": "格式规范"}

    def _check_professional_knowledge(self) -> Dict:
        """检查专业知识"""
        print(f"[5/5] 检查专业知识...")

        issues = []
        warnings = []

        # 检查急救措施是否包含关键要素
        first_aid = self._extract_section("第四部分：急救措施")
        if first_aid:
            required_elements = ["就医", "冲洗"]
            # "脱去"仅对皮肤腐蚀品必须（精确匹配，避免误判含"腐蚀"字样的非腐蚀分类）
            sec2 = self._get_section_text(2)
            if "皮肤腐蚀" in sec2 or "金属腐蚀" in sec2:
                required_elements.append("脱去")
            for elem in required_elements:
                if elem not in first_aid:
                    issues.append(f"急救措施缺少关键要素: {elem}")

            # 检查是否有时间描述（至少应该提到分钟）
            if "分钟" not in first_aid and "15" not in first_aid:
                warnings.append("急救措施缺少具体时间描述")

        # 检查消防措施
        firefighting = self._extract_section("第五部分：消防措施")
        if firefighting:
            if "灭火剂" not in firefighting:
                issues.append("消防措施缺少灭火剂信息")
            if "禁止" not in firefighting and "禁止使用" not in firefighting:
                warnings.append("消防措施缺少禁用灭火剂信息")

        # 检查危险特性描述
        hazard = self._extract_section("第二部分：危险性概述")
        if hazard:
            if len(hazard) < 200:
                warnings.append("危险性概述描述过于简略")

        if issues:
            self.issues.append(f"专业知识问题: {'; '.join(issues)}")
            return {"status": "FAIL", "issues": issues}

        if warnings:
            self.warnings.extend(warnings)
            return {"status": "WARN", "warnings": warnings}

        return {"status": "PASS", "message": "专业知识检查通过"}

    def _extract_section(self, section_name: str) -> str:
        """提取指定部分的内容"""
        pattern = rf"{section_name}.*?(?=## |\Z)"
        match = re.search(pattern, self.content, re.DOTALL)
        return match.group(0) if match else ""

    def _check_cross_section_consistency(self) -> Dict:
        """检查节间一致性"""
        print(f"\n[6/8] 检查节间一致性...")
        issues = []
        c = self.content

        sec2_text = self._get_section_text(2)
        sec5_text = self._get_section_text(5)
        sec7_text = self._get_section_text(7)
        sec8_text = self._get_section_text(8)
        sec9_text = self._get_section_text(9)
        sec11_text = self._get_section_text(11)
        sec3_text = self._get_section_text(3)
        sec10_text = self._get_section_text(10)

        # 规则1: 易燃 → 灭火+闪点
        if "易燃" in sec2_text:
            if "灭火" not in sec5_text and "灭火剂" not in sec5_text:
                issues.append("第2节有易燃分类，但第5节缺少灭火建议")
            if "闪点" not in sec9_text:
                issues.append("第2节有易燃分类，但第9节缺少闪点数据")

        # 规则2: 腐蚀 → 防护（精确匹配皮肤腐蚀/金属腐蚀，避免误判）
        has_corrosion = "皮肤腐蚀" in sec2_text or "金属腐蚀" in sec2_text
        if has_corrosion:
            if "防护手套" not in sec8_text and "防护服" not in sec8_text:
                issues.append("第2节有腐蚀分类，但第8节缺少防护建议")

        # 规则3: 眼危害 → 眼防护
        if "眼刺激" in sec2_text or "眼损伤" in sec2_text:
            if "眼" not in sec8_text and "护目" not in sec8_text:
                issues.append("第2节有眼危害分类，但第8节缺少眼防护建议")

        # 规则4: 呼吸道 → 呼吸防护
        if "呼吸道" in sec2_text or "吸入" in sec2_text:
            if "呼吸" not in sec8_text:
                issues.append("第2节有呼吸道危害，但第8节缺少呼吸防护")

        # 规则5: 急性毒性 → LD50
        if "急性毒性" in sec2_text or "有毒" in sec2_text:
            if "LD50" not in sec11_text and "ld50" not in sec11_text.lower():
                self.warnings.append("第2节有急性毒性分类，但第11节缺少LD50数据")

        # 规则6: 闪点与易燃分类数值校验
        if "易燃" in sec2_text:
            # 提取第9节闪点数值
            fp_match = re.search(r'闪点[：:]\s*([-\d.]+)\s*°C', sec9_text)
            if fp_match:
                flash_point = float(fp_match.group(1))
                # Cat 1: fp < 23°C 且 bbp ≤ 35°C
                if "类别1" in sec2_text or "Cat 1" in sec2_text:
                    if flash_point >= 23:
                        issues.append(f"第2节易燃Cat1但第9节闪点{flash_point}°C >= 23°C，不一致")
                # Cat 2: fp < 23°C
                elif "类别2" in sec2_text or "Cat 2" in sec2_text:
                    if flash_point >= 23:
                        issues.append(f"第2节易燃Cat2但第9节闪点{flash_point}°C >= 23°C，不一致")
                # Cat 3: 23°C ≤ fp < 60°C
                elif "类别3" in sec2_text or "Cat 3" in sec2_text:
                    if flash_point < 23 or flash_point >= 60:
                        self.warnings.append(f"第2节易燃Cat3但第9节闪点{flash_point}°C不在23-60°C范围")

        # 规则7: LD50与急性毒性分类校验
        if "急性毒性" in sec2_text:
            ld50_match = re.search(r'LD50[^\d]*?([\d.]+)\s*mg/kg', sec11_text)
            if ld50_match:
                ld50 = float(ld50_match.group(1))
                if "类别1" in sec2_text or "Cat 1" in sec2_text:
                    if ld50 > 5:
                        self.warnings.append(f"第2节急性毒性Cat1但第11节LD50={ld50}mg/kg > 5mg/kg")
                elif "类别3" in sec2_text or "Cat 3" in sec2_text:
                    if ld50 > 300 or ld50 < 50:
                        self.warnings.append(f"第2节急性毒性Cat3但第11节LD50={ld50}mg/kg不在50-300范围")
                elif "类别4" in sec2_text or "Cat 4" in sec2_text:
                    if ld50 > 2000 or ld50 < 300:
                        self.warnings.append(f"第2节急性毒性Cat4但第11节LD50={ld50}mg/kg不在300-2000范围")

        status = "PASS" if not issues else "FAIL"
        print(f"  节间一致性: {status} ({len(issues)}个问题)")
        for issue in issues:
            print(f"    [!] {issue}")
            self.issues.append(issue)

        return {"status": status, "issues": issues}

    def _check_conflict_fields(self) -> Dict:
        """冲突字段校验 - 检查节间矛盾"""
        print(f"\n[9/10] 冲突字段校验...")
        issues = []
        c = self.content

        # 规则1: 第3节组分浓度之和应接近100%
        sec3 = self._get_section_text(3)
        if sec3:
            conc_matches = re.findall(r'\|\s*\d+(?:\.\d+)?\s*%\s*\|', sec3)
            if conc_matches:
                conc_values = re.findall(r'(\d+(?:\.\d+)?)\s*%', sec3)
                total = sum(float(v) for v in conc_values)
                if abs(total - 100.0) > 5.0 and total > 0:
                    issues.append(f"第3节组分浓度之和为{total:.1f}%，偏离100%超过5%")

        # 规则2: 第2节无急性毒性 → 第11节不应有低LD50值
        sec2 = self._get_section_text(2)
        sec11 = self._get_section_text(11)
        has_acute_tox = "急性毒性" in sec2
        if not has_acute_tox and sec11:
            low_ld50 = re.search(r'LD50[^\d]*?([\d.]+)\s*mg/kg', sec11)
            if low_ld50 and float(low_ld50.group(1)) < 500:
                issues.append(f"第2节无急性毒性分类，但第11节LD50={low_ld50.group(1)}mg/kg较低，应考虑分类")

        # 规则3: 第2节有皮肤腐蚀/金属腐蚀 → 第5节应有腐蚀相关消防建议
        if "皮肤腐蚀" in sec2 or "金属腐蚀" in sec2:
            sec5 = self._get_section_text(5)
            if sec5 and "腐蚀" not in sec5:
                issues.append("第2节有腐蚀分类，但第5节消防措施未提及腐蚀风险")

        # 规则4: 第2节有环境危害 → 第12节应有生态数据
        if "环境" in sec2 or "水生" in sec2 or "H400" in sec2 or "H410" in sec2 or "H411" in sec2:
            sec12 = self._get_section_text(12)
            if sec12 and "无可用数据" in sec12:
                issues.append("第2节有环境危害分类，但第12节显示无生态数据")

        status = "PASS" if not issues else "WARN"
        print(f"  冲突字段: {status} ({len(issues)}个问题)")
        for issue in issues:
            print(f"    [!] {issue}")
            self.warnings.append(issue)

        return {"status": status, "issues": issues}

    def _check_source_traceability(self) -> Dict:
        """来源追溯校验"""
        print(f"\n[8/9] 来源追溯校验...")
        issues = []
        c = self.content

        # 统计 [待确认] 标记
        unconfirmed_count = c.count("[待确认]")
        unconfirmed_lines = []
        for i, line in enumerate(c.split('\n'), 1):
            if "[待确认]" in line:
                unconfirmed_lines.append(f"L{i}: {line.strip()[:60]}")

        # 统计来源注释 <!-- src:... conf:... -->
        source_annotations = re.findall(r'<!--\s*src:(\w+)\s+conf:([\d.]+)\s*-->', c)
        sourced_fields = len(source_annotations)

        # 检查关键字段是否有数据（非[待确认]）
        critical_fields = [
            ("CAS", r'CAS[号#：:\s|]*\d{2,7}-\d{2}-\d'),
            ("分子式", r'分子式[*：:\s|]+[A-Za-z0-9]+'),
            ("GHS分类", r'(?:GHS|危险类别|危险性类别)'),
            ("闪点", r'闪点[*：:\s|]+[-\d.]'),
            ("LD50", r'LD50'),
        ]
        missing_critical = []
        for name, pattern in critical_fields:
            if not re.search(pattern, c):
                missing_critical.append(name)

        if missing_critical:
            issues.append(f"缺少关键字段: {', '.join(missing_critical)}")

        if unconfirmed_count > 10:
            issues.append(f"待确认字段过多({unconfirmed_count}个)，数据可靠性不足")

        status = "PASS" if not issues else "FAIL"
        if unconfirmed_count > 0 and unconfirmed_count <= 10:
            status = "WARN"

        print(f"  来源注释: {sourced_fields}个, 待确认: {unconfirmed_count}个")
        if missing_critical:
            print(f"  缺少关键字段: {missing_critical}")

        for issue in issues:
            self.issues.append(issue)

        return {
            "status": status,
            "unconfirmed_count": unconfirmed_count,
            "unconfirmed_lines": unconfirmed_lines[:10],
            "sourced_fields": sourced_fields,
            "missing_critical": missing_critical,
        }

    def _check_risk_assessment(self) -> Dict:
        """风险分级评估"""
        print(f"\n[7/8] 风险分级评估...")

        high_risk = []
        medium_risk = []
        c = self.content

        for kw in ["致癌", "致突变", "生殖毒性", "Cat 1", "致命", "剧毒"]:
            if kw in c:
                high_risk.append(f"文档包含高风险关键词: {kw}")

        for kw in ["腐蚀", "易燃液体，类别1", "易燃液体，类别2", "易燃液体 Cat 1", "易燃液体 Cat 2"]:
            if kw in c:
                medium_risk.append(f"文档包含中等风险分类: {kw}")

        low_risk_count = c.count("[待确认]")

        if high_risk:
            risk_level = "HIGH"
            suggestion = "必须人工复核所有高风险项"
        elif medium_risk:
            risk_level = "MEDIUM"
            suggestion = "建议人工确认中等风险项"
        elif low_risk_count > 5:
            risk_level = "MEDIUM"
            suggestion = f"有{low_risk_count}个待确认字段，建议补充数据"
        else:
            risk_level = "LOW"
            suggestion = "可自动通过，建议常规审核"

        print(f"  风险等级: {risk_level}")
        print(f"  高风险: {len(high_risk)}, 中风险: {len(medium_risk)}, 待确认: {low_risk_count}")
        print(f"  建议: {suggestion}")

        return {
            "status": "INFO",
            "risk_level": risk_level,
            "high_risk": high_risk,
            "medium_risk": medium_risk,
            "unconfirmed_count": low_risk_count,
            "suggestion": suggestion
        }

    def _get_section_text(self, section_num: int) -> str:
        """提取某个章节的文本"""
        pattern = f"第{self._cn_num(section_num)}部分"
        idx = self.content.find(pattern)
        if idx < 0:
            return ""
        next_idx = len(self.content)
        for i in range(section_num + 1, 17):
            next_pattern = f"第{self._cn_num(i)}部分"
            ni = self.content.find(next_pattern, idx + 10)
            if ni > 0:
                next_idx = ni
                break
        return self.content[idx:next_idx]

    def _cn_num(self, n: int) -> str:
        cn = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
               "十一", "十二", "十三", "十四", "十五", "十六"]
        return cn[n] if n < len(cn) else str(n)


def print_review_report(results: Dict):
    """打印审查报告"""
    print(f"\n{'='*60}")
    print(f"审查报告")
    print(f"{'='*60}")

    status = results.get("status", "UNKNOWN")
    pass_str = "PASS" if status == "PASS" else "FAIL" if status == "FAIL" else "WARN"
    print(f"\n综合判定: {pass_str}")

    checks = [
        ("完整性", results.get("completeness", {})),
        ("GHS一致性", results.get("ghs_consistency", {})),
        ("数据一致性", results.get("data_consistency", {})),
        ("格式规范性", results.get("format_compliance", {})),
        ("专业知识", results.get("professional_check", {}))
    ]

    for name, check in checks:
        check_status = check.get("status", "UNKNOWN")
        icon = "[PASS]" if check_status == "PASS" else "[FAIL]" if check_status == "FAIL" else "[WARN]"
        print(f"\n{icon} {name}: {check_status}")
        if check.get("message"):
            print(f"    {check['message']}")
        if check.get("issues"):
            for issue in check["issues"]:
                print(f"    - {issue}")

    if results.get("issues"):
        print(f"\n关键问题:")
        for issue in results["issues"]:
            print(f"  [FAIL] {issue}")

    if results.get("warnings"):
        print(f"\n警告:")
        for warn in results["warnings"]:
            print(f"  [WARN] {warn}")

    # 改进建议
    print(f"\n改进建议:")
    if status == "FAIL":
        print("  1. 补充缺失的MSDS部分")
        print("  2. 修正GHS分类与H码的对应关系")
        print("  3. 确保数据一致性（CAS号、分子式等）")
        print("  4. 加强急救措施和消防措施的详细程度")
    else:
        print("  1. 内容已较为完整，可进一步细化专业描述")
        print("  2. 确保所有数值来源于可靠数据源")

    print(f"\n{'='*60}")


def main():
    if len(sys.argv) < 2:
        print("用法: python msds_reviewer.py --input <MSDS文件路径>")
        print("示例: python msds_reviewer.py --input ../output/pure/MSDS_108_95_2_detailed.md")
        sys.exit(1)

    # 解析参数
    input_file = None
    if "--input" in sys.argv:
        idx = sys.argv.index("--input")
        input_file = sys.argv[idx + 1]

    if not input_file:
        print("错误: 请指定MSDS文件路径")
        sys.exit(1)

    reviewer = MSDSReviewer(input_file)
    results = reviewer.review()
    print_review_report(results)

    # 输出JSON格式（便于程序处理）
    print(f"\n--- JSON输出 ---")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()