"""
化安通 (HuaAnTong) - MSDS自动生成系统
MSDS 生成与文档管理 API 路由
"""

import json
import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.msds_service import MSDSService
from app.schemas.msds import (
    PureMSDSRequest, MixtureMSDSRequest,
    MSDSDocumentListItem, MSDSDocumentResponse, MSDSTaskResponse,
)
from app.schemas.common import PageResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/msds", tags=["MSDS 生成与管理"])


@router.post("/generate-pure")
async def generate_pure_msds(
    data: PureMSDSRequest,
    db: Session = Depends(get_db),
):
    """生成纯净物 MSDS（异步任务）"""
    service = MSDSService(db)
    company_info = None
    if data.company_info:
        company_info = data.company_info.model_dump()
    task_id = service.generate_pure(data.cas_or_name, company_info)
    return {"task_id": task_id, "status": "generating", "message": "任务已创建"}


@router.post("/generate-mixture")
async def generate_mixture_msds(
    data: MixtureMSDSRequest,
    db: Session = Depends(get_db),
):
    """生成混合物 MSDS（异步任务）"""
    service = MSDSService(db)
    company_info = None
    if data.company_info:
        company_info = data.company_info.model_dump()
    components = [comp.model_dump() for comp in data.components]
    task_id = service.generate_mixture(data.product_name, components, company_info)
    return {"task_id": task_id, "status": "generating", "message": "任务已创建"}


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: int,
    db: Session = Depends(get_db),
):
    """查询生成任务状态"""
    service = MSDSService(db)
    result = service.get_task_status(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    doc_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """MSDS 文档列表"""
    service = MSDSService(db)
    items, total = service.list_documents(page, page_size, doc_type, status)
    return {
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "cas_number": item.cas_number,
                "doc_type": item.doc_type,
                "status": item.status,
                "created_at": str(item.created_at) if item.created_at else None,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: int,
    db: Session = Depends(get_db),
):
    """获取文档详情（JSON 数据）"""
    service = MSDSService(db)
    doc = service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    result = {
        "id": doc.id,
        "title": doc.title,
        "cas_number": doc.cas_number,
        "doc_type": doc.doc_type,
        "status": doc.status,
        "company_info": doc.company_info,
        "error_message": doc.error_message,
        "created_at": str(doc.created_at) if doc.created_at else None,
        "updated_at": str(doc.updated_at) if doc.updated_at else None,
    }

    if doc.data_json:
        try:
            result["data"] = json.loads(doc.data_json)
        except json.JSONDecodeError:
            result["data"] = None
    else:
        result["data"] = None

    if doc.review_result:
        try:
            result["review_result"] = json.loads(doc.review_result)
        except json.JSONDecodeError:
            result["review_result"] = None
    else:
        result["review_result"] = None

    return result


@router.get("/documents/{doc_id}/markdown")
async def get_document_markdown(
    doc_id: int,
    db: Session = Depends(get_db),
):
    """获取 Markdown 格式"""
    service = MSDSService(db)
    md = service.get_document_markdown(doc_id)
    if md is None:
        raise HTTPException(status_code=404, detail="文档不存在或无内容")
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


@router.get("/documents/{doc_id}/pdf")
async def export_pdf(
    doc_id: int,
    db: Session = Depends(get_db),
):
    """导出 PDF"""
    service = MSDSService(db)
    pdf_path = service.export_pdf(doc_id)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="导出失败")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=Path(pdf_path).name,
    )


@router.get("/documents/{doc_id}/word")
async def export_word(
    doc_id: int,
    db: Session = Depends(get_db),
):
    """导出 Word"""
    service = MSDSService(db)
    docx_path = service.export_word(doc_id)
    if not docx_path:
        raise HTTPException(status_code=404, detail="导出失败")
    return FileResponse(
        path=docx_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=Path(docx_path).name,
    )


@router.post("/documents/{doc_id}/review")
async def review_document(
    doc_id: int,
    db: Session = Depends(get_db),
):
    """审查文档质量"""
    service = MSDSService(db)
    result = service.review_document(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="文档不存在")
    return result


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
):
    """删除文档"""
    service = MSDSService(db)
    if not service.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"message": "删除成功"}
