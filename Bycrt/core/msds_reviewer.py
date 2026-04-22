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

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.content = ""
        self.issues = []
        self.warnings = []

    def review(self) -> Dict:
        """执行完整审查"""
        print(f"\n{'='*60}")
        print(f"化安通 MSDS审查")
        print(f"{'='*60}")
        print(f"文件: {self.file_path}")

        if not self.file_path.exists():
            return {"status": "ERROR", "message": f"文件不存在: {self.file_path}"}

        self.content = self.file_path.read_text(encoding='utf-8')

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
            # 提取GHS分类
            ghs_matches = re.findall(r'[\u4e00-\u9fa5]+，类别\d+[A-Z]?', hazard_section)
            h_codes_found = re.findall(r'H\d{3}', hazard_section)

            # 验证H码存在
            if not h_codes_found:
                issues.append("缺少H码（危险说明）")

            # 验证象形图存在
            if "象形图" in hazard_section:
                pictogram_match = re.search(r'象形图[：:]\s*(.+?)(?:\n|$)', hazard_section)
                if pictogram_match:
                    pictograms = pictogram_match.group(1)
                    # 应该有对应GHS分类的象形图
            else:
                issues.append("缺少象形图信息")

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
            required_elements = ["就医", "冲洗", "脱去"]
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