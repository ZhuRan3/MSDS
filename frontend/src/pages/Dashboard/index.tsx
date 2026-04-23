import React, { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Typography, Input, Button, Table, Tag } from 'antd';
import {
  DatabaseOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { msdsApi } from '../../api/msds';

const { Title } = Typography;
const { Search } = Input;

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState({ kb_count: 0, doc_count: 0, llm_provider: '' });
  const [recentDocs, setRecentDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    loadStats();
    loadRecentDocs();
  }, []);

  const loadStats = async () => {
    try {
      const res: any = await fetch('/api/system/status').then(r => r.json());
      setStats(res);
    } catch (e) {
      console.error(e);
    }
  };

  const loadRecentDocs = async () => {
    setLoading(true);
    try {
      const res: any = await msdsApi.listDocuments({ page: 1, page_size: 5 });
      setRecentDocs(res.items || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const handleQuickGenerate = async (value: string) => {
    if (!value.trim()) return;
    setGenerating(true);
    try {
      const res: any = await msdsApi.generatePure({ cas_or_name: value.trim() });
      navigate(`/documents/${res.task_id}`);
    } catch (e) {
      console.error(e);
    }
    setGenerating(false);
  };

  const docColumns = [
    {
      title: '文档名称',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'doc_type',
      key: 'doc_type',
      width: 100,
      render: (type: string) => (
        <Tag color={type === 'pure' ? 'blue' : 'green'}>
          {type === 'pure' ? '纯净物' : '混合物'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const colors: Record<string, string> = {
          generating: 'processing',
          completed: 'success',
          failed: 'error',
        };
        const labels: Record<string, string> = {
          generating: '生成中',
          completed: '已完成',
          failed: '失败',
        };
        return <Tag color={colors[status]}>{labels[status] || status}</Tag>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (text: string) => text ? new Date(text).toLocaleDateString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: any, record: any) => (
        <Button type="link" size="small" onClick={() => navigate(`/documents/${record.id}`)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>仪表板</Title>

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="知识库化学品"
              value={stats.kb_count}
              prefix={<DatabaseOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="MSDS 文档数"
              value={stats.doc_count}
              prefix={<FileTextOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="LLM 提供商"
              value={stats.llm_provider || '未配置'}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="系统版本"
              value="1.0.0"
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card title="快速生成 MSDS" style={{ marginBottom: 24 }}>
        <Search
          placeholder="输入 CAS 号或化学品名称"
          enterButton={<Button type="primary" icon={<ThunderboltOutlined />} loading={generating}>立即生成</Button>}
          size="large"
          onSearch={handleQuickGenerate}
          loading={generating}
        />
      </Card>

      <Card title="最近生成的 MSDS 文档">
        <Table
          columns={docColumns}
          dataSource={recentDocs}
          rowKey="id"
          loading={loading}
          pagination={false}
          size="small"
        />
      </Card>
    </div>
  );
};

export default Dashboard;
