# -*- coding: utf-8 -*-
"""Ollama 本地模型客户端，用于投递前的资格判断（本地推理，零 API 调用成本）

与 DeepSeekClient 保持相同接口（is_ready / check_qualification），
调用方式参考 test_ollama.py：POST {base_url}/api/generate
"""
import json
import logging

import httpx

from app_config import get_config
from ai_logger import log_ai_call, messages_to_text

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama 本地模型客户端"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.base_url = self.config.get("ollama_base_url", "http://localhost:11434").rstrip("/")
        self.model = self.config.get("ollama_model", "qwen2.5:7b")
        self.enabled = self.config.get("ollama_enabled", False)
        self.timeout = self.config.get("ollama_timeout", 300)

    @property
    def is_ready(self):
        """是否已配置模型且启用"""
        return self.enabled and bool(self.model)

    def _call_api(self, messages, temperature=0.3, max_tokens=1000):
        """调用 Ollama 本地模型（同步），取 messages 中最后一条 user 内容作为 prompt"""
        prompt = ""
        for msg in messages:
            if msg.get("role") == "user":
                prompt = msg.get("content", "")

        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format":"json",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        try:
            resp = httpx.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("response", "")
            # 单独记录 AI 请求、使用的模型与响应（日志文件 + 数据库）
            log_ai_call("Ollama", self.model, messages_to_text(messages), content or "")
            return content or None
        except Exception as e:
            logger.error(f"Ollama API 调用失败: {e}")
            return None

    def check_qualification(self, job_info, prompt_template=None):
        """判断职位是否满足投递要求（与 DeepSeekClient 同接口）

        Args:
            job_info: 职位信息字典
            prompt_template: 可选，自定义提示词模板；默认使用配置中的 qualification_prompt

        Returns:
            (qualified, reason): (bool, str) 或 (None, error_msg)
        """
        if not self.is_ready:
            return None, "Ollama 未启用或未配置模型"

        template = prompt_template or self.config.get("qualification_prompt", "")
        # 渲染提示词（替换占位符）
        prompt = self.config.render_with_job(template, job_info)

        messages = [
            {"role": "user", "content": prompt}
        ]
        content = self._call_api(messages)
        if not content:
            return None, "Ollama 调用失败或无响应"

        # 解析 JSON 响应（模型可能输出额外的文字，需要提取 JSON 部分）
        return self._parse_qualification(content)

    def _parse_qualification(self, content):
        """解析模型返回的 JSON（与 DeepSeekClient 相同逻辑）"""
        content = content.strip()
        try:
            # 直接解析
            data = json.loads(content)
            if isinstance(data, dict):
                return bool(data.get("qualified")), str(data.get("reason", ""))
        except json.JSONDecodeError:
            pass

        # 尝试从文本中提取 JSON
        try:
            # 查找第一个 { 和最后一个 }
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = content[start:end + 1]
                data = json.loads(json_str)
                if isinstance(data, dict):
                    return bool(data.get("qualified")), str(data.get("reason", ""))
        except (json.JSONDecodeError, ValueError):
            pass

        # 尝试关键词判断
        if 'true' in content.lower():
            return True, content[:200]
        if 'false' in content.lower():
            return False, content[:200]

        return None, f"无法解析模型响应: {content[:200]}"
