import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from playwright.sync_api import sync_playwright
import os
from pathlib import Path

from app_config import get_config
from dao import apply_record_dao
from dao.blocked_company_dao import blocked_company_dao


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时自动初始化 SQLite 数据库（建表等，幂等）"""
    try:
        from dao.database import init_database
        init_database()
    except Exception as e:
        print(f"数据库初始化失败: {e}")
    yield


app = FastAPI(lifespan=lifespan)

# 全局配置
config = get_config()

# ========== 配置 API（配置持久化到 app_config 表） ==========
@app.get("/api/config")
def get_app_config():
    """获取当前配置（优先从数据库读取）"""
    try:
        config.load_from_db()
    except Exception as e:
        print(f"从数据库加载配置失败: {e}")
    return config.config


@app.put("/api/config")
def update_app_config(updates: dict):
    """更新配置（持久化到 app_config 表，不再使用 config.json）"""
    allowed_keys = {
        "salary_range", "max_apply_count", "search_url", "login_success_keyword",
        "blocked_companies", "locations", "skills",
        "greeting_prompt", "qualification_prompt",
        "deepseek_api_key", "deepseek_model", "deepseek_base_url", "deepseek_enabled",
        "ai_provider", "ollama_base_url", "ollama_model", "ollama_enabled", "ollama_timeout",
        "filter_keywords"
    }
    # 过滤非法字段
    filtered = {k: v for k, v in updates.items() if k in allowed_keys}
    if not filtered:
        raise HTTPException(status_code=400, detail="没有可更新的配置字段")

    # 更新内存配置并持久化到 app_config 表（失败则返回错误，避免前端误以为保存成功）
    try:
        config.update(filtered)
    except Exception as e:
        print(f"保存配置到数据库失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存配置到数据库失败: {str(e)}")

    return {"status": "success", "config": config.config}


@app.post("/api/config/test-deepseek")
def test_deepseek():
    """测试 DeepSeek 配置是否可用"""
    from deepseek_client import DeepSeekClient
    client = DeepSeekClient(config)
    if not client.is_ready:
        raise HTTPException(status_code=400, detail="DeepSeek 未启用或未配置 API Key")

    messages = [{"role": "user", "content": "请回复：连接成功"}]
    content = client._call_api(messages, max_tokens=50)
    if content:
        return {"status": "success", "message": f"DeepSeek 连接成功: {content[:100]}"}
    raise HTTPException(status_code=500, detail="DeepSeek API 调用失败，请检查 API Key 和网络")


@app.post("/api/config/test-ollama")
def test_ollama():
    """测试 Ollama 本地模型配置是否可用"""
    from ollama_client import OllamaClient
    client = OllamaClient(config)
    if not client.is_ready:
        raise HTTPException(status_code=400, detail="Ollama 未启用或未配置模型")

    messages = [{"role": "user", "content": "请回复：连接成功"}]
    content = client._call_api(messages, max_tokens=50)
    if content:
        return {"status": "success", "message": f"Ollama 连接成功: {content[:100]}"}
    raise HTTPException(status_code=500, detail="Ollama 调用失败，请确认本地 Ollama 服务已启动且已拉取对应模型")


# ========== AI 调用日志 API（数据存 ai_logs 表） ==========
@app.get("/api/ai-logs")
def get_ai_logs(page: int = 1, limit: int = 50, provider: str = None):
    """获取 AI 调用日志（分页，可按提供方筛选）"""
    from dao.ai_log_dao import ai_log_dao
    return ai_log_dao.get_paginated(page=page, limit=limit, provider=provider)


@app.get("/api/ai-logs/{log_id}")
def get_ai_log_detail(log_id: int):
    """获取单条 AI 调用日志详情"""
    from dao.ai_log_dao import ai_log_dao
    result = ai_log_dao.get_by_id(log_id)
    if not result:
        raise HTTPException(status_code=404, detail="日志不存在")
    return result


@app.delete("/api/ai-logs/clear")
def clear_ai_logs():
    """清空所有 AI 调用日志"""
    from dao.ai_log_dao import ai_log_dao
    deleted = ai_log_dao.clear()
    return {"success": True, "deleted": deleted}


@app.delete("/api/ai-logs/{log_id}")
def delete_ai_log(log_id: int):
    """删除单条 AI 调用日志"""
    from dao.ai_log_dao import ai_log_dao
    ok = ai_log_dao.delete(log_id)
    if not ok:
        raise HTTPException(status_code=404, detail="日志不存在")
    return {"success": True}


# ========== 屏蔽公司 API（数据存 blocked_companies 表） ==========
@app.get("/api/blocked-companies")
def list_blocked_companies():
    """获取屏蔽公司列表"""
    companies = blocked_company_dao.list_all()
    return {"count": len(companies), "companies": [c.to_dict() for c in companies]}


@app.post("/api/blocked-companies")
def add_blocked_company(payload: dict):
    """添加单个屏蔽公司"""
    name = (payload.get("company_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="公司名称不能为空")
    ok, is_new = blocked_company_dao.add_company(name)
    if not ok:
        raise HTTPException(status_code=400, detail="公司名称不能为空")
    return {"success": True, "is_new": is_new, "company_name": name}


@app.post("/api/blocked-companies/batch")
def add_blocked_companies(payload: dict):
    """批量添加屏蔽公司（导入 txt 用，一行一个）"""
    names = payload.get("company_names") or []
    if not names:
        raise HTTPException(status_code=400, detail="请提供要导入的公司列表")
    added, existed = blocked_company_dao.add_many(names)
    return {"success": True, "added": added, "existed": existed}


@app.delete("/api/blocked-companies/{company_name}")
def delete_blocked_company(company_name: str):
    """删除单个屏蔽公司"""
    ok = blocked_company_dao.remove_company(company_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"未找到屏蔽公司: {company_name}")
    return {"success": True, "company_name": company_name}


# ========== 投递记录 API ==========
@app.get("/api/records")
def get_records(page: int = 1, limit: int = 50, status: str = None, platform: str = None):
    """获取投递记录（支持分页、按状态/平台筛选）
    status 可选值: success / failed / already_applied / skipped / detail_fetched
                  / not_qualified / blocked_company / location_mismatch
                  / keyword_filtered
    platform 可选值: zhilian
    """
    page = max(1, page)
    limit = max(1, min(limit, 500))

    try:
        return apply_record_dao.get_records_paginated(
            page=page, limit=limit, status=status, platform=platform
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取投递记录失败: {str(e)}")


@app.get("/api/records/{record_id}")
def get_record_detail(record_id: int):
    """获取单条投递记录详情"""
    result = apply_record_dao.get_record_by_id(record_id)
    if not result:
        raise HTTPException(status_code=404, detail="记录不存在")
    return result


@app.delete("/api/records/{record_id}")
def delete_record(record_id: int):
    """删除单条投递记录（同时刷新统计）"""
    ok = apply_record_dao.delete_record(record_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"success": True}


@app.get("/api/statistics")
def get_statistics(days: int = 7):
    """获取统计信息"""
    total = apply_record_dao.get_total_count()
    stats = apply_record_dao.get_statistics(days)
    recent = apply_record_dao.get_recent_records(5)
    return {
        "total": total,
        "daily_stats": stats,
        "recent_records": recent
    }


# ========== 投递进程管理 API ==========
class ApplyManager:
    """管理智联投递子进程"""

    def __init__(self):
        self.process = None
        self.platform = "zhilian"   # 平台固定为智联
        self.output = []          # 最近日志输出
        self.max_output = 300
        self.started_at = None
        self.stopped_at = None
        self.lock = threading.Lock()

    @property
    def running(self):
        if self.process is None:
            return False
        return self.process.poll() is None

    def start(self, platform="zhilian"):
        """启动智联投递子进程（异步，不阻塞请求）"""
        with self.lock:
            if self.running:
                return False, "投递已在运行中"

            try:
                # 使用当前 Python 环境运行智联脚本
                python = sys.executable
                script = "zhilian.py"
                # 强制子进程以 UTF-8 输出、无缓冲，避免 Windows GBK 编码/块缓冲
                # 导致日志无法实时转发到控制台和页面
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUNBUFFERED"] = "1"
                cmd = [python, os.path.join(os.path.dirname(__file__), script)]
                self.process = subprocess.Popen(
                    cmd,
                    cwd=os.path.dirname(__file__),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",  # 容错解码，单个非法字节不会导致读取线程崩溃
                    bufsize=1,
                    env=env,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                )
                self.platform = platform
                self.started_at = datetime.now()
                self.stopped_at = None
                self.output = []

                # 后台线程持续读取输出
                threading.Thread(target=self._read_output, daemon=True).start()
                return True, "投递已启动"
            except Exception as e:
                return False, f"启动投递失败: {e}"

    def _read_output(self):
        """后台读取子进程输出：同时打印到控制台，并缓存供页面日志展示"""
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            line = line.rstrip()
            if not line:
                continue
            # 控制台可见（与 uvicorn 自身日志区分，加 [投递] 前缀）
            print(f"[投递] {line}", flush=True)
            with self.lock:
                self.output.append(line)
                if len(self.output) > self.max_output:
                    self.output = self.output[-self.max_output:]

    def stop(self):
        """停止投递进程"""
        with self.lock:
            if not self.running:
                return False, "投递未在运行"
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], capture_output=True)
                else:
                    self.process.terminate()
                self.stopped_at = datetime.now()
                self.output.append("[系统] 投递已停止")
                return True, "投递已停止"
            except Exception as e:
                return False, f"停止投递失败: {e}"

    def status(self):
        """获取投递状态"""
        with self.lock:
            return {
                "running": self.running,
                "platform": self.platform,
                "pid": self.process.pid if self.process and self.running else None,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
                "logs": list(self.output[-100:])
            }


# 全局投递管理器（智联）
apply_managers = {
    "zhilian": ApplyManager(),
}


@app.post("/api/apply/start")
def start_apply(payload: dict = None):
    """启动智联自动投递
    body: {"platform": "zhilian"}
    """
    platform = (payload or {}).get("platform", "zhilian")
    if platform not in apply_managers:
        raise HTTPException(status_code=400, detail="未知平台类型")
    ok, msg = apply_managers[platform].start(platform)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg, "platform": platform}


@app.post("/api/apply/stop")
def stop_apply(payload: dict = None):
    """停止智联自动投递
    body: {"platform": "zhilian"}
    """
    platform = (payload or {}).get("platform", "zhilian")
    if platform not in apply_managers:
        raise HTTPException(status_code=400, detail="未知平台类型")
    ok, msg = apply_managers[platform].stop()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg, "platform": platform}


@app.get("/api/apply/status")
def get_apply_status():
    """获取智联投递状态"""
    return {name: manager.status() for name, manager in apply_managers.items()}


# ========== 保留原有爬虫端点 ==========
@app.get("/crawl/zhaopin")
def crawl_zhaopin():
    """
    GET 请求，无参数，使用保存的 Cookie 爬取智联招聘默认内容
    """
    cookie_file = "zhaopin_cookies.json"

    # 1. 验证 Cookie 文件是否存在
    if not os.path.exists(cookie_file):
        raise HTTPException(
            status_code=401,
            detail="Cookie 文件不存在，请先运行手动登录脚本获取 Cookie"
        )

    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        page = context.new_page()

        # 3. 访问默认页面（无参数，使用固定 URL）
        url = "https://www.zhaopin.com/"
        page.goto(url)
        page.wait_for_load_state("networkidle")

        return {
            "status": "success"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"爬取失败: {str(e)}")


# ========== 静态页面 ==========
@app.get("/", response_class=HTMLResponse)
def index():
    """配置与投递记录展示页面"""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>index.html 不存在</h1><p>请在项目目录下创建 index.html</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)