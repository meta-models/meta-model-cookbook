"""Research-to-slides pipeline: topic -> web search -> outline -> model-designed HTML.

Uses the Model API's built-in web search tool to research a topic, then
generates a structured outline and a full reveal.js HTML presentation.
The model controls both content and visual design.

Run:
  MODEL_API_KEY=your_key python research_to_slides.py "AI Agents in Production"
"""

import json
import os
import sys
import time

from openai import OpenAI

MODEL = os.environ.get("META_MODEL", "muse-spark-1.1")
BASE_URL = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1")


def _extract_search_queries(response) -> list[str]:
    """Extract the search queries the model issued via the web search tool."""
    queries = []
    for item in response.output:
        if item.type == "web_search_call":
            action = getattr(item, "action", None)
            if action:
                query = getattr(action, "query", None)
                if query:
                    queries.append(str(query))
                    continue
                action_queries = getattr(action, "queries", None)
                if action_queries and isinstance(action_queries, list):
                    queries.extend(str(q) for q in action_queries)
    return queries


def _extract_citations(response) -> list[str]:
    """Extract citation URLs from search grounding annotations."""
    urls = []
    seen = set()
    for item in response.output:
        if item.type == "message":
            for block in item.content:
                if hasattr(block, "annotations") and block.annotations:
                    for ann in block.annotations:
                        url = getattr(ann, "url", None)
                        if url and url.startswith("http") and url not in seen:
                            seen.add(url)
                            urls.append(url)
    return urls


def _normalize_outline(outline: dict) -> dict:
    """Normalize model output to match the expected outline schema."""
    if "title" not in outline:
        for key in ("presentation_title", "deck_title", "name", "heading"):
            if key in outline:
                outline["title"] = outline.pop(key)
                break
        else:
            slides = outline.get("slides", [])
            if slides and slides[0].get("layout") == "title":
                outline["title"] = slides[0].get("title", "Presentation")

    for slide in outline.get("slides", []):
        if "bullet_points" not in slide:
            for key in ("bullets", "content", "points", "items", "body", "text"):
                if key in slide and isinstance(slide[key], list):
                    slide["bullet_points"] = slide.pop(key)
                    break
                elif key in slide and isinstance(slide[key], str):
                    slide["bullet_points"] = [slide.pop(key)]
                    break
            else:
                slide["bullet_points"] = []

        if "layout" not in slide:
            slide["layout"] = "content"

        if "sources" not in slide:
            for key in ("citations", "refs", "references", "urls"):
                if key in slide:
                    slide["sources"] = slide.pop(key)
                    break

    return outline


def run_pipeline(topic: str, output_path: str | None = None) -> str:
    """Run the full research-to-slides pipeline."""
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["MODEL_API_KEY"])
    total_searches = 0
    total_tokens = 0

    print(f"\n{'#'*60}")
    print(f"# RESEARCH-TO-SLIDES PIPELINE")
    print(f"# Topic: {topic}")
    print(f"# Model: {MODEL}")
    print(f"{'#'*60}")

    pipeline_start = time.time()

    # ── Step 1: Research via Model API web search tool ──

    print(f"\n{'='*60}")
    print(f"STEP 1: RESEARCH — \"{topic}\"")
    print(f"{'='*60}")

    print(f"  Using Model API web search tool to research the topic...")
    start = time.time()

    research_response = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": (
                "You are a research assistant preparing material for a slide presentation. "
                "Search the web thoroughly for current, authoritative information on the given topic. "
                "Search from multiple angles: overview, architecture patterns, real-world examples, "
                "common pitfalls, and recent developments. "
                "Compile your findings into a structured research brief with clear sections. "
                "Include specific facts, numbers, and examples. Cite your sources with URLs."
            )},
            {"role": "user", "content": (
                f"Research this topic for a 10-12 slide presentation: \"{topic}\"\n\n"
                "Search from at least 3 different angles to get comprehensive coverage. "
                "Include: key concepts, architecture patterns, real-world case studies, "
                "tools/frameworks, common challenges, and recent trends.\n\n"
                "Format your output as a structured research brief with clear sections."
            )},
        ],
        tools=[{"type": "web_search", "search_context_size": "high"}],
    )

    elapsed = time.time() - start
    searches = sum(1 for item in research_response.output if item.type == "web_search_call")
    tokens = research_response.usage.total_tokens if research_response.usage else 0
    total_searches += searches
    total_tokens += tokens

    research_text = research_response.output_text
    search_queries = _extract_search_queries(research_response)
    citation_urls = _extract_citations(research_response)

    print(f"  Done in {elapsed:.1f}s — {searches} web searches, {tokens:,} tokens")
    print(f"  Research brief: {len(research_text):,} characters")
    if search_queries:
        print(f"  Search queries ({len(search_queries)}):")
        for q in search_queries:
            print(f"    → \"{q}\"")

    # ── Step 2: Generate structured outline ──

    print(f"\n{'='*60}")
    print("STEP 2: OUTLINE — generating structured slide outline")
    print(f"{'='*60}")

    start = time.time()

    outline_response = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": (
                "You are a presentation designer. Given research material on a topic, "
                "create a structured outline for a 10-12 slide reveal.js presentation.\n\n"
                "Rules:\n"
                "- First slide: layout='title' with the presentation title and a subtitle\n"
                "- Last slide: layout='references' listing all source URLs\n"
                "- Use layout='content' for most slides (bullet_points with 3-5 items)\n"
                "- Use layout='code' for slides with code examples (include code_block and code_language)\n"
                "- Use layout='comparison' for side-by-side comparisons\n"
                "- Use layout='summary' for key takeaways\n"
                "- Each content slide MUST have a bullet_points array with 3-5 string items\n"
                "- Include speaker_notes for each slide\n"
                "- List source URLs (full https:// URLs, not reference IDs)\n\n"
                "Respond with ONLY valid JSON."
            )},
            {"role": "user", "content": (
                f"Create a slide outline for: \"{topic}\"\n\n"
                f"Research material:\n{research_text[:12000]}"
            )},
        ],
    )

    elapsed = time.time() - start
    tokens = outline_response.usage.total_tokens if outline_response.usage else 0
    total_tokens += tokens

    raw_text = outline_response.output_text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_text = "\n".join(lines)

    outline = json.loads(raw_text)
    outline = _normalize_outline(outline)

    print(f"  Done in {elapsed:.1f}s — {tokens:,} tokens, {len(outline.get('slides', []))} slides")

    # ── Step 3: Model generates full styled HTML ──

    print(f"\n{'='*60}")
    print("STEP 3: DESIGN — model generates full styled HTML")
    print(f"{'='*60}")

    start = time.time()

    design_stream = client.responses.create(
        model=MODEL,
        stream=True,
        input=[
            {"role": "system", "content": (
                "You are an expert web designer who creates visually stunning presentations. "
                "Given a slide outline as JSON, generate a COMPLETE self-contained HTML file "
                "using reveal.js that looks professional and modern.\n\n"
                "Design requirements:\n"
                "- Use reveal.js loaded from CDN: https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/\n"
                "- Use Google Fonts (Inter for body, JetBrains Mono for code)\n"
                "- Dark theme with a rich gradient background (deep navy/indigo/purple tones)\n"
                "- Vibrant accent gradients (indigo, cyan, emerald) for highlights\n"
                "- Glassmorphism: semi-transparent cards with backdrop-filter blur\n"
                "- Emoji icons at the start of key bullet points\n"
                "- Title slide: large gradient text, decorative accent line\n"
                "- Code slides: rounded container with syntax highlighting\n"
                "- All CSS inline in <style> block\n"
                "- Complete HTML from <!DOCTYPE html> to </html>\n"
                "- Include Reveal.initialize() with fade transition and highlight plugin\n\n"
                "Output ONLY the HTML."
            )},
            {"role": "user", "content": (
                f"Generate a beautiful reveal.js HTML presentation from this outline:\n\n"
                f"{json.dumps(outline, indent=2)}"
            )},
        ],
    )

    html_chunks = []
    tokens = 0
    for event in design_stream:
        if event.type == "response.output_text.delta":
            html_chunks.append(event.delta)
            print(".", end="", flush=True)
        elif event.type == "response.completed":
            if event.response.usage:
                tokens = event.response.usage.total_tokens
    print()

    elapsed = time.time() - start
    total_tokens += tokens

    html_content = "".join(html_chunks).strip()
    if html_content.startswith("```"):
        lines = html_content.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        html_content = "\n".join(lines)

    if output_path is None:
        safe_name = topic.lower().replace(" ", "_")[:50]
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "_")
        output_path = f"{safe_name}_slides.html"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"  Done in {elapsed:.1f}s — {tokens:,} tokens, {len(html_content)/1024:.1f} KB")

    # ── Save stats ──

    pipeline_elapsed = time.time() - pipeline_start

    stats = {
        "topic": topic,
        "model": MODEL,
        "pipeline_duration_seconds": round(pipeline_elapsed, 1),
        "steps": {
            "research": {
                "web_searches": total_searches,
                "search_queries": search_queries,
                "citations_found": len(citation_urls),
                "citation_urls": citation_urls,
            },
            "outline": {
                "slide_count": len(outline.get("slides", [])),
                "layouts_used": list({s.get("layout", "content") for s in outline.get("slides", [])}),
            },
            "design": {
                "output_file": os.path.basename(output_path),
                "output_size_kb": round(os.path.getsize(output_path) / 1024, 1),
            },
        },
        "totals": {
            "web_searches": total_searches,
            "tokens": total_tokens,
            "duration_seconds": round(pipeline_elapsed, 1),
            "slide_count": len(outline.get("slides", [])),
            "sources_cited": len(outline.get("all_sources", [])),
        },
    }

    stats_path = output_path.replace(".html", "_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print(f"\n{'='*60}")
    print(f"DONE in {pipeline_elapsed:.1f}s")
    print(f"  Total searches: {total_searches}")
    print(f"  Total tokens: {total_tokens:,}")
    print(f"  Slides: {stats['totals']['slide_count']}")
    print(f"  Output: {output_path}")
    print(f"  Stats:  {stats_path}")
    print(f"  Open in browser: file://{os.path.abspath(output_path)}")
    print(f"{'='*60}")

    return output_path


if __name__ == "__main__":
    if "MODEL_API_KEY" not in os.environ:
        print("Set MODEL_API_KEY to run this pipeline.", file=sys.stderr)
        sys.exit(1)

    topic = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "AI Agents in Production — Architecture Patterns and Lessons Learned"
    )
    run_pipeline(topic)
