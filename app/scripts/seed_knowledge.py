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
    why_it_matters: str
    steps: tuple[str, ...]
    mistakes: tuple[str, ...]
    troubleshooting: tuple[str, ...]


@dataclass(frozen=True)
class TopicSeed:
    slug: str
    title: str
    description: str
    cover_image_url: str
    articles: tuple[ArticleSeed, ...]


TOPICS: tuple[TopicSeed, ...] = (
    TopicSeed(
        slug="smart-watering",
        title="Smart Watering",
        description="Build consistent watering habits using moisture checks, weather context, and plant signals.",
        cover_image_url="https://images.unsplash.com/photo-1485955900006-10f4d324d411?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "watering-check-soil-correctly",
                "How to Check Soil Moisture Correctly",
                "Use finger depth, wooden skewer, and pot-weight checks before every watering session.",
                6,
                "Most watering errors happen when people follow fixed calendars instead of checking root-zone moisture.",
                (
                    "Insert a finger 2-5 cm into the soil depending on pot size.",
                    "Use a wooden skewer to sample deeper layers near the root ball.",
                    "Lift the pot after watering and again before the next watering to learn weight difference.",
                    "Water only when the dryness level matches that plant's tolerance.",
                ),
                (
                    "Checking only the top 1 cm of soil.",
                    "Watering because leaves look slightly droopy at midday heat.",
                    "Assuming all plants in one shelf need water on the same day.",
                ),
                (
                    "If soil surface is dry but skewer is damp, wait 1-2 more days.",
                    "If pot stays heavy for more than 7 days, increase airflow and inspect root health.",
                ),
            ),
            ArticleSeed(
                "overwatering-recovery-plan",
                "Overwatering Recovery Plan for Houseplants",
                "Identify early root stress and recover plants with drainage correction and staged dry-back.",
                7,
                "Overwatering reduces oxygen around roots, which quickly causes root decline and leaf yellowing.",
                (
                    "Stop watering immediately and move plant to bright indirect light.",
                    "Check drainage holes and empty standing water from cache pots.",
                    "Trim dead yellow leaves to reduce stress load.",
                    "If sour smell or black roots appear, unpot, prune rot, and repot in airy mix.",
                ),
                (
                    "Adding fertilizer to a stressed, overwatered plant.",
                    "Keeping the plant in low light where soil dries too slowly.",
                    "Repotting into a much larger pot right after root damage.",
                ),
                (
                    "If leaves keep yellowing after 10 days, inspect roots again for hidden rot.",
                    "If fungus gnats appear, let top layer dry and add coarse top dressing.",
                ),
            ),
            ArticleSeed(
                "underwatering-rehydration",
                "Safe Rehydration for Severely Dry Soil",
                "Recover hydrophobic potting mix using staged soaking, not one heavy flood.",
                6,
                "Bone-dry substrate repels water; a single pour often runs down pot edges and misses roots.",
                (
                    "Water slowly in two or three rounds with 5-10 minute pauses.",
                    "Use bottom watering for 20-30 minutes for compact root balls.",
                    "Lightly aerate top layer with chopstick to help penetration.",
                    "Return to normal schedule only after moisture becomes evenly distributed.",
                ),
                (
                    "Flooding once and assuming roots are fully hydrated.",
                    "Leaving pot submerged for hours, which stresses roots.",
                ),
                (
                    "If leaves stay limp after 24 hours, check for root loss, not just dryness.",
                    "If water still channels down sides, repot with fresh mix and proper wetting.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="light-placement",
        title="Light and Placement",
        description="Match plant species to real indoor light levels and seasonal sun movement.",
        cover_image_url="https://images.unsplash.com/photo-1463320898484-cdee8141c787?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "measure-light-at-home",
                "How to Measure Indoor Light at Home",
                "Combine window direction, shadow test, and lux-app ranges to choose the right spot.",
                6,
                "Correct light placement reduces slow growth, leaf drop, and repeated pest pressure.",
                (
                    "Record window direction: east, west, south, or north.",
                    "Use a phone lux app at leaf level at 9 AM, noon, and 3 PM.",
                    "Classify zones: low light, medium, bright indirect, or direct sun.",
                    "Match each plant group to zones and label shelves for consistency.",
                ),
                (
                    "Measuring only one time of day.",
                    "Ignoring seasonal sun angle changes.",
                    "Placing plants too close to hot afternoon glass.",
                ),
                (
                    "If leaves bleach after moving, increase distance from window by 30-60 cm.",
                    "If internodes stretch, increase light duration or move closer to brighter zone.",
                ),
            ),
            ArticleSeed(
                "grow-light-setup-guide",
                "Grow Light Setup for Apartments",
                "Set practical distance, duration, and mounting height for stable indoor growth.",
                7,
                "Grow lights can replace weak window light when configured with the right intensity and schedule.",
                (
                    "Start with full-spectrum LED bars positioned 20-40 cm above canopy.",
                    "Run 10-12 hours for foliage plants and 12-14 hours for herbs and seedlings.",
                    "Use a timer to keep a fixed daily light window.",
                    "Raise or dim lights when leaf tips pale or curl upward.",
                ),
                (
                    "Running lights 24 hours without dark period.",
                    "Keeping lights too far, causing elongated weak stems.",
                ),
                (
                    "If algae forms on soil, reduce overwatering and improve airflow.",
                    "If leaves are small and pale, increase intensity gradually over one week.",
                ),
            ),
            ArticleSeed(
                "window-placement-mistakes",
                "Common Window Placement Mistakes",
                "Avoid heat drafts, cold glass shock, and hidden low-light corners.",
                5,
                "A good species can still fail if microclimate around the window is unstable.",
                (
                    "Keep tropical foliage away from AC vents and direct heater airflow.",
                    "Rotate plants every 1-2 weeks for even canopy development.",
                    "Use sheer curtains to filter harsh west-facing sun.",
                ),
                (
                    "Placing plants behind blackout curtains.",
                    "Ignoring night temperature drops near winter windows.",
                ),
                (
                    "If one side leans hard, rotate and prune for balance.",
                    "If cold damage appears, move pots 20-30 cm away from glass at night.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="soil-root-health",
        title="Soil and Root Health",
        description="Build breathable mixes and repot strategically to maintain vigorous root systems.",
        cover_image_url="https://images.unsplash.com/photo-1472396961693-142e6e269027?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "potting-mix-components-explained",
                "Potting Mix Components Explained",
                "Understand how coco coir, bark, perlite, compost, and pumice affect moisture and aeration.",
                7,
                "Root oxygen and moisture balance determine whether plants thrive or slowly decline.",
                (
                    "Use coco coir or peat for moisture retention base.",
                    "Add bark and pumice/perlite to create air pockets.",
                    "For tropical aroids, target a chunky fast-draining texture.",
                    "For herbs and vegetables in pots, include compost for nutrient buffering.",
                ),
                (
                    "Using garden soil in indoor pots.",
                    "Packing mix tightly so roots lose airflow.",
                ),
                (
                    "If mix stays wet too long, increase mineral aeration components.",
                    "If mix dries in one day, increase fine moisture-retentive fraction.",
                ),
            ),
            ArticleSeed(
                "repotting-with-minimal-shock",
                "Repotting With Minimal Shock",
                "Follow a low-stress repot workflow to protect active roots and reduce transplant pause.",
                8,
                "Repot shock often comes from rough root handling, poor timing, and abrupt environmental changes.",
                (
                    "Repot during active growth season when recovery is faster.",
                    "Choose new pot only 2-4 cm wider than current root ball.",
                    "Loosen circling roots gently; prune only dead or mushy sections.",
                    "After repotting, water thoroughly once, then monitor moisture closely for one week.",
                ),
                (
                    "Jumping to oversized pots that hold excess water.",
                    "Fertilizing immediately after root disturbance.",
                ),
                (
                    "If leaves droop for 2-3 days, keep light bright but indirect and avoid extra watering.",
                    "If decline continues beyond one week, inspect for root damage or poor drainage.",
                ),
            ),
            ArticleSeed(
                "salt-buildup-soil-reset",
                "How to Reset Salty Potting Soil",
                "Leach fertilizer salts and refresh old compacted mix before roots burn.",
                5,
                "Salt accumulation can mimic nutrient deficiency while actually damaging root tips.",
                (
                    "Flush pot with clean water equal to 2-3 times pot volume.",
                    "Allow full drainage and repeat once after 24 hours if crust persists.",
                    "Trim heavily damaged leaves and resume feeding at half strength.",
                ),
                (
                    "Using strong fertilizer to fix salt stress symptoms.",
                    "Skipping drainage checks during flush.",
                ),
                (
                    "If white crust returns quickly, reduce fertilizer concentration and frequency.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="pests-disease-control",
        title="Pests and Disease Control",
        description="Use early detection, isolation, and repeatable treatment cycles for common indoor plant pests.",
        cover_image_url="https://images.unsplash.com/photo-1524593119779-9d82b2ca2b18?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "weekly-pest-inspection-routine",
                "Weekly Pest Inspection Routine",
                "Catch mites, thrips, scales, and mealybugs before they spread across your plant shelf.",
                5,
                "Pests are easiest to control in early stages when populations are still localized.",
                (
                    "Inspect leaf undersides, nodes, and new growth using a flashlight.",
                    "Check sticky residue, stippling marks, or silvery scratches.",
                    "Isolate suspicious plants immediately in a separate area.",
                ),
                (
                    "Treating all plants blindly without diagnosis.",
                    "Skipping follow-up checks after first treatment.",
                ),
                (
                    "If multiple plants are affected, map infestation zones and treat in batches.",
                ),
            ),
            ArticleSeed(
                "spider-mite-treatment-plan",
                "Spider Mite Treatment Plan",
                "Use wash-down, targeted spray, and repeat intervals to break spider mite life cycle.",
                7,
                "Spider mites multiply fast in warm, dry conditions and cause persistent leaf decline.",
                (
                    "Rinse foliage thoroughly, especially leaf undersides.",
                    "Apply insecticidal soap or horticultural oil according to label.",
                    "Repeat treatment every 4-7 days for at least 3 cycles.",
                    "Increase humidity and airflow balance to reduce reinfestation pressure.",
                ),
                (
                    "Treating once and stopping too early.",
                    "Spraying in direct sun, which can burn leaves.",
                ),
                (
                    "If new stippling appears after cycle 2, extend treatment for two additional rounds.",
                ),
            ),
            ArticleSeed(
                "fungus-gnat-control",
                "Fungus Gnat Control Without Harsh Chemicals",
                "Combine watering discipline, sticky traps, and biological controls for durable gnat suppression.",
                6,
                "Fungus gnats are tied to persistently wet organic soil and can stress seedlings and tender roots.",
                (
                    "Allow top 2-3 cm of substrate to dry between waterings.",
                    "Use yellow sticky traps to monitor adult populations.",
                    "Add sand or pumice top dressing to discourage egg-laying.",
                    "Apply BTI or beneficial nematodes for heavy recurring infestations.",
                ),
                (
                    "Keeping soil constantly moist for all plant types.",
                    "Ignoring larvae stage and targeting only flying adults.",
                ),
                (
                    "If numbers do not drop in 10 days, inspect for hidden water reservoirs in cache pots.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="propagation-multiplication",
        title="Propagation and Multiplication",
        description="Propagate healthy plants by stem cuttings, division, and controlled humidity routines.",
        cover_image_url="https://images.unsplash.com/photo-1512428559087-560fa5ceab42?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "stem-cutting-basics",
                "Stem Cutting Basics",
                "Select healthy node sections and root them under stable humidity and light.",
                6,
                "Node quality and sanitation strongly influence rooting speed and success rate.",
                (
                    "Sterilize cutting tool before each plant.",
                    "Cut 1-2 cm below a healthy node with at least one leaf.",
                    "Remove lower leaves that would sit in water or substrate.",
                    "Place in bright indirect light and warm stable temperatures.",
                ),
                (
                    "Using weak, etiolated stems as source material.",
                    "Letting cuttings sit dry too long before placing in medium.",
                ),
                (
                    "If stem base turns mushy, recut above damaged tissue and restart.",
                ),
            ),
            ArticleSeed(
                "water-vs-soil-propagation",
                "Water vs Soil Propagation",
                "Choose propagation medium based on species behavior, rot risk, and transplant tolerance.",
                6,
                "Different species respond differently; matching medium to plant type improves survival.",
                (
                    "Use water propagation for visual root tracking on easy species.",
                    "Use airy soil propagation when you want to avoid water-to-soil transition shock.",
                    "Change water every 3-5 days if rooting in water.",
                ),
                (
                    "Leaving cuttings in old stagnant water.",
                    "Moving newly rooted water cuttings into dense compact soil.",
                ),
                (
                    "If roots stall, increase warmth and check light intensity.",
                ),
            ),
            ArticleSeed(
                "transfer-rooted-cuttings",
                "Transferring Rooted Cuttings to Soil",
                "Move rooted cuttings into lightly moist substrate and transition humidity gradually.",
                7,
                "Most propagation losses happen during transfer, not initial rooting.",
                (
                    "Transplant when roots are 3-5 cm long with multiple branches.",
                    "Use small pots with airy mix and pre-moistened medium.",
                    "Keep evenly moist for 7-10 days, then taper to normal cycle.",
                ),
                (
                    "Waiting until roots become overly long and brittle.",
                    "Letting new transplant dry hard in first week.",
                ),
                (
                    "If leaf wilt persists beyond 48 hours, increase humidity cover temporarily.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="seasonal-climate-care",
        title="Seasonal and Climate Care",
        description="Adjust care routines for hot seasons, rainy periods, and cooler months with practical checklists.",
        cover_image_url="https://images.unsplash.com/photo-1471193945509-9ad0617afabf?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "summer-heat-protection",
                "Summer Heat Protection for Container Plants",
                "Protect foliage and roots during heat waves with shade timing and hydration strategy.",
                6,
                "Container plants overheat and dry faster than in-ground plants during high-temperature periods.",
                (
                    "Shift sensitive plants away from late afternoon direct sun.",
                    "Water early morning deeply rather than frequent light sprinkles.",
                    "Mulch container surface to reduce evaporation spikes.",
                    "Group plants to create a cooler microclimate.",
                ),
                (
                    "Watering at noon on hot surfaces, causing thermal stress.",
                    "Using black plastic pots in exposed west-facing areas without shielding.",
                ),
                (
                    "If leaves scorch suddenly, provide temporary shade cloth for 3-5 days.",
                ),
            ),
            ArticleSeed(
                "rainy-season-root-protection",
                "Rainy Season Root Protection",
                "Prevent root rot and nutrient leaching during extended wet weather.",
                5,
                "Long wet periods reduce oxygen and can trigger fungal root problems in containers.",
                (
                    "Elevate pots so drainage holes stay clear.",
                    "Reduce irrigation frequency and monitor substrate depth moisture.",
                    "Improve airflow around dense plant groupings.",
                ),
                (
                    "Continuing dry-season watering schedules during frequent rain.",
                    "Leaving saucers full after heavy storms.",
                ),
                (
                    "If lower leaves yellow rapidly, inspect roots and consider partial soil refresh.",
                ),
            ),
            ArticleSeed(
                "vacation-care-plan",
                "Vacation Plant Care Plan (3-14 Days)",
                "Set up low-risk watering and light control before travel.",
                5,
                "Most travel-related plant losses come from poor preparation rather than absence length.",
                (
                    "Water thoroughly 24 hours before departure.",
                    "Move plants out of harsh direct sun to reduce demand.",
                    "Use wick systems or self-watering reservoirs for thirsty species.",
                    "Group plants and add pebble trays for humidity buffering.",
                ),
                (
                    "Fertilizing right before travel.",
                    "Leaving plants in extreme high-light zones with no adjustment.",
                ),
                (
                    "If returning to dry collapse, rehydrate gradually over 24 hours instead of flooding all at once.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="edible-gardening",
        title="Edible Gardening",
        description="Grow herbs and compact vegetables in balconies, patios, and small home gardens.",
        cover_image_url="https://images.unsplash.com/photo-1466692476868-aef1dfb1e735?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "kitchen-herbs-beginner-plan",
                "Beginner Kitchen Herb Plan",
                "Grow basil, mint, and parsley with container spacing, pruning, and harvest timing.",
                6,
                "Herbs provide fast feedback and daily use, making them ideal for consistent gardening practice.",
                (
                    "Use 15-20 cm pots with high-drainage potting mix.",
                    "Give basil and mint at least 4-6 hours of strong light.",
                    "Pinch growing tips weekly to promote branching.",
                ),
                (
                    "Harvesting too heavily from small plants.",
                    "Keeping mint crowded with other herbs in same pot.",
                ),
                (
                    "If basil flowers early, prune flower spikes and improve light and nutrition balance.",
                ),
            ),
            ArticleSeed(
                "chili-pepper-in-pots",
                "Chili Pepper in Pots: Practical Guide",
                "Manage light, feeding, and fruiting stages for productive container chili plants.",
                7,
                "Fruit crops have different nutrient and watering demands than foliage ornamentals.",
                (
                    "Start with at least 25-30 cm deep container and strong sun exposure.",
                    "Use balanced feed in vegetative stage, then higher potassium in flowering stage.",
                    "Support branches once fruit load increases.",
                ),
                (
                    "Overwatering during cool periods.",
                    "Applying high nitrogen late, resulting in leaves without fruit.",
                ),
                (
                    "If flowers drop, check heat stress, inconsistent watering, and low pollination.",
                ),
            ),
            ArticleSeed(
                "leafy-greens-quick-cycle",
                "Quick-Cycle Leafy Greens at Home",
                "Grow lettuce and Asian greens in short cycles with succession sowing.",
                5,
                "Fast greens build confidence and provide reliable harvest even in limited spaces.",
                (
                    "Sow small batches every 7-10 days for continuous harvest.",
                    "Keep medium consistently moist but not soggy.",
                    "Harvest outer leaves first to extend plant productivity.",
                ),
                (
                    "Sowing all seeds at once and losing continuity.",
                    "Ignoring heat which causes early bolting.",
                ),
                (
                    "If leaves turn bitter, shift to cooler light window and harvest younger.",
                ),
            ),
        ),
    ),
)


def _build_html(topic_title: str, article: ArticleSeed) -> str:
    safe_summary = article.summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_why = article.why_it_matters.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    steps_html = "".join(f"<li>{step}</li>" for step in article.steps)
    mistakes_html = "".join(f"<li>{mistake}</li>" for mistake in article.mistakes)
    troubleshooting_html = "".join(f"<li>{tip}</li>" for tip in article.troubleshooting)

    return (
        f"<h2>{article.title}</h2>"
        f"<p>{safe_summary}</p>"
        "<h3>Why it matters</h3>"
        f"<p>{safe_why}</p>"
        f"<p>This guide belongs to <strong>{topic_title}</strong> and is designed for real home-growing conditions.</p>"
        "<h3>Step-by-step</h3>"
        f"<ol>{steps_html}</ol>"
        "<h3>Common mistakes</h3>"
        f"<ul>{mistakes_html}</ul>"
        "<h3>Troubleshooting</h3>"
        f"<ul>{troubleshooting_html}</ul>"
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
