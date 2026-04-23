import React, { useState } from 'react';
import {
  Card, Form, Input, InputNumber, Button, Table, Space, Typography, Steps, message, Alert
} from 'antd';
import { PlusOutlined, DeleteOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { msdsApi } from '../../api/msds';

const { Title, Text } = Typography;

interface ComponentRow {
  key: string;
  name: string;
  cas: string;
  concentration: number;
}

const MixtureGenerate: React.FC = () => {
  const navigate = useNavigate();
  const [productName, setProductName] = useState('');
  const [components, setComponents] = useState<ComponentRow[]>([
    { key: '1', name: '', cas: '', concentration: 0 },
  ]);
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [taskId, setTaskId] = useState<number | null>(null);

  const totalConcentration = components.reduce((sum, c) => sum + (c.concentration || 0), 0);

  const addRow = () => {
    const newKey = String(components.length + 1);
    setComponents([...components, { key: newKey, name: '', cas: '', concentration: 0 }]);
  };

  const removeRow = (key: string) => {
    if (components.length <= 1) return;
    setComponents(components.filter(c => c.key !== key));
  };

  const updateRow = (key: string, field: string, value: any) => {
    setComponents(components.map(c => c.key === key ? { ...c, [field]: value } : c));
  };

  const handleGenerate = async () => {
    const validComponents = components.filter(c => c.name && c.concentration > 0);
    if (validComponents.length < 2) {
      message.error('请至少添加 2 个有效组分');
      return;
    }

    setLoading(true);
    setCurrentStep(1);

    try {
      const res: any = await msdsApi.generateMixture({
        product_name: productName || '混合物',
        components: validComponents.map(c => ({
          name: c.name,
          cas: c.cas,
          concentration: c.concentration,
        })),
      });

      setTaskId(res.task_id);
      setCurrentStep(2);

      const timer = setInterval(async () => {
        try {
          const status: any = await msdsApi.getTaskStatus(res.task_id);
          if (status.status === 'completed') {
            clearInterval(timer);
            setCurrentStep(3);
            setLoading(false);
            message.success('MSDS 生成完成！');
          } else if (status.status === 'failed') {
            clearInterval(timer);
            setCurrentStep(3);
            setLoading(false);
            message.error('生成失败');
          }
        } catch (e) {
          console.error(e);
        }
      }, 3000);
    } catch (e) {
      setLoading(false);
      setCurrentStep(0);
    }
  };

  const columns = [
    {
      title: '组分名称',
      dataIndex: 'name',
      render: (_: any, record: ComponentRow) => (
        <Input
          value={record.name}
          onChange={e => updateRow(record.key, 'name', e.target.value)}
          placeholder="化学品名称"
        />
      ),
    },
    {
      title: 'CAS 号',
      dataIndex: 'cas',
      width: 180,
      render: (_: any, record: ComponentRow) => (
        <Input
          value={record.cas}
          onChange={e => updateRow(record.key, 'cas', e.target.value)}
          placeholder="如: 64-17-5"
        />
      ),
    },
    {
      title: '浓度 (%)',
      dataIndex: 'concentration',
      width: 120,
      render: (_: any, record: ComponentRow) => (
        <InputNumber
          value={record.concentration}
          onChange={v => updateRow(record.key, 'concentration', v || 0)}
          min={0}
          max={100}
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '操作',
      width: 60,
      render: (_: any, record: ComponentRow) => (
        <Button
          type="text"
          danger
          icon={<DeleteOutlined />}
          onClick={() => removeRow(record.key)}
          disabled={components.length <= 1}
        />
      ),
    },
  ];

  return (
    <div>
      <Steps
        current={currentStep}
        items={[{ title: '输入组分' }, { title: 'AI 生成' }, { title: '完成' }]}
        style={{ marginBottom: 24 }}
      />

      {currentStep === 0 && (
        <Card title="混合物 MSDS 生成">
          <Form layout="vertical">
            <Form.Item label="产品名称">
              <Input
                value={productName}
                onChange={e => setProductName(e.target.value)}
                placeholder="混合物产品名称（可选）"
                style={{ marginBottom: 16 }}
              />
            </Form.Item>

            {Math.abs(totalConcentration - 100) > 1 && totalConcentration > 0 && (
              <Alert
                message={`浓度总和为 ${totalConcentration.toFixed(1)}%，不等于 100%`}
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
              />
            )}

            <Table
              columns={columns}
              dataSource={components}
              rowKey="key"
              pagination={false}
              footer={() => (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Button type="dashed" icon={<PlusOutlined />} onClick={addRow}>
                    添加组分
                  </Button>
                  <Text>浓度总和: {totalConcentration.toFixed(1)}%</Text>
                </div>
              )}
            />

            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <Button
                type="primary"
                size="large"
                icon={<ThunderboltOutlined />}
                loading={loading}
                onClick={handleGenerate}
              >
                开始生成 MSDS
              </Button>
            </div>
          </Form>
        </Card>
      )}

      {currentStep === 2 && (
        <Card>
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Title level={4}>正在生成混合物 MSDS...</Title>
            <Text type="secondary">系统正在计算 GHS 分类并调用 AI 生成 MSDS</Text>
          </div>
        </Card>
      )}

      {currentStep === 3 && (
        <Card>
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Title level={4} style={{ color: '#52c41a' }}>混合物 MSDS 生成完成！</Title>
            <Space>
              <Button type="primary" size="large" onClick={() => taskId && navigate(`/documents/${taskId}`)}>
                查看文档
              </Button>
              <Button size="large" onClick={() => { setCurrentStep(0); setTaskId(null); }}>
                继续生成
              </Button>
            </Space>
          </div>
        </Card>
      )}
    </div>
  );
};

export default MixtureGenerate;
