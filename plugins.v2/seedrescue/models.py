"""稀缺保种插件的 API 请求模型。"""

from pydantic import BaseModel, Field
from typing import Optional


class CandidateSelectionPayload(BaseModel):
    """用户确认下载来源时提交的候选标识。"""

    candidate_id: str = Field(..., min_length=1, max_length=160)
    confirmed_download_factor: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    confirm_unknown: bool = False
    skip_future_risk_confirmation: bool = False
