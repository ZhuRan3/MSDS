"""
化安通 (HuaAnTong) - MSDS自动生成系统
MSDS 文档相关 Pydantic Schema
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# -----------------------------------------------------------
# 请求 Schema
# -----------------------------------------------------------

class CompanyInfo(BaseModel):
    """企业信息"""
    name: str = Field("________________", description="企业名称")
    address: str = Field("________________", description="企业地址")
    phone: str = Field("________________", description="联系电话")
    emergency: str = Field("________________", description="应急电话")


class PureMSDSRequest(BaseModel):
    """纯物质 MSDS 生成请求"""
    cas_or_name: str = Field(..., description="CAS号或化学品名称")
    company_info: Optional[CompanyInfo] = Field(None, description="企业信息")


class MixtureComponentInput(BaseModel):
    """混合物组分输入"""
    name: str = Field(..., description="组分名称")
    cas: str = Field("", description="CAS号")
    concentration: float = Field(..., gt=0, le=100, description="浓度(%)")


class MixtureMSDSRequest(BaseModel):
    """混合物 MSDS 生成请求"""
    product_name: str = Field(..., description="产品名称")
    components: List[MixtureComponentInput] = Field(..., min_length=2, description="组分列表")
    company_info: Optional[CompanyInfo] = Field(None, description="企业信息")


# -----------------------------------------------------------
# 响应 Schema
# -----------------------------------------------------------

class MSDSDocumentListItem(BaseModel):
    """MSDS 文档列表项"""
    id: int
    title: str
    cas_number: str = ""
    doc_type: str = "pure"
    status: str = "generating"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class MSDSDocumentResponse(MSDSDocumentListItem):
    """MSDS 文档完整响应"""
    data_json: str = "{}"
    markdown_content: str = ""
    review_result: str = "{}"
    company_info: str = "{}"
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class MSDSTaskResponse(BaseModel):
    """MSDS 任务响应"""
    task_id: int = Field(..., description="任务/文档ID")
    status: str = Field("generating", description="任务状态")
    progress: str = Field("", description="进度描述")
    result: Optional[MSDSDocumentResponse] = Field(None, description="结果（完成时返回）")


class MSDSReviewResult(BaseModel):
    """MSDS 审查结果"""
    status: str = Field("PASS", description="综合判定: PASS/FAIL/WARN")
    completeness: Optional[Dict[str, Any]] = None
    ghs_consistency: Optional[Dict[str, Any]] = None
    data_consistency: Optional[Dict[str, Any]] = None
    format_compliance: Optional[Dict[str, Any]] = None
    professional_check: Optional[Dict[str, Any]] = None
    issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    failed_checks: Optional[List[str]] = None
