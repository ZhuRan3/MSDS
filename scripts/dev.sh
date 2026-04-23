#!/bin/bash
# 开发环境启动脚本
echo "============================================"
echo "化安通 (HuaAnTong) MSDS 系统开发环境启动"
echo "============================================"

# 检查后端依赖
echo "[1/3] 检查后端依赖..."
cd backend
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    echo "创建 Python 虚拟环境..."
    python -m venv venv
fi

# 激活虚拟环境
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

pip install -r requirements.txt -q

# 启动后端
echo "[2/3] 启动 FastAPI 后端..."
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
echo "后端进程 PID: $BACKEND_PID"

cd ..

# 检查前端依赖
echo "[3/3] 启动 React 前端..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "安装前端依赖..."
    npm install
fi
npm run dev &
FRONTEND_PID=$!
echo "前端进程 PID: $FRONTEND_PID"

cd ..

echo ""
echo "============================================"
echo "启动完成！"
echo "  前端: http://localhost:5173"
echo "  后端: http://localhost:8000"
echo "  API 文档: http://localhost:8000/docs"
echo "============================================"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待进程
wait
