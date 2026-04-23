"""
化安通 (HuaAnTong) - MSDS自动生成系统
化学品相关 Pydantic Schema
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class ChemicalBase(BaseModel):
    """化学品基础信息"""
    cas_number: str = Field(..., description="CAS号")
    chemical_name_cn: str = Field("", description="中文名称")
    chemical_name_en: str = Field("", description="英文名称")
    molecular_formula: str = Field("", description="分子式")
    molecular_weight: str = Field("", description="分子量")
    chemical_family: str = Field("", description="化学类别")


class ChemicalCreate(BaseModel):
    """创建化学品请求"""
    cas_or_name: str = Field(..., description="CAS号或化学品名称")
    name_cn: Optional[str] = Field("", description="中文名称（可选）")


class ChemicalUpdate(BaseModel):
    """更新化学品请求"""
    chemical_name_cn: Optional[str] = None
    chemical_name_en: Optional[str] = None
    molecular_formula: Optional[str] = None
    molecular_weight: Optional[str] = None
    chemical_family: Optional[str] = None
    ghs_classifications: Optional[List[str]] = None
    pictograms: Optional[List[str]] = None
    signal_word: Optional[str] = None
    hazard_statements: Optional[List[str]] = None
    flash_point: Optional[str] = None
    boiling_point: Optional[str] = None
    melting_point: Optional[str] = None
    density: Optional[str] = None
    solubility: Optional[str] = None
    ld50_oral: Optional[str] = None
    ld50_dermal: Optional[str] = None
    lc50_inhalation: Optional[str] = None
    un_number: Optional[str] = None


class ChemicalResponse(ChemicalBase):
    """化学品完整响应"""
    id: int
    ghs_classifications: List[str] = Field(default_factory=list, description="GHS分类")
    pictograms: List[str] = Field(default_factory=list, description="象形图")
    signal_word: str = Field("", description="信号词")
    hazard_statements: List[str] = Field(default_factory=list, description="危险说明H码")
    flash_point: str = Field("", description="闪点")
    boiling_point: str = Field("", description="沸点")
    melting_point: str = Field("", description="熔点")
    density: str = Field("", description="相对密度")
    solubility: str = Field("", description="溶解性")
    ld50_oral: str = Field("", description="经口LD50")
    ld50_dermal: str = Field("", description="经皮LD50")
    lc50_inhalation: str = Field("", description="吸入LC50")
    un_number: str = Field("", description="UN编号")
    data_source: str = Field("", description="数据来源")
    completeness: str = Field("", description="数据完整度")

    model_config = {"from_attributes": True}


class ChemicalListItem(BaseModel):
    """化学品列表项（简化版）"""
    id: int
    cas_number: str
    chemical_name_cn: str
    chemical_name_en: str = ""
    molecular_formula: str = ""
    chemical_family: str = ""
    signal_word: str = ""
    data_source: str = ""

    model_config = {"from_attributes": True}
