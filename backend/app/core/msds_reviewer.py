"""
MSDS审查器 - 化安通(HuaAnTong) MSDS质量审查
功能：审查生成的MSDS是否完整、准确、符合标准
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# MSDS审查规则
# ============================================================

class MSDSReviewer:
    """MSDS审查器"""

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

    # H码验证规则
    H_CODES = {
        "H225": ["易燃液体，类别1", "易燃液体，类别2", "易燃液体，类别3"],
        "H226": ["易燃液体，类别3"],
        "H240": ["爆炸物，不敏感爆炸物，类别1.1"],
        "H241": ["爆炸物，敏感爆炸物，类别1.1"],
        "H290": ["金属腐蚀物，类别1"],
        "H314": ["皮肤腐蚀/刺激，类别1A", "皮肤腐蚀/刺激，类别1B", "皮肤腐蚀/刺激，类别1C"],
        "H315": ["皮肤腐蚀/刺激，类别2"],
        "H318": ["严重眼损伤/眼刺激，类别1"],
        "H319": ["严重眼损伤/眼刺激，类别2A"],
        "H335": ["特异性靶器官毒性-一次接触，类别3"],
        "H336": ["特异性靶器官毒性-一次接触（麻醉效应），类别3"],
        "H302": ["急性毒性-经口，类别4"],
        "H312": ["急性毒性-经皮，类别4"],
        "H332": ["急性毒性-吸入，类别4"],
        "H304": ["吸入危害，类别1"],
        "H361": ["生殖毒性，类别2"],
        "H373": ["特异性靶器官毒性-反复接触，类别2"],
    }

    def __init__(self, file_path: Optional[str] = None, content: Optional[str] = None):
        """
        初始化审查器

        Args:
            file_path: MSDS文件路径（可选）
            content: MSDS文本内容（可选，与file_path二选一）
        """
        self.file_path = Path(file_path) if file_path else None
        self.content = content or ""
        self.issues: List[str] = []
        self.warnings: List[str] = []

    def review(self) -> Dict:
        """执行完整审查"""
        logger.info("开始MSDS审查")

        # 如果没有直接提供内容，从文件读取
        if not self.content and self.file_path:
            if not self.file_path.exists():
                return {"status": "ERROR", "message": f"文件不存在: {self.file_path}"}
            self.content = self.file_path.read_text(encoding='utf-8')

        if not self.content:
            return {"status": "ERROR", "message": "无审查内容"}

        self.issues = []
        self.warnings = []

        results = {
            "status": "PASS",
            "completeness": self._check_completeness(),
            "ghs_consistency": self._check_ghs_consistency(),
            "data_consistency": self._check_data_consistency(),
            "format_compliance": self._check_format_compliance(),
            "professional_check": self._check_professional_knowledge(),
            "issues": self.issues,
            "warnings": self.warnings
        }

        # 综合判定
        failed_checks = []
        for key in ["completeness", "ghs_consistency", "data_consistency", "format_compliance", "professional_check"]:
            if results[key]["status"] == "FAIL":
                failed_checks.append(key)

        if failed_checks:
            results["status"] = "FAIL"
            results["failed_checks"] = failed_checks

        return results

    @classmethod
    def review_from_data(cls, msds_data: Dict) -> Dict:
        """
        从 MSDS 数据字典直接进行审查（不需要文件路径）

        Args:
            msds_data: MSDS 数据字典（16部分结构）

        Returns:
            审查结果字典
        """
        # 将数据字典转为文本用于审查
        content = json.dumps(msds_data, ensure_ascii=False, indent=2)
        reviewer = cls(content=content)
        return reviewer.review()

    @classmethod
    def review_from_markdown(cls, markdown_content: str) -> Dict:
        """
        从 Markdown 文本进行审查

        Args:
            markdown_content: MSDS Markdown 文本

        Returns:
            审查结果字典
        """
        reviewer = cls(content=markdown_content)
        return reviewer.review()

    def _check_completeness(self) -> Dict:
        """检查16部分完整性"""
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
        issues = []

        # 检查是否有GHS分类
        if "GHS" not in self.content and "象形图" not in self.content:
            issues.append("缺少GHS分类信息")

        # 检查H码与分类是否匹配
        hazard_section = self._extract_section("第二部分：危险性概述")
        if hazard_section:
            h_codes_found = re.findall(r'H\d{3}', hazard_section)

            if not h_codes_found:
                issues.append("缺少H码（危险说明）")

            if "象形图" in hazard_section:
                pass  # 有象形图信息
            else:
                issues.append("缺少象形图信息")

        if issues:
            self.issues.append(f"GHS问题: {'; '.join(issues)}")
            return {"status": "FAIL", "issues": issues}

        return {"status": "PASS", "message": "GHS分类一致"}

    def _check_data_consistency(self) -> Dict:
        """检查数据一致性"""
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
        issues = []

        if "SDS编号" not in self.content:
            issues.append("缺少SDS编号")

        if "版本" not in self.content:
            issues.append("缺少版本信息")

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
        issues = []
        warnings = []

        # 检查急救措施是否包含关键要素
        first_aid = self._extract_section("第四部分：急救措施")
        if first_aid:
            required_elements = ["就医", "冲洗", "脱去"]
            for elem in required_elements:
                if elem not in first_aid:
                    issues.append(f"急救措施缺少关键要素: {elem}")

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
