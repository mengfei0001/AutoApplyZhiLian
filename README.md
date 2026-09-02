# 智联招聘自动投递

基于 **Playwright + FastAPI + AI 资格判断** 的智联招聘自动投递工具。自动遍历搜索结果、爬取职位详情，先用关键词过滤 + AI 模型判断是否值得投递，再自动点击「立即投递」并附带打招呼语，全程记录投递日志与 AI 调用日志。

注意：首次使用会等待登录， 检测页面中是否出现你所配置的登录名，检测到会跳转到你配置的搜索地址。 下次登录后会自动记住登录信息。

## ✨ 一、功能特性

- 🤖 **自动投递**：自动打开智联搜索页 → 逐条爬取详情 → 判断资格 → 自动投递
- 🧠 **AI 资格判断**：可选 **DeepSeek 云端 API** 或 **本地 Ollama 模型**（可切换，本地零成本），根据职位与你的技能/薪资条件判断是否投递
- 🚫 **关键词过滤**：标题/描述/要求命中配置关键词（如“外包、驻场、销售”）直接跳过，不调用 AI，节省成本
- 📊 **Web 管理界面**：投递记录、统计、配置、屏蔽公司、AI 日志一页搞定
- 📝 **AI 日志**：每次模型调用的请求与返回单独记录（文件 + 数据库双份），方便对比两种模型的判断差异
- ⏭️ **已投递自动跳过**：遇到已投递/已沟通职位 0.3s 快速跳过，翻找可投职位更快

## 🚀 二、快速开始

### 2.1、环境要求
- Python **3.14+**（推荐使用 [uv](https://docs.astral.sh/uv/) 管理）
- 已安装 Chrome/Chromium（Playwright 会拉取）

### 2.2、安装

```bash
# 1. 创建虚拟环境并安装依赖（使用阿里云镜像）
uv sync

# 2. 安装 Playwright 浏览器
python -m playwright install chromium
```


### 2.3、启动
```bash
uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000 
```
访问地址：http://localhost:8000/  


### 2.4、投递配置
<img width="1858" height="925" alt="image" src="https://github.com/user-attachments/assets/b534e126-15e2-4972-9322-f95a18518bb2" />

### 2.5、AI 模型配置
> 支持ollama本地部署模型  和  deepseek api  
<img width="1730" height="813" alt="image" src="https://github.com/user-attachments/assets/015fd044-becd-483a-826d-6d8b082a3f90" />


### 2.6、设置屏蔽公司的列表
<img width="1849" height="836" alt="image" src="https://github.com/user-attachments/assets/ce5d5714-1c6f-45a8-bba6-d39397084571" />

### 2.7、开始投递
> 智联上限每天100个投递， 超过后启动的浏览器程序会自动关闭  
<img width="1879" height="890" alt="image" src="https://github.com/user-attachments/assets/2edf1108-5f15-4cc5-a1da-fccd1517367d" />

**点击查看会展示详情**
<img width="699" height="537" alt="image" src="https://github.com/user-attachments/assets/904a16ac-6f87-4a28-addf-8af9b0a7b2da" />

## 三、效果演示

<img width="311" height="670" alt="image" src="https://github.com/user-attachments/assets/8d616604-3b64-4604-b2ff-808ee3f15dcc" />
     
> 待优化点： 刚进入会有一个弹出层， 目前需要手动点击黑色部分  
<img width="1857" height="579" alt="image" src="https://github.com/user-attachments/assets/44f29e6f-d8cb-4804-9075-f6b6aa7b367f" />

启动会跳转到你配置的地址：  
<img width="1836" height="778" alt="image" src="https://github.com/user-attachments/assets/1c30706f-8335-40c5-8c34-071e468b3bf6" />

<img width="1602" height="939" alt="image" src="https://github.com/user-attachments/assets/5d3f779e-fe7d-454d-8ece-31c01bbce293" />


## 四、技术架构

### 🧱 核心模块
```sh
┌──────────────────────────────────────────────────┐
│  Web UI (index.html · 纯原生 HTML/CSS/JS)       │  交互层：配置、记录、日志、投递控制
├──────────────────────────────────────────────────┤
│  FastAPI (main.py)                              │  API 层：REST 接口 + 投递子进程管理
├──────────────────────┬───────────────────────────┤
│  业务服务模块        │  数据访问层 (DAO)         │
│  ├ zhilian.py       │  ├ apply_record_dao.py    │
│  ├ ai_client.py     │  ├ app_config_dao.py      │
│  │  ├ deepseek      │  ├ blocked_company_dao.py │
│  │  └ ollama        │  └ ai_log_dao.py          │
│  ├ keyword_filter   │  models.py (SQLAlchemy)   │
│  └ ai_logger        │  database.py (SQLite)     │
└──────────────────────┴───────────────────────────┘
           Playwright (chromium headless)
```


| 模块             | 职责                                                                 | 关键技术                                      |
| ---------------- | -------------------------------------------------------------------- | --------------------------------------------- |
| zhilian.py       | 智联自动化投递主流程：列表遍历→详情爬取→关键词过滤→AI 资格判断→点击投递 | Playwright async 会话、DOM 选择器、异常兜底   |
| ai_client.py     | AI 客户端分发，按 ai_provider 切换 DeepSeek / Ollama                  | Strategy 模式                                 |
| deepseek_client.py | DeepSeek 云端 API 调用（OpenAI 兼容协议）                           | httpx                                         |
| ollama_client.py | 本地 Ollama 生成式接口调用（/api/generate）                           | httpx、JSON 解析兜底                          |
| keyword_filter.py| 职位标题/描述/要求的关键词子串匹配，命中直接跳过 AI                   | 纯字符串                                      |
| ai_logger.py     | 双写日志：ai_requests.log 文件 + ai_logs 表                           | Python logging + ORM                          |
| app_config.py    | 配置单例，持久化到数据库，支持提示词模板渲染（{占位符}）              | 字典合并 + 模板替换                           |
| DAO 层           | 四张表：投递记录、配置、屏蔽公司、AI 日志                             | SQLAlchemy 2.0 + SQLite（get_session 上下文） |
| main.py          | REST API + 子进程生命周期（subprocess.Popen）+ 日志轮询               | FastAPI、threading.Lock、SSE‑free 前端轮询    |
| index.html       | 单页管理界面，原生 JS 无框架                                          | fetch 轮询、状态徽章、分页                    |



### 🔁 投递主流程

1. **启动**：`POST /api/apply/start` → FastAPI spawn `python zhilian.py` 子进程
2. **列表爬取**：Playwright 打开搜索页，逐条进入职位详情
3. **资格判定链**（按优先级）：
   - **屏蔽公司** → 跳过（⛔）
   - **地点不符** → 跳过（📍）
   - **关键词过滤** → 跳过（🚫，不调用 AI）
   - **AI 资格判断** → 不满足则跳过（🤖）
4. **投递**：点击「立即投递」→ 关闭发送成功弹框 → 写入投递记录表
5. **步长控制**：上一条若为「已沟通/已投递」下一条仅等 300ms，否则 3–8s

### 🗄️ 数据存储

- **SQLite**（`zhaopin.db`）：
  - `apply_records` — 每次投递结果（含命中 AI 的 reason）
  - `app_config` — 全量配置（JSON 序列化）
  - `blocked_companies` — 屏蔽公司名单
  - `ai_logs` — 每次 AI 请求/响应 + 模型名 + provider
- **文件**：
  - `ai_requests.log` — 人类可读的 AI 调用日志（同 DB 双写）
  - `debug.log` — 运行日志
  - `zhaopin_state.json` — 进程断点状态

### ⚡ 设计亮点

- **配置与状态分离持久化**：不再依赖 `config.json`，全部入库，多实例安全
- **AI 可插拔**：接口统一，`OllamaClient` / `DeepSeekClient` 可一键切换降成本
- **AI 前双过滤**：关键词匹配 0 成本 + 公司/地点硬规则，降低云端调用
- **父子进程解耦**：FastAPI 主线程不阻塞，子进程 stdout/stderr 通过文件实时回显
- **可观测**：AI 调用独立日志（文件+DB + 页面查看），投递记录全状态枚举
