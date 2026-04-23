import React, { useState } from 'react';
import {
  Card, Form, Input, Button, Steps, message, Collapse, Row, Col, Descriptions, Space, Typography
} from 'antd';
import { ThunderboltOutlined, SearchOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { msdsApi } from '../../api/msds';
import { chemicalsApi } from '../../api/chemicals';

const { Title, Text } = Typography;

const PureGenerate: React.FC = () => {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [pubchemData, setPubchemData] = useState<any>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [pollTimer, setPollTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  const steps = [
    { title: '输入信息' },
    { title: '获取数据' },
    { title: 'AI 生成' },
    { title: '完成' },
  ];

  const handleFetchPubChem = async () => {
    const cas = form.getFieldValue('cas_or_name');
    if (!cas) {
      message.warning('请输入 CAS 号或化学品名称');
      return;
    }
    try {
      const res: any = await chemicalsApi.fetchPubChem(cas);
      setPubchemData(res);
      message.success('PubChem 数据获取成功');
    } catch (e) {
      message.error('PubChem 查询失败');
    }
  };

  const handleGenerate = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      setCurrentStep(1);

      const res: any = await msdsApi.generatePure({
        cas_or_name: values.cas_or_name,
        company_name: values.company_name,
        company_address: values.company_address,
        company_phone: values.company_phone,
        emergency_phone: values.emergency_phone,
      });

      setTaskId(res.task_id);
      setCurrentStep(2);

      // Poll for status
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
            message.error('MSDS 生成失败');
          }
        } catch (e) {
          console.error(e);
        }
      }, 3000);

      setPollTimer(timer);
    } catch (e) {
      setLoading(false);
    }
  };

  const handleViewDocument = () => {
    if (taskId) {
      navigate(`/documents/${taskId}`);
    }
  };

  React.useEffect(() => {
    return () => {
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [pollTimer]);

  return (
    <div>
      <Steps current={currentStep} items={steps} style={{ marginBottom: 24 }} />

      {currentStep === 0 && (
        <Card title="纯净物 MSDS 生成">
          <Form form={form} layout="vertical">
            <Form.Item
              name="cas_or_name"
              label="CAS 号或化学品名称"
              rules={[{ required: true, message: '请输入 CAS 号或化学品名称' }]}
            >
              <Input.Search
                placeholder="例如: 108-95-2 或 苯酚"
                enterButton={<Button icon={<SearchOutlined />}>从 PubChem 获取</Button>}
                onSearch={handleFetchPubChem}
              />
            </Form.Item>

            {pubchemData && (
              <Card size="small" title="PubChem 数据预览" style={{ marginBottom: 16 }}>
                <Descriptions size="small" column={2}>
                  <Descriptions.Item label="CID">{pubchemData.cid}</Descriptions.Item>
                  <Descriptions.Item label="分子式">
                    {pubchemData.properties?.MolecularFormula || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="分子量">
                    {pubchemData.properties?.MolecularWeight || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="IUPAC">
                    {pubchemData.properties?.IUPACName || '-'}
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            )}

            <Collapse
              items={[{
                key: 'company',
                label: '企业信息（可选）',
                children: (
                  <>
                    <Row gutter={16}>
                      <Col span={12}>
                        <Form.Item name="company_name" label="企业名称">
                          <Input placeholder="企业名称" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="company_phone" label="联系电话">
                          <Input placeholder="联系电话" />
                        </Form.Item>
                      </Col>
                    </Row>
                    <Form.Item name="company_address" label="企业地址">
                      <Input placeholder="企业地址" />
                    </Form.Item>
                    <Form.Item name="emergency_phone" label="应急电话">
                      <Input placeholder="应急电话" />
                    </Form.Item>
                  </>
                ),
              }]}
              style={{ marginBottom: 16 }}
            />

            <Form.Item>
              <Button
                type="primary"
                size="large"
                icon={<ThunderboltOutlined />}
                loading={loading}
                onClick={handleGenerate}
              >
                开始生成 MSDS
              </Button>
            </Form.Item>
          </Form>
        </Card>
      )}

      {(currentStep === 1 || currentStep === 2) && (
        <Card>
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Title level={4}>正在生成 MSDS...</Title>
            <Text type="secondary">系统正在获取数据并调用 AI 生成 MSDS，请耐心等待</Text>
            <br /><br />
            <Steps
              direction="vertical"
              current={currentStep === 1 ? 0 : 1}
              items={[
                { title: '获取化学品数据' },
                { title: '检索知识库' },
                { title: 'AI 生成各部分内容' },
                { title: '质量审查' },
              ]}
            />
          </div>
        </Card>
      )}

      {currentStep === 3 && (
        <Card>
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Title level={4} style={{ color: '#52c41a' }}>MSDS 生成完成！</Title>
            <Space>
              <Button type="primary" size="large" onClick={handleViewDocument}>
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

export default PureGenerate;
