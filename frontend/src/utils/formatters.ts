// 格式化日期
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  try {
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

// 格式化日期时间
export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  try {
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

// 文档类型标签
export function getDocTypeLabel(type: string): string {
  return type === 'pure' ? '纯净物' : type === 'mixture' ? '混合物' : type;
}

// 文档状态标签
export function getStatusLabel(status: string): { text: string; color: string } {
  switch (status) {
    case 'generating': return { text: '生成中', color: 'processing' };
    case 'completed': return { text: '已完成', color: 'success' };
    case 'failed': return { text: '失败', color: 'error' };
    default: return { text: status, color: 'default' };
  }
}

// 截断文本
export function truncateText(text: string, maxLength: number = 100): string {
  if (!text || text.length <= maxLength) return text || '';
  return text.substring(0, maxLength) + '...';
}
