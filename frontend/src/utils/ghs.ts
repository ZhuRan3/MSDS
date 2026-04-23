// GHS 象形图映射
export const GHS_PICTOGRAMS: Record<string, { name: string; code: string; color: string }> = {
  'GHS01': { name: '爆炸', code: 'GHS01', color: '#e74c3c' },
  'GHS02': { name: '火焰', code: 'GHS02', color: '#e67e22' },
  'GHS03': { name: '氧化剂', code: 'GHS03', color: '#e67e22' },
  'GHS04': { name: '气瓶', code: 'GHS04', color: '#3498db' },
  'GHS05': { name: '腐蚀', code: 'GHS05', color: '#9b59b6' },
  'GHS06': { name: '毒性', code: 'GHS06', color: '#c0392b' },
  'GHS07': { name: '感叹号', code: 'GHS07', color: '#f39c12' },
  'GHS08': { name: '健康危害', code: 'GHS08', color: '#e74c3c' },
  'GHS09': { name: '环境', code: 'GHS09', color: '#27ae60' },
};

// 中文象形图名到GHS代码映射
export const PICTOGRAM_NAME_MAP: Record<string, string> = {
  '爆炸': 'GHS01',
  '火焰': 'GHS02',
  '氧化剂': 'GHS03',
  '气瓶': 'GHS04',
  '腐蚀': 'GHS05',
  '毒性': 'GHS06',
  '感叹号': 'GHS07',
  '健康危害': 'GHS08',
  '环境': 'GHS09',
};

// 化学类别选项
export const CHEMICAL_FAMILIES = [
  '酚类化合物',
  '醇类化合物',
  '酮类化合物',
  '腈类化合物',
  '烷烃化合物',
  '芳香烃',
  '无机碱',
  '有机化合物',
];

// 信号词颜色映射
export function getSignalWordColor(word: string): string {
  if (word === '危险') return '#ff4d4f';
  if (word === '警告') return '#faad14';
  return '#d9d9d9';
}

// GHS 分类标签颜色
export function getGHSClassificationColor(classification: string): string {
  if (classification.includes('易燃')) return '#ff4d4f';
  if (classification.includes('腐蚀')) return '#9b59b6';
  if (classification.includes('毒')) return '#e74c3c';
  if (classification.includes('爆炸')) return '#e74c3c';
  if (classification.includes('氧化')) return '#e67e22';
  if (classification.includes('眼损伤') || classification.includes('眼刺激')) return '#f39c12';
  if (classification.includes('皮肤')) return '#f39c12';
  if (classification.includes('致癌')) return '#c0392b';
  if (classification.includes('生殖')) return '#c0392b';
  if (classification.includes('环境')) return '#27ae60';
  return '#1677ff';
}
