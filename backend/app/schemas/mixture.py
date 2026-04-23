"""
化安通 (HuaAnTong) - MSDS自动生成系统
混合物计算相关 Pydantic Schema
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ComponentInput(BaseModel):
    """混合物组分输入"""
    name: str = Field(..., description="组分名称")
    cas: str = Field("", description="CAS号")
    concentration: float = Field(..., gt=0, le=100, description="浓度(%)")
    ld50_oral: Optional[float] = Field(None, description="经口LD50 (mg/kg)")
    ghs_classifications: Optional[List[str]] = Field(None, description="GHS分类列表")


class MixtureCalculateRequest(BaseModel):
    """混合物GHS分类计算请求"""
    components: List[ComponentInput] = Field(..., min_length=2, description="组分列表")


class MixtureCalculateResponse(BaseModel):
    """混合物GHS分类计算响应"""
    classifications: List[Dict[str, Any]] = Field(default_factory=list, description="分类结果")
    h_codes: List[str] = Field(default_factory=list, description="H码汇总")
    signal_word: str = Field("", description="信号词")
    flammability_class: str = Field("", description="易燃性分类")
    ate_oral: Optional[float] = Field(None, description="经口ATE值")
    ate_dermal: Optional[float] = Field(None, description="经皮ATE值")
    ate_inhalation: Optional[float] = Field(None, description="吸入ATE值")
    unknown_percentage: float = Field(0.0, description="未知毒性组分比例")
    calculation_log: List[str] = Field(default_factory=list, description="计算过程日志")
