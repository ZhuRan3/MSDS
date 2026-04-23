"""
化安通 (HuaAnTong) - MSDS自动生成系统
化学品服务层 - 封装核心模块，提供化学品管理功能
"""

import json
import logging
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.models.chemical import Chemical
from app.core.kb_manager import KnowledgeBaseManager, PubChemFetcher
from app.core.msds_rag_client import ChemicalRAGRetriever

logger = logging.getLogger(__name__)


class ChemicalService:
    """化学品管理服务"""

    def __init__(self, db: Session):
        self.db = db
        self.kb_manager = KnowledgeBaseManager()
        self.rag = ChemicalRAGRetriever()

    def list_chemicals(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        family: Optional[str] = None,
    ) -> tuple:
        """
        获取化学品列表

        Returns:
            (items, total) 元组
        """
        query = self.db.query(Chemical)

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Chemical.cas_number.like(search_term),
                    Chemical.chemical_name_cn.like(search_term),
                    Chemical.chemical_name_en.like(search_term),
                    Chemical.molecular_formula.like(search_term),
                )
            )

        if family:
            query = query.filter(Chemical.chemical_family == family)

        total = query.count()
        items = (
            query.order_by(Chemical.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return items, total

    def get_chemical(self, cas: str) -> Optional[Chemical]:
        """根据CAS号获取化学品"""
        return self.db.query(Chemical).filter(Chemical.cas_number == cas).first()

    def get_chemical_by_id(self, chem_id: int) -> Optional[Chemical]:
        """根据ID获取化学品"""
        return self.db.query(Chemical).filter(Chemical.id == chem_id).first()

    def search_chemicals(self, query: str) -> List[Dict]:
        """
        搜索化学品（先查数据库，再查知识库）

        Returns:
            匹配的化学品数据列表
        """
        results = []

        # 1. 从数据库搜索
        db_results = self.list_chemicals(search=query, page_size=10)
        for item in db_results[0]:
            results.append(self._chemical_to_dict(item))

        # 2. 从知识库搜索
        kb_results = self.kb_manager.search(query)
        for cas, chem_data in kb_results:
            # 避免重复
            if not any(r.get("cas_number") == cas for r in results):
                results.append({
                    "cas_number": cas,
                    "chemical_name_cn": chem_data.get("chemical_name_cn", ""),
                    "chemical_name_en": chem_data.get("chemical_name_en", ""),
                    "molecular_formula": chem_data.get("molecular_formula", ""),
                    "chemical_family": chem_data.get("chemical_family", ""),
                    "data_source": "knowledge_base",
                })

        return results

    def add_chemical(self, cas: str, name: str = "", use_llm: bool = True) -> Optional[Chemical]:
        """
        添加化学品（从PubChem获取数据，可选LLM推断）

        Args:
            cas: CAS号或化学品名称
            name: 中文名称（可选）
            use_llm: 是否使用LLM推断

        Returns:
            新创建的Chemical对象
        """
        # 1. 先添加到知识库
        success = self.kb_manager.add(cas, name, use_llm=use_llm)
        if not success:
            logger.error(f"添加化学品失败: {cas}")
            return None

        # 2. 从知识库读取数据
        kb_data = self.kb_manager.data.get(cas)
        if not kb_data:
            return None

        # 3. 检查数据库是否已存在
        existing = self.get_chemical(kb_data.get("cas_number", cas))
        if existing:
            # 更新
            self._update_from_kb(existing, kb_data)
            self.db.commit()
            self.db.refresh(existing)
            return existing

        # 4. 创建新记录
        chemical = Chemical()
        self._update_from_kb(chemical, kb_data)
        self.db.add(chemical)
        self.db.commit()
        self.db.refresh(chemical)

        return chemical

    def update_chemical(self, cas: str, update_data: Dict) -> Optional[Chemical]:
        """更新化学品信息"""
        chemical = self.get_chemical(cas)
        if not chemical:
            return None

        for key, value in update_data.items():
            if hasattr(chemical, key) and value is not None:
                # JSON字段处理
                if key in ("ghs_classifications", "pictograms", "hazard_statements"):
                    setattr(chemical, key, json.dumps(value, ensure_ascii=False))
                else:
                    setattr(chemical, key, value)

        self.db.commit()
        self.db.refresh(chemical)
        return chemical

    def delete_chemical(self, cas: str) -> bool:
        """删除化学品"""
        chemical = self.get_chemical(cas)
        if not chemical:
            return False

        self.db.delete(chemical)
        self.db.commit()
        return True

    def fetch_from_pubchem(self, cas_or_name: str) -> Optional[Dict]:
        """
        从PubChem获取化学品数据（不保存到数据库）

        Returns:
            PubChem原始数据字典
        """
        fetcher = PubChemFetcher()
        return fetcher.get_all_data(cas_or_name)

    def get_stats(self) -> Dict[str, Any]:
        """获取化学品统计信息"""
        total = self.db.query(Chemical).count()
        kb_count = len(self.kb_manager.data)

        # 按化学类别统计
        families = (
            self.db.query(Chemical.chemical_family, func.count(Chemical.id))
            .group_by(Chemical.chemical_family)
            .all()
        )

        return {
            "total": total,
            "kb_count": kb_count,
            "families": {f[0] or "未分类": f[1] for f in families},
        }

    def _update_from_kb(self, chemical: Chemical, kb_data: Dict):
        """从知识库数据更新Chemical模型"""
        chemical.cas_number = kb_data.get("cas_number", "")
        chemical.chemical_name_cn = kb_data.get("chemical_name_cn", "")
        chemical.chemical_name_en = kb_data.get("chemical_name_en", "")
        chemical.molecular_formula = kb_data.get("molecular_formula", "")
        chemical.molecular_weight = kb_data.get("molecular_weight", "")
        chemical.chemical_family = kb_data.get("chemical_family", "")

        ghs = kb_data.get("ghs_classifications", [])
        chemical.ghs_classifications = json.dumps(ghs, ensure_ascii=False) if isinstance(ghs, list) else str(ghs)

        pictograms = kb_data.get("pictograms", [])
        chemical.pictograms = json.dumps(pictograms, ensure_ascii=False) if isinstance(pictograms, list) else str(pictograms)

        chemical.signal_word = kb_data.get("signal_word", "")

        hazard_stmts = kb_data.get("hazard_statements", [])
        chemical.hazard_statements = json.dumps(hazard_stmts, ensure_ascii=False) if isinstance(hazard_stmts, list) else str(hazard_stmts)

        chemical.flash_point = kb_data.get("flash_point", "")
        chemical.boiling_point = kb_data.get("boiling_point", "")
        chemical.melting_point = kb_data.get("melting_point", "")
        chemical.density = kb_data.get("density", "")
        chemical.solubility = kb_data.get("solubility", "")
        chemical.ld50_oral = kb_data.get("ld50_oral", "")
        chemical.ld50_dermal = kb_data.get("ld50_dermal", "")
        chemical.lc50_inhalation = kb_data.get("lc50_inhalation", "")
        chemical.un_number = kb_data.get("un_number", "")
        chemical.data_source = kb_data.get("data_source", "")
        chemical.completeness = kb_data.get("completeness", "")
        chemical.raw_data = json.dumps(kb_data, ensure_ascii=False)

    @staticmethod
    def _chemical_to_dict(chemical: Chemical) -> Dict:
        """将Chemical模型转为字典"""
        result = {
            "id": chemical.id,
            "cas_number": chemical.cas_number,
            "chemical_name_cn": chemical.chemical_name_cn,
            "chemical_name_en": chemical.chemical_name_en,
            "molecular_formula": chemical.molecular_formula,
            "molecular_weight": chemical.molecular_weight,
            "chemical_family": chemical.chemical_family,
            "signal_word": chemical.signal_word,
            "data_source": chemical.data_source,
        }
        try:
            result["ghs_classifications"] = json.loads(chemical.ghs_classifications or "[]")
        except (json.JSONDecodeError, TypeError):
            result["ghs_classifications"] = []
        try:
            result["pictograms"] = json.loads(chemical.pictograms or "[]")
        except (json.JSONDecodeError, TypeError):
            result["pictograms"] = []
        try:
            result["hazard_statements"] = json.loads(chemical.hazard_statements or "[]")
        except (json.JSONDecodeError, TypeError):
            result["hazard_statements"] = []
        return result
