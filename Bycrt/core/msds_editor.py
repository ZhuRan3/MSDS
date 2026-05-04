"""
化安通 (HuaAnTong) MSDS 手动编辑模块
第六层扩展 - 人工审核/修改接口

功能：
1. 将生成的MSDS导出为结构化JSON（按节拆分）
2. 读取用户修改的override JSON，应用到对应节
3. 按字段级别精准替换（支持全文替换和正则替换）
4. 生成修改前后的diff报告
5. 支持高风险节（S2/S4/S5/S11）单独审查

用法：
  # 导出结构化JSON供人工编辑
  editor = MSDSEditor()
  editor.export_json(md_content, "output/mixture/MSDS_xxx.json")

  # 用户编辑JSON后，应用修改并重新生成MD
  editor.apply_override("output/mixture/MSDS_xxx.json")
  editor.save_md("output/mixture/MSDS_xxx_edited.md")
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class OverrideAction:
    """单条修改记录"""
    section: int
    field: str = ""          # 字段名（空=整节替换）
    action: str = "replace"  # replace / regex / delete / prepend / append
    old: str = ""            # 被替换文本（action=replace时）
    new: str = ""            # 新文本
    pattern: str = ""        # 正则表达式（action=regex时）
    comment: str = ""        # 修改原因备注


@dataclass
class DiffEntry:
    """修改差异记录"""
    section: int
    field: str
    action: str
    old_text: str
    new_text: str
    comment: str = ""


class MSDSEditor:
    """MSDS手动编辑器"""

    # 高风险节（需要重点关注）
    HIGH_RISK_SECTIONS = [2, 4, 5, 11]
    MEDIUM_RISK_SECTIONS = [6, 10, 12]

    # MSDS节标题模板（用于解析和重组）
    SECTION_TITLES = {
        1: "第一部分：化学品及企业标识",
        2: "第二部分：危险性概述",
        3: "第三部分：成分/组成信息",
        4: "第四部分：急救措施",
        5: "第五部分：消防措施",
        6: "第六部分：泄漏应急处理",
        7: "第七部分：操作处置与储存",
        8: "第八部分：接触控制/个体防护",
        9: "第九部分：理化特性",
        10: "第十部分：稳定性和反应性",
        11: "第十一部分：毒理学信息",
        12: "第十二部分：生态学信息",
        13: "第十三部分：废弃处置",
        14: "第十四部分：运输信息",
        15: "第十五部分：法规信息",
        16: "第十六部分：其他信息",
    }

    def __init__(self):
        self._sections: Dict[int, str] = {}    # 节号 → 内容
        self._diffs: List[DiffEntry] = []       # 修改记录
        self._raw_md: str = ""                  # 原始Markdown

    # ============================================================
    # 解析
    # ============================================================

    def parse_md(self, md_content: str) -> Dict[int, str]:
        """
        将MSDS Markdown按节拆分

        Returns:
            {节号: 该节完整内容(含标题)}
        """
        self._raw_md = md_content

        # 按节标题拆分（比按"---"拆分更可靠，不会误切节内出现的分隔线）
        parts = re.split(r'(?=^#\s*第[一二三四五六七八九十]+部分[：:])', md_content, flags=re.MULTILINE)

        sections = {}
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # 匹配节号
            m = re.match(r'#\s*第([一二三四五六七八九十]+)部分[：:]', part)
            if m:
                cn_num = m.group(1)
                sec_num = self._cn_to_int(cn_num)
                if sec_num:
                    sections[sec_num] = part

        self._sections = sections
        return sections

    def parse_md_to_structure(self, md_content: str) -> dict:
        """
        将MSDS Markdown解析为结构化JSON

        Returns:
            {
              "product_name": "...",
              "sections": {
                "1": {
                  "title": "第一部分：化学品及企业标识",
                  "content": "...(原始Markdown)...",
                  "tables": [...],  # 解析的表格
                  "fields": {...},  # 键值对
                  "risk_level": "green"
                },
                ...
              },
              "override_instructions": "..."
            }
        """
        # 始终重新解析，避免缓存的_sections与新的md_content不一致
        self.parse_md(md_content)

        # 保存原始字段值，用于后续override时比较哪些字段被修改
        self._original_fields = {}

        result = {
            "product_name": self._extract_product_name(),
            "sections": {},
            "override_instructions": (
                "修改此JSON文件中的section内容后保存，"
                "使用 msds_editor.py --apply 即可重新生成MSDS。\n"
                "修改方式：\n"
                "  1. 直接修改 content 字段 → 整节替换\n"
                "  2. 在 overrides 数组中添加替换规则 → 按规则替换\n"
                "  3. 修改 fields 中的值（仅修改的值会被应用）"
            ),
        }

        for sec_num in range(1, 17):
            content = self._sections.get(sec_num, "")
            risk = self._get_risk_level(sec_num)
            fields = self._extract_fields(content)

            # 标记含[待确认]的字段，方便用户定位
            needs_review = [
                {"field": k, "current_value": v}
                for k, v in fields.items()
                if "[待确认]" in v or "需实测" in v or "无可用数据" in v
            ]
            # 也扫描content中的待确认行（非表格字段）
            for line in content.split("\n"):
                if "[待确认]" in line or "需实测" in line:
                    # 提取加粗标签
                    label_m = re.match(r'\*\*(.+?)\*\*', line.strip())
                    if label_m:
                        label = label_m.group(1)
                        if not any(n["field"] == label for n in needs_review):
                            needs_review.append({"field": label, "current_value": line.strip()})

            # 保存原始字段值
            self._original_fields[str(sec_num)] = dict(fields)

            section_data = {
                "title": self.SECTION_TITLES.get(sec_num, f"第{sec_num}部分"),
                "content": content,
                "risk_level": risk,
                "tables": self._extract_tables(content),
                "fields": fields,
                "fields_original": dict(fields),  # 保存原始值，用于检测修改
                "needs_review": needs_review,      # 待确认字段清单
                "overrides": [],  # 用户填写的修改规则
            }
            result["sections"][str(sec_num)] = section_data

        return result

    # ============================================================
    # 导出
    # ============================================================

    def export_json(self, md_content: str, output_path: str) -> str:
        """
        导出为结构化JSON供人工编辑

        Args:
            md_content: 原始MSDS Markdown
            output_path: 输出路径

        Returns:
            输出文件路径
        """
        structure = self.parse_md_to_structure(md_content)

        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(structure, f, ensure_ascii=False, indent=2)

        return str(p)

    # ============================================================
    # Override应用
    # ============================================================

    def apply_override_file(self, override_path: str) -> str:
        """
        从override JSON文件读取修改并应用到_sections

        Args:
            override_path: override JSON文件路径

        Returns:
            修改后的完整Markdown
        """
        with open(override_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 如果_sections为空，从JSON中的content字段重建
        if not self._sections:
            for sec_str, sec_data in data.get("sections", {}).items():
                content = sec_data.get("content", "")
                if content:
                    self._sections[int(sec_str)] = content

        # 重建 _original_fields（用于字段级替换时比较哪些值被修改）
        if not hasattr(self, '_original_fields') or not self._original_fields:
            self._original_fields = {}
            for sec_str, sec_data in data.get("sections", {}).items():
                fields = sec_data.get("fields", {})
                if fields:
                    self._original_fields[sec_str] = dict(fields)

        return self.apply_override_data(data)

    def apply_override_data(self, data: dict) -> str:
        """
        应用override数据

        支持两种修改方式：
        1. 修改 sections[N].content → 整节替换
        2. 在 sections[N].overrides 数组中添加替换规则

        Returns:
            修改后的完整Markdown
        """
        if not self._sections:
            print("  [WARN] _sections为空，请先调用parse_md()或确保JSON中包含content。")
            return ""

        self._diffs = []
        sections_data = data.get("sections", {})

        for sec_str, sec_data in sections_data.items():
            sec_num = int(sec_str)
            if sec_num not in self._sections:
                continue

            original = self._sections[sec_num]

            # 方式1: 整节替换
            new_content = sec_data.get("content", "")
            if new_content and new_content != original:
                self._diffs.append(DiffEntry(
                    section=sec_num, field="content", action="full_replace",
                    old_text=original[:100] + "...",
                    new_text=new_content[:100] + "...",
                    comment="整节替换",
                ))
                self._sections[sec_num] = new_content
                continue

            # 方式2: 按override规则替换
            overrides = sec_data.get("overrides", [])
            if overrides:
                modified = self._sections[sec_num]
                for ov in overrides:
                    action = ov.get("action", "replace")
                    comment = ov.get("comment", "")

                    if action == "replace":
                        old = ov.get("old", "")
                        new = ov.get("new", "")
                        if old and old in modified:
                            modified = modified.replace(old, new)
                            self._diffs.append(DiffEntry(
                                section=sec_num, field="",
                                action="replace", old_text=old,
                                new_text=new, comment=comment,
                            ))

                    elif action == "regex":
                        pattern = ov.get("pattern", "")
                        replacement = ov.get("new", "")
                        if pattern:
                            try:
                                modified = re.sub(pattern, replacement, modified)
                                self._diffs.append(DiffEntry(
                                    section=sec_num, field="",
                                    action="regex", old_text=pattern,
                                    new_text=replacement, comment=comment,
                                ))
                            except re.error as e:
                                print(f"  [WARN] 节{sec_num}正则替换失败: {e}")

                    elif action == "prepend":
                        text = ov.get("new", "")
                        if text:
                            # 在节标题后插入
                            lines = modified.split("\n", 1)
                            if len(lines) > 1:
                                modified = lines[0] + "\n" + text + "\n" + lines[1]
                            else:
                                modified = modified + "\n" + text
                            self._diffs.append(DiffEntry(
                                section=sec_num, field="",
                                action="prepend", old_text="",
                                new_text=text, comment=comment,
                            ))

                    elif action == "append":
                        text = ov.get("new", "")
                        if text:
                            modified = modified + "\n" + text
                            self._diffs.append(DiffEntry(
                                section=sec_num, field="",
                                action="append", old_text="",
                                new_text=text, comment=comment,
                            ))

                    elif action == "delete":
                        target = ov.get("old", "")
                        if target and target in modified:
                            modified = modified.replace(target, "")
                            self._diffs.append(DiffEntry(
                                section=sec_num, field="",
                                action="delete", old_text=target,
                                new_text="", comment=comment,
                            ))

                self._sections[sec_num] = modified

            # 方式3: 按fields精确替换（仅替换值发生变化的字段，仅限2列表格节）
            if sec_num in self.MULTI_COL_SECTIONS:
                continue
            fields = sec_data.get("fields", {})
            # 优先使用JSON中的fields_original，其次使用_original_fields
            orig_fields = sec_data.get("fields_original", {})
            if not orig_fields and hasattr(self, '_original_fields'):
                orig_fields = self._original_fields.get(str(sec_num), {})
            if fields and orig_fields:
                modified = self._sections[sec_num]
                for field_name, new_val in fields.items():
                    # 只替换值实际被修改的字段
                    orig_val = orig_fields.get(field_name, "")
                    if orig_val and new_val != orig_val:
                        # 在Markdown中查找 "| field_name | ... |" 行
                        pattern = rf'(\|\s*{re.escape(field_name)}\s*\|)(.*?)(\|)'
                        match = re.search(pattern, modified)
                        if match:
                            old_line = match.group(0)
                            new_line = f"| {field_name} | {new_val} |"
                            modified = modified.replace(old_line, new_line)
                            self._diffs.append(DiffEntry(
                                section=sec_num, field=field_name,
                                action="field_replace", old_text=old_line,
                                new_text=new_line,
                            ))
                self._sections[sec_num] = modified

        return self.rebuild_md()

    # ============================================================
    # 快捷Override
    # ============================================================

    def quick_override(self, md_content: str, actions: List[OverrideAction]) -> str:
        """
        快捷修改接口 - 直接传入修改动作列表

        Args:
            md_content: 原始Markdown
            actions: 修改动作列表

        Returns:
            修改后的Markdown
        """
        self.parse_md(md_content)
        self._diffs = []

        for act in actions:
            sec = act.section
            if sec not in self._sections:
                print(f"  [WARN] 节{sec}不存在")
                continue

            content = self._sections[sec]

            if act.action == "replace":
                if act.old and act.old in content:
                    content = content.replace(act.old, act.new)

            elif act.action == "regex":
                if act.pattern:
                    try:
                        content = re.sub(act.pattern, act.new, content)
                    except re.error as e:
                        print(f"  [WARN] 节{sec}正则失败: {e}")

            elif act.action == "full":
                if act.new:
                    # 保留节标题（第一行），只替换标题后的内容
                    header_line = content.split("\n", 1)[0]
                    content = header_line + "\n" + act.new

            elif act.action == "append":
                content = content + "\n" + act.new

            elif act.action == "prepend":
                lines = content.split("\n", 1)
                content = lines[0] + "\n" + act.new + "\n" + (lines[1] if len(lines) > 1 else "")

            elif act.action == "delete":
                if act.old:
                    content = content.replace(act.old, "")

            self._diffs.append(DiffEntry(
                section=sec, field=act.field,
                action=act.action, old_text=act.old[:80],
                new_text=act.new[:80], comment=act.comment,
            ))
            self._sections[sec] = content

        return self.rebuild_md()

    # ============================================================
    # 重组输出
    # ============================================================

    def rebuild_md(self) -> str:
        """将_sections重组为完整Markdown"""
        parts = []
        for i in range(1, 17):
            if i in self._sections:
                parts.append(self._sections[i])
        if not parts:
            print("  [WARN] rebuild_md: 所有节均缺失")
        return "\n---\n".join(parts)

    def save_md(self, output_path: str):
        """保存修改后的Markdown"""
        content = self.rebuild_md()
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return str(p)

    def save_md_with_pdf(self, output_path: str):
        """保存Markdown并生成PDF"""
        md_path = self.save_md(output_path)
        try:
            core_dir = str(Path(__file__).resolve().parent)
            if core_dir not in sys.path:
                sys.path.insert(0, core_dir)
            from pdf_generator import generate_pdf
            pdf_path = str(Path(output_path).with_suffix('.pdf'))
            # 读取Markdown内容（generate_pdf第一个参数是内容不是路径）
            md_content = Path(md_path).read_text(encoding='utf-8')
            generate_pdf(md_content, pdf_path, title=Path(output_path).stem)
            print(f"  已保存PDF: {pdf_path}")
        except Exception as e:
            print(f"  [WARN] PDF生成失败: {e}")

    # ============================================================
    # Diff报告
    # ============================================================

    def get_diff_report(self) -> List[Dict]:
        """获取修改差异报告"""
        return [
            {
                "section": d.section,
                "section_title": self.SECTION_TITLES.get(d.section, ""),
                "field": d.field,
                "action": d.action,
                "old": d.old_text[:200],
                "new": d.new_text[:200],
                "comment": d.comment,
            }
            for d in self._diffs
        ]

    def print_diff_summary(self):
        """打印修改摘要"""
        if not self._diffs:
            print("  无修改。")
            return

        print(f"\n{'='*50}")
        print(f"  MSDS修改摘要 ({len(self._diffs)}处)")
        print(f"{'='*50}")
        for d in self._diffs:
            title = self.SECTION_TITLES.get(d.section, f"节{d.section}")
            print(f"\n  [{d.action}] {title}")
            if d.field:
                print(f"    字段: {d.field}")
            if d.old_text:
                _safe_print("    原文", d.old_text[:80])
            if d.new_text:
                _safe_print("    改为", d.new_text[:80])
            if d.comment:
                _safe_print("    备注", d.comment)

    # ============================================================
    # 高风险节审查
    # ============================================================

    def get_high_risk_sections(self) -> Dict[int, str]:
        """获取高风险节的内容（S2/S4/S5/S11）"""
        return {
            sec: self._sections.get(sec, "")
            for sec in self.HIGH_RISK_SECTIONS
            if sec in self._sections
        }

    def review_high_risk(self) -> List[Dict]:
        """
        审查高风险节的内容，返回可疑项列表

        检查规则：
        - 含有 [待确认] 标记
        - 含有推断值标记
        - 含有 AI来源标记
        - 关键字段为空
        """
        issues = []
        for sec_num in self.HIGH_RISK_SECTIONS + self.MEDIUM_RISK_SECTIONS:
            content = self._sections.get(sec_num, "")
            title = self.SECTION_TITLES.get(sec_num, "")

            # 检查 [待确认]
            if "[待确认]" in content:
                count = content.count("[待确认]")
                issues.append({
                    "section": sec_num,
                    "title": title,
                    "severity": "high",
                    "issue": f"含{count}处[待确认]标记，需人工补充",
                    "suggestion": "请在override JSON中补充对应字段的实际值",
                })

            # 检查推断值
            if "推断值" in content:
                issues.append({
                    "section": sec_num,
                    "title": title,
                    "severity": "medium",
                    "issue": "含推断值标记，准确性需验证",
                    "suggestion": "建议查阅实验数据或权威文献确认",
                })

            # 检查AI来源
            if "src:ai" in content or "src:inference" in content:
                issues.append({
                    "section": sec_num,
                    "title": title,
                    "severity": "high",
                    "issue": "含AI推断/推理来源标记，可能不准确",
                    "suggestion": "建议人工核对并替换为验证后的数据",
                })

            # 检查关键词段为空
            empty_patterns = [
                (r'无可用数据', '含"无可用数据"'),
                (r'无数据资料', '含"无数据资料"'),
            ]
            for pattern, desc in empty_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    issues.append({
                        "section": sec_num,
                        "title": title,
                        "severity": "low",
                        "issue": f"{desc} ({len(matches)}处)",
                        "suggestion": "建议补充实际数据",
                    })

        return issues

    # ============================================================
    # 内部工具
    # ============================================================

    def _cn_to_int(self, cn: str) -> Optional[int]:
        """中文数字转整数（支持1-16）"""
        mapping = {
            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
            "十一": 11, "十二": 12, "十三": 13, "十四": 14,
            "十五": 15, "十六": 16,
        }
        return mapping.get(cn)

    def _get_risk_level(self, section: int) -> str:
        """获取节的风险等级"""
        if section in self.HIGH_RISK_SECTIONS:
            return "red"
        elif section in self.MEDIUM_RISK_SECTIONS:
            return "orange"
        return "green"

    def _extract_product_name(self) -> str:
        """从S1提取产品名称"""
        s1 = self._sections.get(1, "")
        m = re.search(r'\|\s*化学品名称\s*\|\s*(.*?)\s*\|', s1)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_tables(self, content: str) -> List[List[List[str]]]:
        """提取Markdown表格"""
        tables = []
        current_rows = []
        in_table = False

        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("|") and "|" in stripped[1:]:
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                # 跳过分隔行
                if all(set(c) <= {"-", ":"} for c in cells):
                    continue
                current_rows.append(cells)
                in_table = True
            else:
                if in_table and current_rows:
                    tables.append(current_rows)
                    current_rows = []
                in_table = False

        if current_rows:
            tables.append(current_rows)

        return tables

    # 多列表格的节（字段替换不适用于这些节的表格）
    MULTI_COL_SECTIONS = {3, 14}

    def _extract_fields(self, content: str) -> Dict[str, str]:
        """提取键值对字段（Markdown表格中的，仅2列表格行）"""
        fields = {}
        for line in content.split("\n"):
            stripped = line.strip()
            # 统计 "|" 的数量（去掉首尾可能的开头"|"）
            if not stripped.startswith("|"):
                continue
            pipe_count = stripped.count("|")
            # 2列表格行: "| key | val |" → pipe_count=4 (含首尾空串分割)
            # 3+列表格行: "| a | b | c |" → pipe_count>=5
            if pipe_count > 4:
                continue  # 多列表格行，跳过
            m = re.match(r'\|\s*(.*?)\s*\|\s*(.*?)\s*\|', stripped)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                # 跳过分隔行
                if key and not all(c in "-: " for c in key):
                    fields[key] = val
        return fields


# ============================================================
# 工具函数
# ============================================================

def _safe_print(label: str, text: str):
    """安全打印（处理Windows GBK编码）"""
    suffix = "..." if len(text) >= 80 else ""
    try:
        print(f"{label}: {text}{suffix}")
    except UnicodeEncodeError:
        safe = text.encode('gbk', errors='replace').decode('gbk')
        print(f"{label}: {safe}{suffix}")


# ============================================================
# CLI
# ============================================================

def main():
    """命令行入口"""
    # Windows GBK控制台编码保护
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    import argparse

    parser = argparse.ArgumentParser(
        description="化安通 MSDS 编辑工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 导出MSDS为结构化JSON（供人工编辑）
  python msds_editor.py --export MSDS_乙醇.md -o MSDS_乙醇_edit.json

  # 应用修改后的JSON，生成新的MD文件
  python msds_editor.py --apply MSDS_乙醇_edit.json -o MSDS_乙醇_v2.md

  # 审查高风险节
  python msds_editor.py --review MSDS_乙醇.md

  # 快捷替换
  python msds_editor.py --replace MSDS_乙醇.md --section 4 --old "漱口" --new "用水漱口" --comment "补充说明"
        """,
    )

    parser.add_argument("--export", type=str, help="导出MSDS MD为结构化JSON")
    parser.add_argument("--apply", type=str, help="应用override JSON修改")
    parser.add_argument("--review", type=str, help="审查MSDS高风险节")
    parser.add_argument("--replace", type=str, help="快捷替换单个MSDS文件")

    parser.add_argument("-o", "--output", type=str, default="", help="输出文件路径")
    parser.add_argument("--section", type=int, default=0, help="目标节号（用于--replace）")
    parser.add_argument("--old", type=str, default="", help="被替换文本（用于--replace）")
    parser.add_argument("--new", type=str, default="", help="新文本（用于--replace）")
    parser.add_argument("--comment", type=str, default="", help="修改备注")
    parser.add_argument("--pdf", action="store_true", help="同时生成PDF")

    args = parser.parse_args()

    if not any([args.export, args.apply, args.review, args.replace]):
        parser.print_help()
        sys.exit(1)

    editor = MSDSEditor()

    if args.export:
        # 导出为JSON
        md_path = args.export
        if not Path(md_path).exists():
            # 尝试相对于output目录
            md_path = str(PROJECT_ROOT / "output" / "pure" / args.export)
            if not Path(md_path).exists():
                md_path = str(PROJECT_ROOT / "output" / "mixture" / args.export)

        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        out_path = args.output or md_path.replace(".md", "_edit.json")
        result = editor.export_json(md_content, out_path)
        print(f"已导出结构化JSON: {result}")
        print(f"请编辑此文件后使用 --apply 应用修改")

    elif args.apply:
        # 应用override
        json_path = args.apply
        editor.apply_override_file(json_path)

        out_path = args.output
        if not out_path:
            out_path = json_path.replace("_edit.json", "_v2.md")
            if out_path == json_path:
                out_path = json_path.replace(".json", "_v2.md")

        if args.pdf:
            editor.save_md_with_pdf(out_path)
        else:
            editor.save_md(out_path)

        editor.print_diff_summary()
        print(f"\n已保存修改后文件: {out_path}")

    elif args.review:
        # 审查高风险节
        md_path = args.review
        if not Path(md_path).exists():
            md_path = str(PROJECT_ROOT / "output" / "pure" / args.review)
            if not Path(md_path).exists():
                md_path = str(PROJECT_ROOT / "output" / "mixture" / args.review)

        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        editor.parse_md(md_content)
        issues = editor.review_high_risk()

        if issues:
            print(f"\n{'='*60}")
            print(f"  MSDS高风险审查报告")
            print(f"{'='*60}")
            for issue in issues:
                icon = {"high": "!!", "medium": "!", "low": "~"}[issue["severity"]]
                print(f"\n  [{icon}] 节{issue['section']} {issue['title']}")
                print(f"      问题: {issue['issue']}")
                print(f"      建议: {issue['suggestion']}")
        else:
            print("  未发现高风险问题。")

    elif args.replace:
        # 快捷替换
        md_path = args.replace
        if not Path(md_path).exists():
            md_path = str(PROJECT_ROOT / "output" / "pure" / args.replace)
            if not Path(md_path).exists():
                md_path = str(PROJECT_ROOT / "output" / "mixture" / args.replace)

        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        if not args.section:
            print("  [ERROR] --replace 需要指定 --section 节号")
            sys.exit(1)

        action = OverrideAction(
            section=args.section,
            action="replace",
            old=args.old,
            new=args.new,
            comment=args.comment,
        )
        result = editor.quick_override(md_content, [action])

        out_path = args.output or md_path.replace(".md", "_edited.md")
        if args.pdf:
            editor.save_md_with_pdf(out_path)
        else:
            editor.save_md(out_path)

        editor.print_diff_summary()
        print(f"\n已保存: {out_path}")


if __name__ == "__main__":
    main()
