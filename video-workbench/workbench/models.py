from typing import Literal
from pydantic import BaseModel, Field, field_validator


class JobRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    owner: str = Field(min_length=1, max_length=30)
    script: str = Field(min_length=1, max_length=3000)
    template: Literal['new', 'selling', 'promo'] = 'new'
    ratio: Literal['9:16', '16:9'] = '9:16'
    selection: Literal['ordered', 'ai'] = 'ordered'
    narration: Literal['none', 'volcengine'] = 'volcengine'
    tts_speaker: str = Field(default='zh_female_vv_uranus_bigtts', min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_-]+$')
    tts_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    bgm_volume: float = Field(default=0.35, ge=0, le=1)
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


class SpeechPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20)
    speaker: str = Field(default='zh_female_vv_uranus_bigtts', min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_-]+$')
    speed: float = Field(default=1, ge=.5, le=2)


class RevisionRequest(BaseModel):
    request: JobRequest


class LoginRequest(BaseModel):
    code: str = Field(max_length=256)
