from fastapi import status

class AppException(Exception):
    def __init__(self, code: int, message: str, http_status: int = 500):
        self.code = code
        self.message = message
        self.http_status = http_status

class BusinessException(AppException):
    def __init__(self, message="Business error"):
        super().__init__(40000, message, status.HTTP_400_BAD_REQUEST)

class AuthenticationException(AppException):
    def __init__(self, message="Authentication failed"):
        super().__init__(40100, message, status.HTTP_401_UNAUTHORIZED)

class RateLimitException(AppException):
    def __init__(self, message="Too many requests"):
        super().__init__(42900, message, status.HTTP_429_TOO_MANY_REQUESTS)

class DatabaseException(AppException):
    def __init__(self, message="Database error"):
        super().__init__(50001, message, status.HTTP_500_INTERNAL_SERVER_ERROR)

class InfrastructureException(AppException):
    def __init__(self, message="Infrastructure error"):
        super().__init__(50002, message, status.HTTP_500_INTERNAL_SERVER_ERROR)

class LLMException(AppException):
    def __init__(self, message="LLM service error"):
        super().__init__(50003, message, status.HTTP_500_INTERNAL_SERVER_ERROR)

class SecurityException(AppException):
    def __init__(self, message="Security violation"):
        super().__init__(40300, message, status.HTTP_403_FORBIDDEN)