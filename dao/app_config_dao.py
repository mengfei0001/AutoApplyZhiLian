"""应用配置 DAO"""
import json
import logging

from sqlalchemy import select

from dao.database import get_session
from dao.models import AppConfig

logger = logging.getLogger(__name__)


class AppConfigDAO:
    """应用配置数据访问对象"""

    def save_config(self, config_dict: dict) -> bool:
        """保存应用配置（整体覆盖）"""
        try:
            with get_session() as session:
                # 先获取已有的所有 key
                existing = set(session.scalars(select(AppConfig.config_key)).all())

                # 更新或新增
                for key, value in config_dict.items():
                    record = session.get(AppConfig, key)
                    json_value = json.dumps(value, ensure_ascii=False)
                    if record:
                        record.config_value = json_value
                    else:
                        session.add(AppConfig(config_key=key, config_value=json_value))

                # 删除不在新配置中的旧 key（整体覆盖语义）
                keys_to_remove = existing - set(config_dict.keys())
                if keys_to_remove:
                    for key in keys_to_remove:
                        record = session.get(AppConfig, key)
                        if record:
                            session.delete(record)

                session.commit()
            logger.info(f"应用配置已保存到数据库: {len(config_dict)} 项")
            return True
        except Exception as e:
            logger.error(f"保存配置到数据库失败: {e}")
            return False

    def load_config(self) -> dict:
        """从数据库加载应用配置"""
        try:
            with get_session() as session:
                rows = session.execute(
                    select(AppConfig.config_key, AppConfig.config_value)
                ).all()
                if not rows:
                    return {}
                config = {}
                for key, value in rows:
                    try:
                        config[key] = json.loads(value) if value else None
                    except (json.JSONDecodeError, TypeError):
                        config[key] = value
                logger.info(f"从数据库加载应用配置: {len(config)} 项")
                return config
        except Exception as e:
            logger.error(f"从数据库加载配置失败: {e}")
            return {}


# 全局单例
app_config_dao = AppConfigDAO()