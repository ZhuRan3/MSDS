"""
化安通 (HuaAnTong) - MSDS自动生成系统
知识库管理 API 路由
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.knowledge_service import KnowledgeService
from app.services.chemical_service import ChemicalService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["知识库管理"])


class BatchAddRequest(BaseModel):
    """批量添加请求"""
    cas_list: List[str]
    use_llm: bool = True


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """知识库统计信息"""
    service = KnowledgeService(db)
    return service.get_stats()


@router.post("/batch-add")
async def batch_add(
    data: BatchAddRequest,
    db: Session = Depends(get_db),
):
    """批量添加化学品"""
    service = ChemicalService(db)
    results = []
    for cas in data.cas_list:
        cas = cas.strip()
        if not cas:
            continue
        chemical = service.add_chemical(cas, use_llm=data.use_llm)
        if chemical:
            results.append({"cas": cas, "status": "success"})
        else:
            results.append({"cas": cas, "status": "failed"})
    return {"results": results, "total": len(results)}
