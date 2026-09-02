"""ORM 模型定义"""
from datetime import datetime, date

from sqlalchemy import (
    String, Integer, Text, DateTime, Date, Enum, Index, func,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from dao.database import Base

# 投递状态枚举值
APPLY_STATUS = (
    'success', 'failed', 'already_applied', 'skipped',
    'detail_fetched', 'not_qualified', 'blocked_company', 'location_mismatch',
    'keyword_filtered'
)


class ApplyRecord(Base):
    """投递记录表"""
    __tablename__ = 'apply_records'
    __table_args__ = (
        Index('idx_job_hash', 'job_hash'),
        Index('idx_job_hash2', 'job_hash2'),
        Index('idx_status', 'status'),
        Index('idx_apply_time', 'apply_time'),
        Index('idx_company', 'company_name'),
        Index('idx_description', 'job_description', 'job_requirements'),
        {
            'comment': '投递记录表',
        },
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment='职位唯一标识(标题+公司)'
    )
    job_hash2: Mapped[str | None] = mapped_column(
        String(64), comment='职位唯一标识2(详情页URL提取)'
    )
    job_title: Mapped[str] = mapped_column(String(255), nullable=False, comment='职位标题')
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, comment='公司名称')
    job_url: Mapped[str | None] = mapped_column(String(500), comment='职位链接')
    salary: Mapped[str | None] = mapped_column(String(100), comment='薪资范围')
    work_location: Mapped[str | None] = mapped_column(String(255), comment='工作地点')
    job_description: Mapped[str | None] = mapped_column(Text, comment='岗位描述')
    job_requirements: Mapped[str | None] = mapped_column(Text, comment='岗位要求')
    experience_required: Mapped[str | None] = mapped_column(String(100), comment='经验要求')
    education_required: Mapped[str | None] = mapped_column(String(100), comment='学历要求')
    job_category: Mapped[str | None] = mapped_column(String(100), comment='职位类别')
    registered_capital: Mapped[str | None] = mapped_column(String(100), comment='注册资本')
    company_scale: Mapped[str | None] = mapped_column(String(100), comment='公司规模/人数')
    platform: Mapped[str] = mapped_column(
        String(20), default='zhilian', server_default='zhilian', comment='平台类型: zhilian'
    )
    status: Mapped[str] = mapped_column(
        Enum(*APPLY_STATUS), default='success', comment='投递状态'
    )
    apply_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment='投递时间'
    )
    error_msg: Mapped[str | None] = mapped_column(Text, comment='错误信息')
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )

    def to_dict(self) -> dict:
        """转换为字典（用于 API 响应）"""
        return {
            'id': self.id,
            'job_hash': self.job_hash,
            'job_hash2': self.job_hash2,
            'job_title': self.job_title,
            'company_name': self.company_name,
            'job_url': self.job_url,
            'salary': self.salary,
            'work_location': self.work_location,
            'job_description': self.job_description,
            'job_requirements': self.job_requirements,
            'experience_required': self.experience_required,
            'education_required': self.education_required,
            'job_category': self.job_category,
            'registered_capital': self.registered_capital,
            'company_scale': self.company_scale,
            'platform': self.platform,
            'status': self.status,
            'apply_time': self.apply_time.strftime('%Y-%m-%d %H:%M:%S') if self.apply_time else None,
            'error_msg': self.error_msg,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }


class ApplyStatistics(Base):
    """投递统计表"""
    __tablename__ = 'apply_statistics'
    __table_args__ = (
        Index('idx_stat_date', 'stat_date'),
        {
            'comment': '投递统计表',
        },
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(
        Date, nullable=False, unique=True, comment='统计日期'
    )
    total_applied: Mapped[int] = mapped_column(Integer, default=0, comment='总投递数')
    success_count: Mapped[int] = mapped_column(Integer, default=0, comment='成功数')
    failed_count: Mapped[int] = mapped_column(Integer, default=0, comment='失败数')
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, comment='跳过数')
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )


class AppConfig(Base):
    """应用配置表"""
    __tablename__ = 'app_config'
    __table_args__ = (
        {
            'comment': '应用配置表',
        },
    )

    config_key: Mapped[str] = mapped_column(String(64), primary_key=True, comment='配置键')
    config_value: Mapped[str | None] = mapped_column(Text, comment='配置值(JSON序列化)')
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )


class BlockedCompany(Base):
    """屏蔽公司表（投递时需要跳过的公司/关键词）"""
    __tablename__ = 'blocked_companies'
    __table_args__ = (
        Index('idx_blocked_company_name', 'company_name', unique=True),
        {
            'comment': '屏蔽公司表',
        },
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, comment='公司名称/关键词'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, server_default=func.current_timestamp(),
        comment='添加时间'
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'company_name': self.company_name,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


class AiLog(Base):
    """AI 调用日志表（记录每次请求内容、使用的模型与返回结果）"""
    __tablename__ = 'ai_logs'
    __table_args__ = (
        Index('idx_ai_log_provider', 'provider'),
        Index('idx_ai_log_created', 'created_at'),
        {
            'comment': 'AI 调用日志表',
        },
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(
        String(20), default='deepseek', comment='模型提供方: deepseek/ollama'
    )
    model: Mapped[str] = mapped_column(String(100), comment='模型名称')
    request_text: Mapped[str] = mapped_column(Text, comment='请求内容（提示词）')
    response_text: Mapped[str] = mapped_column(Text, comment='模型返回内容')
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, server_default=func.current_timestamp(),
        comment='调用时间'
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'provider': self.provider,
            'model': self.model,
            'request_text': self.request_text,
            'response_text': self.response_text,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }