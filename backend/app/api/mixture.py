"""
化安通 (HuaAnTong) - MSDS自动生成系统
混合物 GHS 分类计算 API 路由
"""

import logging
from fastapi import APIRouter, HTTPException
from app.schemas.mixture import MixtureCalculateRequest, MixtureCalculateResponse
from app.core.mixture_calculator import MixtureCalculator, Component, build_component
from dataclasses import asdict

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mixture", tags=["混合物 GHS 计算"])


@router.post("/calculate")
async def calculate_mixture_ghs(data: MixtureCalculateRequest):
    """执行混合物 GHS 分类计算"""
    # 构建组分对象
    components = []
    for comp_input in data.components:
        # 先尝试从知识库加载
        comp = build_component(
            name=comp_input.name,
            cas=comp_input.cas,
            concentration=comp_input.concentration,
        )
        # 覆盖用户提供的值
        if comp_input.ld50_oral is not None:
            comp.ld50_oral = comp_input.ld50_oral
        if comp_input.ghs_classifications is not None:
            comp.ghs_classifications = comp_input.ghs_classifications
        components.append(comp)

    if not components:
        raise HTTPException(status_code=400, detail="请提供至少2个组分")

    # 执行计算
    calculator = MixtureCalculator(components)
    result = calculator.calculate_all()

    return {
        "classifications": result.classifications,
        "h_codes": result.h_codes,
        "signal_word": result.signal_word,
        "flammability_class": result.flammability_class,
        "ate_oral": result.ate_oral,
        "ate_dermal": result.ate_dermal,
        "ate_inhalation": result.ate_inhalation,
        "unknown_percentage": result.unknown_percentage,
        "calculation_log": result.calculation_log,
    }


@router.post("/preview")
async def preview_mixture_ghs(data: MixtureCalculateRequest):
    """预览计算结果（不保存）"""
    return await calculate_mixture_ghs(data)
