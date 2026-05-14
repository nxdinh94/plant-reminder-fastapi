from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeTopicSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    title: str
    description: str
    cover_image_url: str
    sort_order: int


class KnowledgeArticleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_id: str
    slug: str
    title: str
    summary: str
    hero_image_url: str
    read_minutes: int = Field(ge=1)
    sort_order: int


class KnowledgeArticleDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_id: str
    slug: str
    title: str
    summary: str
    hero_image_url: str
    html_content: str
    read_minutes: int = Field(ge=1)
    sort_order: int
    created_at: datetime
    updated_at: datetime
