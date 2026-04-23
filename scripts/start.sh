#!/bin/bash
# 生产启动脚本
echo "============================================"
echo "化安通 (HuaAnTong) MSDS 系统启动"
echo "============================================"

cd backend

# 激活虚拟环境
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

echo "启动服务..."
uvicorn app.main:app --host 0.0.0.0 --port 8000
