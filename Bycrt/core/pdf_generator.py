"""
MD -> PDF 转换模块（仿真实 MSDS 排版）
化安通 (HuaAnTong) MSDS自动生成系统

排版规范（参考《合规化学网》石油大学真实 SDS 格式 + 截图）:
- A4 纵向，边距 ~20mm
- 章节标题（第X部分）：大字号粗体 + 左侧红色竖条标识
- 子标题（紧急概述/GHS分类等）：粗体，中等字号
- 键值对：标签(加粗)：值，无表格边框
- 表格：简洁线框表，表头浅灰背景加粗
- 页眉：产品名称 + 页码
- 正文：9pt 宋体
- 上标字符 (³²°) → HTML <super> 渲染
- [待确认]：红色标注

依赖：reportlab
"""

import re
import sys
import hashlib
from pathlib import Path
from typing import List, Tuple

# 修复 Python 3.8 的 hashlib.md5 不支持 usedforsecurity 参数
# reportlab 内部调用 md5(data, usedforsecurity=False)
if not hasattr(hashlib, '_orig_md5'):
    _orig_md5 = hashlib.md5
    def _patched_md5(data=b'', usedforsecurity=True):
        return _orig_md5(data)
    hashlib.md5 = _patched_md5

# ============================================================
# 常量
# ============================================================

_FONT_SIMSUN = "C:/Windows/Fonts/simsun.ttc"
_FONT_SIMHEI = "C:/Windows/Fonts/simhei.ttf"

# 颜色 (R, G, B)
_CLR_REVIEW      = (0xCC, 0x00, 0x00)   # 红色 [待确认]
_CLR_LINE         = (0xAA, 0xAA, 0xAA)   # 灰色分隔线
_CLR_HEADER_FG    = (0x55, 0x55, 0x55)   # 页眉深灰字
_CLR_SECTION_BAR  = (0xC0, 0x00, 0x00)   # 章节标题左侧红色竖条
_CLR_SECTION_FG   = (0x00, 0x00, 0x00)   # 章节标题黑色字
_CLR_SUBTITLE_FG  = (0x00, 0x00, 0x00)   # 子标题黑色字
_CLR_TBL_BORDER   = (0x66, 0x66, 0x66)   # 表格边框灰
_CLR_TBL_HDR_BG   = (0xE8, 0xE8, 0xE8)   # 表头浅灰背景
_CLR_KV_LINE      = (0xCC, 0xCC, 0xCC)   # KV 行分隔线

# GHS 象形图参数
_GHS_PICT_SIZE = 48  # PDF 中显示的像素大小（points）
_GHS_ASSETS_DIR = Path(__file__).parent.parent / "assets" / "ghs"

# ============================================================
# GHS 象形图（PNG 图片嵌入）
# ============================================================

def _get_ghs_image(code, size=_GHS_PICT_SIZE):
    """获取 GHS 象形图 Image flowable（从 PNG 文件加载）"""
    from reportlab.platypus import Image as RLImage
    png_path = _GHS_ASSETS_DIR / f"{code}.png"
    if png_path.exists():
        return RLImage(str(png_path), width=size, height=size)
    return _create_ghs_pictogram_fallback(code, size)

def _create_ghs_pictogram_fallback(code, size=_GHS_PICT_SIZE):
    """PNG 文件不存在时的回退：reportlab Drawing"""
    from reportlab.graphics.shapes import Drawing, Polygon, String
    from reportlab.lib.colors import Color
    red = Color(0xC0/255, 0, 0)
    white = Color(1, 1, 1)
    black = Color(0, 0, 0)
    d = Drawing(size, size)
    cx, cy = size/2, size/2
    pad = 3
    half = (size - 2*pad) / 2
    diamond = Polygon(
        points=[cx, cy+half, cx+half, cy, cx, cy-half, cx-half, cy],
        fillColor=white, strokeColor=red, strokeWidth=2.0)
    d.add(diamond)
    d.add(String(cx-10, cy-4, code, fontSize=6, fillColor=black, fontName='Helvetica'))
    return d

def _parse_pictogram_codes(value):
    """从象形图文本提取 [(code, 中文名), ...]"""
    return re.findall(r'(GHS\d\d)\s*\(([^)]+)\)', value)


# ============================================================
# 文本处理工具
# ============================================================

def _fix_superscripts(text: str) -> str:
    """Unicode 上标/特殊字符 → HTML 标记"""
    text = text.replace('\u00b3', '<super>3</super>')   # ³
    text = text.replace('\u00b2', '<super>2</super>')   # ²
    text = text.replace('\u00b9', '<super>1</super>')   # ¹
    text = text.replace('\u2070', '<super>0</super>')   # ⁰
    text = text.replace('\u00b0', '<super>o</super>')   # °
    text = text.replace('\u2265', '>=')                 # ≥
    text = text.replace('\u2264', '<=')                 # ≤
    text = text.replace('\u00b1', '+/-')                # ±
    text = text.replace('\u2212', '-')                  # −
    text = text.replace('\u2014', '--')                 # —
    text = text.replace('\u2013', '-')                  # –
    text = text.replace('\u00b5', 'u')                  # µ
    return text


def _strip_md_format(text: str) -> str:
    """去除 Markdown 格式标记"""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'\s*<!--.*?-->', '', text)
    return text.strip()


def _sanitize_for_para(text: str) -> str:
    """为 reportlab Paragraph 准备文本：去 MD + 修复上标 + 转义 XML"""
    text = _strip_md_format(text)
    text = _fix_superscripts(text)
    # 占位符保护 super 标签
    placeholders = {}
    idx = [0]
    def _save_super(m):
        key = f'\x00SUP{idx[0]}\x00'
        placeholders[key] = m.group(0)
        idx[0] += 1
        return key
    text = re.sub(r'<super>\d+</super>|<super>o</super>', _save_super, text)
    # XML 转义
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    # 恢复 super 标签
    for key, val in placeholders.items():
        text = text.replace(key, val)
    return text


def _highlight_review(text: str) -> str:
    """将 [待确认] 标记为红色"""
    return text.replace('[待确认]', '<font color="#CC0000">[待确认]</font>')


# ============================================================
# Markdown 解析 → 结构化数据
# ============================================================

def parse_md(md_content: str) -> List[dict]:
    """
    将 SDS Markdown 解析为结构化块列表。

    块类型:
      {"type": "section", "title": "第X部分：..."}
      {"type": "subtitle", "title": "紧急概述"}
      {"type": "kv_table", "rows": [(label, value), ...]}
      {"type": "multi_table", "rows": [[cell, ...], ...]}
      {"type": "kv_line", "label": "...", "value": "..."}
      {"type": "list", "items": ["...", ...]}
      {"type": "text", "content": "..."}
    """
    blocks = []
    lines = md_content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line or line == '---':
            i += 1
            continue

        line = re.sub(r'\s*<!--.*?-->', '', line)

        # H1 章节标题: # 第X部分：...
        if line.startswith('# '):
            blocks.append({"type": "section", "title": line[2:].strip()})
            i += 1
            continue

        # 表格
        if line.startswith('|'):
            table_rows = []
            multi_col = False
            while i < len(lines) and lines[i].strip().startswith('|'):
                row_line = re.sub(r'\s*<!--.*?-->', '', lines[i].strip())
                if re.match(r'^\|[\s\-:|]+\|$', row_line):
                    i += 1
                    continue
                cells = [c.strip() for c in row_line.split('|')[1:-1]]
                if len(cells) > 2:
                    multi_col = True
                    table_rows.append(cells)
                elif len(cells) == 2:
                    table_rows.append(cells)
                elif len(cells) == 1:
                    table_rows.append([cells[0], ""])
                i += 1
            if table_rows:
                if multi_col:
                    blocks.append({"type": "multi_table", "rows": table_rows})
                else:
                    blocks.append({"type": "kv_table", "rows": [(r[0], r[1]) for r in table_rows]})
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

        # 粗体标签行: **标签**: 值  (kv_line，视为子标题级)
        m = re.match(r'\*\*(.+?)\*\*[：:]\s*(.*)', line)
        if m:
            label = m.group(1)
            value = m.group(2)
            if value.strip():
                blocks.append({"type": "kv_line", "label": label, "value": value})
            else:
                # 无值的粗体标签 → 视为子标题
                blocks.append({"type": "subtitle", "title": label})
            i += 1
            continue

        # 斜体独立行
        m = re.match(r'\*(.+?)\*', line)
        if m and m.group(1) == line[1:-1]:
            blocks.append({"type": "text", "content": line})
            i += 1
            continue

        blocks.append({"type": "text", "content": line})
        i += 1

    return blocks


# ============================================================
# reportlab PDF 渲染
# ============================================================

_fonts_registered = False

def _register_fonts():
    """注册中文字体"""
    global _fonts_registered
    if _fonts_registered:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    if Path(_FONT_SIMSUN).exists():
        pdfmetrics.registerFont(TTFont('SimSun', _FONT_SIMSUN, subfontIndex=0))
        try:
            pdfmetrics.registerFont(TTFont('SimSunBold', _FONT_SIMSUN, subfontIndex=1))
        except Exception:
            pdfmetrics.registerFont(TTFont('SimSunBold', _FONT_SIMSUN, subfontIndex=0))
        registerFontFamily('SimSun', normal='SimSun', bold='SimSunBold')

    if Path(_FONT_SIMHEI).exists():
        pdfmetrics.registerFont(TTFont('SimHei', _FONT_SIMHEI))
        registerFontFamily('SimHei', normal='SimHei', bold='SimHei')

    _fonts_registered = True


def generate_pdf(md_content: str, output_path: str, title: str = "SDS") -> str:
    """
    从 Markdown 生成 MSDS PDF（仿合规化学网真实 SDS 排版）

    排版特点：
    - 章节标题（第X部分）：大号粗体 + 左侧红色竖条
    - 子标题（紧急概述等）：粗体，中等字号
    - 键值对：标签(粗体)：值，行间细线分隔
    - 多列表格：带边框，表头浅灰背景
    - 页眉：产品名 | 页码
    - 页脚：化安通信息

    Args:
        md_content: SDS Markdown 内容
        output_path: PDF 输出路径
        title: 文档标题（用于页眉）

    Returns:
        PDF 文件路径
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import Color
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        KeepTogether
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    _register_fonts()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    PAGE_W, PAGE_H = A4   # 595.3 x 841.9
    MARGIN = 20 * mm
    CONTENT_W = PAGE_W - 2 * MARGIN

    # ---- 颜色 ----
    line_clr      = Color(*[c / 255 for c in _CLR_LINE])
    header_fg     = Color(*[c / 255 for c in _CLR_HEADER_FG])
    section_bar   = Color(*[c / 255 for c in _CLR_SECTION_BAR])
    tbl_border    = Color(*[c / 255 for c in _CLR_TBL_BORDER])
    tbl_hdr_bg    = Color(*[c / 255 for c in _CLR_TBL_HDR_BG])
    kv_line_clr   = Color(*[c / 255 for c in _CLR_KV_LINE])

    # ---- 字体 ----
    # 正文用宋体，粗体用黑体（SimSun 粗体变体不明显）
    FONT = 'SimSun' if Path(_FONT_SIMSUN).exists() else 'SimHei'
    FONT_BOLD = 'SimHei' if Path(_FONT_SIMHEI).exists() else FONT

    # ---- 字号 ----
    SZ_SECTION  = 12       # 章节标题（大号）
    SZ_SUBTITLE = 10       # 子标题（中号）
    SZ_BODY     = 9        # 正文
    SZ_TABLE    = 8.5      # 表格内文字
    SZ_HEADER   = 8        # 页眉

    # ---- 样式定义 ----

    # 章节标题样式（第X部分 — 大号，黑体加粗）
    style_section = ParagraphStyle(
        'Section', fontName=FONT_BOLD, fontSize=SZ_SECTION, leading=18,
        textColor=Color(0, 0, 0), alignment=TA_LEFT,
        spaceBefore=0, spaceAfter=0, wordWrap='CJK')

    # 子标题样式（紧急概述/GHS分类等 — 中号，黑体加粗）
    style_subtitle = ParagraphStyle(
        'Subtitle', fontName=FONT_BOLD, fontSize=SZ_SUBTITLE, leading=15,
        textColor=Color(0, 0, 0), alignment=TA_LEFT,
        spaceBefore=2 * mm, spaceAfter=0.5 * mm, wordWrap='CJK')

    # 正文样式
    style_body = ParagraphStyle(
        'Body', fontName=FONT, fontSize=SZ_BODY, leading=14,
        alignment=TA_LEFT, spaceAfter=0, wordWrap='CJK')

    # 表格标签样式（黑体加粗）
    style_tbl_label = ParagraphStyle(
        'TblLabel', fontName=FONT_BOLD, fontSize=SZ_TABLE, leading=12,
        alignment=TA_LEFT, wordWrap='CJK')

    # 表格值样式
    style_tbl_value = ParagraphStyle(
        'TblValue', fontName=FONT, fontSize=SZ_TABLE, leading=12,
        alignment=TA_LEFT, wordWrap='CJK')

    # 表格单元格样式
    style_tbl_cell = ParagraphStyle(
        'TblCell', fontName=FONT, fontSize=SZ_TABLE, leading=12,
        alignment=TA_LEFT, wordWrap='CJK')

    # 表格表头单元格样式（黑体加粗）
    style_tbl_cell_bold = ParagraphStyle(
        'TblCellBold', fontName=FONT_BOLD, fontSize=SZ_TABLE, leading=12,
        alignment=TA_LEFT, wordWrap='CJK')

    # KV 行标签样式（黑体加粗）
    style_kv_label = ParagraphStyle(
        'KVLabel', fontName=FONT_BOLD, fontSize=SZ_BODY, leading=14,
        alignment=TA_LEFT, wordWrap='CJK')

    # KV 行值样式
    style_kv_value = ParagraphStyle(
        'KVValue', fontName=FONT, fontSize=SZ_BODY, leading=14,
        alignment=TA_LEFT, wordWrap='CJK')

    # ---- 解析 MD ----
    blocks = parse_md(md_content)

    # ---- 页眉/页脚 ----
    page_num = [0]

    def header_footer(canvas, doc):
        page_num[0] += 1
        canvas.saveState()

        y_top = PAGE_H - 10 * mm
        y_hdr_line = y_top - 1.5 * mm
        y_bottom_line = MARGIN - 2 * mm
        y_footer = MARGIN - 5 * mm

        # ---- 页眉 ----
        canvas.setFont(FONT, SZ_HEADER)
        canvas.setFillColor(header_fg)
        canvas.drawString(MARGIN, y_top, f"{title}")
        canvas.drawRightString(PAGE_W - MARGIN, y_top, f"第 {page_num[0]} 页")
        # 页眉线
        canvas.setStrokeColor(line_clr)
        canvas.setLineWidth(0.3)
        canvas.line(MARGIN, y_hdr_line, PAGE_W - MARGIN, y_hdr_line)

        # ---- 页脚 ----
        canvas.setLineWidth(0.3)
        canvas.line(MARGIN, y_bottom_line, PAGE_W - MARGIN, y_bottom_line)
        canvas.setFont(FONT, 6.5)
        canvas.setFillColor(header_fg)
        canvas.drawCentredString(PAGE_W / 2, y_footer,
                                 "化安通 (HuaAnTong) 智能MSDS系统自动生成  |  GB/T 16483-2008 / GB/T 17519-2013")

        canvas.restoreState()

    # ---- 构建文档 ----
    doc = SimpleDocTemplate(
        str(output), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 2 * mm, bottomMargin=MARGIN)

    elements = []

    # ---- 红色竖条宽度 ----
    BAR_W = 2 * mm
    # ---- 内容区缩进（相对于章节标题） ----
    INDENT = 4 * mm
    INDENT_W = CONTENT_W - INDENT

    for block in blocks:
        btype = block["type"]

        # ==============================================================
        # 章节标题（第X部分）— 大号粗体 + 左侧红色竖条
        # ==============================================================
        if btype == "section":
            title_text = _sanitize_for_para(block["title"])

            # 用表格实现：左红色竖条 + 右标题文字
            bar_data = [[
                '',  # 红色竖条单元格（空内容，靠背景色）
                Paragraph(f'<b>{title_text}</b>', style_section),
            ]]
            bar_table = Table(bar_data, colWidths=[BAR_W, CONTENT_W - BAR_W])
            bar_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                # 左侧红色竖条
                ('BACKGROUND', (0, 0), (0, 0), section_bar),
                ('LEFTPADDING', (0, 0), (0, 0), 0),
                ('RIGHTPADDING', (0, 0), (0, 0), 0),
                # 标题文字区
                ('LEFTPADDING', (1, 0), (1, 0), 2 * mm),
                ('RIGHTPADDING', (1, 0), (1, 0), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 1.5 * mm),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5 * mm),
            ]))
            elements.append(Spacer(1, 4 * mm))
            elements.append(bar_table)
            # 标题下方细线
            elements.append(Spacer(1, 0.5 * mm))

        # ==============================================================
        # 子标题（粗体标签无值 → 如 "GHS分类", "预防措施"）
        # ==============================================================
        elif btype == "subtitle":
            sub_text = _sanitize_for_para(block["title"])
            elements.append(Spacer(1, 1.5 * mm))
            elements.append(Paragraph(f'<b>{sub_text}</b>', style_subtitle))

        # ==============================================================
        # 双列键值表格（无边框，仿真实 SDS 风格）
        # ==============================================================
        elif btype == "kv_table":
            label_w = INDENT_W * 0.30
            value_w = INDENT_W * 0.70
            table_data = []
            for label, value in block["rows"]:
                lbl = _sanitize_for_para(label)
                val = _sanitize_for_para(value)
                val = _highlight_review(val)
                table_data.append([
                    Paragraph(f'<b>{lbl}</b>', style_tbl_label),
                    Paragraph(val, style_tbl_value),
                ])
            if table_data:
                t = Table(table_data, colWidths=[label_w, value_w])
                t.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0.8 * mm),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0.8 * mm),
                    ('LINEBELOW', (0, 0), (-1, -1), 0.2, kv_line_clr),
                ]))
                # 缩进包裹
                wrap = Table([[Spacer(1, 0), t]], colWidths=[INDENT, INDENT_W])
                wrap.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))
                elements.append(wrap)

        # ==============================================================
        # 多列表格（如 S3 成分表、S14 运输信息）
        # ==============================================================
        elif btype == "multi_table":
            rows = block["rows"]
            ncols = max(len(r) for r in rows)
            if ncols == 4:
                col_w = [INDENT_W * 0.16, INDENT_W * 0.16,
                         INDENT_W * 0.12, INDENT_W * 0.56]
            elif ncols == 3:
                col_w = [INDENT_W * 0.25, INDENT_W * 0.30, INDENT_W * 0.45]
            else:
                first = INDENT_W * 0.25
                col_w = [first] + [(INDENT_W - first) / (ncols - 1)] * (ncols - 1)

            table_data = []
            for ri, row in enumerate(rows):
                cells_out = []
                for ci in range(ncols):
                    cell_text = _sanitize_for_para(row[ci]) if ci < len(row) else ""
                    cell_text = _highlight_review(cell_text)
                    if ri == 0:
                        cells_out.append(Paragraph(cell_text, style_tbl_cell_bold))
                    else:
                        cells_out.append(Paragraph(cell_text, style_tbl_cell))
                table_data.append(cells_out)
            if table_data:
                t = Table(table_data, colWidths=col_w)
                t.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 1.5 * mm),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 1.5 * mm),
                    ('TOPPADDING', (0, 0), (-1, -1), 0.8 * mm),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0.8 * mm),
                    ('BACKGROUND', (0, 0), (-1, 0), tbl_hdr_bg),
                    ('LINEBELOW', (0, 0), (-1, 0), 0.5, tbl_border),
                    ('LINEBELOW', (0, 1), (-1, -1), 0.2, kv_line_clr),
                    ('BOX', (0, 0), (-1, -1), 0.5, tbl_border),
                    ('LINEAFTER', (0, 0), (-2, -1), 0.2, kv_line_clr),
                ]))
                # 缩进包裹
                wrap = Table([[Spacer(1, 0), t]], colWidths=[INDENT, INDENT_W])
                wrap.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))
                elements.append(wrap)

        # ==============================================================
        # 标签: 值 行 — 作为 KV 行渲染（粗体标签 + 值）
        # ==============================================================
        elif btype == "kv_line":
            lbl = _sanitize_for_para(block["label"])

            # ---- 象形图特殊渲染：图像 + 文字 ----
            if block["label"].strip() == "象形图":
                pict_pairs = _parse_pictogram_codes(block["value"])
                if pict_pairs:
                    style_pict_label = ParagraphStyle(
                        'PictLabel', fontName=FONT, fontSize=7, leading=10,
                        alignment=TA_CENTER, wordWrap='CJK')
                    pict_cells = []
                    for code, cn_name in pict_pairs:
                        pict_img = _get_ghs_image(code)
                        mini_data = [
                            [pict_img],
                            [Paragraph(f'{code}<br/>({cn_name})', style_pict_label)],
                        ]
                        mini_w = _GHS_PICT_SIZE + 4
                        mini_t = Table(mini_data, colWidths=[mini_w])
                        mini_t.setStyle(TableStyle([
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                            ('LEFTPADDING', (0, 0), (-1, -1), 1),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 1),
                            ('TOPPADDING', (0, 0), (-1, -1), 1),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                        ]))
                        pict_cells.append(mini_t)

                    # 主行：标签 + 象形图
                    pict_row = [[
                        Paragraph(f'<b>{lbl}</b>', style_kv_label),
                    ] + pict_cells]
                    col_widths = [INDENT_W * 0.25] + [mini_w] * len(pict_cells)
                    pict_table = Table(pict_row, colWidths=col_widths)
                    pict_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (0, 0), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 0.5 * mm),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 0.5 * mm),
                    ]))
                    wrap = Table([[Spacer(1, 0), pict_table]], colWidths=[INDENT, INDENT_W])
                    wrap.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 0),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                    ]))
                    elements.append(wrap)
                    continue

            # ---- 普通 KV 行渲染 ----
            val = _sanitize_for_para(block["value"])
            val = _highlight_review(val)
            kv_w_label = INDENT_W * 0.25
            kv_w_value = INDENT_W * 0.75
            kv_data = [[
                Paragraph(f'<b>{lbl}</b>', style_kv_label),
                Paragraph(val, style_kv_value),
            ]]
            kv_t = Table(kv_data, colWidths=[kv_w_label, kv_w_value])
            kv_t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0.5 * mm),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0.5 * mm),
            ]))
            # 缩进包裹
            wrap = Table([[Spacer(1, 0), kv_t]], colWidths=[INDENT, INDENT_W])
            wrap.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(wrap)

        # ==============================================================
        # 列表项
        # ==============================================================
        elif btype == "list":
            for item in block["items"]:
                item_text = _sanitize_for_para(item)
                item_text = _highlight_review(item_text)
                list_style = ParagraphStyle(
                    'ListItem', parent=style_body,
                    leftIndent=INDENT + 3 * mm)
                elements.append(Paragraph(f'- {item_text}', list_style))
                elements.append(Spacer(1, 0.2 * mm))

        # ==============================================================
        # 普通文本
        # ==============================================================
        elif btype == "text":
            text = _sanitize_for_para(block["content"])
            text = _highlight_review(text)
            raw = _strip_md_format(block["content"])
            if raw.startswith('本文档由') or raw.startswith('*'):
                elements.append(Spacer(1, 2 * mm))
                elements.append(Paragraph(
                    f'<i>{text.strip("*")}</i>',
                    ParagraphStyle('Disclaimer', parent=style_body,
                                   fontSize=7, textColor=header_fg)))
            else:
                text_style = ParagraphStyle(
                    'TextIndent', parent=style_body,
                    leftIndent=INDENT)
                elements.append(Paragraph(text, text_style))
                elements.append(Spacer(1, 0.3 * mm))

    # ---- 生成 PDF ----
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
