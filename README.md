# 语音约碰面地点

全栈骨架：后端 FastAPI（端口 8003），前端 React + Vite（端口 5175）。

## 环境要求

- Python 3.11
- Node.js 22.12 及以上的 22.x

## 后端

```bash
cd backend
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --host 0.0.0.0 --port 8003 --reload
```

健康检查：`GET http://localhost:8003/health`  
交互文档：`http://localhost:8003/docs`

可选本地测试（需已安装依赖）：

```bash
cd backend
pytest tests/test_health.py -q
```

## 前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开：`http://localhost:5175`

## 说明

- 外部服务密钥写在 `backend/.env`，仓库只保留 `.env.example` 空值模板。
- 未填写密钥时，`GET /health` 仍应返回成功。
- 录音与其余业务接口尚未实现。

## 测试分层

- **模拟测试**：对已实现接口使用 Mock / TestClient，避免反复付费。
- **真实接口验收**：配置密钥后，由人工验证 ASR、DeepSeek、高德、TTS，并完成前端全链路验收。Mock 通过不能证明真实联调已跑通。
