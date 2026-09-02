# -*- coding: utf-8 -*-
"""AI 客户端统一入口：根据配置在 DeepSeek（云端）与 Ollama（本地）之间切换"""
from app_config import get_config
from deepseek_client import DeepSeekClient
from ollama_client import OllamaClient


def get_ai_client():
    """根据当前配置返回 AI 客户端实例（每次构造，读取最新配置）

    通过配置项 ai_provider 切换：'ollama' 使用本地 Ollama，'deepseek' 使用 DeepSeek。
    未启用或未配置对应服务时返回 None。
    """
    config = get_config()
    provider = config.get("ai_provider", "deepseek")
    if provider == "ollama" and config.get("ollama_enabled", False):
        return OllamaClient(config)
    if config.get("deepseek_enabled", False):
        return DeepSeekClient(config)
    return None
