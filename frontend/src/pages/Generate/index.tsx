import React from 'react';
import { Tabs, Typography } from 'antd';
import PureGenerate from './PureGenerate';
import MixtureGenerate from './MixtureGenerate';

const { Title } = Typography;

const Generate: React.FC = () => {
  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>MSDS 生成工作台</Title>
      <Tabs
        defaultActiveKey="pure"
        items={[
          {
            key: 'pure',
            label: '纯净物 MSDS',
            children: <PureGenerate />,
          },
          {
            key: 'mixture',
            label: '混合物 MSDS',
            children: <MixtureGenerate />,
          },
        ]}
      />
    </div>
  );
};

export default Generate;
