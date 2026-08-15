from slowapi import Limiter
from slowapi.util import get_remote_address

# 全局限流器：供 main.py 注册与各路由装饰器共享。
# 注意：生产部署在反向代理（Nginx）之后时，get_remote_address 拿到的是代理 IP，
# 应改用 slowapi.util.get_ipaddr 以识别真实客户端 IP，避免所有用户被当作同一来源限流。
limiter = Limiter(key_func=get_remote_address)
