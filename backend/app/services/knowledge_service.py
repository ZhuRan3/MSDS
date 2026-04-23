"""
化安通 (HuaAnTong) - MSDS自动生成系统
知识库服务层 - 封装知识库管理功能
"""

import logging
import time
from typing import Dict, Any, List

from app.core.kb_manager import KnowledgeBaseManager
from app.core.msds_rag_client import ChemicalRAGRetriever

logger = logging.getLogger(__name__)


class KnowledgeService:
    """知识库管理服务"""

    def __init__(self, db=None):
        self.db = db
        self.kb_manager = KnowledgeBaseManager()
        self.rag = ChemicalRAGRetriever()

    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        kb_count = len(self.kb_manager.data)
        rag_kb_count = len(self.rag.kb.chemicals)

        # 统计化学类别分布
        families = {}
        for cas, chem in self.kb_manager.data.items():
            family = chem.get("chemical_family", "未分类")
            families[family] = families.get(family, 0) + 1

        return {
            "kb_count": kb_count,
            "rag_kb_count": rag_kb_count,
            "families": families,
        }

    def batch_add(self, cas_list: List[str], use_llm: bool = True) -> Dict[str, Any]:
        """
        批量添加化学品到知识库

        Args:
            cas_list: CAS号列表
            use_llm: 是否使用LLM推断

        Returns:
            批量操作结果
        """
        results = {
            "total": len(cas_list),
            "success": 0,
            "failed": 0,
            "details": [],
        }

        for cas in cas_list:
            cas = cas.strip()
            if not cas:
                continue

            try:
                success = self.kb_manager.add(cas, use_llm=use_llm)
                if success:
                    results["success"] += 1
                    results["details"].append({"cas": cas, "status": "success"})
                else:
                    results["failed"] += 1
                    results["details"].append({"cas": cas, "status": "failed", "reason": "PubChem查询失败"})

                # 避免请求过快
                time.sleep(0.5)

            except Exception as e:
                results["failed"] += 1
                results["details"].append({"cas": cas, "status": "failed", "reason": str(e)})
                logger.error(f"批量添加化学品失败: {cas}, error={e}")

        return results

    def search(self, query: str) -> List[Dict]:
        """搜索知识库中的化学品"""
        results = []
        kb_results = self.kb_manager.search(query)
        for cas, chem_data in kb_results:
            results.append({
                "cas_number": cas,
                "chemical_name_cn": chem_data.get("chemical_name_cn", ""),
                "chemical_name_en": chem_data.get("chemical_name_en", ""),
                "molecular_formula": chem_data.get("molecular_formula", ""),
                "chemical_family": chem_data.get("chemical_family", ""),
            })
        return results

    def remove(self, cas: str) -> bool:
        """从知识库移除化学品"""
        return self.kb_manager.remove(cas)

    def update(self, cas: str) -> bool:
        """更新知识库中的化学品数据"""
        return self.kb_manager.update(cas)
