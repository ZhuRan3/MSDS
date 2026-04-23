import React, { useEffect, useState } from 'react';
import { Card, Typography, Descriptions, Tag, Button, Space, Spin, Alert } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { chemicalsApi } from '../../api/chemicals';
import { getGHSClassificationColor } from '../../utils/ghs';

const { Title } = Typography;

const ChemicalDetail: React.FC = () => {
  const { cas } = useParams<{ cas: string }>();
  const navigate = useNavigate();
  const [chemical, setChemical] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (cas) loadChemical();
  }, [cas]);

  const loadChemical = async () => {
    setLoading(true);
    try {
      const res: any = await chemicalsApi.get(cas!);
      setChemical(res);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!chemical) return <Alert message="化学品不存在" type="error" />;

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/knowledge')}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>{chemical.chemical_name_cn || chemical.cas_number}</Title>
      </Space>

      <Card title="基本信息" style={{ marginBottom: 16 }}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="CAS 号">{chemical.cas_number}</Descriptions.Item>
          <Descriptions.Item label="中文名称">{chemical.chemical_name_cn}</Descriptions.Item>
          <Descriptions.Item label="英文名称">{chemical.chemical_name_en}</Descriptions.Item>
          <Descriptions.Item label="分子式">{chemical.molecular_formula}</Descriptions.Item>
          <Descriptions.Item label="分子量">{chemical.molecular_weight}</Descriptions.Item>
          <Descriptions.Item label="化学类别">{chemical.chemical_family}</Descriptions.Item>
          <Descriptions.Item label="UN 编号">{chemical.un_number}</Descriptions.Item>
          <Descriptions.Item label="数据来源">{chemical.data_source}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="GHS 分类" style={{ marginBottom: 16 }}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="信号词">
            <Tag color={chemical.signal_word === '危险' ? 'red' : 'orange'}>
              {chemical.signal_word}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="象形图">
            <Space>{(chemical.pictograms || []).map((p: string, i: number) => <Tag key={i}>{p}</Tag>)}</Space>
          </Descriptions.Item>
          <Descriptions.Item label="GHS 分类" span={2}>
            <Space wrap>
              {(chemical.ghs_classifications || []).map((c: string, i: number) => (
                <Tag key={i} color={getGHSClassificationColor(c)}>{c}</Tag>
              ))}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="危险说明" span={2}>
            <Space wrap>{(chemical.hazard_statements || []).map((h: string, i: number) => <Tag key={i}>{h}</Tag>)}</Space>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="理化性质" style={{ marginBottom: 16 }}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="闪点">{chemical.flash_point || '-'}</Descriptions.Item>
          <Descriptions.Item label="沸点">{chemical.boiling_point || '-'}</Descriptions.Item>
          <Descriptions.Item label="熔点">{chemical.melting_point || '-'}</Descriptions.Item>
          <Descriptions.Item label="密度">{chemical.density || '-'}</Descriptions.Item>
          <Descriptions.Item label="溶解性" span={2}>{chemical.solubility || '-'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="毒理学数据">
        <Descriptions bordered column={2}>
          <Descriptions.Item label="经口 LD50">{chemical.ld50_oral || '-'}</Descriptions.Item>
          <Descriptions.Item label="经皮 LD50">{chemical.ld50_dermal || '-'}</Descriptions.Item>
          <Descriptions.Item label="吸入 LC50" span={2}>{chemical.lc50_inhalation || '-'}</Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
};

export default ChemicalDetail;
