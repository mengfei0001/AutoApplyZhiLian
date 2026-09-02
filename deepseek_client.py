import json
import logging
import httpx

from app_config import get_config
from ai_logger import log_ai_call, messages_to_text

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """DeepSeek API 客户端，用于投递前的资格判断"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.api_key = self.config.get("deepseek_api_key", "")
        self.model = self.config.get("deepseek_model", "deepseek-chat")
        self.base_url = self.config.get("deepseek_base_url", "https://api.deepseek.com")
        self.enabled = self.config.get("deepseek_enabled", False)

    @property
    def is_ready(self):
        """是否已配置 API Key 且启用"""
        return self.enabled and bool(self.api_key)

    def _call_api(self, messages, temperature=0.3, max_tokens=1000):
        """调用 DeepSeek API（同步）"""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # 单独记录 AI 请求、使用的模型与响应（日志文件 + 数据库）
            log_ai_call("DeepSeek", self.model, messages_to_text(messages), content)
            return content
        except Exception as e:
            logger.error(f"DeepSeek API 调用失败: {e}")
            return None

    def check_qualification(self, job_info, prompt_template=None):
        """判断职位是否满足投递要求

        Args:
            job_info: 职位信息字典
            prompt_template: 可选，自定义提示词模板；默认使用配置中的 qualification_prompt

        Returns:
            (qualified, reason): (bool, str) 或 (None, error_msg)
        """
        if not self.is_ready:
            return None, "DeepSeek 未启用或未配置 API Key"

        template = prompt_template or self.config.get("qualification_prompt", "")
        # 渲染提示词（替换占位符）
        prompt = self.config.render_with_job(template, job_info)

        messages = [
            {"role": "user", "content": prompt}
        ]
        content = self._call_api(messages)
        if not content:
            return None, "DeepSeek API 调用失败或无响应"

        # 解析 JSON 响应（模型可能输出额外的文字，需要提取 JSON 部分）
        return self._parse_qualification(content)

    def _parse_qualification(self, content):
        """解析模型返回的 JSON"""
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


# 全局单例
deepseek_client = DeepSeekClient()


def get_deepseek_client():
    """获取全局 DeepSeek 客户端单例"""
    return deepseek_client