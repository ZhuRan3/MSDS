"""
化安通 (HuaAnTong) - MSDS自动生成系统
FastAPI 应用入口 + 静态文件托管
"""

import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.api import chemicals, msds, knowledge, mixture

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    logger.info("化安通 MSDS 系统启动中...")
    init_db()
    logger.info("数据库初始化完成")

    # 将 JSON 知识库中的数据同步到 SQLite
    _sync_knowledge_base()

    yield
    logger.info("化安通 MSDS 系统关闭")


def _sync_knowledge_base():
    """将 chemical_db.json 中的数据同步到 SQLite"""
    import json
    from app.database import SessionLocal
    from app.models.chemical import Chemical

    kb_file = settings.kb_file
    if not kb_file.exists():
        logger.info("知识库文件不存在，跳过同步")
        return

    db = SessionLocal()
    try:
        with open(kb_file, "r", encoding="utf-8") as f:
            kb_data = json.load(f)

        synced = 0
        for cas, chem_data in kb_data.items():
            existing = db.query(Chemical).filter(Chemical.cas_number == cas).first()
            if not existing:
                chemical = Chemical()
                chemical.cas_number = cas
                chemical.chemical_name_cn = chem_data.get("chemical_name_cn", "")
                chemical.chemical_name_en = chem_data.get("chemical_name_en", "")
                chemical.molecular_formula = chem_data.get("molecular_formula", "")
                chemical.molecular_weight = str(chem_data.get("molecular_weight", ""))
                chemical.chemical_family = chem_data.get("chemical_family", "")

                ghs = chem_data.get("ghs_classifications", [])
                chemical.ghs_classifications = json.dumps(ghs, ensure_ascii=False) if isinstance(ghs, list) else str(ghs)

                pictograms = chem_data.get("pictograms", [])
                chemical.pictograms = json.dumps(pictograms, ensure_ascii=False) if isinstance(pictograms, list) else str(pictograms)

                chemical.signal_word = chem_data.get("signal_word", "")

                hazard_stmts = chem_data.get("hazard_statements", [])
                chemical.hazard_statements = json.dumps(hazard_stmts, ensure_ascii=False) if isinstance(hazard_stmts, list) else str(hazard_stmts)

                chemical.flash_point = chem_data.get("flash_point", "")
                chemical.boiling_point = chem_data.get("boiling_point", "")
                chemical.melting_point = chem_data.get("melting_point", "")
                chemical.density = chem_data.get("density", "")
                chemical.solubility = chem_data.get("solubility", "")
                chemical.ld50_oral = chem_data.get("ld50_oral", "")
                chemical.ld50_dermal = chem_data.get("ld50_dermal", "")
                chemical.lc50_inhalation = chem_data.get("lc50_inhalation", "")
                chemical.un_number = chem_data.get("un_number", "")
                chemical.data_source = chem_data.get("data_source", "knowledge_base")
                chemical.completeness = chem_data.get("completeness", "")
                chemical.raw_data = json.dumps(chem_data, ensure_ascii=False)

                db.add(chemical)
                synced += 1

        if synced > 0:
            db.commit()
            logger.info(f"同步 {synced} 条知识库数据到 SQLite")
        else:
            logger.info("知识库数据已是最新")
    except Exception as e:
        logger.error(f"同步知识库失败: {e}")
        db.rollback()
    finally:
        db.close()


# ============================================================
# FastAPI 应用实例
# ============================================================

app = FastAPI(
    title="化安通 MSDS 管理系统",
    description="AI 驱动的化学品安全技术说明书(MSDS/SDS)自动生成系统",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 注册 API 路由
# ============================================================

app.include_router(chemicals.router, prefix="/api")
app.include_router(msds.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(mixture.router, prefix="/api")


# ============================================================
# 系统状态接口
# ============================================================

@app.get("/api/system/status", tags=["系统"])
async def system_status():
    """系统状态"""
    import os
    from app.database import SessionLocal
    from app.models.chemical import Chemical
    from app.models.msds import MSDSDocument

    db = SessionLocal()
    try:
        kb_count = db.query(Chemical).count()
        doc_count = db.query(MSDSDocument).count()
    finally:
        db.close()

    # 检测当前 LLM 提供商
    provider = "未配置"
    if os.environ.get("ANTHROPIC_API_KEY") or settings.ANTHROPIC_API_KEY:
        provider = "anthropic"
    elif os.environ.get("HUANTONG_LLM_API_KEY") or settings.HUANTONG_LLM_API_KEY:
        provider = "openai"
    elif os.environ.get("HUANTONG_LLM_PROVIDER") == "ollama" or settings.HUANTONG_LLM_PROVIDER == "ollama":
        provider = "ollama"

    return {
        "status": "running",
        "version": "1.0.0",
        "llm_provider": provider,
        "kb_count": kb_count,
        "doc_count": doc_count,
    }


# ============================================================
# 静态文件托管（生产模式）
# ============================================================

frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
    logger.info(f"前端静态文件已挂载: {frontend_dist}")
