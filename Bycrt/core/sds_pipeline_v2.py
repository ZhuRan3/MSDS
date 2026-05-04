"""
化安通 (HuaAnTong) MSDS自动生成系统 - 七层统一Pipeline

串联全部7层：
  L1 数据源(db/) → L2 实体标准化 → L3 证据检索融合
  → L4 分类引擎 → L5 SDS生成 → L6 自动审查 → L7 输出归档

用法：
  python sds_pipeline_v2.py --query "乙醇"
  python sds_pipeline_v2.py --query "64-17-5" --name "乙醇"
  python sds_pipeline_v2.py --mixture "乙醇:64-17-5:30,甲醇:67-56-1:30,丙酮:67-64-1:15,丙三醇:56-81-5:25"
  python sds_pipeline_v2.py --query "苯酚" --output output/pure/MSDS_phenol.md
"""

import json
import re
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

# 项目根 = core/ 的上级 (Bycrt/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

# 确保输出目录存在
(OUTPUT_DIR / "pure").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "mixture").mkdir(parents=True, exist_ok=True)


@dataclass
class PipelineResult:
    """Pipeline输出结果"""
    markdown: str                     # 完整16节SDS
    review_report: Dict = field(default_factory=dict)   # L6审查报告
    review_flags: List[str] = field(default_factory=list)  # 待确认字段
    sources: Dict[str, str] = field(default_factory=dict)   # 字段来源摘要
    risk_level: str = "LOW"           # HIGH/MEDIUM/LOW
    file_path: str = ""               # 保存路径
    coverage: float = 0.0             # 数据覆盖率
    query: str = ""                   # 原始查询
    version: str = "1.0"              # 文档版本号
    revision_date: str = ""           # 修订日期
    edit_json_path: str = ""          # 导出的可编辑JSON路径（--export-json时）


class SDSPipeline:
    """七层统一Pipeline"""

    def __init__(self):
        self.retriever = None
        self._init_modules()

    def _init_modules(self):
        """延迟加载各层模块"""
        core_dir = Path(__file__).resolve().parent
        if str(core_dir) not in sys.path:
            sys.path.insert(0, str(core_dir))

        from evidence_fusion import EvidenceRetriever
        from sds_generator import SDSGenerator, generate_pure_sds, generate_mixture_sds
        from msds_reviewer import MSDSReviewer

        self.retriever = EvidenceRetriever()
        self.SDSGenerator = SDSGenerator
        self.generate_pure_sds = generate_pure_sds
        self.generate_mixture_sds = generate_mixture_sds
        self.MSDSReviewer = MSDSReviewer

    def generate_pure(self, query: str, product_name: str = "",
                      output_path: str = "", use_llm: bool = False,
                      pdf: bool = False) -> PipelineResult:
        """
        纯净物SDS生成全流程

        Args:
            query: CAS号或化学品名称
            product_name: 产品名称（可选）
            output_path: 输出路径（可选）
            use_llm: 是否使用LLM增强
        """
        print(f"\n{'='*60}")
        print(f"化安通 MSDS Pipeline - 纯净物模式")
        print(f"{'='*60}")
        print(f"查询: {query}")

        # L2+L3: 证据检索融合
        print(f"\n[L3] 证据检索...")
        pool = self.retriever.retrieve(query)

        if not pool.evidences:
            # 尝试通过kb_manager添加
            print(f"  [INFO] 本地无数据，尝试从PubChem获取...")
            kb_data = self._fetch_and_cache(query)
            if kb_data:
                pool = self.retriever.retrieve(query)
            else:
                print(f"  [FAIL] 无法获取 {query} 的数据")
                return PipelineResult(
                    markdown="", query=query,
                    review_flags=[f"无法获取{query}的数据"],
                    risk_level="HIGH",
                )

        # 导出为dict用于SDS生成
        data_dict = pool.to_dict()
        coverage = self.retriever.get_coverage(pool)
        quality_coverage = self.retriever.get_quality_coverage(pool)
        sources = pool.get_source_summary()

        print(f"  字段覆盖: {len(pool.evidences)}个, 覆盖率: {coverage*100:.0f}%")
        print(f"  高质量覆盖率: {quality_coverage*100:.0f}% (conf≥0.7)")
        print(f"  缺失字段: {pool.missing_fields}")

        # 数据冲突警告
        if pool.conflicts:
            print(f"  [WARN] 检测到 {len(pool.conflicts)} 个数据冲突:")
            for c in pool.conflicts:
                print(f"    - {c['field']}: {c['values']}")
        low_conf = self.retriever.get_low_confidence_fields(pool)
        if low_conf:
            print(f"  [WARN] {len(low_conf)} 个低置信度字段: {', '.join(low_conf[:5])}")

        # L4: 分类（纯净物直接从GHS分类构建）
        # 将冲突信息注入data_dict，供生成器使用
        if pool.conflicts:
            data_dict["_data_conflicts"] = [
                f"{c['field']}: 多源数据不一致(已取最高优先级来源)" for c in pool.conflicts
            ]
        classifications = self._build_pure_classifications(data_dict)

        # L5: SDS生成
        print(f"\n[L5] SDS生成...")
        from datetime import datetime as _dt
        rev_date = _dt.now().strftime("%Y-%m-%d")
        content, review_flags = self.generate_pure_sds(
            data_dict, product_name or pool.name_cn,
            use_llm=use_llm, version="1.0", revision_date=rev_date,
        )

        # L6: 自动审查
        print(f"\n[L6] 自动审查...")
        reviewer = self.MSDSReviewer.from_content(content)
        review_report = reviewer.review()

        # 保存
        if not output_path:
            safe_name = (product_name or pool.name_cn or query).replace(" ", "_")
            output_path = str(OUTPUT_DIR / "pure" / f"MSDS_{safe_name}.md")

        self._save_output(output_path, content, generate_pdf=pdf)

        # 来源摘要
        print(f"\n[L7] 输出完成: {output_path}")
        print(f"  审查状态: {review_report.get('status', 'N/A')}")
        print(f"  风险等级: {review_report.get('risk_assessment', {}).get('risk_level', 'N/A')}")

        return PipelineResult(
            markdown=content,
            review_report=review_report,
            review_flags=review_flags,
            sources=sources,
            risk_level=review_report.get("risk_assessment", {}).get("risk_level", "LOW"),
            file_path=output_path,
            coverage=coverage,
            query=query,
            version="1.0",
            revision_date=rev_date,
        )

    def generate_mixture(self, components_str: str, product_name: str = "",
                         output_path: str = "", use_llm: bool = False,
                         pdf: bool = False) -> PipelineResult:
        """
        混合物SDS生成全流程

        Args:
            components_str: 组分字符串 "名称:CAS:浓度,名称:CAS:浓度"
            product_name: 产品名称
            output_path: 输出路径
            use_llm: 是否使用LLM增强
        """
        print(f"\n{'='*60}")
        print(f"化安通 MSDS Pipeline - 混合物模式")
        print(f"{'='*60}")

        # 解析组分
        components_input = self._parse_components(components_str)
        print(f"组分数量: {len(components_input)}")

        # L2+L3: 对每个组分检索
        from mixture_calculator import build_component, MixtureCalculator

        components_data = []
        components_objs = []
        pool_coverage_list = []

        for name, cas, conc in components_input:
            print(f"\n[L3] 检索组分: {name} ({cas})")
            pool = self.retriever.retrieve(cas)

            if not pool.evidences:
                kb_data = self._fetch_and_cache(cas, name)
                if kb_data:
                    pool = self.retriever.retrieve(cas)

            if pool.evidences:
                data_dict = pool.to_dict()
                # 添加sds_generator.set_components()需要的键名
                data_dict["name"] = data_dict.get("chemical_name_cn", name)
                data_dict["cas"] = data_dict.get("cas_number", cas)
                data_dict["concentration"] = f"{conc}%"
                if pool.name_cn:
                    data_dict.setdefault("chemical_name_cn", pool.name_cn)
                components_data.append(data_dict)
                comp_cov = self.retriever.get_coverage(pool)
                pool_coverage_list.append(comp_cov)
                print(f"  OK - {pool.name_cn}, {len(pool.evidences)}字段, 覆盖率{comp_cov*100:.0f}%")
            else:
                components_data.append({
                    "chemical_name_cn": name, "cas_number": cas,
                    "name": name, "cas": cas, "concentration": f"{conc}%",
                })
                pool_coverage_list.append(0.0)
                print(f"  WARN - 未找到 {name} 的数据")

            # 构建MixtureCalculator组分对象
            comp_obj = build_component(name, cas, conc)
            components_objs.append(comp_obj)

        # 计算混合物覆盖率：按浓度加权的平均覆盖率
        total_conc = sum(conc for _, _, conc in components_input)
        if total_conc > 0:
            mixture_coverage = sum(
                cov * conc / total_conc
                for cov, (_, _, conc) in zip(pool_coverage_list, components_input)
            )
        else:
            mixture_coverage = 0.0

        # L4: 混合物分类计算
        print(f"\n[L4] 混合物分类计算...")
        calculator = MixtureCalculator(components_objs)
        mix_result = calculator.calculate_all()

        # 转为SDS生成器需要的格式
        classifications = mix_result.classifications
        print(f"  分类结果: {len(classifications)}项")
        for cls in classifications:
            print(f"    - {cls.get('hazard', '')} ({cls.get('h_code', '')})")

        # L5: SDS生成
        print(f"\n[L5] SDS生成...")
        from datetime import datetime as _dt
        rev_date = _dt.now().strftime("%Y-%m-%d")
        content, review_flags = self.generate_mixture_sds(
            components_data, classifications,
            product_name,
            use_llm=use_llm, version="1.0", revision_date=rev_date,
            calc_result=mix_result,
        )

        # L6: 审查
        print(f"\n[L6] 自动审查...")
        reviewer = self.MSDSReviewer.from_content(content)
        review_report = reviewer.review()

        # 保存
        if not output_path:
            safe_name = (product_name or "mixture_" + datetime.now().strftime("%Y%m%d%H%M%S")).replace(" ", "_")
            output_path = str(OUTPUT_DIR / "mixture" / f"MSDS_{safe_name}.md")

        self._save_output(output_path, content, generate_pdf=pdf)

        print(f"\n[L7] 输出完成: {output_path}")
        print(f"  审查状态: {review_report.get('status', 'N/A')}")

        return PipelineResult(
            markdown=content,
            review_report=review_report,
            review_flags=review_flags,
            sources={},
            risk_level=review_report.get("risk_assessment", {}).get("risk_level", "LOW"),
            file_path=output_path,
            coverage=mixture_coverage,
            query=components_str,
            version="1.0",
            revision_date=rev_date,
        )

    def _build_pure_classifications(self, data_dict: dict) -> List[dict]:
        """从KB数据构建纯净物分类结果"""
        from sds_generator import SDSGenerator
        gen = SDSGenerator()
        ghs_list = data_dict.get("ghs_classifications", [])
        if not isinstance(ghs_list, list):
            ghs_list = [str(ghs_list)] if ghs_list else []

        classifications = []
        for ghs_cls in ghs_list:
            h_code = gen.templates.hazard_to_h_code(ghs_cls)
            signal = gen.templates.hazard_to_signal_word(ghs_cls)
            picts = gen.templates.hazard_to_pictograms(ghs_cls)
            classifications.append({
                "hazard": ghs_cls,
                "h_code": h_code,
                "signal": signal,
                "pictograms": picts,
            })
        return classifications

    def _fetch_and_cache(self, query: str, name: str = "") -> Optional[dict]:
        """通过kb_manager获取并缓存数据"""
        try:
            from kb_manager import KnowledgeBaseManager
            mgr = KnowledgeBaseManager()
            # 如果query不是CAS号（不匹配 \d+-\d+-\d+），尝试翻译为英文名
            cas_pattern = re.compile(r'^\d+-\d+-\d+$')
            actual_query = query
            if not cas_pattern.match(query):
                # 中文名或英文名，PubChem可能不支持中文
                translated = self._translate_to_english(query)
                if translated:
                    actual_query = translated
                    print(f"  [INFO] 中文名 '{query}' → 英文名 '{translated}'")
            success = mgr.add(actual_query, name_cn=name or query, use_llm=True)
            if success:
                # 重新加载retriever的KB
                self.retriever.kb = self.retriever._load_kb()
                return mgr.data.get(actual_query)
        except Exception as e:
            print(f"  [WARN] kb_manager获取失败: {e}")
        return None

    # 名称翻译映射（从 name_translations.json 加载，延迟初始化）
    _cn_en_map: Optional[Dict[str, str]] = None

    def _get_cn_en_map(self) -> Dict[str, str]:
        """加载中英文名称映射"""
        if SDSPipeline._cn_en_map is None:
            try:
                map_path = PROJECT_ROOT / "db" / "name_translations.json"
                with open(map_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                SDSPipeline._cn_en_map = data.get("cn_to_en", {})
            except Exception:
                SDSPipeline._cn_en_map = {}
        return SDSPipeline._cn_en_map

    def _translate_to_english(self, chinese_name: str) -> Optional[str]:
        """将中文化学品名翻译为英文名（用于PubChem查询）"""
        # 先检查是否已经是英文名
        if re.match(r'^[a-zA-Z0-9\s\-_,.]+$', chinese_name):
            return chinese_name
        # 从 name_translations.json 加载映射
        cn_en_map = self._get_cn_en_map()
        if chinese_name in cn_en_map:
            return cn_en_map[chinese_name]
        # 尝试LLM翻译
        try:
            sys_path = str(Path(__file__).resolve().parent)
            if sys_path not in sys.path:
                sys.path.insert(0, sys_path)
            from msds_llm_client import llm_infer
            prompt = f"请将以下化学品中文名称翻译为最常见的英文名称，只返回英文名，不要其他内容：{chinese_name}"
            result = llm_infer(prompt, "")
            if result and len(result.strip()) < 50:
                return result.strip()
        except:
            pass
        return None

    def _parse_components(self, components_str: str) -> List[tuple]:
        """解析组分字符串 "名称:CAS:浓度,..." """
        result = []
        for part in components_str.split(","):
            part = part.strip()
            fields = part.split(":")
            if len(fields) >= 3:
                name = fields[0].strip()
                cas = fields[1].strip()
                conc = float(fields[2].strip())
                result.append((name, cas, conc))
            elif len(fields) == 2:
                # CAS:浓度
                cas = fields[0].strip()
                conc = float(fields[1].strip())
                result.append((cas, cas, conc))
        return result

    def export_edit_json(self, md_content: str, md_path: str) -> str:
        """
        导出MSDS为结构化JSON，供人工编辑

        Args:
            md_content: MSDS Markdown内容
            md_path: 原始MD文件路径（用于推导JSON路径）

        Returns:
            JSON文件路径
        """
        from msds_editor import MSDSEditor
        editor = MSDSEditor()
        json_path = str(Path(md_path).with_suffix(".json"))
        editor.export_json(md_content, json_path)
        print(f"  已导出可编辑JSON: {json_path}")
        return json_path

    def apply_override(self, md_content: str, override_path: str,
                        output_path: str = "", generate_pdf: bool = False) -> str:
        """
        应用override JSON修改MSDS内容

        Args:
            md_content: 原始MSDS Markdown
            override_path: override JSON文件路径
            output_path: 输出路径（可选）
            generate_pdf: 是否同时生成PDF

        Returns:
            修改后的Markdown
        """
        from msds_editor import MSDSEditor
        editor = MSDSEditor()
        editor.parse_md(md_content)
        new_content = editor.apply_override_file(override_path)

        if not output_path:
            p = Path(override_path)
            output_path = str(p.with_name(p.stem.replace("_edit", "") + "_v2.md"))

        if generate_pdf:
            editor.save_md_with_pdf(output_path)
        else:
            editor.save_md(output_path)

        editor.print_diff_summary()
        print(f"  已保存修改后MSDS: {output_path}")
        return new_content

    def _save_output(self, path: str, content: str, generate_pdf: bool = False):
        """保存输出文件（MD + 可选 PDF）"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  已保存: {path}")

        if generate_pdf:
            try:
                from pdf_generator import generate_pdf
                pdf_path = str(p.with_suffix('.pdf'))
                generate_pdf(content, pdf_path, title=p.stem)
                print(f"  已保存PDF: {pdf_path}")
            except Exception as e:
                print(f"  [WARN] PDF生成失败: {e}")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="化安通 MSDS Pipeline - 七层统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python sds_pipeline_v2.py --query "乙醇"
  python sds_pipeline_v2.py --query "64-17-5" --name "乙醇"
  python sds_pipeline_v2.py --mixture "乙醇:64-17-5:30,甲醇:67-56-1:30,丙酮:67-64-1:15,丙三醇:56-81-5:25"
  python sds_pipeline_v2.py --query "苯酚" --output output/pure/MSDS_phenol.md
        """,
    )
    parser.add_argument("--query", type=str, help="查询化学品（CAS号或名称）")
    parser.add_argument("--name", type=str, default="", help="化学品中文名称")
    parser.add_argument("--mixture", type=str, help="混合物组分（格式: 名称:CAS:浓度,...）")
    parser.add_argument("--output", type=str, default="", help="输出文件路径")
    parser.add_argument("--json", action="store_true", help="以JSON格式输出元数据")
    parser.add_argument("--use-llm", action="store_true", help="使用LLM增强文本生成")
    parser.add_argument("--pdf", action="store_true", help="同时输出PDF格式")
    parser.add_argument("--export-json", action="store_true",
                        help="导出结构化JSON供人工编辑（与--query/--mixture配合使用）")
    parser.add_argument("--override", type=str, default="",
                        help="应用override JSON修改已有MSDS（传入JSON文件路径）")
    parser.add_argument("--review-edit", action="store_true",
                        help="生成后自动审查高风险节并导出可编辑JSON")

    args = parser.parse_args()

    if not args.query and not args.mixture and not args.override:
        parser.print_help()
        sys.exit(1)

    pipeline = SDSPipeline()

    # 模式1: 应用override修改已有MSDS
    if args.override and not args.query and not args.mixture:
        override_path = args.override
        if not Path(override_path).exists():
            print(f"  [ERROR] override文件不存在: {override_path}")
            sys.exit(1)
        # 读取override JSON中记录的原始MD路径，或从JSON路径推导
        with open(override_path, "r", encoding="utf-8") as f:
            ov_data = json.load(f)
        # 尝试找到原始MD文件
        md_path = override_path.replace(".json", ".md").replace("_edit", "")
        if not Path(md_path).exists():
            # 尝试 _v2.md
            md_path = override_path.replace("_edit.json", ".md").replace(".json", ".md")
        if not Path(md_path).exists():
            print(f"  [ERROR] 找不到原始MSDS文件，请用 --output 指定输出路径")
            sys.exit(1)

        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        output_path = args.output or ""
        new_content = pipeline.apply_override(
            md_content, override_path,
            output_path=output_path, generate_pdf=args.pdf,
        )
        print(f"\n完成。修改后的文件已保存。")
        return

    if args.query:
        result = pipeline.generate_pure(
            query=args.query,
            product_name=args.name,
            output_path=args.output,
            use_llm=args.use_llm,
            pdf=args.pdf,
        )
    elif args.mixture:
        result = pipeline.generate_mixture(
            components_str=args.mixture,
            product_name=args.name,
            output_path=args.output,
            use_llm=args.use_llm,
            pdf=args.pdf,
        )
    else:
        parser.print_help()
        sys.exit(1)

    # 输出结果摘要
    if args.json:
        meta = {
            "query": result.query,
            "file_path": result.file_path,
            "coverage": f"{result.coverage*100:.0f}%",
            "risk_level": result.risk_level,
            "review_status": result.review_report.get("status"),
            "review_flags": result.review_flags,
            "sources": result.sources,
            "version": result.version,
            "revision_date": result.revision_date,
        }
        print(f"\n--- Pipeline元数据 ---")
        print(json.dumps(meta, ensure_ascii=False, indent=2))

    # --export-json: 导出结构化JSON供人工编辑
    if args.export_json or args.review_edit:
        json_path = pipeline.export_edit_json(result.markdown, result.file_path)
        result.edit_json_path = json_path

    # --review-edit: 审查高风险节并提示
    if args.review_edit:
        from msds_editor import MSDSEditor
        editor = MSDSEditor()
        editor.parse_md(result.markdown)
        issues = editor.review_high_risk()
        if issues:
            print(f"\n{'='*60}")
            print(f"  高风险节审查报告")
            print(f"{'='*60}")
            for issue in issues:
                icon = {"high": "!!", "medium": "!", "low": "~"}[issue["severity"]]
                print(f"  [{icon}] 节{issue['section']} {issue['title']}")
                print(f"      问题: {issue['issue']}")
                print(f"      建议: {issue['suggestion']}")
            print(f"\n  请编辑以下JSON文件修改问题后，使用 --override 应用修改:")
            print(f"  {result.edit_json_path}")
        else:
            print(f"\n  高风险审查通过，未发现问题。")


if __name__ == "__main__":
    main()
