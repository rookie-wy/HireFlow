from typing import TypeVar, Generic, Optional
from pydantic import BaseModel

T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None
    trace_id: Optional[str] = None

def success(data: T, trace_id: str = "") -> APIResponse[T]:
    return APIResponse(code=200, message="success", data=data, trace_id=trace_id)

def error(code: int, message: str, trace_id: str = "") -> APIResponse:
    return APIResponse(code=code, message=message, data=None, trace_id=trace_id)