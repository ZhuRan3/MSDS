import React, { useState } from 'react';
import {
  Card, Typography, Table, Input, InputNumber, Button, Space, Tag, Descriptions,
  Alert, Divider, message,
} from 'antd';
import { CalculatorOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { mixtureApi } from '../../api/mixture';
import { getGHSClassificationColor } from '../../utils/ghs';

const { Title, Text } = Typography;

interface CompRow {
  key: string;
  name: string;
  cas: string;
  concentration: number;
}

const Calculator: React.FC = () => {
  const [components, setComponents] = useState<CompRow[]>([
    { key: '1', name: '', cas: '', concentration: 0 },
    { key: '2', name: '', cas: '', concentration: 0 },
  ]);
  const [result, setResult] = useState<any>(null);
  const [calculating, setCalculating] = useState(false);

  const total = components.reduce((s, c) => s + (c.concentration || 0), 0);

  const addRow = () => {
    setComponents([...components, { key: Date.now().toString(), name: '', cas: '', concentration: 0 }]);
  };

  const removeRow = (key: string) => {
    if (components.length <= 2) return;
    setComponents(components.filter(c => c.key !== key));
  };

  const updateRow = (key: string, field: string, value: any) => {
    setComponents(components.map(c => c.key === key ? { ...c, [field]: value } : c));
  };

  const handleCalculate = async () => {
    const valid = components.filter(c => c.name && c.concentration > 0);
    if (valid.length < 2) {
      message.error('请至少填写 2 个有效组分');
      return;
    }

    setCalculating(true);
    try {
      const res: any = await mixtureApi.calculate({
        components: valid.map(c => ({
          name: c.name,
          cas: c.cas,
          concentration: c.concentration,
        })),
      });
      setResult(res);
    } catch (e) {
      message.error('计算失败');
    }
    setCalculating(false);
  };

  const columns = [
    {
      title: '组分名称',
      dataIndex: 'name',
      render: (_: any, r: CompRow) => (
        <Input value={r.name} onChange={e => updateRow(r.key, 'name', e.target.value)} placeholder="化学品名称" />
      ),
    },
    {
      title: 'CAS 号',
      dataIndex: 'cas',
      width: 160,
      render: (_: any, r: CompRow) => (
        <Input value={r.cas} onChange={e => updateRow(r.key, 'cas', e.target.value)} placeholder="如: 64-17-5" />
      ),
    },
    {
      title: '浓度 (%)',
      dataIndex: 'concentration',
      width: 110,
      render: (_: any, r: CompRow) => (
        <InputNumber value={r.concentration} onChange={v => updateRow(r.key, 'concentration', v || 0)}
          min={0} max={100} style={{ width: '100%' }} />
      ),
    },
    {
      title: '',
      width: 50,
      render: (_: any, r: CompRow) => (
        <Button type="text" danger icon={<DeleteOutlined />} onClick={() => removeRow(r.key)}
          disabled={components.length <= 2} />
      ),
    },
  ];

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>混合物 GHS 分类计算器</Title>

      <Card title="组分编辑器" style={{ marginBottom: 16 }}>
        {Math.abs(total - 100) > 1 && total > 0 && (
          <Alert message={`浓度总和为 ${total.toFixed(1)}%，不等于 100%`} type="warning" showIcon style={{ marginBottom: 12 }} />
        )}
        <Table
          columns={columns}
          dataSource={components}
          rowKey="key"
          pagination={false}
          footer={() => (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <Button type="dashed" icon={<PlusOutlined />} onClick={addRow}>添加组分</Button>
              <Text>总和: {total.toFixed(1)}%</Text>
            </div>
          )}
        />
        <div style={{ marginTop: 16, textAlign: 'right' }}>
          <Button type="primary" size="large" icon={<CalculatorOutlined />} loading={calculating}
            onClick={handleCalculate}>
            计算 GHS 分类
          </Button>
        </div>
      </Card>

      {result && (
        <Card title="计算结果">
          <Descriptions bordered column={2} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="信号词">
              <Tag color={result.signal_word === '危险' ? 'red' : 'orange'} style={{ fontSize: 16, padding: '4px 12px' }}>
                {result.signal_word}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="H 码汇总">
              <Space>{(result.h_codes || []).map((h: string, i: number) => <Tag key={i} color="red">{h}</Tag>)}</Space>
            </Descriptions.Item>
            {result.ate_oral && (
              <Descriptions.Item label="经口 ATE">{result.ate_oral.toFixed(1)} mg/kg</Descriptions.Item>
            )}
            {result.ate_dermal && (
              <Descriptions.Item label="经皮 ATE">{result.ate_dermal.toFixed(1)} mg/kg</Descriptions.Item>
            )}
            {result.flammability_class && (
              <Descriptions.Item label="易燃性分类" span={2}>{result.flammability_class}</Descriptions.Item>
            )}
          </Descriptions>

          <Title level={5}>分类详情</Title>
          <Table
            size="small"
            dataSource={(result.classifications || []).map((c: any, i: number) => ({ ...c, _key: i }))}
            rowKey="_key"
            pagination={false}
            columns={[
              { title: '危害分类', dataIndex: 'hazard', key: 'hazard',
                render: (v: string) => <Tag color={getGHSClassificationColor(v)}>{v}</Tag> },
              { title: 'H 码', dataIndex: 'h_code', key: 'h_code', width: 80 },
              { title: '信号', dataIndex: 'signal', key: 'signal', width: 80,
                render: (v: string) => <Tag color={v === '危险' ? 'red' : 'orange'}>{v}</Tag> },
              { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true },
            ]}
          />

          {result.calculation_log && result.calculation_log.length > 0 && (
            <>
              <Divider />
              <Title level={5}>计算过程</Title>
              <Card size="small" style={{ background: '#fafafa', maxHeight: 300, overflow: 'auto' }}>
                <pre style={{ fontSize: 12, margin: 0 }}>
                  {result.calculation_log.join('\n')}
                </pre>
              </Card>
            </>
          )}
        </Card>
      )}
    </div>
  );
};

export default Calculator;
