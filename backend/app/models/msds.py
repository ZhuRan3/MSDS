"""
化安通 (HuaAnTong) - MSDS自动生成系统
MSDS 文档数据模型
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from app.database import Base


class MSDSDocument(Base):
    """MSDS 文档表"""
    __tablename__ = "msds_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), default="", comment="文档标题")
    cas_number = Column(String(50), default="", index=True, comment="关联CAS号")
    doc_type = Column(String(20), default="pure", comment="文档类型: pure/mixture")
    status = Column(String(20), default="generating", comment="状态: generating/completed/failed")

    # 16部分数据（JSON 字符串）
    data_json = Column(Text, default="{}", comment="16部分数据(JSON)")
    # 生成的 Markdown 内容
    markdown_content = Column(Text, default="", comment="Markdown全文")
    # 审查结果（JSON 字符串）
    review_result = Column(Text, default="{}", comment="审查结果(JSON)")
    # 企业信息（JSON 字符串）
    company_info = Column(Text, default="{}", comment="企业信息(JSON)")
    # 错误信息
    error_message = Column(Text, nullable=True, comment="错误信息")

    # 时间戳
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def __repr__(self):
        return f"<MSDSDocument(id={self.id}, title={self.title}, status={self.status})>"
