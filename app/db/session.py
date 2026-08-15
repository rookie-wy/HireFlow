import os
import pymysql
from dbutils.pooled_db import PooledDB
from contextlib import contextmanager
from app.core.config import settings
from app.core.exceptions import DatabaseException
import logging

logger = logging.getLogger(__name__)

# 解析 MySQL URL (格式: mysql+pymysql://user:password@host:port/dbname?charset=utf8mb4)
def _parse_db_url():
    url = settings.DATABASE_URL
    # 简单解析，假设格式 mysql+pymysql://user:pass@host:port/db?params
    prefix, rest = url.split("://", 1)
    user_pass, host_db = rest.split("@", 1)
    user, pwd = user_pass.split(":", 1)
    host_port, db = host_db.split("/", 1)
    if "?" in db:
        db, params = db.split("?", 1)
    else:
        params = ""
    if ":" in host_port:
        host, port = host_port.split(":", 1)
    else:
        host = host_port
        port = 3306
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": pwd,
        "db": db,
        "charset": "utf8mb4"
    }

connection_pool = None

def init_pool():
    global connection_pool
    if connection_pool is not None:
        return
    try:
        cfg = _parse_db_url()
        connection_pool = PooledDB(
            creator=pymysql,
            maxconnections=10,
            mincached=2,
            maxcached=5,
            blocking=True,
            **cfg
        )
        _init_schema()
        logger.info("MySQL connection pool initialized")
    except Exception as e:
        logger.error(f"Failed to init MySQL pool: {e}")
        raise DatabaseException("Database initialization failed")

def _init_schema():
    """执行建表脚本（幂等，使用 IF NOT EXISTS）。"""
    schema_path = os.path.join(os.path.dirname(__file__), "init_db.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()
    conn = connection_pool.connection()
    try:
        with conn.cursor() as cur:
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
        conn.commit()
    finally:
        conn.close()


def get_connection():
    if connection_pool is None:
        init_pool()
    return connection_pool.connection()

def release_connection(conn):
    if conn:
        conn.close()


def close_pool():
    global connection_pool
    if connection_pool:
        connection_pool.close()
        connection_pool = None

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_connection(conn)