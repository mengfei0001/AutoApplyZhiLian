# 智联招聘自动投递

基于 **Playwright + FastAPI + AI 资格判断** 的智联招聘自动投递工具。自动遍历搜索结果、爬取职位详情，先用关键词过滤 + AI 模型判断是否值得投递，再自动点击「立即投递」并附带打招呼语，全程记录投递日志与 AI 调用日志。

注意：首次使用会等待登录， 检测页面中是否出现你所配置的登录名，检测到会跳转到你配置的搜索地址

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

** 启动会跳转到你配置的地址**  

> 带优化点： 刚进入会有一个弹出层， 目前需要手动点击黑色部分

<img width="1857" height="579" alt="image" src="https://github.com/user-attachments/assets/44f29e6f-d8cb-4804-9075-f6b6aa7b367f" />

点击后如下：
<img width="1836" height="778" alt="image" src="https://github.com/user-attachments/assets/1c30706f-8335-40c5-8c34-071e468b3bf6" />

<img width="1602" height="939" alt="image" src="https://github.com/user-attachments/assets/5d3f779e-fe7d-454d-8ece-31c01bbce293" />


## 四、技术机构









