# MSDS生成系统缺陷清单

> 版本: 1.0 | 日期: 2026-05-03 | 状态: 待修复

## 缺陷统计

| 优先级 | 数量 | 说明 |
|--------|------|------|
| P0 阻塞级 | 4 | 不修复则不可商用 |
| P1 高优先级 | 3 | 严重影响报告质量 |
| P2 中等优先级 | 4 | 提升专业度 |

---

## P0 阻塞级缺陷

### DEF-001: Tier 2化学品字段名中英文不匹配导致84%数据丢失

- **严重性**: P0-阻塞
- **影响范围**: 52/62个化学品（所有PubChem导入的条目）
- **根因**: `sds_generator.py` 的 `set_chemical_data()` (~L262) 只读取英文key（如 `skin_corrosion_category`），Tier 2化学品使用中文key（如 `皮肤腐蚀类别`），数据被静默丢弃
- **涉及文件**:
  - `Bycrt/core/sds_generator.py` L262-403 (`set_chemical_data`)
  - `Bycrt/core/evidence_fusion.py` L287-446 (`_extract_kb_evidence`)
- **具体丢失字段**:

| 中文key | 期望英文key | 涉及SDS章节 |
|---------|------------|-------------|
| `皮肤腐蚀类别` | `skin_corrosion_category` | S11 毒理学 |
| `眼损伤类别` | `eye_damage_category` | S11 毒理学 |
| `IARC致癌分类` | `carcinogenicity_iarc` | S11 毒理学 |
| `solubility` | `solubility_details` | S9 理化特性 |
| `BCF生物富集系数` | `bioaccumulation_bcf` | S12 生态学 |
| `Koc土壤迁移系数` | `mobility_in_soil` | S12 生态学 |
| `生物降解性` | `persistence_degradability` | S12 生态学 |
| (完全缺失) | `first_aid_notes` | S4 急救 |
| (完全缺失) | `toxicology_notes` | S11 毒理学 |
| (完全缺失) | `transport_class/packing_group` | S14 运输 |
| (完全缺失) | `pc_twa/pc_stel/acgih_tlv` | S8 暴露控制 |
| (完全缺失) | `appearance/odor` | S9 理化特性 |

- **修复方案**: 在 `set_chemical_data()` 添加中文key→英文key的fallback映射；在 `evidence_fusion.py` 补充缺失的alias条目

### DEF-002: GHS分类名称格式不匹配导致H-code查找失败

- **严重性**: P0-阻塞
- **影响范围**: 所有包含特定GHS分类的Tier 2化学品
- **根因**: `_normalize_hazard()` (~L118) 无法将PubChem分类格式转换为 `ghs_mappings.json` 的标准key
- **涉及文件**:
  - `Bycrt/core/sds_generator.py` L118-141 (`_normalize_hazard`), L90-116 (`hazard_to_h_code`)
  - `Bycrt/core/mixture_calculator.py` L968-988 (`_normalize_ghs_for_matching`)
- **具体匹配失败案例**:

| PubChem格式 | 映射key格式 | 结果 |
|------------|------------|------|
| `对水生环境有害-急性危害, 类别3` | `危害水生环境-急性 Cat 3` | 匹配失败 |
| `特异性靶器官毒性-一次接触, 类别1 (呼吸道)` | `特异性靶器官毒性-单次 Cat 1` | 器官限定符阻断匹配 |
| `严重眼损伤/眼刺激, 类别2A` | `严重眼损伤/眼刺激 Cat 2A` | 匹配成功 |
| `皮肤腐蚀/刺激, 类别1A` | `皮肤腐蚀/刺激 Cat 1A` | 匹配成功 |

- **修复方案**: 添加分类名称别名映射表（如 `对水生环境有害-急性危害` → `危害水生环境-急性`）；器官限定符剥离后单独存储

### DEF-003: 模板"低粘度有机液体"应用于无机化学品

- **严重性**: P0-阻塞
- **影响范围**: 盐酸等所有含C+H但非有机物的化学品；混合物吸入危害描述
- **根因**:
  - `generate_section_11()` ~L1784 检查 `formula` 中含 `"C"` 和 `"H"` 即判定为有机物
  - 盐酸（HCl）分子式虽不含C但混合物模板硬编码"含低粘度有机液体组分"
- **涉及文件**:
  - `Bycrt/core/sds_generator.py` L1784-1792 (纯物质S11), L2524 (混合物S11)
- **具体错误**:
  - 盐酸MSDS第十一部分: "低粘度有机液体，误吸可引起化学性肺炎"（盐酸是无机酸水溶液）
  - 盐酸MSDS第十部分: "含氯有机物在紫外线或高温下可分解产生光气"（盐酸非含氯有机物）
  - 混合物吸入危害: 固定使用"含低粘度有机液体组分"
- **修复方案**: 增加化学品类型检测，无机酸/碱/盐不使用有机液体模板

### DEF-004: kb_manager.py数据导入字段名错误

- **严重性**: P0-阻塞
- **影响范围**: 所有未来通过PubChem导入的化学品
- **根因**:
  - L478: `chemical_name_en` 存储SMILES字符串而非英文名
  - L412-413: LLM prompt请求中文key `皮肤腐蚀类别`/`眼损伤类别`
  - L538: `chem.update(llm_data)` 无条件覆盖且无key校验
- **涉及文件**: `Bycrt/core/kb_manager.py` L412-413, L478, L538
- **修复方案**: 修复英文名取值，改LLM prompt为英文key，添加key规范化

---

## P1 高优先级缺陷

### DEF-005: Reviewer仅覆盖17个H-code无法验证GHS一致性

- **严重性**: P1-高
- **影响范围**: 所有MSDS的自动审核质量
- **根因**: `msds_reviewer.py` L55-73 硬编码仅17个H-code（GHS应有60+个）
- **涉及文件**: `Bycrt/core/msds_reviewer.py` L55-73, L146-191, L176-180
- **附带问题**:
  - L160: 正则表达式不支持括号限定符和英文Cat格式
  - L176-180: 未识别H-code被静默跳过而非标记
- **修复方案**: 从 `ghs_mappings.json` 动态加载H-code映射

### DEF-006: 混合物溶解性等文本字段直接拼接产生矛盾

- **严重性**: P1-高
- **影响范围**: 所有混合物MSDS的S9理化特性
- **根因**: 混合物S9溶解性字段直接用分号拼接各组分描述，不进行语义融合
- **涉及文件**: `Bycrt/core/sds_generator.py` 混合物S9生成逻辑
- **具体案例**: "微溶于水...；与水完全互溶；微溶于水..."（矛盾内容拼接）
- **修复方案**: 添加文本去重融合逻辑

### DEF-007: 盐酸浓度标注错误

- **严重性**: P1-高
- **影响范围**: CAS 7647-01-0 盐酸的S3组成信息
- **根因**: 纯物质统一标注">=99.0%"，但盐酸（水溶液）标准浓度为36-38%
- **涉及文件**: `Bycrt/core/sds_generator.py` S3生成逻辑
- **修复方案**: 添加CAS→典型浓度的映射表

---

## P2 中等优先级缺陷

### DEF-008: 数据退化——benchmark有数据但生成文件丢失

- **严重性**: P2-中
- **影响范围**: 丙酮、乙醇等Tier 1化学品的BCF数据
- **根因**: 生成器未读取某些存在于数据库中的字段
- **涉及文件**: `Bycrt/core/sds_generator.py` S12生态学生成逻辑

### DEF-009: OEL数据缺失——已知限值未填充

- **严重性**: P2-中
- **影响范围**: Tier 2化学品的S8暴露控制
- **根因**: PubChem不提供中国OEL数据，LLM推断不稳定
- **涉及文件**: `Bycrt/core/kb_manager.py`, `Bycrt/db/chemical_db.json`

### DEF-010: 爆炸极限内部矛盾

- **严重性**: P2-中
- **影响范围**: 乙醇等可燃液体的S9理化特性
- **根因**: 组合字段（3.3%-19.0%）有数据，但独立的爆炸上限/下限字段显示"无可用数据"
- **涉及文件**: `Bycrt/core/sds_generator.py` S9生成逻辑

### DEF-011: PDF生成异常——工业除漆剂仅27KB

- **严重性**: P2-中
- **影响范围**: 工业除漆剂的PDF输出
- **根因**: 生成过程可能中断
- **涉及文件**: `Bycrt/core/pdf_generator.py`

---

## 修复进度

| 编号 | 状态 | 修复日期 | 修改文件 |
|------|------|---------|---------|
| DEF-001 | **已修复** | 2026-05-03 | sds_generator.py, evidence_fusion.py |
| DEF-002 | **已修复** | 2026-05-03 | sds_generator.py, mixture_calculator.py |
| DEF-003 | **已修复** | 2026-05-03 | sds_generator.py |
| DEF-004 | **已修复** | 2026-05-03 | kb_manager.py |
| DEF-005 | **已修复** | 2026-05-03 | msds_reviewer.py |
| DEF-006 | **已修复** | 2026-05-03 | sds_generator.py |
| DEF-007 | **已修复** | 2026-05-03 | sds_generator.py |
| DEF-008 | **已修复** | 2026-05-03 | sds_generator.py (S12条件逻辑) |
| DEF-009 | **已修复** | 2026-05-03 | chemical_db.json (补充OEL数据) |
| DEF-010 | **已修复** | 2026-05-03 | sds_generator.py (S9爆炸极限解析) |
| DEF-011 | 待修复 | - | pdf_generator.py (需重新生成验证) |

## 硬编码内容外部化

| 步骤 | 状态 | 新文件 | 说明 |
|------|------|--------|------|
| Step 1 | **完成** | safety_knowledge.json | 5个安全知识库(急救/消防/储运/处置/毒性) |
| Step 2 | **完成** | chemical_type_rules.json | 类型检测/分解/运输/浓度/推断规则 |
| Step 3 | **完成** | name_translations.json | 72条中英文名映射(含别名) |
| Step 4 | **完成** | sds_generator.py | 加载JSON替代硬编码KB+规则 |
| Step 5 | **完成** | sds_pipeline_v2.py | CN_EN_MAP改为JSON加载 |
| Step 6 | **完成** | kb_manager.py | _apply_default_inference改为JSON驱动 |
