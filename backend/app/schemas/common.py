"""
化安通 (HuaAnTong) - MSDS自动生成系统
通用 Pydantic Schema
"""

from typing import Generic, TypeVar, Optional, List, Any
from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """分页参数"""
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(20, ge=1, le=100, description="每页数量")


class PageResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(0, description="总数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页数量")


class APIResponse(BaseModel, Generic[T]):
    """统一 API 响应"""
    code: int = Field(200, description="状态码")
    message: str = Field("success", description="消息")
    data: Optional[T] = Field(None, description="数据")


class SystemStatus(BaseModel):
    """系统状态"""
    status: str = Field("running", description="系统状态")
    version: str = Field("1.0.0", description="版本号")
    llm_provider: str = Field("", description="当前LLM提供商")
    kb_count: int = Field(0, description="知识库化学品数量")
    db_count: int = Field(0, description="数据库化学品数量")
    doc_count: int = Field(0, description="MSDS文档数量")
