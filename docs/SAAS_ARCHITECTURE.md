# SaaS 后台管理系统 - 架构设计文档

## 📋 目录
1. [系统概述](#系统概述)
2. [技术架构](#技术架构)
3. [功能模块](#功能模块)
4. [数据库设计](#数据库设计)
5. [API 设计](#api-设计)
6. [权限体系](#权限体系)

---

## 系统概述

### 核心设计理念
- **多租户架构**：支持多租户隔离（共享数据库共享Schema）
- **模块化设计**：可插拔的功能模块
- **权限精细化**：基于角色的访问控制（RBAC）
- **响应式UI**：现代化的用户界面

### 系统定位
企业级多租户SaaS后台管理系统，提供完整的租户、用户、权限、计费管理等核心功能。

---

## 技术架构

### 前端技术栈
```
- Tailwind CSS 3.x     - UI 框架
- Alpine.js 3.x        - 轻量级交互框架
- HTMX 1.9.x           - 无刷新页面更新
- Django Templates     - 服务器端渲染
```

### 后端技术栈
```
- Django 5.x           - Web 框架
- Django REST Framework - API 框架
- Django Channels      - WebSocket 支持
- PostgreSQL/SQLite    - 数据库
- Redis                - 缓存/会话存储
```

### 项目结构
```
apps/
├── saas/                  # SaaS 核心模块
│   ├── models.py          # 数据模型
│   ├── views.py           # 视图函数
│   ├── urls.py            # 路由配置
│   ├── serializers.py     # API 序列化
│   ├── permissions.py     # 权限控制
│   ├── admin.py           # 后台管理
│   └── templates/saas/    # 模板文件
├── users/                 # 用户模块（已存在）
└── core/                  # 核心模块（已存在）
```

---

## 功能模块

### 1. 租户管理 (Tenant Management)
- 租户创建/编辑/删除
- 租户套餐配置
- 租户状态管理（激活/禁用）
- 租户数据统计

### 2. 用户管理 (User Management)
- 租户内用户CRUD
- 用户角色分配
- 用户状态管理
- 批量操作

### 3. 权限管理 (Permission Management)
- 角色管理（Role）
- 权限配置（Permission）
- 角色权限关联
- 用户角色绑定

### 4. 套餐管理 (Plan Management)
- 套餐定义
- 功能模块配置
- 价格策略
- 套餐上下架

### 5. 订单管理 (Order Management)
- 订单创建/查询
- 支付记录
- 订单状态流转
- 退款处理

### 6. 数据统计 (Analytics)
- 租户数据概览
- 用户活跃统计
- 收入分析
- 系统监控

### 7. 系统设置 (System Settings)
- 全局配置
- 通知模板
- 日志审计
- 数据备份

---

## 数据库设计

### 核心数据表关系图

```
┌─────────────────┐
│    Tenant       │  租户表
└────────┬────────┘
         │
         ├─── TenantSubscription (订阅关系)
         │
         ├─── TenantMember (租户成员)
         │
         ├─── TenantConfig (租户配置)
         │
         └─── Order (订单)
                │
                └─── Invoice (发票)

┌─────────────────┐
│      User       │  用户表（已存在）
└────────┬────────┘
         │
         ├─── Role (角色)
         │
         └─── Permission (权限)

┌─────────────────┐
│      Plan       │  套餐表
└────────┬────────┘
         │
         └─── PlanFeature (套餐功能)
```

### 详细数据表说明

#### 1. Tenant (租户表)
```python
- id              # 租户ID
- name            # 租户名称
- slug            # 租户标识（URL友好）
- domain          # 租户域名（可选）
- logo            # 租户Logo
- description     # 描述
- status          # 状态（active/suspended/cancelled）
- plan            # 关联套餐
- billing_date    # 账单日期
- stripe_customer_id  # Stripe客户ID（可选）
- created_by      # 创建者
- created_at      # 创建时间
- updated_at      # 更新时间
```

#### 2. TenantSubscription (租户订阅表)
```python
- id              # 订阅ID
- tenant          # 关联租户
- plan            # 关联套餐
- status          # 状态（active/cancelled/past_due）
- start_date      # 开始时间
- end_date        # 结束时间
- auto_renew      # 是否自动续费
- stripe_subscription_id  # Stripe订阅ID
```

#### 3. TenantMember (租户成员表)
```python
- id              # 成员ID
- tenant          # 关联租户
- user            # 关联用户
- role            # 关联角色
- is_active       # 是否激活
- joined_at       # 加入时间
- invited_by      # 邀请者
```

#### 4. TenantConfig (租户配置表)
```python
- id              # 配置ID
- tenant          # 关联租户
- key             # 配置键
- value           # 配置值
- category        # 配置分类
- description     # 配置描述
```

#### 5. Plan (套餐表)
```python
- id              # 套餐ID
- name            # 套餐名称
- slug            # 套餐标识
- description     # 套餐描述
- price           # 月费
- price_yearly    # 年费（可选）
- currency        # 货币类型
- max_users       # 最大用户数
- max_storage     # 最大存储空间（MB）
- is_active       # 是否在售
- is_featured     # 是否推荐
- sort_order      # 排序
- created_at      # 创建时间
```

#### 6. PlanFeature (套餐功能表)
```python
- id              # 功能ID
- plan            # 关联套餐
- feature_code    # 功能编码
- feature_name    # 功能名称
- description     # 功能描述
- value           # 配置值
- is_enabled      # 是否启用
```

#### 7. Role (角色表)
```python
- id              # 角色ID
- tenant          # 关联租户（可空，系统角色）
- name            # 角色名称
- slug            # 角色标识
- description     # 角色描述
- is_system       # 是否系统内置角色
- is_active       # 是否激活
- permissions     # 关联权限（M2M）
```

#### 8. Permission (权限表)
```python
- id              # 权限ID
- name            # 权限名称
- slug            # 权限标识
- description     # 权限描述
- module          # 所属模块
- is_active       # 是否激活
```

#### 9. Order (订单表)
```python
- id              # 订单ID
- tenant          # 关联租户
- user            # 关联用户
- plan            # 关联套餐
- order_number    # 订单号
- amount          # 订单金额
- currency        # 货币
- status          # 状态（pending/paid/cancelled/refunded）
- payment_method  # 支付方式
- payment_date    # 支付时间
- stripe_payment_id  # Stripe支付ID
- created_at      # 创建时间
```

#### 10. Invoice (发票表)
```python
- id              # 发票ID
- order           # 关联订单
- tenant          # 关联租户
- invoice_number  # 发票号
- amount          # 金额
- currency        # 货币
- status          # 状态（pending/paid/overdue）
- due_date        # 到期日期
- paid_date       # 支付日期
- pdf_file        # PDF文件
- sent_at         # 发送时间
```

---

## API 设计

### RESTful API 端点

#### 租户管理
```
GET    /api/saas/tenants/              # 租户列表
POST   /api/saas/tenants/              # 创建租户
GET    /api/saas/tenants/{id}/         # 租户详情
PUT    /api/saas/tenants/{id}/         # 更新租户
DELETE /api/saas/tenants/{id}/         # 删除租户
PATCH  /api/saas/tenants/{id}/toggle/  # 切换租户状态
```

#### 套餐管理
```
GET    /api/saas/plans/               # 套餐列表
POST   /api/saas/plans/               # 创建套餐
GET    /api/saas/plans/{id}/          # 套餐详情
PUT    /api/saas/plans/{id}/          # 更新套餐
DELETE /api/saas/plans/{id}/          # 删除套餐
```

#### 用户管理
```
GET    /api/saas/tenants/{id}/members/      # 租户成员列表
POST   /api/saas/tenants/{id}/members/      # 添加成员
PUT    /api/saas/tenants/{id}/members/{mid}/# 更新成员
DELETE /api/saas/tenants/{id}/members/{mid}/# 移除成员
```

#### 权限管理
```
GET    /api/saas/roles/                 # 角色列表
POST   /api/saas/roles/                 # 创建角色
GET    /api/saas/roles/{id}/            # 角色详情
PUT    /api/saas/roles/{id}/            # 更新角色
DELETE /api/saas/roles/{id}/            # 删除角色

GET    /api/saas/permissions/           # 权限列表
```

#### 订单管理
```
GET    /api/saas/orders/                # 订单列表
GET    /api/saas/orders/{id}/           # 订单详情
POST   /api/saas/orders/{id}/refund/    # 订单退款
```

---

## 权限体系

### RBAC 权限模型
```
User (用户)
  └── Member (租户成员关系)
        └── Role (角色)
              └── Permission (权限)
```

### 内置角色
1. **Super Admin (超级管理员)** - 系统级，可管理所有租户
2. **Tenant Admin (租户管理员)** - 租户级，可管理当前租户
3. **Member (成员)** - 基础用户权限

### 权限粒度
```
├─ tenant
│  ├─ tenant.create
│  ├─ tenant.read
│  ├─ tenant.update
│  └─ tenant.delete
├─ user
│  ├─ user.create
│  ├─ user.read
│  ├─ user.update
│  └─ user.delete
├─ billing
│  ├─ billing.read
│  └─ billing.manage
├─ analytics
│  └─ analytics.read
└─ system
   ├─ system.config
   └─ system.log
```

---

## 后续工作建议

### Phase 1 - 核心功能
- [ ] 数据库模型设计与创建
- [ ] 基础CRUD功能
- [ ] 用户认证与权限
- [ ] 租户管理界面

### Phase 2 - 支付与计费
- [ ] 套餐管理
- [ ] 订单系统
- [ ] 支付集成（Stripe/支付宝/微信）
- [ ] 发票生成

### Phase 3 - 高级功能
- [ ] 数据统计与仪表板
- [ ] 日志审计
- [ ] API管理
- [ ] Webhook集成

---

## 附录

### 设计原则
1. **渐进式开发** - 先实现核心功能，再逐步扩展
2. **多租户隔离** - 所有租户数据完全隔离
3. **性能优先** - 关键操作考虑性能优化
4. **可扩展性** - 模块化设计，易于添加新功能
