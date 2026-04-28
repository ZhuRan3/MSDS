"""
MD → PDF 转换模块（仿真实 MSDS 排版）
化安通 (HuaAnTong) MSDS自动生成系统

排版规范（参考真实 CGHS MSDS）:
- A4 纵向，上下左右 15mm 边距
- 章节标题：深灰背景条 + 白色 12pt 粗体
- 表格：无边框双列布局（标签 | 值），仅用细分隔线
- 正文：9pt 宋体/黑体
- 页眉：产品名称 + 版本 + 页码
- [待确认]：红色标注

依赖：reportlab (已安装)
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional

# ============================================================
# 常量
# ============================================================

_FONT_SIMSUN = "C:/Windows/Fonts/simsun.ttc"
_FONT_SIMHEI = "C:/Windows/Fonts/simhei.ttf"
_FONT_MSURO = "C:/Windows/Fonts/msyh.ttc"

# 颜色
_CLR_SECTION_BG = (0x33, 0x33, 0x33)   # 深灰章节背景
_CLR_SECTION_FG = (0xFF, 0xFF, 0xFF)   # 白色标题字
_CLR_REVIEW     = (0xCC, 0x00, 0x00)   # 红色[待确认]
_CLR_LINE       = (0xAA, 0xAA, 0xAA)   # 浅灰分隔线
_CLR_HEADER_FG  = (0x66, 0x66, 0x66)   # 页眉灰色字


# ============================================================
# Markdown 解析 → 结构化数据
# ============================================================

def parse_md(md_content: str) -> List[dict]:
    """
    将 SDS Markdown 解析为结构化块列表

    每个块类型:
      {"type": "section", "title": "第X部分：..."}
      {"type": "kv_table", "rows": [(label, value), ...]}
      {"type": "kv_line", "label": "...", "value": "..."}
      {"type": "list", "items": ["...", ...]}
      {"type": "text", "content": "..."}
    """
    blocks = []
    lines = md_content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 空行 / 分割线
        if not line or line == '---':
            i += 1
            continue

        # 移除源追踪注释
        line = re.sub(r'\s*<!--.*?-->', '', line)

        # H1 章节标题
        if line.startswith('# '):
            blocks.append({"type": "section", "title": line[2:].strip()})
            i += 1
            continue

        # 表格 | ... | ... |
        if line.startswith('|'):
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                row_line = re.sub(r'\s*<!--.*?-->', '', lines[i].strip())
                # 跳过分隔行
                if re.match(r'^\|[\s\-:|]+\|$', row_line):
                    i += 1
                    continue
                cells = [c.strip() for c in row_line.split('|')[1:-1]]
                if len(cells) >= 2:
                    table_rows.append((cells[0], cells[1]))
                i += 1
            if table_rows:
                blocks.append({"type": "kv_table", "rows": table_rows})
            continue

        # 列表项
        if line.startswith('- '):
            items = []
            while i < len(lines) and lines[i].strip().startswith('- '):
                item = re.sub(r'\s*<!--.*?-->', '', lines[i].strip()[2:].strip())
                items.append(item)
                i += 1
            blocks.append({"type": "list", "items": items})
            continue

        # 粗体标签行: **标签**: 值
        m = re.match(r'\*\*(.+?)\*\*[：:]\s*(.*)', line)
        if m:
            label = m.group(1)
            value = m.group(2)
            blocks.append({"type": "kv_line", "label": label, "value": value})
            i += 1
            continue

        # 斜体独立行
        m = re.match(r'\*(.+?)\*', line)
        if m and m.group(1) == line[1:-1]:
            blocks.append({"type": "text", "content": line})
            i += 1
            continue

        # 普通文本
        blocks.append({"type": "text", "content": line})
        i += 1

    return blocks


# ============================================================
# reportlab PDF 渲染
# ============================================================

def _register_fonts():
    """注册中文字体"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if Path(_FONT_SIMSUN).exists():
        pdfmetrics.registerFont(TTFont('SimSun', _FONT_SIMSUN))
    if Path(_FONT_SIMHEI).exists():
        pdfmetrics.registerFont(TTFont('SimHei', _FONT_SIMHEI))


def _strip_md_format(text: str) -> str:
    """去除 Markdown 格式标记，返回纯文本"""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # 粗体
    text = re.sub(r'\*(.+?)\*', r'\1', text)       # 斜体
    text = re.sub(r'\s*<!--.*?-->', '', text)        # 注释
    return text.strip()


def generate_pdf(md_content: str, output_path: str, title: str = "SDS") -> str:
    """
    从 Markdown 生成 MSDS PDF（仿真实 CGHS 排版）

    Args:
        md_content: SDS Markdown 内容
        output_path: PDF 输出路径
        title: 文档标题（用于页眉）

    Returns:
        PDF 文件路径
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import Color, HexColor
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        KeepTogether, HRFlowable
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    _register_fonts()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    PAGE_W, PAGE_H = A4
    MARGIN = 15 * mm
    CONTENT_W = PAGE_W - 2 * MARGIN

    # 颜色
    section_bg = Color(*[c / 255 for c in _CLR_SECTION_BG])
    review_fg = Color(*[c / 255 for c in _CLR_REVIEW])
    line_clr = Color(*[c / 255 for c in _CLR_LINE])
    header_fg = Color(*[c / 255 for c in _CLR_HEADER_FG])

    # 样式
    font = 'SimHei' if Path(_FONT_SIMHEI).exists() else 'SimSun'
    FONT_SIZE = 9
    SECTION_FONT_SIZE = 11

    style_section = ParagraphStyle(
        'Section', fontName=font, fontSize=SECTION_FONT_SIZE, leading=16,
        textColor=Color(1, 1, 1), alignment=TA_CENTER, spaceAfter=4 * mm)

    style_body = ParagraphStyle(
        'Body', fontName=font, fontSize=FONT_SIZE, leading=14,
        alignment=TA_LEFT, spaceAfter=1 * mm)

    style_label = ParagraphStyle(
        'Label', fontName=font, fontSize=FONT_SIZE, leading=13,
        alignment=TA_LEFT)

    style_value = ParagraphStyle(
        'Value', fontName=font, fontSize=FONT_SIZE, leading=13,
        alignment=TA_LEFT)

    # 解析 MD
    blocks = parse_md(md_content)

    # 页眉/页脚
    page_num = [0]

    def header_footer(canvas, doc):
        page_num[0] += 1
        canvas.saveState()
        # 页眉线
        canvas.setStrokeColor(line_clr)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - MARGIN + 4 * mm, PAGE_W - MARGIN, PAGE_H - MARGIN + 4 * mm)
        # 页眉文字
        canvas.setFont(font, 7)
        canvas.setFillColor(header_fg)
        canvas.drawString(MARGIN, PAGE_H - MARGIN + 5 * mm,
                          f"化学品安全技术说明书 (SDS) — 化安通自动生成")
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 5 * mm,
                               f"第 {page_num[0]} 页")
        # 页脚线
        canvas.line(MARGIN, MARGIN - 4 * mm, PAGE_W - MARGIN, MARGIN - 4 * mm)
        canvas.drawCentredString(PAGE_W / 2, MARGIN - 8 * mm,
                                 "本文档由化安通(HuaAnTong)智能MSDS系统自动生成")
        canvas.restoreState()

    # 构建文档
    doc = SimpleDocTemplate(
        str(output), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 8 * mm, bottomMargin=MARGIN + 4 * mm)

    elements = []

    for block in blocks:
        if block["type"] == "section":
            # 章节标题：深灰背景条
            title_text = _strip_md_format(block["title"])
            # 用表格模拟背景条
            t = Table(
                [[Paragraph(title_text, style_section)]],
                colWidths=[CONTENT_W],
                rowHeights=[8 * mm]
            )
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), section_bg),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4 * mm),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4 * mm),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(Spacer(1, 3 * mm))
            elements.append(t)
            elements.append(Spacer(1, 2 * mm))

        elif block["type"] == "kv_table":
            # 无边框双列表格
            label_w = CONTENT_W * 0.3
            value_w = CONTENT_W * 0.7
            table_data = []
            for label, value in block["rows"]:
                label_clean = _strip_md_format(label)
                value_clean = _strip_md_format(value)
                # [待确认] 红色标注
                if '[待确认]' in value_clean:
                    value_html = value_clean.replace(
                        '[待确认]',
                        '<font color="#CC0000">[待确认]</font>')
                else:
                    value_html = value_clean
                table_data.append([
                    Paragraph(f'<b>{label_clean}</b>', style_label),
                    Paragraph(value_html, style_value),
                ])
            if table_data:
                t = Table(table_data, colWidths=[label_w, value_w])
                t.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (0, -1), 2 * mm),
                    ('LEFTPADDING', (1, 0), (1, -1), 3 * mm),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
                    ('TOPPADDING', (0, 0), (-1, -1), 1.5 * mm),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5 * mm),
                    # 细横线分隔
                    ('LINEBELOW', (0, 0), (-1, -2), 0.3, line_clr),
                    # 首行顶部线
                    ('LINEABOVE', (0, 0), (-1, 0), 0.5, line_clr),
                    # 末行底部线
                    ('LINEBELOW', (0, -1), (-1, -1), 0.5, line_clr),
                ]))
                elements.append(t)
                elements.append(Spacer(1, 2 * mm))

        elif block["type"] == "kv_line":
            # 标签: 值 行
            label_clean = _strip_md_format(block["label"])
            value_clean = _strip_md_format(block["value"])
            if '[待确认]' in value_clean:
                value_html = value_clean.replace(
                    '[待确认]', '<font color="#CC0000">[待确认]</font>')
            else:
                value_html = value_clean
            elements.append(Paragraph(
                f'<b>{label_clean}</b>：{value_html}', style_body))

        elif block["type"] == "list":
            # 列表项
            for item in block["items"]:
                item_clean = _strip_md_format(item)
                if '[待确认]' in item_clean:
                    item_clean = item_clean.replace(
                        '[待确认]', '<font color="#CC0000">[待确认]</font>')
                elements.append(Paragraph(
                    f'&nbsp;&nbsp;&nbsp;• {item_clean}', style_body))
            elements.append(Spacer(1, 1 * mm))

        elif block["type"] == "text":
            text_clean = _strip_md_format(block["content"])
            if '[待确认]' in text_clean:
                text_clean = text_clean.replace(
                    '[待确认]', '<font color="#CC0000">[待确认]</font>')
            # 斜体免责声明
            if text_clean.startswith('本文档由') or text_clean.startswith('*'):
                elements.append(Spacer(1, 2 * mm))
                elements.append(Paragraph(
                    f'<i>{text_clean.strip("*")}</i>',
                    ParagraphStyle('Disclaimer', parent=style_body,
                                   fontSize=7, textColor=header_fg)))
            else:
                elements.append(Paragraph(text_clean, style_body))

    # 生成 PDF
    doc.build(elements, onFirstPage=header_footer, onLaterPages=header_footer)
    return str(output)


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python pdf_generator.py <input.md> [output.pdf]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.md', '.pdf')

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    result = generate_pdf(content, output_file)
    print(f"PDF 已生成: {result}")
