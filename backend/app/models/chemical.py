"""
化安通 (HuaAnTong) - MSDS自动生成系统
化学品数据模型
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from app.database import Base


class Chemical(Base):
    """化学品知识库表"""
    __tablename__ = "chemicals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cas_number = Column(String(50), unique=True, nullable=False, index=True)
    chemical_name_cn = Column(String(255), default="", comment="中文名称")
    chemical_name_en = Column(String(255), default="", comment="英文名称")
    molecular_formula = Column(String(100), default="", comment="分子式")
    molecular_weight = Column(String(50), default="", comment="分子量")
    chemical_family = Column(String(100), default="", comment="化学类别/家族")

    # GHS 分类信息（JSON 字符串）
    ghs_classifications = Column(Text, default="[]", comment="GHS分类列表(JSON)")
    pictograms = Column(Text, default="[]", comment="象形图列表(JSON)")
    signal_word = Column(String(50), default="", comment="信号词")
    hazard_statements = Column(Text, default="[]", comment="危险说明H码(JSON)")

    # 理化性质
    flash_point = Column(String(100), default="", comment="闪点")
    boiling_point = Column(String(100), default="", comment="沸点")
    melting_point = Column(String(100), default="", comment="熔点")
    density = Column(String(100), default="", comment="相对密度")
    solubility = Column(String(255), default="", comment="溶解性")

    # 毒理学数据
    ld50_oral = Column(String(100), default="", comment="经口LD50")
    ld50_dermal = Column(String(100), default="", comment="经皮LD50")
    lc50_inhalation = Column(String(100), default="", comment="吸入LC50")

    # 运输信息
    un_number = Column(String(20), default="", comment="UN编号")

    # 元信息
    data_source = Column(String(100), default="", comment="数据来源")
    completeness = Column(String(50), default="", comment="数据完整度")
    raw_data = Column(Text, default="{}", comment="原始完整数据(JSON)")

    # 时间戳
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def __repr__(self):
        return f"<Chemical(cas={self.cas_number}, name={self.chemical_name_cn})>"
