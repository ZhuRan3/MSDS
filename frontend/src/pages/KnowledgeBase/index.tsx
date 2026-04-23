import React, { useEffect, useState } from 'react';
import {
  Table, Card, Typography, Tag, Button, Space, Input, message, Popconfirm, Modal,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { chemicalsApi } from '../../api/chemicals';
import { getGHSClassificationColor } from '../../utils/ghs';

const { Title } = Typography;
const { Search } = Input;

const KnowledgeBase: React.FC = () => {
  const navigate = useNavigate();
  const [chemicals, setChemicals] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addCas, setAddCas] = useState('');
  const [addName, setAddName] = useState('');
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    loadChemicals();
  }, [page, search]);

  const loadChemicals = async () => {
    setLoading(true);
    try {
      const res: any = await chemicalsApi.list({ page, page_size: 20, search: search || undefined });
      setChemicals(res.items || []);
      setTotal(res.total || 0);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const handleAdd = async () => {
    if (!addCas.trim()) {
      message.warning('请输入 CAS 号或化学品名称');
      return;
    }
    setAdding(true);
    try {
      await chemicalsApi.add(addCas, addName);
      message.success('添加成功');
      setAddModalOpen(false);
      setAddCas('');
      setAddName('');
      loadChemicals();
    } catch (e) {
      message.error('添加失败');
    }
    setAdding(false);
  };

  const handleDelete = async (cas: string) => {
    try {
      await chemicalsApi.delete(cas);
      message.success('删除成功');
      loadChemicals();
    } catch (e) {
      message.error('删除失败');
    }
  };

  const columns = [
    {
      title: 'CAS 号',
      dataIndex: 'cas_number',
      key: 'cas_number',
      width: 130,
    },
    {
      title: '中文名称',
      dataIndex: 'chemical_name_cn',
      key: 'chemical_name_cn',
      ellipsis: true,
    },
    {
      title: '英文名称',
      dataIndex: 'chemical_name_en',
      key: 'chemical_name_en',
      ellipsis: true,
    },
    {
      title: '分子式',
      dataIndex: 'molecular_formula',
      key: 'molecular_formula',
      width: 100,
    },
    {
      title: '化学类别',
      dataIndex: 'chemical_family',
      key: 'chemical_family',
      width: 120,
    },
    {
      title: '信号词',
      dataIndex: 'signal_word',
      key: 'signal_word',
      width: 80,
      render: (word: string) => word ? (
        <Tag color={word === '危险' ? 'red' : 'orange'}>{word}</Tag>
      ) : '-',
    },
    {
      title: 'GHS 分类',
      dataIndex: 'ghs_classifications',
      key: 'ghs_classifications',
      width: 200,
      render: (classifications: string[]) => (
        <Space wrap size={2}>
          {(classifications || []).slice(0, 2).map((c, i) => (
            <Tag key={i} color={getGHSClassificationColor(c)} style={{ fontSize: 11 }}>
              {c.length > 12 ? c.substring(0, 12) + '...' : c}
            </Tag>
          ))}
          {(classifications || []).length > 2 && <Tag>+{classifications.length - 2}</Tag>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: any, record: any) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />}
            onClick={() => navigate(`/knowledge/${record.cas_number}`)}>
            详情
          </Button>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.cas_number)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>知识库管理</Title>
        <Space>
          <Button icon={<PlusOutlined />} type="primary" onClick={() => setAddModalOpen(true)}>
            添加化学品
          </Button>
          <Button icon={<ReloadOutlined />} onClick={loadChemicals}>刷新</Button>
        </Space>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Search
          placeholder="搜索 CAS 号、中英文名、分子式"
          allowClear
          onSearch={setSearch}
          style={{ maxWidth: 400 }}
        />
      </Card>

      <Card>
        <Table
          columns={columns}
          dataSource={chemicals}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize: 20,
            total,
            onChange: setPage,
            showTotal: t => `共 ${t} 条`,
          }}
        />
      </Card>

      <Modal
        title="添加化学品"
        open={addModalOpen}
        onOk={handleAdd}
        onCancel={() => setAddModalOpen(false)}
        confirmLoading={adding}
        okText="添加"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            placeholder="CAS 号（如: 108-95-2）"
            value={addCas}
            onChange={e => setAddCas(e.target.value)}
          />
          <Input
            placeholder="中文名称（可选，如: 苯酚）"
            value={addName}
            onChange={e => setAddName(e.target.value)}
          />
        </Space>
      </Modal>
    </div>
  );
};

export default KnowledgeBase;
