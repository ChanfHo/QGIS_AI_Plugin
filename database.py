"""统一管理PostgreSQL连接参数和连接创建。"""

import os
from typing import Dict

import psycopg2


def get_database_config() -> Dict[str, object]:
    """读取项目共用的数据库连接参数。"""
    return {
        "host": os.getenv("QGIS_AI_DB_HOST", "39.102.119.130"),
        "port": int(os.getenv("QGIS_AI_DB_PORT", "5432")),
        "dbname": os.getenv("QGIS_AI_DB_NAME", "qgis_ai_plugin_db"),
        "user": os.getenv("QGIS_AI_DB_USER", "postgres"),
        "password": os.getenv("QGIS_AI_DB_PASSWORD", "iamchanfho"),
        "connect_timeout": int(os.getenv("QGIS_AI_DB_CONNECT_TIMEOUT", "5")),
    }


def connect_database():
    """建立项目共用的PostgreSQL连接。"""
    return psycopg2.connect(**get_database_config())


def configure_qgis_uri(uri) -> None:
    """为QGIS数据源URI设置统一的PostgreSQL连接参数。"""
    config = get_database_config()
    uri.setConnection(
        str(config["host"]),
        str(config["port"]),
        str(config["dbname"]),
        str(config["user"]),
        str(config["password"]),
    )
