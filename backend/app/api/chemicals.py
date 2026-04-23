"""
化安通 (HuaAnTong) - MSDS自动生成系统
化学品管理 API 路由
"""

import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.chemical_service import ChemicalService
from app.schemas.chemical import ChemicalCreate, ChemicalResponse, ChemicalListItem
from app.schemas.common import APIResponse, PageResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chemicals", tags=["化学品管理"])


def _chemical_to_response(chem) -> dict:
    """将 Chemical 模型转为响应字典"""
    result = {
        "id": chem.id,
        "cas_number": chem.cas_number,
        "chemical_name_cn": chem.chemical_name_cn,
        "chemical_name_en": chem.chemical_name_en,
        "molecular_formula": chem.molecular_formula,
        "molecular_weight": chem.molecular_weight,
        "chemical_family": chem.chemical_family,
        "signal_word": chem.signal_word,
        "flash_point": chem.flash_point,
        "boiling_point": chem.boiling_point,
        "melting_point": chem.melting_point,
        "density": chem.density,
        "solubility": chem.solubility,
        "ld50_oral": chem.ld50_oral,
        "ld50_dermal": chem.ld50_dermal,
        "lc50_inhalation": chem.lc50_inhalation,
        "un_number": chem.un_number,
        "data_source": chem.data_source,
        "completeness": chem.completeness,
    }
    try:
        result["ghs_classifications"] = json.loads(chem.ghs_classifications or "[]")
    except (json.JSONDecodeError, TypeError):
        result["ghs_classifications"] = []
    try:
        result["pictograms"] = json.loads(chem.pictograms or "[]")
    except (json.JSONDecodeError, TypeError):
        result["pictograms"] = []
    try:
        result["hazard_statements"] = json.loads(chem.hazard_statements or "[]")
    except (json.JSONDecodeError, TypeError):
        result["hazard_statements"] = []
    return result


@router.get("")
async def list_chemicals(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    family: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """化学品列表（分页、搜索、筛选）"""
    service = ChemicalService(db)
    items, total = service.list_chemicals(page, page_size, search, family)
    return {
        "items": [_chemical_to_response(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/search")
async def search_chemicals(
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    """搜索化学品（支持 CAS、中英文名）"""
    service = ChemicalService(db)
    results = service.search_chemicals(q)
    return {"items": results, "total": len(results)}


@router.get("/{cas}")
async def get_chemical(cas: str, db: Session = Depends(get_db)):
    """获取化学品详情"""
    service = ChemicalService(db)
    chemical = service.get_chemical(cas)
    if not chemical:
        raise HTTPException(status_code=404, detail=f"化学品不存在: {cas}")
    return _chemical_to_response(chemical)


@router.post("")
async def add_chemical(
    data: ChemicalCreate,
    db: Session = Depends(get_db),
):
    """添加化学品到知识库"""
    service = ChemicalService(db)
    chemical = service.add_chemical(data.cas_or_name, data.name_cn, use_llm=True)
    if not chemical:
        raise HTTPException(status_code=400, detail="添加失败，无法从PubChem获取数据")
    return _chemical_to_response(chemical)


@router.put("/{cas}")
async def update_chemical(cas: str, db: Session = Depends(get_db)):
    """从PubChem更新化学品数据"""
    service = ChemicalService(db)
    chemical = service.add_chemical(cas, use_llm=True)
    if not chemical:
        raise HTTPException(status_code=400, detail="更新失败")
    return _chemical_to_response(chemical)


@router.delete("/{cas}")
async def delete_chemical(cas: str, db: Session = Depends(get_db)):
    """删除化学品"""
    service = ChemicalService(db)
    if not service.delete_chemical(cas):
        raise HTTPException(status_code=404, detail="化学品不存在")
    return {"message": "删除成功"}


@router.post("/fetch-pubchem")
async def fetch_pubchem(data: ChemicalCreate):
    """从PubChem获取化学品数据（预览，不保存）"""
    from app.core.kb_manager import PubChemFetcher
    fetcher = PubChemFetcher()
    result = fetcher.get_all_data(data.cas_or_name)
    if not result:
        raise HTTPException(status_code=404, detail="PubChem未找到该化学品")
    return result
