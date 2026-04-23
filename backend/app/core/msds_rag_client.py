"""
RAG知识库检索模块
化安通 (HuaAnTong) AI MSDS自动生成系统

基于化学品参考数据库的RAG检索系统
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

from app.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# 知识库结构
# ============================================================

class ChemicalKnowledgeBase:
    """化学品知识库"""

    def __init__(self):
        self.chemicals = {}  # cas -> chemical data
        self.formula_index = {}  # formula pattern -> [cas]
        self.family_index = {}  # chemical family -> [cas]
        self.name_index = {}  # name keywords -> [(cas, score)]
        self._load_knowledge_base()

    def _load_knowledge_base(self):
        """加载知识库"""
        db_file = settings.kb_file
        if db_file.exists():
            try:
                with open(db_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for cas, chem in data.items():
                        self.chemicals[cas] = chem
                        self._index_chemical(cas, chem)
                logger.info(f"知识库已加载: {len(self.chemicals)} 种化学品")
            except Exception as e:
                logger.error(f"知识库加载失败: {e}")
        else:
            logger.warning(f"知识库文件不存在: {db_file}")

    def _index_chemical(self, cas: str, chem: Dict):
        """索引单个化学品"""
        # 按化学家族索引
        family = chem.get('chemical_family', '')
        if family:
            if family not in self.family_index:
                self.family_index[family] = []
            self.family_index[family].append(cas)

        # 按分子式索引（提取碳原子数）
        formula = chem.get('molecular_formula', '')
        if formula:
            c_match = re.search(r'C(\d*)', formula)
            if c_match:
                c_count = int(c_match.group(1) or '0')
                if c_count not in self.formula_index:
                    self.formula_index[c_count] = []
                self.formula_index[c_count].append(cas)

        # 按名称索引（分词）
        names = []
        cn_name = chem.get('chemical_name_cn', '')
        en_name = chem.get('chemical_name_en', '')
        synonyms = chem.get('synonyms', [])

        if cn_name:
            names.append(cn_name)
        if en_name:
            names.append(en_name)
        names.extend(synonyms)

        for name in names:
            keywords = self._extract_keywords(name)
            for kw in keywords:
                if kw not in self.name_index:
                    self.name_index[kw] = []
                self.name_index[kw].append((cas, len(kw)))

    def _extract_keywords(self, text: str) -> List[str]:
        """提取中英文关键词"""
        keywords = []
        chinese = re.findall(r'[\u4e00-\u9fa5]+', text)
        keywords.extend(chinese)
        english = re.findall(r'[a-zA-Z]+', text)
        keywords.extend([w.lower() for w in english if len(w) > 2])
        return keywords

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        检索最相关的化学品数据

        Args:
            query: CAS号、化学名、分子式等
            top_k: 返回前k个结果

        Returns:
            相关化学品数据列表
        """
        results = []

        # 1. CAS号精确匹配
        query_clean = query.replace('-', '').strip()
        for cas in self.chemicals:
            if cas.replace('-', '') == query_clean:
                results.append((cas, 100))

        # 2. CAS号包含匹配
        if not results:
            for cas in self.chemicals:
                if query_clean in cas.replace('-', ''):
                    results.append((cas, 90))

        # 3. 化学名匹配
        if not results:
            query_lower = query.lower()
            for cas, chem in self.chemicals.items():
                cn_name = chem.get('chemical_name_cn', '').lower()
                if query_lower in cn_name or cn_name in query_lower:
                    results.append((cas, 85))
                    continue
                en_name = chem.get('chemical_name_en', '').lower()
                if query_lower in en_name or en_name in query_lower:
                    results.append((cas, 80))
                    continue
                synonyms = chem.get('synonyms', [])
                for syn in synonyms:
                    if query_lower in syn.lower():
                        results.append((cas, 75))
                        break

        # 4. 关键词匹配
        if not results:
            keywords = self._extract_keywords(query)
            kw_scores = {}
            for kw in keywords:
                if kw in self.name_index:
                    for cas, kw_len in self.name_index[kw]:
                        score = kw_len * 5
                        if cas in kw_scores:
                            kw_scores[cas] += score
                        else:
                            kw_scores[cas] = score
            results = [(cas, score) for cas, score in kw_scores.items()]

        # 5. 化学家族匹配
        if not results:
            for family in self.family_index:
                if family in query:
                    for cas in self.family_index[family]:
                        results.append((cas, 60))
                    break

        # 去重并排序
        seen = set()
        unique_results = []
        for cas, score in results:
            if cas not in seen:
                seen.add(cas)
                unique_results.append((cas, score))
        unique_results.sort(key=lambda x: x[1], reverse=True)

        # 返回top_k个结果
        top_results = []
        for cas, score in unique_results[:top_k]:
            chem = self.chemicals[cas].copy()
            chem['_relevance_score'] = score
            top_results.append(chem)

        return top_results

    def get_by_cas(self, cas: str) -> Optional[Dict]:
        """根据CAS号获取化学品数据"""
        return self.chemicals.get(cas)

    def get_by_family(self, family: str) -> List[Dict]:
        """根据化学家族获取化学品列表"""
        cas_list = self.family_index.get(family, [])
        return [self.chemicals[cas] for cas in cas_list if cas in self.chemicals]

    @property
    def count(self) -> int:
        return len(self.chemicals)


# ============================================================
# RAG检索器
# ============================================================

class ChemicalRAGRetriever:
    """化学品RAG检索器"""

    def __init__(self):
        self.kb = ChemicalKnowledgeBase()

    def retrieve_for_msds(self, query: str) -> Dict:
        """
        为MSDS生成检索相关化学品数据

        Returns:
            {
                'has_knowledge': True/False,
                'retrieved_chemicals': [...],
                'primary_chemical': {...} or None,
                'context': "用于LLM的上下文字符串"
            }
        """
        retrieved = self.kb.retrieve(query, top_k=3)

        if not retrieved:
            return {
                'has_knowledge': False,
                'retrieved_chemicals': [],
                'primary_chemical': None,
                'context': ''
            }

        primary = retrieved[0] if retrieved else None
        context = self._build_context(retrieved)

        return {
            'has_knowledge': True,
            'retrieved_chemicals': retrieved,
            'primary_chemical': primary,
            'context': context
        }

    def _build_context(self, chemicals: List[Dict]) -> str:
        """构建用于LLM的上下文"""
        context_parts = ["参考化学品知识库数据："]

        for i, chem in enumerate(chemicals, 1):
            score = chem.get('_relevance_score', 0)
            context_parts.append(f"\n【参考化学品 {i}】(相关度:{score}%)")
            context_parts.append(f"  名称: {chem.get('chemical_name_cn', 'N/A')} ({chem.get('chemical_name_en', 'N/A')})")
            context_parts.append(f"  CAS号: {chem.get('cas_number', 'N/A')}")
            context_parts.append(f"  分子式: {chem.get('molecular_formula', 'N/A')}")
            context_parts.append(f"  化学家族: {chem.get('chemical_family', 'N/A')}")

            # 危险性信息
            ghs = chem.get('ghs_classifications', [])
            if ghs:
                context_parts.append(f"  GHS分类: {', '.join(ghs)}")

            hazard = chem.get('hazard_statements', [])
            if hazard:
                context_parts.append(f"  危险说明: {', '.join(hazard)}")

            # 物理性质
            props = []
            if chem.get('flash_point'):
                props.append(f"闪点:{chem.get('flash_point')}")
            if chem.get('boiling_point'):
                props.append(f"沸点:{chem.get('boiling_point')}")
            if chem.get('melting_point'):
                props.append(f"熔点:{chem.get('melting_point')}")
            if props:
                context_parts.append(f"  理化性质: {', '.join(props)}")

            # 毒理学数据
            ld50 = chem.get('ld50_oral', '')
            if ld50:
                context_parts.append(f"  急性毒性LD50(经口): {ld50}")

            # 急救措施
            first_aid = chem.get('first_aid_measures', {})
            if first_aid:
                context_parts.append(f"  急救措施: {first_aid}")

            # 运输信息
            un = chem.get('un_number', '')
            if un:
                context_parts.append(f"  UN编号: {un}")

        return '\n'.join(context_parts)
