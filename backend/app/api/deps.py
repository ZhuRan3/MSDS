"""
化安通 (HuaAnTong) - MSDS自动生成系统
API 公共依赖注入
"""

from typing import Generator
from sqlalchemy.orm import Session
from app.database import get_db as _get_db
from app.services.chemical_service import ChemicalService
from app.services.msds_service import MSDSService
from app.services.knowledge_service import KnowledgeService


def get_db() -> Generator:
    """获取数据库会话"""
    return _get_db()


def get_chemical_service(db: Session = None) -> ChemicalService:
    """获取化学品服务"""
    if db is None:
        from app.database import SessionLocal
        db = SessionLocal()
    return ChemicalService(db)


def get_msds_service(db: Session = None) -> MSDSService:
    """获取MSDS服务"""
    if db is None:
        from app.database import SessionLocal
        db = SessionLocal()
    return MSDSService(db)


def get_knowledge_service(db: Session = None) -> KnowledgeService:
    """获取知识库服务"""
    if db is None:
        from app.database import SessionLocal
        db = SessionLocal()
    return KnowledgeService(db)
