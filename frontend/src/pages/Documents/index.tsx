import React, { useEffect, useState } from 'react';
import { Table, Card, Typography, Tag, Button, Space, message, Popconfirm } from 'antd';
import { DeleteOutlined, EyeOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { msdsApi } from '../../api/msds';

const { Title } = Typography;

const Documents: React.FC = () => {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  useEffect(() => {
    loadDocuments();
  }, [page, pageSize]);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const res: any = await msdsApi.listDocuments({ page, page_size: pageSize });
      setDocuments(res.items || []);
      setTotal(res.total || 0);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const handleDelete = async (id: number) => {
    try {
      await msdsApi.deleteDocument(id);
      message.success('删除成功');
      loadDocuments();
    } catch (e) {
      message.error('删除失败');
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
    {
      title: '文档名称',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: 'CAS 号',
      dataIndex: 'cas_number',
      key: 'cas_number',
      width: 130,
    },
    {
      title: '类型',
      dataIndex: 'doc_type',
      key: 'doc_type',
      width: 90,
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
      width: 90,
      render: (status: string) => {
        const map: Record<string, { color: string; label: string }> = {
          generating: { color: 'processing', label: '生成中' },
          completed: { color: 'success', label: '已完成' },
          failed: { color: 'error', label: '失败' },
        };
        const info = map[status] || { color: 'default', label: status };
        return <Tag color={info.color}>{info.label}</Tag>;
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
      width: 120,
      render: (_: any, record: any) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/documents/${record.id}`)}
          >
            查看
          </Button>
          <Popconfirm title="确定删除此文档？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>MSDS 文档管理</Title>
        <Button icon={<ReloadOutlined />} onClick={loadDocuments}>刷新</Button>
      </div>
      <Card>
        <Table
          columns={columns}
          dataSource={documents}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Card>
    </div>
  );
};

export default Documents;
