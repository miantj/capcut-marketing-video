from typing import Literal
from pydantic import BaseModel, Field, field_validator


class JobRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    owner: str = Field(min_length=1, max_length=30)
    script: str = Field(min_length=1, max_length=3000)
    template: Literal['new', 'selling', 'promo'] = 'new'
    ratio: Literal['9:16', '16:9'] = '9:16'
    selection: Literal['ordered', 'ai'] = 'ordered'
    narration: Literal['none'] = 'none'
    bgm_volume: float = Field(default=0.35, ge=0, le=1)
    notes: str = Field(default='', max_length=1000)
    allow_cloud_analysis: bool = False

    @field_validator('title', 'owner', 'script')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('不能为空')
        return value.strip()


class FileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: Literal['video', 'bgm']
    size: int = Field(gt=0)


class RevisionRequest(BaseModel):
    request: JobRequest


class LoginRequest(BaseModel):
    code: str = Field(max_length=256)
