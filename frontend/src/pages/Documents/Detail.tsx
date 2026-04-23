import React, { useEffect, useState } from 'react';
import {
  Card, Typography, Descriptions, Tag, Button, Space, Spin, Anchor, Row, Col,
  Table, Alert, message,
} from 'antd';
import {
  ArrowLeftOutlined, SafetyCertificateOutlined,
  FilePdfOutlined, FileWordOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { msdsApi } from '../../api/msds';
import type { MSDSData } from '../../types/msds';

const { Title, Text } = Typography;

const SDS_PART_NAMES: Record<string, string> = {
  document_info: '文档信息',
  part1_identification: '第一部分：化学品及企业标识',
  part2_hazard: '第二部分：危险性概述',
  part3_composition: '第三部分：成分/组成信息',
  part4_first_aid: '第四部分：急救措施',
  part5_firefighting: '第五部分：消防措施',
  part6_spill: '第六部分：泄漏应急处理',
  part7_handling: '第七部分：操作处置与储存',
  part8_exposure: '第八部分：接触控制/个体防护',
  part9_physical: '第九部分：理化特性',
  part10_stability: '第十部分：稳定性和反应性',
  part11_toxicology: '第十一部分：毒理学信息',
  part12_ecology: '第十二部分：生态学信息',
  part13_disposal: '第十三部分：废弃处置',
  part14_transport: '第十四部分：运输信息',
  part15_regulatory: '第十五部分：法规信息',
  part16_other: '第十六部分：其他信息',
};

const Detail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [reviewResult, setReviewResult] = useState<any>(null);

  useEffect(() => {
    if (id) loadDocument();
  }, [id]);

  const loadDocument = async () => {
    setLoading(true);
    try {
      const res: any = await msdsApi.getDocument(Number(id));
      setDoc(res);
    } catch (e) {
      message.error('文档加载失败');
    }
    setLoading(false);
  };

  const handleExportPdf = async () => {
    try {
      const res: any = await msdsApi.exportPdf(Number(id));
      // Download blob
      const url = window.URL.createObjectURL(new Blob([res]));
      const link = document.createElement('a');
      link.href = url;
      link.download = `MSDS_${id}.pdf`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      message.error('PDF 导出失败');
    }
  };

  const handleExportWord = async () => {
    try {
      const res: any = await msdsApi.exportWord(Number(id));
      const url = window.URL.createObjectURL(new Blob([res]));
      const link = document.createElement('a');
      link.href = url;
      link.download = `MSDS_${id}.docx`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      message.error('Word 导出失败');
    }
  };

  const handleReview = async () => {
    try {
      const res: any = await msdsApi.reviewDocument(Number(id));
      setReviewResult(res);
      message.success('审查完成');
    } catch (e) {
      message.error('审查失败');
    }
  };

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!doc) return <Alert message="文档不存在" type="error" />;

  const data = doc.data as MSDSData | null;

  const renderPart = (_partKey: string, partData: any) => {
    if (!partData || typeof partData !== 'object') return <Text type="secondary">无数据</Text>;

    return (
      <Descriptions bordered size="small" column={1}>
        {Object.entries(partData).map(([key, value]) => {
          if (key.startsWith('_')) return null;
          return (
            <Descriptions.Item key={key} label={key.replace(/_/g, ' ')}>
              {renderValue(value)}
            </Descriptions.Item>
          );
        })}
      </Descriptions>
    );
  };

  const renderValue = (value: any): React.ReactNode => {
    if (value === null || value === undefined) return <Text type="secondary">无资料</Text>;
    if (typeof value === 'string') return value || <Text type="secondary">-</Text>;
    if (typeof value === 'number') return String(value);
    if (Array.isArray(value)) {
      if (value.length === 0) return <Text type="secondary">-</Text>;
      if (typeof value[0] === 'string') return value.map((v, i) => <Tag key={i}>{v}</Tag>);
      return (
        <Table
          size="small"
          dataSource={value.map((v, i) => ({ ...v, _key: i }))}
          rowKey="_key"
          pagination={false}
          columns={Object.keys(value[0]).filter(k => !k.startsWith('_')).map(k => ({
            title: k.replace(/_/g, ' '),
            dataIndex: k,
            key: k,
            render: (v: any) => renderValue(v),
          }))}
        />
      );
    }
    if (typeof value === 'object') {
      return (
        <Descriptions size="small" column={1}>
          {Object.entries(value).map(([k, v]) => (
            <Descriptions.Item key={k} label={k.replace(/_/g, ' ')}>
              {renderValue(v)}
            </Descriptions.Item>
          ))}
        </Descriptions>
      );
    }
    return String(value);
  };

  const partKeys = data ? Object.keys(data).filter(k => k.startsWith('part')) : [];

  const anchorItems = partKeys.map(key => ({
    key,
    href: `#section-${key}`,
    title: SDS_PART_NAMES[key] || key,
  }));

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, alignItems: 'center' }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/documents')}>返回</Button>
          <Title level={4} style={{ margin: 0 }}>{doc.title}</Title>
          <Tag color={doc.status === 'completed' ? 'green' : 'blue'}>{doc.status}</Tag>
          <Tag>{doc.doc_type === 'pure' ? '纯净物' : '混合物'}</Tag>
        </Space>
        <Space>
          <Button icon={<FilePdfOutlined />} onClick={handleExportPdf}>导出 PDF</Button>
          <Button icon={<FileWordOutlined />} onClick={handleExportWord}>导出 Word</Button>
          <Button icon={<SafetyCertificateOutlined />} onClick={handleReview}>审查报告</Button>
        </Space>
      </div>

      {reviewResult && (
        <Card size="small" title="审查结果" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Tag color={reviewResult.status === 'PASS' ? 'green' : reviewResult.status === 'FAIL' ? 'red' : 'orange'}>
              综合: {reviewResult.status}
            </Tag>
            {reviewResult.issues?.map((issue: string, i: number) => (
              <Alert key={i} message={issue} type="error" showIcon />
            ))}
            {reviewResult.warnings?.map((warn: string, i: number) => (
              <Alert key={i} message={warn} type="warning" showIcon />
            ))}
          </Space>
        </Card>
      )}

      <Row gutter={16}>
        <Col span={4}>
          <Anchor items={anchorItems} offsetTop={80} />
        </Col>
        <Col span={20}>
          {data && partKeys.map(key => (
            <Card
              key={key}
              id={`section-${key}`}
              title={SDS_PART_NAMES[key] || key}
              size="small"
              style={{ marginBottom: 12 }}
            >
              {renderPart(key, data[key as keyof MSDSData])}
            </Card>
          ))}
        </Col>
      </Row>
    </div>
  );
};

export default Detail;
