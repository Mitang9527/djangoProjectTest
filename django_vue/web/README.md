# 图灵智绘 AI · 前端（Vue3 + Vite）

Web + H5 兼容的电商商品图 / 视频生成前端，调用 Django 后端 `apps/ai_studio` 的接口。
桌面端组件用 **Element Plus**，移动端导航用 **Vant**，同一套代码响应式适配。

## 目录结构
```
django_vue/web/
├── package.json
├── vite.config.js        # dev server 代理 /api -> Django:8000
├── index.html
└── src/
    ├── main.js           # 注册 ElementPlus + Vant + Pinia + Router
    ├── App.vue           # 响应式布局：桌面 el-menu / 移动 van-nav-bar + van-tabbar
    ├── router/           # 路由（首页 / 工作台 / 登录）
    ├── api/              # axios 封装（自动附 JWT）+ aiStudio 接口
    ├── store/user.js     # Pinia：token / 用户名 / 额度（localStorage 持久化）
    ├── styles/global.css # 深色主题 + 响应式断点
    └── views/            # Home / Studio / Login
```

## 本地运行
```bash
cd django_vue/web
npm install
npm run dev          # http://localhost:5173
```

前端开发服务器通过 `vite.config.js` 的 proxy 把 `/api` 转发到后端 `http://127.0.0.1:8000`。

## 后端配套
后端位于 `apps/ai_studio`（已被框架自动发现，路由前缀 `/api/ai_studio/`）：
- `POST /api/ai_studio/demo-login/` 演示登录（创建用户 + 签发 JWT + 赠送 50 额度）
- `GET  /api/ai_studio/quota/`     查询额度
- `GET  /api/ai_studio/tasks/`     任务列表
- `POST /api/ai_studio/generate/`  创建生成任务（冻结额度 -> mock 生成 -> 确认扣减）

后端启动：
```bash
python manage.py migrate          # 生成 ai_studio 迁移
python manage.py runserver 8000   # 或 gunicorn / daphne
# 异步模式（settings.AI_STUDIO_SYNC=False）需另起 Celery worker：
celery -A djangoProjectTest worker -l info
```

## 说明
- `demo-login` 仅为演示打通闭环，生产应改用正式注册 + 已接好的 OIDC SSO。
- 生成目前为 **mock**（后端产出 SVG 占位图，离线可预览）；接入真实模型时替换
  `apps/ai_studio/services.py` 的 `run_mock_generation` 即可，额度冻结-确认机制不变。
- 额度采用「冻结-确认扣减」模式：创建任务先冻结，成功确认、失败返还，流水不可变可对账。
