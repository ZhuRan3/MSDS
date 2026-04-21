"""
LLM客户端 - 用于MSDS文本生成（RAG增强版）
化安通 (HuaAnTong) AI MSDS自动生成系统

RAG增强：优先从知识库检索，LLM仅用于补充和生成自然语言
"""

import os
import json
from typing import Dict, Optional, List

# LLM提供商配置
LLMProvider = os.environ.get("HUANTONG_LLM_PROVIDER", "openai")  # openai / anthropic / ollama
LLM_API_KEY = os.environ.get("HUANTONG_LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("HUANTONG_LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("HUANTONG_LLM_MODEL", "gpt-4o-mini")

# Anthropic specific (MiniMax)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


# 判断实际可用的LLM提供商（动态检查）
def get_active_provider() -> Optional[str]:
    """返回实际可用的LLM提供商"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("HUANTONG_LLM_API_KEY"):
        return "openai"
    if os.environ.get("HUANTONG_LLM_PROVIDER") == "ollama":
        return "ollama"
    return None


def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.2, max_tokens: int = 16000) -> Optional[str]:
    """
    调用LLM生成文本
    """
    provider = get_active_provider()
    if provider == "anthropic":
        return _call_anthropic(prompt, system_prompt, temperature, max_tokens)
    elif provider == "openai":
        return _call_openai(prompt, system_prompt, temperature, max_tokens)
    elif provider == "ollama":
        return _call_ollama(prompt, system_prompt, temperature)
    return None


def _call_anthropic(prompt: str, system_prompt: str, temperature: float, max_tokens: int) -> Optional[str]:
    """调用Anthropic Claude API (MiniMax)"""
    try:
        import anthropic
        client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            base_url=ANTHROPIC_BASE_URL
        )
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        # Find first TextBlock (skip ThinkingBlock)
        for block in response.content:
            if block.type == "text":
                return block.text
        return None
    except Exception as e:
        print(f"  [WARN] Anthropic API调用失败: {e}")
        return None


def _call_openai(prompt: str, system_prompt: str, temperature: float, max_tokens: int) -> Optional[str]:
    """调用OpenAI API"""
    try:
        import requests
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        resp = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=data, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [WARN] OpenAI API调用失败: {e}")
        return None


def _call_ollama(prompt: str, system_prompt: str, temperature: float) -> Optional[str]:
    """调用本地Ollama服务"""
    try:
        import requests
        data = {
            "model": LLM_MODEL or "llama3",
            "prompt": prompt,
            "system": system_prompt,
            "temperature": temperature,
            "stream": False
        }
        resp = requests.post(f"{LLM_BASE_URL}/api/generate", json=data, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        print(f"  [WARN] Ollama调用失败: {e}")
        return None


# ============================================================
# MSDS文本生成Prompt模板
# ============================================================

MSDS_SYSTEM_PROMPT = """你是一位专业的化学品安全技术说明书(MSDS)编写专家。

你根据化学品的基础数据，生成符合GB/T 16483-2008标准的16部分MSDS内容。

要求：
1. 使用简体中文，术语准确
2. 内容详尽专业，避免模糊表述
3. GHS分类和H/P代码必须准确
4. 急救措施、消防措施要针对具体化学品特性
5. 不要编造具体数值，使用"无资料"表示未知数据
6. 输出纯文本或Markdown格式，不要有额外解释

化学品种类包括：酚类、醇类、酮类、腈类、烷烃、芳香烃、无机碱等。
"""

# ============================================================
# RAG上下文增强
# ============================================================

def build_rag_prompt(base_prompt: str, rag_context: str = "") -> str:
    """构建带RAG上下文的prompt"""
    if not rag_context:
        return base_prompt
    return f"""{base_prompt}

【重要 - 参考知识库数据】
请参考以下知识库中的真实化学品数据来生成内容（特别是数值、危险性分类、急救措施等）：
{rag_context}

【注意】
- 如果知识库中有该化学品的具体数据，优先使用知识库数据
- 知识库中未收录的化学品，使用通用化学知识推断
- 不要编造知识库中不存在的具体数值
"""

def generate_hazard_description(chem_data: Dict, rag_context: str = "") -> str:
    """生成危险性描述（第二部分）"""
    base_prompt = f"""为以下化学品生成MSDS危险性概述中的紧急概述（约80-120字）：

化学品信息：
- 中文名称：{chem_data.get('chemical_name_cn', '')}
- CAS号：{chem_data.get('cas_number', '')}
- 化学类别：{chem_data.get('chemical_family', '')}
- GHS分类：{', '.join(chem_data.get('ghs_classifications', []))}
- 信号词：{chem_data.get('signal_word', '')}
- UN编号：{chem_data.get('un_number', '')}

请参考真实MSDS格式，生成详细的紧急概述，包括：
1. 主要危险（燃烧性/腐蚀性/毒性等）
2. 健康危害（对眼睛/皮肤/呼吸道/消化道的具体影响）
3. 环境危害
4. 特殊危险性（如有）

要求：
- 内容详尽，80-120字
- 符合GB/T 16483-2008标准
- 使用专业化学术语
- 不要省略任何危险信息"""

    prompt = build_rag_prompt(base_prompt, rag_context)
    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.2)
    if result:
        return result.strip()
    # 回退
    return f"具有{chem_data.get('chemical_family', '')}特性，可能造成健康危害。"


def generate_first_aid_section(chem_data: Dict, is_corrosive: bool, is_toxic: bool, rag_context: str = "") -> Dict:
    """生成急救措施（第四部分）"""
    family = chem_data.get('chemical_family', '')
    hazard_list = chem_data.get('ghs_classifications', [])

    base_prompt = f"""为以下化学品生成MSDS第四部分急救措施（参考真实MSDS格式）：

化学品信息：
- 中文名称：{chem_data.get('chemical_name_cn', '')}
- CAS号：{chem_data.get('cas_number', '')}
- 类别：{family}
- 腐蚀性：{'是' if is_corrosive else '否'}
- 毒性：{'是' if is_toxic else '否'}
- GHS分类：{', '.join(hazard_list)}
- 口服LD50：{chem_data.get('ld50_oral', '无资料')}
- 闪点：{chem_data.get('flash_point', '无资料')}

请生成详细的急救措施，参考真实MSDS格式：
1. 吸入：具体症状+处理+就医建议（40-60字）
2. 皮肤接触：脱衣+冲洗时间+就医+后续处理（40-60字）
3. 眼睛接触：冲洗时间+隐形眼镜处理+就医（40-60字）
4. 食入：禁止催吐的原因+具体处理+禁忌+就医（40-60字）
5. 救援人员防护：具体防护装备
6. 对医生提示：解毒剂+对症治疗+观察要点

格式：JSON格式输出
{{
  "inhalation": "...",
  "skin_contact": "...",
  "eye_contact": "...",
  "ingestion": "...",
  "protection_for_rescuers": "...",
  "notes_to_physician": "..."
}}

注意：腐蚀性化学品禁止催吐，毒性化学品要强调立即就医。"""

    prompt = build_rag_prompt(base_prompt, rag_context)
    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.2)
    if result:
        try:
            # 尝试解析JSON
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    # 回退到模板
    ingestion = "不要催吐。漱口。立即就医。" if is_corrosive or is_toxic else "如误咽，不得催吐。用水漱口。就医。"
    skin = "立即脱去所有沾染的衣服。用大量清水持续冲洗至少15分钟。立即就医。" if is_corrosive else "立即脱去污染的衣着。用肥皂水和清水彻底冲洗皮肤至少15分钟。如有不适感，就医。"
    return {
        "inhalation": "立即撤离现场至空气新鲜处。保持呼吸道通畅。如呼吸困难，给氧。如呼吸停止，立即进行人工呼吸。就医。",
        "skin_contact": skin,
        "eye_contact": "立即提起眼睑，用流动清水或生理盐水持续冲洗至少15分钟。隐形眼镜须取下并分开清洗。立即就医。",
        "ingestion": ingestion
    }


def generate_firefighting_section(chem_data: Dict, is_flammable: bool, is_corrosive: bool, is_explosive: bool, rag_context: str = "") -> Dict:
    """生成消防措施（第五部分）"""
    flash_point = chem_data.get('flash_point', '未知')
    family = chem_data.get('chemical_family', '')
    boiling_point = chem_data.get('boiling_point', '无资料')
    density = chem_data.get('density', '无资料')

    base_prompt = f"""为以下化学品生成MSDS第五部分消防措施（参考真实MSDS格式）：

化学品信息：
- 中文名称：{chem_data.get('chemical_name_cn', '')}
- CAS号：{chem_data.get('cas_number', '')}
- 闪点：{flash_point}
- 沸点：{boiling_point}
- 相对密度：{density}
- 易燃：{'是' if is_flammable else '否'}
- 腐蚀性：{'是' if is_corrosive else '否'}
- 爆炸性：{'是' if is_explosive else '否'}
- 类别：{family}

请生成详细的消防措施，参考真实MSDS格式：
1. 危险特性（80-100字）：描述燃烧特性、蒸气密度、与空气形成爆炸混合物的可能性、腐蚀性、对人体的特殊危害
2. 适用灭火剂（40-60字）：具体灭火剂类型和使用条件
3. 禁止使用的灭火剂及原因（30-50字）
4. 消防建议（60-80字）：消防人员防护装备、灭火时特殊注意事项、容器处理建议

格式：JSON格式输出
{{
  "hazard_characteristics": "...",
  "extinguishing_media": "...",
  "extinguishing_prohibited": "...",
  "firefighting_advice": "..."
}}"""

    prompt = build_rag_prompt(base_prompt, rag_context)
    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.2)
    if result:
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    # 回退
    hazard_parts = []
    if is_flammable:
        hazard_parts.append(f"高度易燃液体，闪点{flash_point}。")
    if is_corrosive:
        hazard_parts.append("具有腐蚀性，可对金属造成损害。")
    if is_explosive:
        hazard_parts.append("具有爆炸性。")

    return {
        "hazard_characteristics": "".join(hazard_parts) if hazard_parts else "未分类为危险化学品。",
        "extinguishing_media": "干粉灭火器、CO2、水喷雾、泡沫" if is_flammable else "待定",
        "extinguishing_prohibited": "禁止使用直流水（可能使火势蔓延）" if is_flammable else "无",
        "firefighting_advice": "消防人员须穿戴防护装备。在上风方向灭火。" if is_flammable else "遵循标准消防程序。"
    }


def generate_spill_section(chem_data: Dict, is_flammable: bool, is_corrosive: bool, is_toxic: bool, rag_context: str = "") -> Dict:
    """生成泄漏应急处理（第六部分）"""
    vapor_pressure = chem_data.get('vapor_pressure', '无资料')
    boiling_point = chem_data.get('boiling_point', '无资料')

    base_prompt = f"""为以下化学品生成MSDS第六部分泄漏应急处理（参考真实MSDS格式）：

化学品信息：
- 中文名称：{chem_data.get('chemical_name_cn', '')}
- CAS号：{chem_data.get('cas_number', '')}
- 蒸气压：{vapor_pressure}
- 沸点：{boiling_point}
- 易燃：{'是' if is_flammable else '否'}
- 腐蚀性：{'是' if is_corrosive else '否'}
- 毒性：{'是' if is_toxic else '否'}
- 类别：{chem_data.get('chemical_family', '')}

请生成详细的泄漏应急处理措施，参考真实MSDS格式：
1. 人员防护（60-80字）：具体呼吸防护、皮肤防护、眼睛防护要求
2. 应急响应（60-80字）：隔离距离、疏散区域、上风/下风方向、禁止进入人员
3. 环境保护（50-70字）：防止进入排水沟、下水道、土壤、水体的具体措施
4. 泄漏隔离方法（60-80字）：小量和大量的不同处理方法
5. 清理方法（60-80字）：具体中和、吸收、冲洗方法，废液处理
6. 应急人员防护装备（40-60字）：具体装备清单

格式：JSON格式输出
{{
  "personal_precautions": "...",
  "emergency_response": "...",
  "environmental_precautions": "...",
  "containment_methods": "...",
  "cleaning_methods": "...",
  "ppe_for_cleanup": "..."
}}"""

    prompt = build_rag_prompt(base_prompt, rag_context)
    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.2)
    if result:
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    # 回退
    cleaning = "用大量清水冲洗。避免排放至下水道。" if is_corrosive else "用清水冲洗污染区域。废液须按危险废物处理。"
    return {
        "personal_precautions": "确保通风。穿戴防护装备（呼吸防护、防化学手套、安全护目镜）。",
        "emergency_response": "隔离泄漏区域至少50米。疏散人员至上风安全区域。禁止无关人员进入。",
        "environmental_precautions": "防止泄漏物进入排水沟、下水道、地下室或密闭空间。如进入水体或土壤，通知当地环保部门。",
        "containment_methods": "小量：用惰性材料（如活性炭、砂土）吸收。大量：构筑围堤收容。",
        "cleaning_methods": cleaning,
        "ppe_for_cleanup": "正压呼吸器（紧急时）、防化学手套、安全护目镜、全面防护服。"
    }


def generate_handling_section(chem_data: Dict, is_flammable: bool, is_corrosive: bool, rag_context: str = "") -> Dict:
    """生成操作处置与储存（第七部分）"""
    family = chem_data.get('chemical_family', '')
    flash_point = chem_data.get('flash_point', '无资料')

    base_prompt = f"""为以下化学品生成MSDS第七部分操作处置与储存（参考真实MSDS格式）：

化学品信息：
- 中文名称：{chem_data.get('chemical_name_cn', '')}
- CAS号：{chem_data.get('cas_number', '')}
- 闪点：{flash_point}
- 易燃：{'是' if is_flammable else '否'}
- 腐蚀性：{'是' if is_corrosive else '否'}
- 类别：{family}

请生成详细的操作处置与储存措施，参考真实MSDS格式：
1. 操作注意事项（80-100字）：密闭操作局部排风、自动化建议、操作人员培训要求、禁止吸烟/饮食、避免接触、废弃注意事项
2. 储存条件（80-100字）：阴凉干燥库房、温度湿度要求、远离火种热源、容器密封要求、分类储存要求、备急设施
3. 禁配物（60-80字）：具体化学品名称，如强氧化剂、酸类、碱类等

格式：JSON格式输出
{{
  "operation_notes": "...",
  "storage_conditions": "...",
  "incompatible_materials": "..."
}}"""

    prompt = build_rag_prompt(base_prompt, rag_context)
    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.2)
    if result:
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    # 回退
    handling = "操作须在通风良好的地方进行。远离热源和火源。穿戴适当的防护装备。操作后彻底洗手。"
    if is_flammable:
        handling += "禁止吸烟。使用防爆设备和工具。"
    storage = "储存于阴凉、干燥、通风良好的地方。远离热源和火源。容器须密闭。"
    if is_corrosive:
        storage += "储存于耐腐蚀容器中（如玻璃、聚乙烯）。"
    incompatible = "强氧化剂、酸类、碱类、铝、锌"

    return {
        "operation_notes": handling,
        "storage_conditions": storage,
        "incompatible_materials": incompatible
    }


def generate_toxicology_section(chem_data: Dict, rag_context: str = "") -> Dict:
    """生成毒理学信息（第十一部分）"""
    ghs = ', '.join(chem_data.get('ghs_classifications', []))

    base_prompt = f"""为以下化学品生成MSDS第十一部分毒理学信息（参考真实MSDS格式）：

化学品信息：
- 中文名称：{chem_data.get('chemical_name_cn', '')}
- CAS号：{chem_data.get('cas_number', '')}
- 类别：{chem_data.get('chemical_family', '')}
- GHS分类：{ghs}
- 口服LD50：{chem_data.get('ld50_oral', '无资料')}
- 经皮LD50：{chem_data.get('ld50_dermal', '无资料')}
- 吸入LC50：{chem_data.get('lc50_inhalation', '无资料')}

请生成详细的毒理学信息，参考真实MSDS格式：
1. 急性毒性（60-80字）：LD50具体数值、实验动物、吸收途径
2. 皮肤腐蚀/刺激（40-60字）：具体表现、GHS分类依据
3. 严重眼损伤/眼刺激（40-60字）：具体表现、对视力的影响
4. 呼吸/皮肤致敏性（40-50字）：致敏性分类依据
5. 致癌性（50-70字）：IARC分类、OSHA/NTP列表情况
6. 生殖毒性（50-70字）：动物实验结果、分类依据
7. 单次接触STOT（60-80字）：靶器官、具体症状、麻醉效应
8. 反复接触STOT（60-80字）：靶器官、长期暴露后果

格式：JSON格式输出
{{
  "acute_toxicity": {{"oral_ld50": "...", "dermal_ld50": "...", "inhalation_lc50": "..."}},
  "skin_corrosion_irritation": "...",
  "serious_eye_damage_irritation": "...",
  "respiratory_skin_sensitization": "...",
  "carcinogenicity": "...",
  "reproductive_toxicity": "...",
  "stot_single_exposure": "...",
  "stot_repeated_exposure": "..."
}}"""

    prompt = build_rag_prompt(base_prompt, rag_context)
    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.2)
    if result:
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    # 回退
    return {
        "acute_toxicity": {
            "oral_ld50": chem_data.get('ld50_oral', '无资料'),
            "dermal_ld50": "无资料",
            "inhalation_lc50": "无资料"
        },
        "skin_corrosion_irritation": "皮肤腐蚀/刺激。",
        "serious_eye_damage_irritation": "严重眼损伤/眼刺激。",
        "respiratory_skin_sensitization": "不致敏。",
        "carcinogenicity": "无资料",
        "reproductive_toxicity": "无资料",
        "stot_single_exposure": "高浓度可能引起呼吸道刺激或麻醉效应。",
        "stot_repeated_exposure": "长期接触可能对器官造成损害。"
    }


def generate_ecology_section(chem_data: Dict, is_toxic: bool, rag_context: str = "") -> Dict:
    """生成生态学信息（第十二部分）"""
    base_prompt = f"""为以下化学品生成MSDS第十二部分生态学信息（参考真实MSDS格式）：

化学品信息：
- 中文名称：{chem_data.get('chemical_name_cn', '')}
- CAS号：{chem_data.get('cas_number', '')}
- 类别：{chem_data.get('chemical_family', '')}
- 毒性：{'是' if is_toxic else '否'}
- 生物富集潜力BCF：{chem_data.get('bcf', '无资料')}
- 土壤迁移性Koc：{chem_data.get('koc', '无资料')}

请生成详细的生态学信息，参考真实MSDS格式：
1. 生态毒性（60-80字）：鱼类LC50、无脊椎动物EC50、藻类EC50的具体数值和实验条件
2. 持久性和降解性（60-80字）：生物降解性、光降解、化学降解途径、半衰期
3. 生物富集潜力（50-70字）：BCF值、log Kow、蓄积性评估
4. 土壤迁移性（50-70字）：Koc值、迁移性评估、地下水污染风险
5. 其他不良效应（50-70字）：对水生/陆生生物的具体危害

格式：JSON格式输出
{{
  "ecotoxicity": {{"fish_lc50": "...", "invertebrate_ec50": "...", "algae_ec50": "..."}},
  "persistence_degradability": "...",
  "bioaccumulation_potential": "...",
  "soil_mobility": "...",
  "other_adverse_effects": "..."
}}"""

    prompt = build_rag_prompt(base_prompt, rag_context)
    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.2)
    if result:
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    # 回退
    return {
        "ecotoxicity": {"fish_lc50": "无资料", "invertebrate_ec50": "无资料", "algae_ec50": "无资料"},
        "persistence_degradability": "具有一定的生物降解性。",
        "bioaccumulation_potential": "BCF值低，生物富集潜力不大。",
        "soil_mobility": "可能在土壤中迁移。",
        "other_adverse_effects": "对水生生物有害。" if is_toxic else "无特殊不良效应。"
    }


def generate_stability_section(chem_data: Dict, is_flammable: bool, rag_context: str = "") -> Dict:
    """生成稳定性和反应性（第十部分）"""
    family = chem_data.get('chemical_family', '')

    prompt = f"""为以下化学品生成MSDS第十部分稳定性和反应性：

化学品信息：
- 名称：{chem_data.get('chemical_name_cn', '')}
- CAS：{chem_data.get('cas_number', '')}
- 易燃：{'是' if is_flammable else '否'}
- 类别：{family}

请生成：
1. 稳定性
2. 应避免的条件
3. 禁配物
4. 危险分解产物
5. 聚合危害

格式：JSON格式输出
{{
  "stability": "...",
  "conditions_to_avoid": "...",
  "incompatible_materials": "...",
  "hazardous_decomposition": "...",
  "polymerization_hazard": "..."
}}"""

    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.2)
    if result:
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    # 回退
    return {
        "stability": "在正常储存和操作条件下稳定。",
        "conditions_to_avoid": "高温、火源、静电、强氧化剂。" if is_flammable else "无特殊条件。",
        "incompatible_materials": "强氧化剂、酸类、碱类。",
        "hazardous_decomposition": "燃烧或高温分解时产生一氧化碳、二氧化碳、及其他有机裂解产物。",
        "polymerization_hazard": "不会发生聚合反应。"
    }


def generate_disposal_section() -> Dict:
    """生成废弃处置（第十三部分）"""
    prompt = """生成MSDS第十三部分废弃处置：

内容包括：
1. 处置方法（委托有资质危险废物处理商，不得直接排入下水道或土壤）
2. 容器处理（空容器须彻底清洗后再处置）
3. 注意事项（参阅国家和地方有关法规，遵守危险废物转移联单制度）

格式：JSON格式输出
{
  "disposal_methods": "...",
  "container_handling": "...",
  "notes": "..."
}"""

    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.1)
    if result:
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    return {
        "disposal_methods": "须委托有资质的危险废物处理商进行处置。不得直接排入下水道或土壤。",
        "container_handling": "空容器须彻底清洗（或干燥后）再处置。残留物可能具有危害性。",
        "notes": "处置前应参阅国家和地方有关法规。遵守危险废物转移联单制度。"
    }


def generate_regulatory_section() -> Dict:
    """生成法规信息（第十五部分）"""
    prompt = """生成MSDS第十五部分法规信息：

内容包括：
1. 中国法规（《危险化学品安全管理条例》、GB 30000系列等）
2. 国际/地区法规（UN RTDG、GHS、REACH、OSHA等）

格式：JSON格式输出
{
  "china_regulations": ["...", "..."],
  "international_regulations": ["...", "..."]
}"""

    result = call_llm(prompt, MSDS_SYSTEM_PROMPT, temperature=0.1)
    if result:
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass

    return {
        "china_regulations": [
            "《危险化学品安全管理条例》（国务院令第591号）",
            "《危险化学品目录》（2015版，含2026年调整）",
            "《重点监管的危险化学品名录》（2013版）",
            "GB 30000系列《化学品分类和标签规范》",
            "GBZ 2.1-2019《工作场所有害因素职业接触限值 化学有害因素》"
        ],
        "international_regulations": [
            "《联合国危险货物运输建议书》（UN RTDG）",
            "《全球化学品统一分类和标签制度》（GHS Rev.10）",
            "《欧盟REACH法规》（(EC) No 1907/2006）",
            "《美国OSHA标准》（29 CFR 1910.1200）"
        ]
    }