"""
系统测试对标脚本 - 对比生成SDS与val/真实SDS
化安通 (HuaAnTong) MSDS自动生成系统

用法:
  python core/test_benchmark.py
  python core/test_benchmark.py --output output/benchmark_report.md
"""

import re
import json
import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAL_DIR = PROJECT_ROOT / "val"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class FieldComparison:
    """单个字段的对比结果"""
    field_name: str
    expected: str       # 真实SDS中的值
    actual: str         # 生成SDS中的值
    match: bool         # 是否匹配
    note: str = ""      # 说明


@dataclass
class BenchmarkResult:
    """单个化学品的对标结果"""
    chemical_name: str
    cas: str
    fields: List[FieldComparison] = field(default_factory=list)
    match_count: int = 0
    total_count: int = 0
    match_rate: float = 0.0
    extra_classifications: List[str] = field(default_factory=list)
    missing_classifications: List[str] = field(default_factory=list)


def extract_fields_from_md(content: str) -> Dict[str, str]:
    """从Markdown SDS中提取关键字段（兼容val/和生成两种格式）"""
    fields = {}

    # CAS号 - 格式: "**CAS号**: 67-64-1" 或 "| CAS号 | 67-64-1 <!-- src:kb --> |"
    m = re.search(r'CAS[号#]*[*：:\s|]*(\d{2,7}-\d{2}-\d)', content)
    if m:
        fields['cas'] = m.group(1)

    # 分子式 - 格式: "**分子式**: C3H6O" 或 "| 分子式 | C3H6O <!-- src:kb --> |"
    m = re.search(r'分子式[*：:\s|]+([A-Za-z0-9]+)', content)
    if m:
        fields['formula'] = m.group(1)

    # 分子量
    m = re.search(r'分子量[*：:\s|]+([\d.]+)', content)
    if m:
        fields['mw'] = m.group(1)

    # UN编号 - 格式: "UN1090" 或 "UN编号 | 1090"
    m = re.search(r'UN\s*(?:编号)?[*：:\s|]*(?:UN)?(\d{3,4})', content)
    if m:
        fields['un'] = m.group(1)

    # 闪点 - 支持两种表格格式和生成格式
    m = re.search(r'(?:^\|\s*)?闪点(?:\s*\|\s*|\*\*:\s*|[：:\s]+)([-\d.]+)', content, re.MULTILINE)
    if m:
        fields['flash_point'] = m.group(1)

    # 沸点
    m = re.search(r'(?:^\|\s*)?沸点(?:\s*\|\s*|\*\*:\s*|[：:\s]+)([-\d.]+)', content, re.MULTILINE)
    if m:
        fields['boiling_point'] = m.group(1)

    # 熔点
    m = re.search(r'(?:^\|\s*)?熔点(?:\s*\|\s*|\*\*:\s*|[：:\s]+)([-\d.]+)', content, re.MULTILINE)
    if m:
        fields['melting_point'] = m.group(1)

    # 密度
    m = re.search(r'(?:^\|\s*)?密度(?:\s*\|\s*|\*\*:\s*|[：:\s]+)([\d.]+)', content, re.MULTILINE)
    if m:
        fields['density'] = m.group(1)

    # LD50经口 - 多种格式 (有/无mg/kg单位)
    m = re.search(r'LD50[*经口\s：:]*([\d,]+)\s*mg/kg', content)
    if not m:
        m = re.search(r'LD50[*经口\s：:]*([\d,]+)', content)
    if not m:
        m = re.search(r'LD50[^\n]*?经口[：:]*\s*([\d,]+)\s*mg/kg', content)
    if not m:
        m = re.search(r'LD50[^\n]*?口服[：:]*\s*([\d,]+)\s*mg/kg', content)
    if not m:
        m = re.search(r'LD50[^\d]*?([\d,]+)\s*mg/kg', content)
    if m:
        fields['ld50_oral'] = m.group(1).replace(',', '')

    # 信号词
    m = re.search(r'信号词[*：:\s]*(危险|警告)', content)
    if m:
        fields['signal_word'] = m.group(1)

    # IUPAC名称
    m = re.search(r'IUPAC[*名称：:\s]*\|?\s*(\S+)', content)
    if m:
        val = m.group(1).strip()
        if val and val != '-' and not val.startswith('<!--'):
            fields['iupac'] = val

    return fields


def extract_ghs_classifications(content: str) -> List[str]:
    """提取GHS分类列表（兼容val/和生成格式）"""
    classifications = []
    # 匹配 "- 易燃液体，类别2" 或 "- 易燃液体，类别2 (H225)" 等格式
    matches = re.findall(
        r'^\s*[-*]\s*(.+?(?:类别|Cat\.?)[\s\dA-Za-z\u4e00-\u9fa5（）()]+)',
        content, re.MULTILINE
    )
    for cls in matches:
        cls = cls.strip()
        # 清理H码后缀: "(H225)" 或 " (H336)"
        cls = re.sub(r'\s*\(H\d{3}[A-Z]?\)\s*$', '', cls)
        # 清理HTML注释
        cls = re.sub(r'\s*<!--[^>]*-->', '', cls)
        # 清理markdown加粗标记: **严重眼损伤/眼刺激**: 严重眼损伤/眼刺激，类别2A
        # 只保留冒号后面的部分
        if '**' in cls and '：' in cls:
            parts = cls.split('：', 1)
            if len(parts) > 1 and '类别' in parts[1]:
                cls = parts[1].strip()
        elif '**' in cls and ':' in cls:
            parts = cls.split(':', 1)
            if len(parts) > 1 and '类别' in parts[1]:
                cls = parts[1].strip()
        # 清理残留的*号
        cls = cls.replace('*', '').strip()
        # 过滤掉成分表格行（含CAS号格式或浓度≥）
        if re.match(r'^\d{2,7}-\d{2}-\d', cls):
            continue
        if '≥' in cls or '%' in cls:
            continue
        if cls and 3 < len(cls) < 80:
            classifications.append(cls)
    return classifications


def normalize_value(val: str) -> str:
    """标准化数值用于比较"""
    val = str(val).strip()
    val = re.sub(r'[（(].+?[）)]', '', val)  # 去括号内容
    val = val.replace(' ', '').replace(',', '')
    val = val.replace('°C', '').replace('℃', '')
    val = val.replace('g/cm³', '').replace('g/cm3', '')
    val = val.replace('mg/kg', '').replace('mg/L', '')
    val = val.replace('kPa', '').replace('%', '')
    return val.strip()


def values_match(expected: str, actual: str, tolerance: float = 0.05) -> bool:
    """比较两个值是否匹配（支持数值容差）"""
    e_norm = normalize_value(expected)
    a_norm = normalize_value(actual)

    if e_norm == a_norm:
        return True

    # 尝试数值比较
    try:
        e_num = float(e_norm)
        a_num = float(a_norm)
        if e_num == 0:
            return a_num == 0
        return abs(a_num - e_num) / abs(e_num) <= tolerance
    except (ValueError, ZeroDivisionError):
        pass

    # 文本包含匹配（排除空字符串匹配）
    if e_norm and a_norm and (e_norm in a_norm or a_norm in e_norm):
        return True

    return False


def compare_classifications(expected: list, actual: list) -> Tuple[List[str], List[str]]:
    """对比GHS分类，返回(多余分类, 缺失分类)"""
    def normalize_cls(s):
        s = s.replace('，', '').replace(',', '').replace(' ', '').lower()
        s = re.sub(r'[（）()]', '', s)
        return s

    e_set = {normalize_cls(c) for c in expected}
    a_set = {normalize_cls(c) for c in actual}

    extra = [c for c in actual if normalize_cls(c) not in e_set]
    missing = [c for c in expected if normalize_cls(c) not in a_set]
    return extra, missing


def benchmark_one(val_path: Path) -> Optional[BenchmarkResult]:
    """对标单个化学品"""
    name = val_path.stem
    parts = name.split('_')
    chem_name = parts[0] if parts else name
    cas = parts[1] if len(parts) > 1 else ""

    # 读取真实SDS
    val_content = val_path.read_text(encoding='utf-8')
    val_fields = extract_fields_from_md(val_content)
    val_ghs = extract_ghs_classifications(val_content)

    # 用Pipeline生成SDS
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sds_pipeline_v2 import SDSPipeline
    pipeline = SDSPipeline()

    output_file = str(OUTPUT_DIR / f"benchmark_{name}.md")
    try:
        result = pipeline.generate_pure(
            query=cas or chem_name,
            product_name=chem_name,
            output_path=output_file,
        )
    except Exception as e:
        print(f"  [ERROR] 生成失败: {e}")
        return None

    if not result.markdown:
        return None

    # 提取生成SDS的字段
    gen_fields = extract_fields_from_md(result.markdown)
    gen_ghs = extract_ghs_classifications(result.markdown)

    # 逐字段对比
    comparisons = []
    field_map = {
        'cas': ('CAS号', 'cas'),
        'formula': ('分子式', 'formula'),
        'mw': ('分子量', 'mw'),
        'un': ('UN编号', 'un'),
        'flash_point': ('闪点', 'flash_point'),
        'boiling_point': ('沸点', 'boiling_point'),
        'melting_point': ('熔点', 'melting_point'),
        'density': ('密度', 'density'),
        'ld50_oral': ('LD50经口', 'ld50_oral'),
        'signal_word': ('信号词', 'signal_word'),
    }

    for key, (label, _) in field_map.items():
        e_val = val_fields.get(key, "")
        a_val = gen_fields.get(key, "")
        if e_val:
            match = values_match(e_val, a_val)
            note = ""
            if not match and a_val:
                note = f"真实={e_val}, 生成={a_val}"
            elif not a_val:
                note = "生成SDS中未提取到"
            comparisons.append(FieldComparison(
                field_name=label,
                expected=e_val,
                actual=a_val or "(未找到)",
                match=match,
                note=note,
            ))

    # GHS分类对比
    extra, missing = compare_classifications(val_ghs, gen_ghs)

    match_count = sum(1 for c in comparisons if c.match)
    total_count = len(comparisons)

    return BenchmarkResult(
        chemical_name=chem_name,
        cas=cas,
        fields=comparisons,
        match_count=match_count,
        total_count=total_count,
        match_rate=match_count / total_count if total_count else 0,
        extra_classifications=extra,
        missing_classifications=missing,
    )


def run_benchmark():
    """执行全部对标"""
    print(f"\n{'='*70}")
    print(f"化安通 MSDS系统 - 对标测试")
    print(f"{'='*70}")
    print(f"对比对象: val/ 真实SDS vs Pipeline生成SDS")
    print(f"测试化学品:")

    val_files = sorted(VAL_DIR.glob("*.md"))
    val_files = [f for f in val_files if f.name not in ("README.md",) and "指南" not in f.name]

    for f in val_files:
        print(f"  - {f.stem}")

    results = []
    for vf in val_files:
        print(f"\n{'─'*50}")
        print(f"对标: {vf.stem}")
        r = benchmark_one(vf)
        if r:
            results.append(r)
            print(f"  字段匹配: {r.match_count}/{r.total_count} ({r.match_rate*100:.0f}%)")
            for c in r.fields:
                icon = "OK" if c.match else "XX"
                print(f"  [{icon}] {c.field_name}: {c.expected} vs {c.actual}")
                if c.note:
                    print(f"       {c.note}")
            if r.missing_classifications:
                print(f"  缺失分类: {r.missing_classifications}")
            if r.extra_classifications:
                print(f"  多余分类: {r.extra_classifications}")

    # 汇总报告
    print(f"\n{'='*70}")
    print(f"汇总报告")
    print(f"{'='*70}")

    total_match = 0
    total_fields = 0
    for r in results:
        total_match += r.match_count
        total_fields += r.total_count
        print(f"  {r.chemical_name}({r.cas}): {r.match_count}/{r.total_count} = {r.match_rate*100:.0f}%")

    overall_rate = total_match / total_fields if total_fields else 0
    print(f"\n  总体字段匹配率: {total_match}/{total_fields} = {overall_rate*100:.1f}%")

    # 保存报告
    report_path = OUTPUT_DIR / "benchmark_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 化安通 MSDS系统 - 对标测试报告\n\n")
        f.write(f"## 总体结果: **{total_match}/{total_fields} = {overall_rate*100:.1f}%**\n\n")
        f.write("| 化学品 | CAS | 匹配率 | 匹配/总数 | 缺失分类 | 多余分类 |\n")
        f.write("|--------|-----|--------|-----------|----------|----------|\n")
        for r in results:
            missing_str = ", ".join(r.missing_classifications[:2]) if r.missing_classifications else "-"
            extra_str = ", ".join(r.extra_classifications[:2]) if r.extra_classifications else "-"
            if r.missing_classifications and len(r.missing_classifications) > 2:
                missing_str += f" (+{len(r.missing_classifications)-2})"
            if r.extra_classifications and len(r.extra_classifications) > 2:
                extra_str += f" (+{len(r.extra_classifications)-2})"
            f.write(f"| {r.chemical_name} | {r.cas} | {r.match_rate*100:.0f}% | {r.match_count}/{r.total_count} | {missing_str} | {extra_str} |\n")

        f.write(f"\n## 逐字段明细\n\n")
        for r in results:
            f.write(f"### {r.chemical_name} ({r.cas})\n\n")
            f.write("| 字段 | 真实值 | 生成值 | 匹配 |\n")
            f.write("|------|--------|--------|------|\n")
            for c in r.fields:
                icon = "Y" if c.match else "N"
                f.write(f"| {c.field_name} | {c.expected} | {c.actual} | {icon} |\n")
            if r.fields:
                f.write("\n")

    print(f"\n报告已保存: {report_path}")
    return results


if __name__ == "__main__":
    run_benchmark()
