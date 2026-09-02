"""数据库连接管理（SQLAlchemy 2.0 + SQLite）"""
import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session

logger = logging.getLogger(__name__)

# SQLite 数据库文件（位于项目根目录，无需额外服务）
BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "zhaopin.db"
DB_URL = f"sqlite:///{DB_FILE}"


class Base(DeclarativeBase):
    """ORM 模型基类"""
    pass


# 全局 Engine 和 Session 工厂（惰性初始化）
_engine = None
_session_factory = None


def get_engine():
    """获取全局 SQLAlchemy Engine（惰性创建）"""
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(
            DB_URL,
            echo=False,
        )
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
        logger.info(f"SQLAlchemy Engine 已创建: {DB_FILE}")
    return _engine


def get_session() -> Session:
    """获取一个数据库会话（调用方需手动 close）"""
    return get_engine() and _session_factory()


def _ensure_column(table: str, column: str, ddl_type: str):
    """SQLite 幂等补充新列（create_all 不会给已存在的表加列，需手动 ALTER TABLE）"""
    from sqlalchemy import text
    with get_engine().connect() as conn:
        cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        if column not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
            conn.commit()
            logger.info(f"已为 {table} 补充新列: {column} {ddl_type}")


def _migrate_legacy_blocked_companies():
    """将旧版 app_config.blocked_companies 迁移到 blocked_companies 表（幂等：仅当新表为空时执行）"""
    from app_config import get_config
    from dao.blocked_company_dao import blocked_company_dao
    if blocked_company_dao.count() > 0:
        return  # 新表已有数据，不做重复迁移
    legacy = get_config().get("blocked_companies", []) or []
    legacy = [c for c in legacy if c and str(c).strip()]
    if legacy:
        added, existed = blocked_company_dao.add_many(legacy)
        logger.info(f"已迁移旧配置中的屏蔽公司: 新增 {added}, 已存在 {existed}")


def init_database():
    """初始化数据库和表结构（幂等）"""
    from dao import models  # noqa: F401  （确保模型注册到 Base.metadata）
    engine = get_engine()
    Base.metadata.create_all(engine)

    # 兼容已有表：为 apply_records 补充新增列（SQLite 需手动 ALTER TABLE）
    try:
        _ensure_column('apply_records', 'company_scale', 'VARCHAR(100)')
    except Exception as e:
        logger.warning(f"补充 apply_records.company_scale 列失败: {e}")
    try:
        _ensure_column('apply_records', 'platform', 'VARCHAR(20) DEFAULT \'zhilian\'')
    except Exception as e:
        logger.warning(f"补充 apply_records.platform 列失败: {e}")

    # 兼容旧配置：将 app_config 中遗留的屏蔽公司迁移到独立表
    try:
        _migrate_legacy_blocked_companies()
    except Exception as e:
        logger.warning(f"迁移旧屏蔽公司配置失败: {e}")

    # 兼容已有表：回填历史数据的 job_hash2（从 job_url 中提取详情页唯一 ID）
    try:
        from dao.apply_record_dao import apply_record_dao
        backfilled = apply_record_dao.backfill_job_hash2()
        if backfilled:
            logger.info(f"已自动回填 {backfilled} 条历史记录的 job_hash2")
    except Exception as e:
        logger.warning(f"回填 job_hash2 失败（可稍后手动执行）: {e}")

    logger.info(f"✅ 数据库初始化成功: {DB_FILE.name}")


def dispose_engine():
    """释放数据库连接池（应用退出时调用）"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("数据库连接池已释放")
