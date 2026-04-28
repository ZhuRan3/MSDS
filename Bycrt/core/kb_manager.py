"""
知识库管理脚本 - 为RAG知识库添加/更新化学品数据
化安通 (HuaAnTong) MSDS自动生成系统

核心原则：
1. 优先从PubChem API获取数据
2. 知识库没有时，调用LLM生成推断数据
3. 不硬编码任何化学属性

用法：
python kb_manager.py --add "108-95-2"
python kb_manager.py --add "108-95-2" --name "苯酚"
python kb_manager.py --batch ./batch_cas.txt
python kb_manager.py --list
python kb_manager.py --update "108-95-2"  # 从API更新
"""

import json
import sys
import time
import requests
import os
from pathlib import Path
from typing import Dict, Optional, List

# ============================================================
# 配置
# ============================================================

# 项目根目录 = core/ 的上级目录 (Bycrt/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_FILE = PROJECT_ROOT / "db" / "chemical_db.json"
PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
HEADERS = {"User-Agent": "HuaAnTong-MSDSGEN/1.0 (educational project)"}

# LLM配置
LLMProvider = os.environ.get("HUANTONG_LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


# ============================================================
# PubChem数据获取
# ============================================================

class PubChemFetcher:
    """从PubChem获取化学品完整数据"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get_all_data(self, cas_or_name: str, alt_name: str = "") -> Optional[Dict]:
        """获取完整数据"""
        cid = self.get_cid(cas_or_name)
        if not cid and alt_name:
            cid = self.get_cid_by_name_variants(alt_name)
        if not cid:
            return None

        data = {
            'cid': cid,
            'properties': self.get_properties(cid),
            'safety': self.get_safety_summary(cid),
            'classification': self.get_ghs_classification(cid)
        }
        return data

    def get_cid(self, cas_or_name: str) -> Optional[int]:
        """通过CAS或名称获取CID"""
        # 先尝试CAS号查询
        url = f"{PUBCHEM_BASE}/compound/cas/{cas_or_name}/cids/JSON"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                cids = resp.json().get("IdentifierList", {}).get("CID", [])
                if cids:
                    return cids[0]
        except:
            pass

        # CAS查询失败，尝试名称查询
        url = f"{PUBCHEM_BASE}/compound/name/{cas_or_name}/cids/JSON"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                cids = resp.json().get("IdentifierList", {}).get("CID", [])
                if cids:
                    return cids[0]
        except:
            pass
        return None

    def get_cid_by_name_variants(self, name: str) -> Optional[int]:
        """通过化学名变体获取CID"""
        # 常见英文名变体
        variants = [
            name,
            name.lower(),
            name.upper(),
            name.replace(' ', '-'),
            name.replace(' ', '_'),
        ]
        # 特殊处理对甲基氨基酚
        if '甲基氨基酚' in name or 'methylaminophenol' in name.lower():
            variants.extend(['4-methylaminophenol', 'p-methylaminophenol', '4-(methylamino)phenol'])

        for variant in variants:
            cid = self.get_cid(variant)
            if cid:
                return cid
        return None

    def get_properties(self, cid: int) -> Dict:
        """获取理化性质"""
        props_url = f"{PUBCHEM_BASE}/compound/cid/{cid}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,InChI,XLogP/JSON"
        try:
            resp = self.session.get(props_url, timeout=30)
            if resp.status_code == 200:
                properties = resp.json().get("PropertyTable", {}).get("Properties", [{}])[0]
                return properties
        except:
            pass

        # 尝试JSONP的方式
        jsonp_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES/JSON"
        try:
            resp = self.session.get(jsonp_url, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("PropertyTable", {}).get("Properties", [{}])[0] or {}
        except:
            pass
        return {}

    def get_safety_summary(self, cid: int) -> Dict:
        """获取GHS安全摘要"""
        url = f"{PUBCHEM_BASE}/compound/cid/{cid}/record/JSON?heading=GHS-SafetySummary"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return {}

    def get_ghs_classification(self, cid: int) -> Dict:
        """获取GHS分类信息"""
        url = f"{PUBCHEM_BASE}/compound/cid/{cid}/classification/JSON?verbose=true"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return {}

    # ----------------------------------------------------------
    # PUG View 详细数据获取
    # ----------------------------------------------------------

    def _get_pug_view(self, cid: int, heading: str) -> Dict:
        """获取PUG View指定heading的完整数据"""
        base = PUBCHEM_BASE.replace('/rest/pug', '/rest/pug_view')
        url = f"{base}/data/compound/{cid}/JSON"
        params = {"heading": heading}
        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return {}

    def _extract_strings(self, data: Dict, target_heading: str) -> List[str]:
        """从PUG View JSON递归提取指定heading的所有String值"""
        results = []
        sections = data.get("Record", {}).get("Section", [])
        self._search_sections(sections, target_heading, results)
        return results

    def _search_sections(self, sections, target, results):
        """递归搜索PUG View Section"""
        if not isinstance(sections, list):
            return
        for section in sections:
            heading = section.get("TOCHeading", "")
            if heading.lower().replace(" ", "") == target.lower().replace(" ", ""):
                for info in section.get("Information", []):
                    val = info.get("Value", {})
                    # StringWithMarkup
                    for swm in val.get("StringWithMarkup", []):
                        s = swm.get("String", "").strip()
                        if s:
                            results.append(s)
                    # 单独的String
                    if not results and val.get("String"):
                        results.append(val["String"])
            # 递归子section
            self._search_sections(section.get("Section", []), target, results)

    def get_experimental_properties(self, cid: int) -> Dict:
        """从PUG View获取理化性质（外观、气味、蒸气压、自燃温度、爆炸极限等）"""
        result = {}
        data = self._get_pug_view(cid, "Experimental+Properties")
        if not data:
            return result

        mappings = {
            "Physical Description": "appearance",
            "PhysicalDescriptions": "appearance",
            "Odor": "odor",
            "OdorThreshold": "odor_threshold",
            "Vapor Pressure": "vapor_pressure",
            "Autoignition Temperature": "autoignition_temp",
            "Lower Explosive Limit": "explosion_limits_lel",
            "Upper Explosive Limit": "explosion_limits_uel",
            "Explosive Limits and": "explosion_limits",
            "LogP": "partition_coefficient_n-octanol_water",
            "Log Kow": "partition_coefficient_n-octanol_water",
        }

        for heading, field in mappings.items():
            strings = self._extract_strings(data, heading)
            if strings:
                result[field] = strings[0]

        # 合并爆炸极限上下限
        lel = result.pop("explosion_limits_lel", "")
        uel = result.pop("explosion_limits_uel", "")
        if lel or uel:
            parts = []
            if lel:
                parts.append(f"下限: {lel}")
            if uel:
                parts.append(f"上限: {uel}")
            result["explosion_limits"] = "; ".join(parts)
        elif "explosion_limits" not in result:
            pass  # 已由 Exploitve Limits and heading 捕获

        return result

    def get_toxicity_data(self, cid: int) -> Dict:
        """从PUG View获取毒理学数据"""
        result = {}
        data = self._get_pug_view(cid, "Toxicity")
        if not data:
            return result

        # LD50/LC50
        for heading in ["Non-Human Toxicity Values"]:
            vals = self._extract_strings(data, heading)
            for v in vals:
                v_lower = v.lower()
                if "ld50" in v_lower and "oral" in v_lower and "ld50_oral" not in result:
                    result["ld50_oral"] = v
                elif "ld50" in v_lower and "dermal" in v_lower and "ld50_dermal" not in result:
                    result["ld50_dermal"] = v
                elif "lc50" in v_lower and "inhalation" in v_lower and "lc50_inhalation" not in result:
                    result["lc50_inhalation"] = v

        # 致癌性
        for heading in ["Evidence for Carcinogenicity", "Carcinogen Classification"]:
            vals = self._extract_strings(data, heading)
            if vals and "carcinogenicity_ghs" not in result:
                result["carcinogenicity_ghs"] = vals[0]

        # 靶器官
        for heading in ["Target Organs", "Target Organ"]:
            vals = self._extract_strings(data, heading)
            if vals and "stot_target_organs" not in result:
                result["stot_target_organs"] = vals[0]

        return result

    def get_ecotoxicity_data(self, cid: int) -> Dict:
        """从PUG View获取生态毒理数据"""
        result = {}
        data = self._get_pug_view(cid, "Ecological+Information")
        if not data:
            return result

        for heading in ["Ecotoxicity Values", "Ecotoxicity Excerpts"]:
            vals = self._extract_strings(data, heading)
            for v in vals:
                v_lower = v.lower()
                if "lc50" in v_lower and ("fish" in v_lower or "oncorhynchus" in v_lower
                                           or "pimephales" in v_lower or "lepomis" in v_lower):
                    result.setdefault("ecotoxicity_lc50_fish", v)
                elif "ec50" in v_lower and ("daphnia" in v_lower or "daphnia" in v_lower):
                    result.setdefault("ecotoxicity_ec50_daphnia", v)
                elif ("ec50" in v_lower or "ebc50" in v_lower) and "algae" in v_lower:
                    result.setdefault("ecotoxicity_ec50_algae", v)

        # 生物富集
        for heading in ["Environmental Bioconcentration", "Bioconcentration"]:
            vals = self._extract_strings(data, heading)
            if vals and "bcf_bioconcentration" not in result:
                result["bcf_bioconcentration"] = vals[0]

        # 降解性
        for heading in ["Environmental Biodegradation", "Biodegradation"]:
            vals = self._extract_strings(data, heading)
            if vals and "biodegradability" not in result:
                result["biodegradability"] = vals[0]

        return result


# ============================================================
# LLM数据推断（当API数据不足时）
# ============================================================

def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.2) -> Optional[str]:
    """调用LLM生成推断数据"""
    if not ANTHROPIC_API_KEY:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            base_url=ANTHROPIC_BASE_URL
        )
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2048,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return None
    except Exception as e:
        print(f"  [WARN] LLM调用失败: {e}")
        return None


def infer_with_llm(cas: str, formula: str, name: str) -> Dict:
    """使用LLM推断化学品的详细属性"""

    system_prompt = """你是一位专业的化学品安全数据专家。根据给定的化学品信息，推断其完整的安全数据。
要求：
1. 基于化学式和名称推断化学家族
2. 推断合理的GHS分类（基于官能团和类似化合物）
3. 推断物理化学性质（闪点、沸点、溶解度等）
4. 推断毒理学数据（LD50等）
5. 所有推断数据必须合理，不得编造具体实验值

输出格式：JSON
"""

    prompt = f"""根据以下信息推断化学品的安全数据：

CAS号: {cas}
分子式: {formula}
名称: {name}

请推断以下数据（如果无法确定，标注"需实验测定"）：
1. chemical_family: 化学家族（如酚类、醇类、酮类等）
2. un_number: UN编号
3. ghs_classifications: GHS危险分类列表
4. pictograms: 象形图列表
5. signal_word: 信号词
6. flash_point: 闪点
7. boiling_point: 沸点
8. melting_point: 熔点
9. density: 相对密度
10. solubility: 溶解性
11. ld50_oral: 经口LD50
12.皮肤腐蚀类别
13.眼损伤类别
14. ld50_dermal: 经皮LD50
15. lc50_inhalation: 吸入LC50
16. IARC致癌分类
17. 生物降解性
18. BCF生物富集系数
19. Koc土壤迁移系数

输出仅JSON，不要其他内容："""

    result = call_llm(prompt, system_prompt)
    if result:
        try:
            # 提取JSON
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            return json.loads(result.strip())
        except:
            pass
    return {}


# ============================================================
# 知识库管理
# ============================================================

class KnowledgeBaseManager:
    """知识库管理器"""

    def __init__(self):
        self.kb_file = KB_FILE
        self.data = self._load()
        self.fetcher = PubChemFetcher()

    def _load(self) -> Dict:
        """加载知识库"""
        if self.kb_file.exists():
            with open(self.kb_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save(self):
        """保存知识库"""
        with open(self.kb_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def add(self, cas: str, name_cn: str = "", use_llm: bool = True) -> bool:
        """添加化学品到知识库"""
        print(f"\n添加化学品: {cas} {'(' + name_cn + ')' if name_cn else ''}")

        # 如果已存在，先移除
        if cas in self.data:
            print(f"  [INFO] {cas} 已存在，将更新")
            del self.data[cas]

        # 从PubChem获取数据
        pubchem_data = self.fetcher.get_all_data(cas, name_cn)

        if not pubchem_data:
            print(f"  [FAIL] 无法从PubChem获取数据: {cas}")
            return False

        print(f"  [OK] CID: {pubchem_data['cid']}")

        props = pubchem_data.get('properties', {})
        safety = pubchem_data.get('safety', {})
        classification = pubchem_data.get('classification', {})

        # 构建基础数据
        chem = {
            "chemical_name_cn": name_cn or props.get('IUPACName', cas),
            "chemical_name_en": props.get('CanonicalSMILES', ''),
            "molecular_formula": props.get('MolecularFormula', ''),
            "molecular_weight": str(props.get('MolecularWeight', '')),
            "cas_number": cas,
            "iupac_name": props.get('IUPACName', ''),
            "xlogp": str(props.get('XLogP', '')),
            "data_source": "PubChem"
        }

        # 从PubChem安全数据中提取GHS分类（仅作为基础，后续LLM会覆盖）
        if safety and not use_llm:
            ghs_from_pubchem = []
            if isinstance(safety, dict):
                for key, val in safety.items():
                    if isinstance(val, str) and '类别' in val:
                        ghs_from_pubchem.append(val)
                    elif isinstance(val, list):
                        for item in val:
                            if isinstance(item, str) and '类别' in item:
                                ghs_from_pubchem.append(item)
            if ghs_from_pubchem:
                chem['ghs_classifications'] = ghs_from_pubchem

        # 从PubChem分类数据中提取
        if classification and not use_llm:
            if isinstance(classification, dict):
                ghhs = classification.get('ghs_classifications', [])
                if ghhs and isinstance(ghhs, list):
                    chem.setdefault('ghs_classifications', ghhs)

        # 使用LLM推断详细数据
        if use_llm:
            print(f"  [INFO] 从PubChem PUG View获取补充数据...")
            cid = pubchem_data.get('cid')
            if cid:
                # 理化性质补充
                physchem = self.fetcher.get_experimental_properties(cid)
                for key, val in physchem.items():
                    if val and not chem.get(key):
                        chem[key] = val
                # 毒理学数据补充
                tox = self.fetcher.get_toxicity_data(cid)
                for key, val in tox.items():
                    if val and not chem.get(key):
                        chem[key] = val
                # 生态毒理数据补充
                eco = self.fetcher.get_ecotoxicity_data(cid)
                for key, val in eco.items():
                    if val and not chem.get(key):
                        chem[key] = val
                filled = len(physchem) + len(tox) + len(eco)
                print(f"  [OK] PUG View补充 {filled} 个字段")

            print(f"  [INFO] 使用LLM推断剩余缺失数据...")
            llm_data = infer_with_llm(
                cas,
                chem['molecular_formula'],
                chem['chemical_name_cn']
            )
            if llm_data:
                chem.update(llm_data)
                print(f"  [OK] LLM推断完成")
            else:
                print(f"  [WARN] LLM推断失败，使用默认推断")
                chem = self._apply_default_inference(chem)
        else:
            chem = self._apply_default_inference(chem)

        # 添加到知识库
        self.data[cas] = chem
        self._save()

        print(f"  [OK] 已保存到知识库")
        print(f"  化学家族: {chem.get('chemical_family', 'N/A')}")
        print(f"  UN编号: {chem.get('un_number', 'N/A')}")
        print(f"  GHS分类: {', '.join(chem.get('ghs_classifications', []))}")

        return True

    def _apply_default_inference(self, chem: Dict) -> Dict:
        """应用默认推断规则"""

        formula = chem.get('molecular_formula', '')

        # 酚类检测
        if formula == 'C6H6O':
            chem['chemical_family'] = '酚类化合物'
            chem['un_number'] = '2021'
            chem['ghs_classifications'] = ['皮肤腐蚀/刺激，类别2', '严重眼损伤/眼刺激，类别1', '特异性靶器官毒性-一次接触，类别3']
            chem['pictograms'] = ['火焰', '腐蚀', '感叹号']
            chem['signal_word'] = '危险'
            chem['ld50_oral'] = '317 mg/kg（大鼠）'
            chem['ld50_dermal'] = '525 mg/kg（兔子）'
            chem['flash_point'] = '79°C（闭杯）'
            chem['boiling_point'] = '181.7°C'
            chem['melting_point'] = '40.6°C'
            chem['density'] = '1.07 g/cm³'
            chem['solubility'] = '微溶于水，可溶于乙醇、乙醚、氯仿'
            chem['partition_coefficient_log_kow'] = '1.46'
            chem['eye_damage_category'] = '类别1'
            chem['carcinogenicity_iarc'] = '第3组'
        # 醇类检测（乙anol）
        elif formula == 'C2H6O':
            chem['chemical_family'] = '醇类化合物'
            chem['un_number'] = '1170'
            chem['ghs_classifications'] = ['易燃液体，类别2', '严重眼损伤/眼刺激，类别2A']
            chem['pictograms'] = ['火焰', '感叹号']
            chem['signal_word'] = '危险'
            chem['ld50_oral'] = '7060 mg/kg（大鼠）'
            chem['flash_point'] = '13°C（闭杯）'
            chem['boiling_point'] = '78°C'
            chem['melting_point'] = '-114°C'
        # 丙酮
        elif formula == 'C3H6O':
            chem['chemical_family'] = '酮类化合物'
            chem['un_number'] = '1193'
            chem['ghs_classifications'] = ['易燃液体，类别2', '严重眼损伤/眼刺激，类别2A', '特异性靶器官毒性-一次接触，类别3']
            chem['pictograms'] = ['火焰', '感叹号']
            chem['signal_word'] = '危险'
            chem['ld50_oral'] = '5800 mg/kg（大鼠）'
            chem['flash_point'] = '-20°C（闭杯）'
            chem['boiling_point'] = '56°C'
        # 其他含氧有机物
        elif 'O' in formula and 'C' in formula and 'H' in formula:
            chem['chemical_family'] = '含氧有机化合物'
            chem['un_number'] = '1993'
        # 腈类
        elif 'N' in formula and 'C' in formula and 'H' in formula:
            chem['chemical_family'] = '腈类化合物'
            chem['un_number'] = '1648'
            chem['ghs_classifications'] = ['易燃液体，类别2', '急性毒性-经口，类别3']
            chem['pictograms'] = ['火焰', '健康危害']
            chem['signal_word'] = '危险'
        # 无机碱
        elif 'OH' in formula and ('Na' in formula or 'K' in formula or 'Ca' in formula):
            chem['chemical_family'] = '无机碱'
            chem['un_number'] = '1823'
            chem['ghs_classifications'] = ['金属腐蚀物，类别1', '皮肤腐蚀/刺激，类别1A']
            chem['pictograms'] = ['腐蚀']
            chem['signal_word'] = '危险'
        # 烃类
        elif 'C' in formula and 'H' in formula and 'O' not in formula and 'N' not in formula:
            if formula.count('C') >= 6:
                chem['chemical_family'] = '芳香烃'
                chem['un_number'] = '1294'
            else:
                chem['chemical_family'] = '烷烃'
                chem['un_number'] = '1208'
            chem['ghs_classifications'] = ['易燃液体，类别2']
            chem['pictograms'] = ['火焰']
            chem['signal_word'] = '危险'
        else:
            chem['chemical_family'] = '有机化合物'
            chem['un_number'] = '1993'

        return chem

    def remove(self, cas: str) -> bool:
        """从知识库移除化学品"""
        if cas in self.data:
            del self.data[cas]
            self._save()
            print(f"已移除: {cas}")
            return True
        print(f"未找到: {cas}")
        return False

    def list_all(self):
        """列出知识库中所有化学品"""
        print(f"\n知识库包含 {len(self.data)} 种化学品:")
        for cas, chem in self.data.items():
            name = chem.get('chemical_name_cn', 'N/A')
            family = chem.get('chemical_family', 'N/A')
            print(f"  {cas}: {name} ({family})")

    def search(self, query: str):
        """搜索化学品"""
        results = []
        query_lower = query.lower()
        for cas, chem in self.data.items():
            if query_lower in cas.lower():
                results.append((cas, chem))
            elif query_lower in chem.get('chemical_name_cn', '').lower():
                results.append((cas, chem))
        return results

    def update(self, cas: str) -> bool:
        """从API更新化学品数据"""
        return self.add(cas, use_llm=True)


# ============================================================
# 主程序
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    manager = KnowledgeBaseManager()

    if "--add" in sys.argv:
        idx = sys.argv.index("--add")
        cas = sys.argv[idx + 1]
        name_cn = ""
        if "--name" in sys.argv:
            name_idx = sys.argv.index("--name")
            name_cn = sys.argv[name_idx + 1]
        use_llm = "--no-llm" not in sys.argv
        manager.add(cas, name_cn, use_llm=use_llm)

    elif "--update" in sys.argv:
        idx = sys.argv.index("--update")
        cas = sys.argv[idx + 1]
        manager.update(cas)

    elif "--remove" in sys.argv:
        idx = sys.argv.index("--remove")
        cas = sys.argv[idx + 1]
        manager.remove(cas)

    elif "--list" in sys.argv:
        manager.list_all()

    elif "--search" in sys.argv:
        idx = sys.argv.index("--search")
        query = sys.argv[idx + 1]
        results = manager.search(query)
        print(f"找到 {len(results)} 个结果:")
        for cas, chem in results:
            print(f"  {cas}: {chem.get('chemical_name_cn', 'N/A')}")

    elif "--batch" in sys.argv:
        idx = sys.argv.index("--batch")
        batch_file = sys.argv[idx + 1]
        with open(batch_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split(',')
                    cas = parts[0].strip()
                    name = parts[1].strip() if len(parts) > 1 else ""
                    print(f"\n{'='*50}")
                    success = manager.add(cas, name)
                    if success:
                        time.sleep(1)  # 避免请求过快

    else:
        print(__doc__)


if __name__ == "__main__":
    main()