# -*- coding: utf-8 -*-
"""AI 请求/响应日志：将每次 AI 调用的请求内容、使用的模型与返回结果单独记录到日志文件"""
import logging
import os

# 独立日志文件（与运行日志分离，便于排查 AI 判断结果）
AI_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_requests.log")


def get_ai_logger():
    """获取专用的 AI 日志记录器（写 ai_requests.log，UTF-8 编码）"""
    logger = logging.getLogger("ai_requests")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(AI_LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def messages_to_text(messages):
    """把 messages 列表转换为可读文本（拼接各角色的内容）"""
    parts = []
    for m in messages or []:
        role = m.get("role", "")
        content = m.get("content", "")
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def log_ai_call(provider, model, request_text, response_text):
    """记录一次 AI 调用：写入独立日志文件 + 存入 ai_logs 表

    数据库写入失败不影响主流程（仅记录到文件）。
    """
    ai_logger.info(
        "模型: %s/%s\n请求:\n%s\n响应:\n%s",
        provider, model, request_text, response_text or "",
    )
    try:
        from dao.ai_log_dao import ai_log_dao
        ai_log_dao.add(provider, model, request_text, response_text or "")
    except Exception:
        # 数据库不可用时仅保留文件日志，不阻塞 AI 判断主流程
        pass


# 全局单例
ai_logger = get_ai_logger()
