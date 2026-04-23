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
                      output_path: str = "", use_llm: bool = False) -> PipelineResult:
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
        sources = pool.get_source_summary()

        print(f"  字段覆盖: {len(pool.evidences)}个, 覆盖率: {coverage*100:.0f}%")
        print(f"  缺失字段: {pool.missing_fields}")

        # L4: 分类（纯净物直接从GHS分类构建）
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

        self._save_output(output_path, content)

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
                         output_path: str = "", use_llm: bool = False) -> PipelineResult:
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
            product_name or "混合物",
            use_llm=use_llm, version="1.0", revision_date=rev_date,
        )

        # L6: 审查
        print(f"\n[L6] 自动审查...")
        reviewer = self.MSDSReviewer.from_content(content)
        review_report = reviewer.review()

        # 保存
        if not output_path:
            safe_name = (product_name or "mixture").replace(" ", "_")
            output_path = str(OUTPUT_DIR / "mixture" / f"MSDS_{safe_name}.md")

        self._save_output(output_path, content)

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
            success = mgr.add(query, name_cn=name, use_llm=True)
            if success:
                # 重新加载retriever的KB
                self.retriever.kb = self.retriever._load_kb()
                return mgr.data.get(query)
        except Exception as e:
            print(f"  [WARN] kb_manager获取失败: {e}")
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

    def _save_output(self, path: str, content: str):
        """保存输出文件"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  已保存: {path}")


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

    args = parser.parse_args()

    if not args.query and not args.mixture:
        parser.print_help()
        sys.exit(1)

    pipeline = SDSPipeline()

    if args.query:
        result = pipeline.generate_pure(
            query=args.query,
            product_name=args.name,
            output_path=args.output,
            use_llm=args.use_llm,
        )
    elif args.mixture:
        result = pipeline.generate_mixture(
            components_str=args.mixture,
            product_name=args.name,
            output_path=args.output,
            use_llm=args.use_llm,
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


if __name__ == "__main__":
    main()
