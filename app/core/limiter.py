from pathlib import Path

from slowapi import Limiter
from slowapi.util import get_remote_address

# 全局限流器：供 main.py 注册与各路由装饰器共享。
# 注意：生产部署在反向代理（Nginx）之后时，get_remote_address 拿到的是代理 IP，
# 应改用 slowapi.util.get_ipaddr 以识别真实客户端 IP，避免所有用户被当作同一来源限流。
#
# storage_uri 显式指定内存存储；config_filename 指向 src/.env.limiter（纯 ASCII 占位
# 文件），阻止 slowapi 内部用 starlette.Config 读取 .env —— Windows 下 starlette 以
# 系统 GBK 编码打开文件，遇到 .env 中的 UTF-8 中文注释会抛 UnicodeDecodeError 导致
# 启动崩溃。用绝对路径避免依赖运行时的当前工作目录。
_LIMITER_CONFIG = str(Path(__file__).resolve().parents[2] / ".env.limiter")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    config_filename=_LIMITER_CONFIG,
)
