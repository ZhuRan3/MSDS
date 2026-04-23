#!/bin/bash
# 生产构建脚本
echo "============================================"
echo "化安通 (HuaAnTong) MSDS 系统生产构建"
echo "============================================"

cd frontend
echo "[1/2] 构建前端..."
npm run build
echo "前端构建完成: frontend/dist/"

cd ..

echo "[2/2] 安装后端依赖..."
cd backend
pip install -r requirements.txt -q

echo ""
echo "============================================"
echo "构建完成！使用以下命令启动："
echo "  cd backend"
echo "  uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "访问 http://localhost:8000 即可使用系统"
echo "============================================"
