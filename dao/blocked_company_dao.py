"""屏蔽公司 DAO（投递时需要跳过的公司/关键词）"""
import logging

from sqlalchemy import select, delete

from dao.database import get_session
from dao.models import BlockedCompany

logger = logging.getLogger(__name__)


class BlockedCompanyDAO:
    """屏蔽公司数据访问对象

    屏蔽项为公司名称或关键词，命中方式为子串匹配：
    只要真实公司名称包含任一屏蔽关键词即视为需要跳过。
    """

    def list_all(self) -> list[BlockedCompany]:
        """按添加时间倒序返回全部屏蔽公司"""
        with get_session() as session:
            return list(
                session.scalars(
                    select(BlockedCompany).order_by(BlockedCompany.id.desc())
                )
            )

    def list_names(self) -> list[str]:
        """返回所有屏蔽关键词（去重、去空白）"""
        with get_session() as session:
            rows = session.scalars(select(BlockedCompany.company_name)).all()
        seen = set()
        result = []
        for name in rows:
            n = (name or '').strip()
            if n and n not in seen:
                seen.add(n)
                result.append(n)
        return result

    def count(self) -> int:
        """屏蔽公司总数"""
        with get_session() as session:
            return len(session.scalars(select(BlockedCompany.id)).all())

    def add_company(self, company_name: str) -> tuple[bool, bool]:
        """添加单个屏蔽公司。返回 (是否成功, 是否为新增)"""
        name = (company_name or '').strip()
        if not name:
            return False, False
        with get_session() as session:
            exists = session.scalar(
                select(BlockedCompany).where(BlockedCompany.company_name == name)
            )
            if exists:
                return True, False
            session.add(BlockedCompany(company_name=name))
            session.commit()
            return True, True

    def add_many(self, company_names: list) -> tuple[int, int]:
        """批量添加。返回 (新增数, 已存在数)"""
        names = []
        seen = set()
        for raw in company_names or []:
            n = (raw or '').strip()
            if n and n not in seen:
                seen.add(n)
                names.append(n)

        added = 0
        existed = 0
        with get_session() as session:
            for name in names:
                exists = session.scalar(
                    select(BlockedCompany).where(BlockedCompany.company_name == name)
                )
                if exists:
                    existed += 1
                else:
                    session.add(BlockedCompany(company_name=name))
                    added += 1
            session.commit()
        return added, existed

    def remove_company(self, company_name: str) -> bool:
        """删除单个屏蔽公司，返回是否删除成功"""
        name = (company_name or '').strip()
        with get_session() as session:
            result = session.execute(
                delete(BlockedCompany).where(BlockedCompany.company_name == name)
            )
            session.commit()
            return result.rowcount > 0

    def is_blocked(self, company_name: str) -> bool:
        """判断公司是否命中屏蔽列表（子串匹配，任一关键词命中即 True）"""
        if not company_name:
            return False
        for keyword in self.list_names():
            if keyword in company_name:
                return True
        return False


# 全局单例
blocked_company_dao = BlockedCompanyDAO()
