from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.knowledge import KnowledgeArticle, KnowledgeTopic
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeArticleDetail,
    KnowledgeArticleSummary,
    KnowledgeTopicSummary,
)


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/topics", response_model=list[KnowledgeTopicSummary])
def list_topics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeTopic]:
    del current_user
    statement = select(KnowledgeTopic).order_by(KnowledgeTopic.sort_order.asc(), KnowledgeTopic.title.asc())
    return list(db.execute(statement).scalars())


@router.get("/topics/{topic_id}/articles", response_model=list[KnowledgeArticleSummary])
def list_topic_articles(
    topic_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeArticle]:
    del current_user
    topic = db.execute(select(KnowledgeTopic).where(KnowledgeTopic.id == topic_id)).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")

    statement = (
        select(KnowledgeArticle)
        .where(KnowledgeArticle.topic_id == topic_id)
        .order_by(KnowledgeArticle.sort_order.asc(), KnowledgeArticle.title.asc())
    )
    return list(db.execute(statement).scalars())


@router.get("/articles/{article_id}", response_model=KnowledgeArticleDetail)
def get_article_detail(
    article_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeArticle:
    del current_user
    entity = db.execute(
        select(KnowledgeArticle).where(KnowledgeArticle.id == article_id)
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return entity
