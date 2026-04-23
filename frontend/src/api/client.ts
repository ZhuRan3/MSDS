import axios from 'axios';
import { message } from 'antd';

const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Response interceptor
client.interceptors.response.use(
  (response) => {
    return response.data;
  },
  (error) => {
    if (error.response) {
      const msg = error.response.data?.detail || error.response.data?.message || '请求失败';
      message.error(msg);
    } else if (error.request) {
      message.error('网络错误，请检查后端服务是否启动');
    } else {
      message.error('请求配置错误');
    }
    return Promise.reject(error);
  }
);

export default client;
