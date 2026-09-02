import logging

from dao.app_config_dao import app_config_dao

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "salary_range": "15000-25000",
    "max_apply_count": 0,
    "search_url": "https://www.zhaopin.com/sou/jl530/kw01L00O80EO062/p1?sl=15001,25000",
    "login_success_keyword": "孟飞",
    "blocked_companies": [],
    "locations": [],
    "skills": "",
    "greeting_prompt": "您好，我对贵公司的{job_title}岗位很感兴趣。我具备{skills}，期望薪资在{salary_range}元/月范围内，期待能与您进一步沟通。",
    "qualification_prompt": "请根据以下职位信息和我（求职者）的条件，判断我是否满足该职位的投递要求。\n\n【职位标题】{job_title}\n【职位描述】{job_description}\n【职位要求】{job_requirements}\n【薪资范围】{salary}\n【工作地点】{location}\n【经验要求】{experience}\n【学历要求】{education}\n\n【我的期望薪资】{salary_range}\n【我的专业技能】{skills}\n\n请只输出JSON格式：{\"qualified\": true/false, \"reason\": \"简短原因\"}\nqualified为true表示满足投递要求，false表示不满足。",
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_enabled": False,
    # AI 提供方切换：deepseek（云端 API）/ ollama（本地模型，零成本）
    "ai_provider": "deepseek",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "qwen2.5:7b",
    "ollama_enabled": False,
    "ollama_timeout": 300,
    # 关键词过滤：职位标题/描述/要求命中任一关键词则直接跳过，不调用 AI 模型（支持换行/逗号分隔）
    "filter_keywords": ""
}


class AppConfig:
    """配置管理类，配置统一持久化到 app_config 表（不再使用 config.json）"""

    def __init__(self):
        self.config = self.load()

    def load(self):
        """从数据库加载配置，数据库为空或不可用时使用默认配置"""
        db_config = app_config_dao.load_config()
        if db_config:
            merged = DEFAULT_CONFIG.copy()
            merged.update(db_config)
            return merged
        return DEFAULT_CONFIG.copy()

    def save(self, config=None):
        """保存配置到数据库（失败时抛出 RuntimeError）"""
        if config is not None:
            self.config = config
        ok = app_config_dao.save_config(self.config)
        if not ok:
            raise RuntimeError("配置保存到数据库失败")
        return True

    def get(self, key, default=None):
        """获取配置项"""
        return self.config.get(key, default)

    def set(self, key, value):
        """设置配置项并保存到数据库"""
        self.config[key] = value
        self.save()
        return True

    def update(self, updates):
        """批量更新配置并保存到数据库"""
        for key, value in updates.items():
            self.config[key] = value
        self.save()
        return True

    def render_prompt(self, template, variables):
        """渲染提示词模板，支持 {占位符} 引用配置项

        Args:
            template: 提示词模板字符串
            variables: 变量字典，如 {'job_title': 'xxx', 'skills': 'yyy'}
        """
        result = template
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            if placeholder in result:
                result = result.replace(placeholder, str(value) if value else '')
        return result

    # ===== 兼容旧接口（参数 db 保留兼容，实际始终以数据库为准） =====
    def save_to_db(self, db=None):
        """保存配置到数据库"""
        return self.save()

    def load_from_db(self, db=None):
        """从数据库重新加载配置（数据库为准，不合并内存中的旧值）"""
        db_config = app_config_dao.load_config()
        if db_config:
            merged = DEFAULT_CONFIG.copy()
            merged.update(db_config)
            self.config = merged
            return True
        return False

    def render_with_job(self, template, job_info):
        """根据职位信息渲染提示词模板

        支持占位符：
          {job_title} {job_description} {job_requirements} {salary}
          {location} {experience} {education} {company}
          {salary_range} {skills} {greeting}
        """
        variables = {
            'job_title': job_info.get('title', ''),
            'job_description': job_info.get('description', ''),
            'job_requirements': job_info.get('requirements', ''),
            'salary': job_info.get('salary', ''),
            'location': job_info.get('location', ''),
            'experience': job_info.get('experience', ''),
            'education': job_info.get('education', ''),
            'company': job_info.get('company', ''),
            'salary_range': self.get('salary_range', ''),
            'skills': self.get('skills', ''),
            'greeting': self.render_prompt(self.get('greeting_prompt', ''), {
                'job_title': job_info.get('title', ''),
                'company': job_info.get('company', ''),
                'salary_range': self.get('salary_range', ''),
                'skills': self.get('skills', ''),
            })
        }
        return self.render_prompt(template, variables)


# 全局单例
config = AppConfig()


def get_config():
    """获取全局配置单例"""
    return config
