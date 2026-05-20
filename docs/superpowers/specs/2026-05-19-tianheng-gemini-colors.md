# TIANHENG Gemini 风格配色重设计

## 目标

将当前暗色单色系升级为 Gemini 风格：深蓝底 + 蓝紫渐变光晕 + 玻璃拟态 + 高饱和状态色。

## 配色变更

### 基础色

| Token | 当前值 | 新值 | 说明 |
|-------|--------|------|------|
| `background` | `#0b0f14` | `#080d1a` | 深海军蓝底 |
| `panel` | `#141a22` | `rgba(14,22,48,0.80)` | 半透明玻璃卡片 |
| `border` | `#1e2733` | `rgba(75,115,205,0.10)` | 蓝调半透明边框 |
| `text-primary` | `#e2e8f0` | `#edf2ff` | 微蓝调白 |
| `text-secondary` | `#7c8a9e` | `#8899bb` | 蓝灰 |

### 强调色

| Token | 当前值 | 新值 | 说明 |
|-------|--------|------|------|
| `accent` | — | `#5b8def` | 新增：主强调蓝 |
| `accent-secondary` | — | `#8b5cf6` | 新增：次强调紫 |
| `info` | `#3b82f6` | `#5b8def` | 更新为亮蓝 |
| `pending` | `#3e4a5c` | `#1e2d4a` | 稍亮蓝灰 |

### 保留不变

`running: #f0a020`, `success: #22c55e`, `error: #ef4444`, `crash: #f97316`

## 视觉新增

1. **背景光球** — 两个固定 radial-gradient 光斑（右上蓝、左下紫），z-index 底层
2. **玻璃拟态** — 所有卡片 `bg-panel` 改为半透明 + `backdrop-blur-sm`
3. **渐变按钮** — 主操作按钮（新建任务、提交任务）用 `#5b8def → #8b5cf6` 渐变

## 改动文件

| 文件 | 改动 |
|------|------|
| `app/globals.css` | 更新 CSS 变量 + 新增光球层 + 玻璃卡片 class |
| `app/layout.tsx` | body 内加光球 div |
| `tailwind.config.ts` | 更新色值 + 新增 accent/accent-secondary + 渐变按钮动画 |
| `components/TopBar.tsx` | 新建任务按钮改用渐变 |
| `components/CreateTaskDialog.tsx` | 提交按钮改用渐变 |
