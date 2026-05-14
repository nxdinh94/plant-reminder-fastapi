from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeArticle, KnowledgeTopic


@dataclass(frozen=True)
class ArticleSeed:
    slug: str
    title: str
    summary: str
    read_minutes: int


@dataclass(frozen=True)
class TopicSeed:
    slug: str
    title: str
    description: str
    cover_image_url: str
    articles: tuple[ArticleSeed, ...]


TOPICS: tuple[TopicSeed, ...] = (
    TopicSeed(
        slug="watering-basics",
        title="Watering Basics",
        description="Learn practical watering routines that prevent overwatering and underwatering.",
        cover_image_url="https://images.unsplash.com/photo-1485955900006-10f4d324d411?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed("watering-check-soil", "How to Check Soil Moisture Correctly", "Use touch, skewer, and pot-weight checks before watering.", 4),
            ArticleSeed("watering-frequency-by-season", "Adjusting Water Frequency by Season", "Map watering intervals to temperature, humidity, and growth pace.", 5),
            ArticleSeed("signs-overwatering", "Signs of Overwatering and Fast Recovery", "Identify mushy roots and yellowing patterns, then recover safely.", 6),
            ArticleSeed("signs-underwatering", "Signs of Underwatering and Rehydration", "Recognize crisp leaves, droop timing, and slow rehydration techniques.", 5),
            ArticleSeed("bottom-watering-guide", "Bottom Watering Step-by-Step", "When and how to bottom-water plants without root stress.", 5),
            ArticleSeed("watering-after-repotting", "Watering After Repotting", "Protect new roots with careful moisture control in week one.", 4),
            ArticleSeed("water-quality-for-plants", "Water Quality: Tap, Filtered, and Rainwater", "Choose the right water source and avoid mineral buildup.", 4),
            ArticleSeed("emergency-dry-pot", "Emergency Plan for Bone-Dry Soil", "Recover hydrophobic soil with staged soaking and aeration.", 6),
        ),
    ),
    TopicSeed(
        slug="light-and-placement",
        title="Light and Placement",
        description="Position plants for healthier growth by matching each species to available light.",
        cover_image_url="https://images.unsplash.com/photo-1463320898484-cdee8141c787?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed("measure-light-home", "How to Measure Light at Home", "Use orientation, shadow test, and lux apps for quick decisions.", 4),
            ArticleSeed("direct-vs-indirect-light", "Direct vs Bright Indirect Light", "Understand window intensity and burn risk for common houseplants.", 5),
            ArticleSeed("low-light-plants", "Plants That Tolerate Low Light", "Choose resilient options for offices and shaded rooms.", 4),
            ArticleSeed("rotate-plants-even-growth", "Rotate Plants for Even Growth", "Prevent leaning and one-sided canopy development.", 3),
            ArticleSeed("supplemental-grow-lights", "Using Grow Lights Effectively", "Set distance and schedule for stable vegetative growth.", 6),
            ArticleSeed("summer-light-stress", "Handling Summer Light Stress", "Protect leaves during peak afternoon sun.", 4),
            ArticleSeed("winter-light-strategy", "Winter Light Strategy", "Compensate for short days without overwatering.", 5),
            ArticleSeed("window-placement-mistakes", "Top Window Placement Mistakes", "Avoid heat drafts, curtains, and glass scorch issues.", 4),
        ),
    ),
    TopicSeed(
        slug="soil-and-potting",
        title="Soil and Potting",
        description="Build breathable soil mixes and repot with less shock.",
        cover_image_url="https://images.unsplash.com/photo-1472396961693-142e6e269027?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed("potting-mix-components", "Potting Mix Components Explained", "Understand peat, coco coir, bark, perlite, and pumice roles.", 6),
            ArticleSeed("mixes-by-plant-type", "Soil Mixes by Plant Type", "Quick recipes for aroids, succulents, herbs, and ferns.", 6),
            ArticleSeed("when-to-repot", "When to Repot: Clear Triggers", "Root-bound signals and timing around growth cycles.", 5),
            ArticleSeed("repotting-with-minimal-shock", "Repotting With Minimal Shock", "Step-by-step method to reduce transplant stress.", 7),
            ArticleSeed("pot-size-selection", "Choosing Pot Size Correctly", "Avoid overpotting and drainage mistakes.", 4),
            ArticleSeed("drainage-and-aeration", "Drainage and Aeration Essentials", "Keep oxygen available around roots.", 4),
            ArticleSeed("fertilizer-after-repot", "Fertilizer Timing After Repotting", "Delay feeding and restart safely.", 3),
            ArticleSeed("salty-soil-reset", "Resetting Salty or Compacted Soil", "Leach salts and refresh medium structure.", 5),
        ),
    ),
    TopicSeed(
        slug="pests-and-diseases",
        title="Pests and Diseases",
        description="Diagnose early, isolate quickly, and treat plants with low-risk routines.",
        cover_image_url="https://images.unsplash.com/photo-1524593119779-9d82b2ca2b18?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed("pest-inspection-routine", "Weekly Pest Inspection Routine", "Catch mites, thrips, and mealybugs before spread.", 4),
            ArticleSeed("spider-mite-treatment", "Spider Mite Treatment Plan", "Wash, prune, and repeat cycles for reliable control.", 6),
            ArticleSeed("fungus-gnat-control", "Fungus Gnat Control Without Harsh Chemicals", "Dry-back strategy and top-dressing methods.", 5),
            ArticleSeed("mealybug-spot-treatment", "Mealybug Spot Treatment", "Use alcohol swabs and follow-up checks effectively.", 5),
            ArticleSeed("leaf-spot-diagnosis", "Leaf Spot: Fungal vs Bacterial Clues", "Differentiate spread patterns and adjust care.", 6),
            ArticleSeed("root-rot-first-aid", "Root Rot First Aid", "Immediate rescue workflow when roots turn dark and soft.", 7),
            ArticleSeed("plant-quarantine-protocol", "Quarantine Protocol for New Plants", "Simple 2-3 week process to protect your collection.", 4),
            ArticleSeed("preventive-hygiene", "Preventive Hygiene Checklist", "Clean tools and surfaces to reduce recurring outbreaks.", 3),
        ),
    ),
    TopicSeed(
        slug="propagation",
        title="Propagation",
        description="Multiply healthy plants through cuttings, division, and node care.",
        cover_image_url="https://images.unsplash.com/photo-1512428559087-560fa5ceab42?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed("stem-cutting-basics", "Stem Cutting Basics", "Choose healthy nodes and make clean cuts.", 4),
            ArticleSeed("water-vs-soil-propagation", "Water vs Soil Propagation", "Compare speed, rot risk, and transplant shock.", 5),
            ArticleSeed("prop-box-setup", "Simple Propagation Box Setup", "Create a humid environment for difficult cuttings.", 5),
            ArticleSeed("rooting-hormone-guide", "Do You Need Rooting Hormone?", "When hormone helps and when technique matters more.", 4),
            ArticleSeed("division-for-clumping-plants", "Division for Clumping Plants", "Safely separate offsets and rhizomes.", 5),
            ArticleSeed("propagation-light-and-temp", "Best Light and Temperature for Rooting", "Set stable conditions for faster root initiation.", 4),
            ArticleSeed("transfer-rooted-cuttings", "Transferring Rooted Cuttings to Soil", "Prevent collapse when moving from water to soil.", 6),
            ArticleSeed("propagation-failure-debug", "Propagation Failure Debug Guide", "Common causes and fast fixes when cuttings stall.", 6),
        ),
    ),
    TopicSeed(
        slug="seasonal-care",
        title="Seasonal Care",
        description="Adapt watering, feeding, and light as weather and day length change.",
        cover_image_url="https://images.unsplash.com/photo-1471193945509-9ad0617afabf?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed("spring-reset-checklist", "Spring Reset Checklist", "Prune, repot, and resume feeding with control.", 5),
            ArticleSeed("summer-heat-protection", "Summer Heat Protection", "Reduce stress from heat waves and rapid dry-down.", 5),
            ArticleSeed("autumn-transition", "Autumn Transition Care", "Shift to slower growth routines before winter.", 4),
            ArticleSeed("winter-survival-guide", "Winter Survival Guide", "Avoid overwatering and cold-draft damage.", 6),
            ArticleSeed("humidity-management", "Humidity Management by Season", "Balance airflow and moisture to avoid fungus.", 4),
            ArticleSeed("fertilizer-calendar", "Practical Fertilizer Calendar", "Feed less in dormancy and more in active growth.", 4),
            ArticleSeed("vacation-care-plan", "Vacation Care Plan", "Prepare plants for 3-14 days away from home.", 5),
            ArticleSeed("storm-and-power-outage", "Storm and Power Outage Plant Care", "Protect indoor plants during disruptions.", 4),
        ),
    ),
)


def _build_html(topic_title: str, article: ArticleSeed) -> str:
    safe_summary = article.summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<h2>{article.title}</h2>"
        f"<p>{safe_summary}</p>"
        "<h3>Why it matters</h3>"
        f"<p>{topic_title} decisions are easier when you use repeatable checks instead of fixed calendar dates.</p>"
        "<h3>How to do it</h3>"
        "<ul>"
        "<li>Observe the plant and substrate before taking action.</li>"
        "<li>Make one change at a time and track response for 7-14 days.</li>"
        "<li>Adjust gradually and avoid extreme swings.</li>"
        "</ul>"
        "<h3>Common mistakes</h3>"
        "<p>Most setbacks come from changing multiple variables at once or copying care intervals from unrelated species.</p>"
    )


def seed_knowledge_content() -> tuple[int, int]:
    db = SessionLocal()
    topic_count = 0
    article_count = 0
    try:
        for topic_index, topic_seed in enumerate(TOPICS):
            topic = db.execute(
                select(KnowledgeTopic).where(KnowledgeTopic.slug == topic_seed.slug)
            ).scalar_one_or_none()

            if topic is None:
                topic = KnowledgeTopic(slug=topic_seed.slug)
                db.add(topic)

            topic.title = topic_seed.title
            topic.description = topic_seed.description
            topic.cover_image_url = topic_seed.cover_image_url
            topic.sort_order = topic_index
            topic_count += 1

            db.flush()

            for article_index, article_seed in enumerate(topic_seed.articles):
                article = db.execute(
                    select(KnowledgeArticle).where(KnowledgeArticle.slug == article_seed.slug)
                ).scalar_one_or_none()

                if article is None:
                    article = KnowledgeArticle(slug=article_seed.slug)
                    db.add(article)

                article.topic_id = topic.id
                article.title = article_seed.title
                article.summary = article_seed.summary
                article.hero_image_url = topic_seed.cover_image_url
                article.html_content = _build_html(topic_seed.title, article_seed)
                article.read_minutes = article_seed.read_minutes
                article.sort_order = article_index
                article_count += 1

        db.commit()
        return topic_count, article_count
    finally:
        db.close()


if __name__ == "__main__":
    topics, articles = seed_knowledge_content()
    print(f"Seeded knowledge content: topics={topics}, articles={articles}")
