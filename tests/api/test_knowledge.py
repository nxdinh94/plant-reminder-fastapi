from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.models.knowledge import KnowledgeArticle, KnowledgeTopic


@contextmanager
def _test_db(client: TestClient):
    generator = client.app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        yield db
    finally:
        generator.close()


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "knowledge@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed(db) -> tuple[str, str]:
    topic = KnowledgeTopic(
        slug="topic-b",
        title="Topic B",
        description="B",
        cover_image_url="https://example.com/topic-b.jpg",
        sort_order=2,
    )
    topic2 = KnowledgeTopic(
        slug="topic-a",
        title="Topic A",
        description="A",
        cover_image_url="https://example.com/topic-a.jpg",
        sort_order=1,
    )
    db.add_all([topic, topic2])
    db.flush()

    article = KnowledgeArticle(
        topic_id=topic2.id,
        slug="article-2",
        title="Article 2",
        summary="Summary 2",
        hero_image_url="https://example.com/article-2.jpg",
        html_content="<p>2</p>",
        read_minutes=4,
        sort_order=2,
    )
    article2 = KnowledgeArticle(
        topic_id=topic2.id,
        slug="article-1",
        title="Article 1",
        summary="Summary 1",
        hero_image_url="https://example.com/article-1.jpg",
        html_content="<p>1</p>",
        read_minutes=3,
        sort_order=1,
    )
    db.add_all([article, article2])
    db.commit()
    return topic2.id, article2.id


def test_knowledge_endpoints_require_auth(client: TestClient) -> None:
    topics = client.get("/api/v1/knowledge/topics")
    articles = client.get("/api/v1/knowledge/topics/1/articles")
    detail = client.get("/api/v1/knowledge/articles/1")

    assert topics.status_code == 401
    assert articles.status_code == 401
    assert detail.status_code == 401


def test_list_topics_ordered(client: TestClient) -> None:
    headers = _auth_headers(client)
    with _test_db(client) as db:
        _seed(db)

    response = client.get("/api/v1/knowledge/topics", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert [item["slug"] for item in payload] == ["topic-a", "topic-b"]


def test_list_articles_and_detail(client: TestClient) -> None:
    headers = _auth_headers(client)
    with _test_db(client) as db:
        topic_id, article_id = _seed(db)

    response = client.get(f"/api/v1/knowledge/topics/{topic_id}/articles", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert [item["slug"] for item in payload] == ["article-1", "article-2"]

    detail_response = client.get(f"/api/v1/knowledge/articles/{article_id}", headers=headers)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["html_content"] == "<p>1</p>"


def test_topic_or_article_not_found(client: TestClient) -> None:
    headers = _auth_headers(client)

    missing_topic = client.get(
        "/api/v1/knowledge/topics/missing-topic/articles",
        headers=headers,
    )
    missing_article = client.get(
        "/api/v1/knowledge/articles/missing-article",
        headers=headers,
    )

    assert missing_topic.status_code == 404
    assert missing_article.status_code == 404
