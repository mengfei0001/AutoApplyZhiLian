"""AI 调用日志 DAO"""
import logging

from sqlalchemy import select, func, delete

from dao.database import get_session
from dao.models import AiLog

logger = logging.getLogger(__name__)


class AiLogDAO:
    """AI 调用日志数据访问对象"""

    def add(self, provider: str, model: str, request_text: str, response_text: str) -> bool:
        """新增一条 AI 调用日志"""
        try:
            with get_session() as session:
                session.add(AiLog(
                    provider=str(provider or 'unknown').lower(),
                    model=model or '',
                    request_text=request_text or '',
                    response_text=response_text or '',
                ))
                session.commit()
                return True
        except Exception as e:
            logger.error(f"新增 AI 日志失败: {e}")
            return False

    def get_by_id(self, log_id: int) -> dict | None:
        """按 ID 获取 AI 调用日志"""
        try:
            with get_session() as session:
                record = session.get(AiLog, log_id)
                return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"获取 AI 日志失败: {e}")
            return None

    def get_paginated(self, page: int = 1, limit: int = 50, provider: str = None) -> dict:
        """分页获取 AI 调用日志（可按提供方筛选，倒序）"""
        page = max(1, page)
        limit = max(1, min(limit, 500))
        try:
            with get_session() as session:
                count_stmt = select(func.count()).select_from(AiLog)
                stmt = select(AiLog)
                if provider:
                    count_stmt = count_stmt.where(AiLog.provider == provider)
                    stmt = stmt.where(AiLog.provider == provider)
                total = session.scalar(count_stmt) or 0

                stmt = (
                    stmt.order_by(AiLog.created_at.desc(), AiLog.id.desc())
                    .offset((page - 1) * limit)
                    .limit(limit)
                )
                records = session.scalars(stmt).all()
                return {
                    'total': total,
                    'page': page,
                    'limit': limit,
                    'records': [r.to_dict() for r in records],
                }
        except Exception as e:
            logger.error(f"分页获取 AI 日志失败: {e}")
            return {'total': 0, 'page': page, 'limit': limit, 'records': []}

    def delete(self, log_id: int) -> bool:
        """删除单条 AI 日志"""
        try:
            with get_session() as session:
                result = session.execute(delete(AiLog).where(AiLog.id == log_id))
                session.commit()
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"删除 AI 日志失败: {e}")
            return False

    def clear(self) -> int:
        """清空所有 AI 日志，返回删除条数"""
        try:
            with get_session() as session:
                result = session.execute(delete(AiLog))
                session.commit()
                return result.rowcount or 0
        except Exception as e:
            logger.error(f"清空 AI 日志失败: {e}")
            return 0


# 全局单例
ai_log_dao = AiLogDAO()
