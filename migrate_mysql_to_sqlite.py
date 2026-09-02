"""将 MySQL 中的数据迁移到 SQLite（一次性脚本）

用法:
    python migrate_mysql_to_sqlite.py

前提:
    1. 旧 MySQL 服务可用（默认 localhost:3306 / root / 123456 / zhaopin）
    2. 目标为项目根目录的 zhaopin.db（由 dao.database 管理，会自动建表）

说明:
    - 只迁移 3 张业务表: apply_records / apply_statistics / app_config
    - 采用"公共列"交集拷贝，兼容两库列不完全一致的情况
    - 幂等：对已存在的记录使用 INSERT OR REPLACE，可重复执行
"""
import datetime
import sqlite3
import sys
import io

# Windows GBK 控制台无法打印 emoji，强制使用 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pymysql
from sqlalchemy import inspect

from dao.database import DB_FILE, Base, get_engine

# 旧 MySQL 连接配置（按实际环境修改）
MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'zhaopin',
    'port': 3306,
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}

# 需要迁移的业务表（表名: 该表是否包含自增主键 id）
TABLES = {
    'apply_records': True,
    'apply_statistics': True,
    'app_config': False,
}


def main():
    print(f"目标 SQLite: {DB_FILE}")
    print("=" * 60)

    # 1. 连接旧 MySQL
    try:
        mysql_conn = pymysql.connect(**MYSQL_CONFIG)
    except Exception as e:
        print(f"❌ 无法连接 MySQL: {e}")
        print("   请确认 MySQL 服务已启动，并检查 MYSQL_CONFIG 配置")
        sys.exit(1)
    print("✅ 已连接 MySQL")

    # 2. 创建 SQLite 表结构（幂等）
    engine = get_engine()
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    print("✅ 已创建 SQLite 表结构")

    # 3. 逐表迁移数据
    sqlite_conn = sqlite3.connect(DB_FILE)

    def _to_sqlite_value(v):
        """将 MySQL 取回的值转换为 SQLite 可安全绑定的类型

        把 datetime/date 统一转成文本，避免 executemany 预编译语句
        因参数类型不一致抛出 datatype mismatch。
        """
        if isinstance(v, datetime.datetime):
            return v.strftime('%Y-%m-%d %H:%M:%S.%f') if v.microsecond else v.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(v, datetime.date):
            return v.strftime('%Y-%m-%d')
        return v

    for table, has_id in TABLES.items():
        # 获取 MySQL 表列（description 始终是元组列表，取第一项为列名）
        with mysql_conn.cursor() as cur:
            cur.execute(f"SELECT * FROM `{table}` LIMIT 0")
            mysql_cols = [d[0] for d in cur.description]

        # 获取 SQLite 表列（只取两库公共列）
        sqlite_cols = [c['name'] for c in insp.get_columns(table)]
        common_cols = [c for c in mysql_cols if c in sqlite_cols]

        if not common_cols:
            print(f"⚠️  {table}: 无公共列，跳过")
            continue

        # MySQL 标识符用反引号；SQLite 标识符用双引号（MySQL 中双引号是字符串字面量）
        mysql_col_str = ','.join(f'`{c}`' for c in common_cols)
        sqlite_col_str = ','.join(f'"{c}"' for c in common_cols)
        placeholders = ','.join(['?'] * len(common_cols))
        sql = f'INSERT OR REPLACE INTO "{table}" ({sqlite_col_str}) VALUES ({placeholders})'

        # 读取 MySQL 数据
        with mysql_conn.cursor() as cur:
            cur.execute(f"SELECT {mysql_col_str} FROM `{table}`")
            rows = cur.fetchall()

        if not rows:
            print(f"ℹ️  {table}: 0 行（无数据）")
            continue

        # 写入 SQLite（datetime 统一转文本，规避 executemany 类型缓存问题）
        values = [[_to_sqlite_value(r[c]) for c in common_cols] for r in rows]
        with sqlite_conn:
            sqlite_conn.executemany(sql, values)
        print(f"✅ {table}: 迁移 {len(rows)} 行")

    mysql_conn.close()
    sqlite_conn.close()
    print("=" * 60)
    print("🎉 数据迁移完成")
    print(f"    SQLite 数据库: {DB_FILE}")
    print("    提示: 迁移后请重启服务，让应用使用 SQLite 读取数据")


if __name__ == '__main__':
    main()
