"""投递记录 DAO"""
import hashlib
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select, func, update, delete, or_, case
from sqlalchemy.orm import Session

from dao.database import get_session
from dao.models import ApplyRecord, ApplyStatistics

logger = logging.getLogger(__name__)

# 智联招聘详情页 URL 中的唯一职位 ID 模式
# 示例: https://www.zhaopin.com/jobdetail/CC337626410J40872302610.htm?refcode=4019...
_JOB_DETAIL_ID_RE = re.compile(r'/jobdetail/([A-Za-z0-9_-]+)\.htm')


def _job_hash(job_info: dict) -> str:
    """根据职位信息生成唯一标识"""
    job_key = f"{job_info.get('title', '')}_{job_info.get('company', '')}"
    return hashlib.md5(job_key.encode('utf-8')).hexdigest()


def _extract_job_hash2(job_info: dict) -> str | None:
    """从详情页 URL 中提取职位唯一 ID（如 CC337626410J40872302610）

    示例 URL:
      https://www.zhaopin.com/jobdetail/CC337626410J40872302610.htm?refcode=4019&srccode=401901

    Returns:
        提取到的唯一 ID 字符串；无法提取时返回 None
    """
    # 优先使用 job_info 中已提取的 job_hash2
    direct = job_info.get('job_hash2')
    if direct:
        return str(direct).strip()

    # 从 URL 中提取
    url = job_info.get('url') or ''
    match = _JOB_DETAIL_ID_RE.search(url)
    if match:
        return match.group(1)
    return None


def _format_record_log(job_info: dict, status: str, action: str) -> str:
    """生成新增/更新投递记录的详细日志（含公司、注册资本、公司规模/人数）"""
    title = job_info.get('title') or job_info.get('job_title') or '未知'
    company = job_info.get('company') or job_info.get('company_name') or '未知公司'
    capital = job_info.get('registered_capital') or '未获取'
    scale = job_info.get('company_scale') or '未获取'
    return (f"{action}投递记录: {title} - {status}"
            f" | 公司: {company}"
            f" | 注册资本: {capital}"
            f" | 公司规模/人数: {scale}")


class ApplyRecordDAO:
    """投递记录数据访问对象"""

    # ===== 基础 CRUD =====

    def add_record(self, job_info: dict, status: str = 'success', error_msg: str = None) -> bool:
        """添加或更新投递记录（包含岗位描述）"""
        job_hash = _job_hash(job_info)
        job_hash2 = _extract_job_hash2(job_info)
        now = datetime.now()

        with get_session() as session:
            try:
                # 按 job_hash 或 job_hash2 查找已有记录（兼容旧数据：旧记录无 job_hash2）
                record = session.scalar(
                    select(ApplyRecord).where(
                        or_(
                            ApplyRecord.job_hash == job_hash,
                            ApplyRecord.job_hash2 == job_hash2 if job_hash2 else False,
                        )
                    ).limit(1)
                )

                if record:
                    # 更新已有记录
                    record.status = status
                    record.apply_time = now
                    record.error_msg = error_msg
                    record.job_description = job_info.get('description', '')
                    record.job_requirements = job_info.get('requirements', '')
                    record.experience_required = job_info.get('experience', '')
                    record.education_required = job_info.get('education', '')
                    record.job_category = job_info.get('category', '')
                    record.registered_capital = job_info.get('registered_capital', '')
                    record.company_scale = job_info.get('company_scale', '')
                    record.platform = job_info.get('platform') or record.platform
                    # 补齐 job_hash2（旧数据可能为空）
                    if job_hash2 and not record.job_hash2:
                        record.job_hash2 = job_hash2
                    logger.info(_format_record_log(job_info, status, "更新"))
                else:
                    # 插入新记录
                    record = ApplyRecord(
                        job_hash=job_hash,
                        job_hash2=job_hash2,
                        job_title=job_info.get('title', '未知'),
                        company_name=job_info.get('company', '未知'),
                        job_url=job_info.get('url', ''),
                        salary=job_info.get('salary', ''),
                        work_location=job_info.get('location', ''),
                        job_description=job_info.get('description', ''),
                        job_requirements=job_info.get('requirements', ''),
                        experience_required=job_info.get('experience', ''),
                        education_required=job_info.get('education', ''),
                        job_category=job_info.get('category', ''),
                        registered_capital=job_info.get('registered_capital', ''),
                        company_scale=job_info.get('company_scale', ''),
                        platform=job_info.get('platform') or 'zhilian',
                        status=status,
                        apply_time=now,
                        error_msg=error_msg,
                    )
                    session.add(record)
                    logger.info(_format_record_log(job_info, status, "新增"))

                # 更新统计（与记录在同一个事务中）
                self.update_statistics(session)
                session.commit()
                return True
            except Exception as e:
                session.rollback()
                logger.error(f"添加投递记录失败: {e}")
                return False

    def backfill_job_hash2(self) -> int:
        """回填历史数据的 job_hash2（从 job_url 中提取详情页唯一 ID）

        适用于数据库迁移前已存在的旧记录：它们没有 job_hash2，
        通过 job_url 中的 /jobdetail/{id}.htm 模式提取并回填。

        Returns:
            成功回填的记录数
        """
        updated = 0
        try:
            with get_session() as session:
                records = session.scalars(
                    select(ApplyRecord).where(
                        or_(
                            ApplyRecord.job_hash2.is_(None),
                            ApplyRecord.job_hash2 == '',
                        ),
                        ApplyRecord.job_url.isnot(None),
                        ApplyRecord.job_url != '',
                    )
                ).all()

                for record in records:
                    match = _JOB_DETAIL_ID_RE.search(record.job_url or '')
                    if match:
                        record.job_hash2 = match.group(1)
                        updated += 1

                session.commit()
                if updated:
                    logger.info(f"已回填 {updated} 条历史记录的 job_hash2")
                return updated
        except Exception as e:
            logger.error(f"回填 job_hash2 失败: {e}")
            return 0

    def is_job_applied(self, job_info: dict) -> bool:
        """检查职位是否已投递

        判断依据：job_hash 与 job_hash2 两个值一起判断。
        - 新记录：按 job_hash2（详情页 URL 唯一 ID）匹配最准确
        - 旧记录（无 job_hash2）：回退到 job_hash 匹配
        - 同时保留 URL 精确匹配
        """
        if not job_info:
            return False

        job_hash = _job_hash(job_info)
        job_hash2 = _extract_job_hash2(job_info)
        try:
            with get_session() as session:
                # 条件1：job_hash 匹配（兼容旧数据）
                conditions = [
                    ApplyRecord.job_hash == job_hash,
                ]
                # 条件2：job_hash2 匹配（详情页 URL 唯一 ID）
                if job_hash2:
                    conditions.append(ApplyRecord.job_hash2 == job_hash2)

                record = session.scalar(
                    select(ApplyRecord).where(
                        or_(*conditions),
                        ApplyRecord.status.in_(('success', 'already_applied'))
                    ).limit(1)
                )
                if record:
                    logger.debug(
                        f"职位已投递: {job_info.get('title')} - {record.status} "
                        f"(job_hash={job_hash}, job_hash2={job_hash2})"
                    )
                    return True

                # 按 URL 检查
                if job_info.get('url'):
                    url_record = session.scalar(
                        select(ApplyRecord).where(ApplyRecord.job_url == job_info.get('url'))
                    )
                    if url_record:
                        logger.debug(f"职位URL已投递: {job_info.get('title')}")
                        return True

                return False
        except Exception as e:
            logger.error(f"检查投递状态失败: {e}")
            return False

    def get_record_by_id(self, record_id: int) -> dict | None:
        """按 ID 获取投递记录"""
        try:
            with get_session() as session:
                record = session.get(ApplyRecord, record_id)
                return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"获取记录详情失败: {e}")
            return None

    def delete_record(self, record_id: int) -> bool:
        """按 ID 删除投递记录，并刷新当日统计"""
        try:
            with get_session() as session:
                result = session.execute(delete(ApplyRecord).where(ApplyRecord.id == record_id))
                session.commit()
                if result.rowcount == 0:
                    return False
            # 删除后刷新统计，避免与记录不一致
            self.update_statistics()
            return True
        except Exception as e:
            logger.error(f"删除投递记录失败: {e}")
            return False

    def get_records_paginated(
            self,
            page: int = 1,
            limit: int = 50,
            status: str = None,
            platform: str = None,
    ) -> dict:
        """分页获取投递记录（可按状态/平台筛选）"""
        page = max(1, page)
        limit = max(1, min(limit, 500))

        try:
            with get_session() as session:
                # 统计总数
                count_stmt = select(func.count()).select_from(ApplyRecord)
                if status:
                    count_stmt = count_stmt.where(ApplyRecord.status == status)
                if platform:
                    count_stmt = count_stmt.where(ApplyRecord.platform == platform)
                total = session.scalar(count_stmt) or 0

                # 查询当前页
                stmt = select(ApplyRecord)
                if status:
                    stmt = stmt.where(ApplyRecord.status == status)
                if platform:
                    stmt = stmt.where(ApplyRecord.platform == platform)
                stmt = stmt.order_by(ApplyRecord.apply_time.desc()).offset((page - 1) * limit).limit(limit)
                records = session.scalars(stmt).all()

                return {
                    'total': total,
                    'page': page,
                    'limit': limit,
                    'records': [r.to_dict() for r in records],
                }
        except Exception as e:
            logger.error(f"分页获取投递记录失败: {e}")
            return {'total': 0, 'page': page, 'limit': limit, 'records': []}

    def get_recent_records(self, limit: int = 10) -> list:
        """获取最近的投递记录"""
        try:
            with get_session() as session:
                stmt = (
                    select(ApplyRecord)
                    .order_by(ApplyRecord.apply_time.desc())
                    .limit(limit)
                )
                records = session.scalars(stmt).all()
                result = []
                for r in records:
                    result.append({
                        'job_title': r.job_title,
                        'company_name': r.company_name,
                        'status': r.status,
                        'apply_time': r.apply_time.strftime('%Y-%m-%d %H:%M:%S') if r.apply_time else None,
                        'error_msg': r.error_msg,
                        'description_preview': (r.job_description or '')[:100],
                    })
                return result
        except Exception as e:
            logger.error(f"获取最近记录失败: {e}")
            return []

    def get_total_count(self) -> int:
        """获取总投递数"""
        try:
            with get_session() as session:
                return session.scalar(select(func.count()).select_from(ApplyRecord)) or 0
        except Exception as e:
            logger.error(f"获取总投递数失败: {e}")
            return 0

    # ===== 统计 =====

    def update_statistics(self, session: Session = None) -> None:
        """更新每日统计（注意：调用方需自行 commit）"""
        try:
            own_session = session is None
            if own_session:
                session = get_session()

            today = datetime.now().date()

            # 统计当日数据（case when 跨数据库写法）
            stats = session.execute(
                select(
                    func.count().label('total'),
                    func.sum(case((ApplyRecord.status == 'success', 1), else_=0)).label('success_count'),
                    func.sum(case((ApplyRecord.status == 'failed', 1), else_=0)).label('failed_count'),
                    func.sum(case((ApplyRecord.status == 'already_applied', 1), else_=0)).label('skipped_count'),
                ).where(func.date(ApplyRecord.apply_time) == today)
            ).one()

            total = stats.total or 0
            success_count = stats.success_count or 0
            failed_count = stats.failed_count or 0
            skipped_count = stats.skipped_count or 0

            # 查找或创建当日统计
            daily_stat = session.scalar(
                select(ApplyStatistics).where(ApplyStatistics.stat_date == today)
            )
            if daily_stat:
                daily_stat.total_applied = total
                daily_stat.success_count = success_count
                daily_stat.failed_count = failed_count
                daily_stat.skipped_count = skipped_count
            else:
                session.add(ApplyStatistics(
                    stat_date=today,
                    total_applied=total,
                    success_count=success_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                ))

            if own_session:
                session.commit()
                session.close()
        except Exception as e:
            logger.error(f"更新统计失败: {e}")
            if own_session:
                session.rollback()
                session.close()

    def get_statistics(self, days: int = 7) -> list:
        """获取最近 N 天的统计信息"""
        try:
            # 计算截止日期（在 Python 侧计算，避免数据库方言差异）
            cutoff_date = datetime.now().date() - timedelta(days=days)
            with get_session() as session:
                stmt = (
                    select(
                        ApplyStatistics.stat_date,
                        ApplyStatistics.total_applied,
                        ApplyStatistics.success_count,
                        ApplyStatistics.failed_count,
                        ApplyStatistics.skipped_count,
                        func.round(
                            ApplyStatistics.success_count * 100.0 /
                            func.nullif(ApplyStatistics.total_applied, 0), 2
                        ).label('success_rate'),
                    )
                    .where(ApplyStatistics.stat_date >= cutoff_date)
                    .order_by(ApplyStatistics.stat_date.desc())
                )
                rows = session.execute(stmt).all()
                return [
                    {
                        'stat_date': row.stat_date.strftime('%Y-%m-%d') if row.stat_date else None,
                        'total_applied': row.total_applied or 0,
                        'success_count': row.success_count or 0,
                        'failed_count': row.failed_count or 0,
                        'skipped_count': row.skipped_count or 0,
                        'success_rate': float(row.success_rate) if row.success_rate is not None else None,
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return []


# 全局单例
apply_record_dao = ApplyRecordDAO()