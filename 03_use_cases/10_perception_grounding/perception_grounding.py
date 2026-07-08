"""Perception grounding: image + dietary prompt -> interactive HTML overlay.

The model analyzes a photo in a single API call, identifies food items
at specific pixel locations, and generates a self-contained HTML page
with color-coded dots and nutrition info overlaid on the image.

Run:
  MODEL_API_KEY=your_key python perception_grounding.py examples/food_in_fridge.jpeg
"""

import argparse
import base64
import io
import os
import sys
import time

from openai import OpenAI
from PIL import Image

MODEL = os.environ.get("MODEL_NAME", "muse-spark-1.1")
BASE_URL = os.environ.get("MODEL_BASE_URL", "https://api.meta.ai/v1")

MAX_IMAGE_DIMENSION = 1280

DEFAULT_PROMPT = (
    "I am pescatarian with high cholesterol. "
    "Put green dots on recommended food and red dots on not recommended food. "
    "Don't duplicate dots and make sure the dots are localized properly. "
    "When hovering over the dot, show personalized justification and "
    '"health score" out of 10, along with calories and carbs, protein, and fat. '
    "Health score numbers should appear right above the dot without hovering. "
    "The description that shows when hovering should go above all other dots."
)

SYSTEM_PROMPT = """You receive an image and a dietary prompt. Identify each food item, determine its location as percentage coordinates, and generate a complete self-contained HTML file.

HTML structure:
- Embed the image using the placeholder IMAGE_DATA_URI (will be replaced automatically)
- Position: relative container, position: absolute dots at percentage-based locations
- Green dots (#22c55e) for recommended items, red dots (#ef4444) for not recommended
- 16px circle dots with white border
- Health score label always visible above each dot
- On hover: dark tooltip with item name, justification, health score, calories, carbs, protein, fat
- Tooltips must use JavaScript to stay within the image container: if near top (<30%), show below; if near left edge (<25%), align left; if near right edge (>75%), align right
- Responsive layout, overflow: hidden on container
- Output ONLY the complete HTML from <!DOCTYPE html> to </html>. No markdown fences."""


def _load_and_resize_image(image_path: str) -> str:
    """Load an image, resize if too large, return as base64 data URI."""
    img = Image.open(image_path)
    original_size = img.size

    if max(img.size) > MAX_IMAGE_DIMENSION:
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)
        print(f"  Resized: {original_size[0]}x{original_size[1]} -> {img.size[0]}x{img.size[1]}")

    buf = io.BytesIO()
    fmt = "JPEG" if image_path.lower().endswith((".jpg", ".jpeg")) else "PNG"
    img.save(buf, format=fmt, quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{b64}"


def run_perception(
    image_path: str,
    prompt: str = DEFAULT_PROMPT,
    output_path: str | None = None,
) -> str:
    """Analyze an image and generate an interactive HTML overlay."""
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["MODEL_API_KEY"])

    image_filename = os.path.basename(image_path)

    print(f"\nPerception Grounding")
    print(f"  Model: {MODEL}")
    print(f"  Image: {image_filename}")
    print(f"  Prompt: {prompt[:80]}...")

    image_data_uri = _load_and_resize_image(image_path)
    print(f"  Generating HTML overlay", end="", flush=True)

    start = time.time()

    stream = client.responses.create(
        model=MODEL,
        stream=True,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": image_data_uri,
                    },
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                ],
            },
        ],
    )

    html_chunks = []
    tokens = 0
    for event in stream:
        if event.type == "response.output_text.delta":
            html_chunks.append(event.delta)
            print(".", end="", flush=True)
        elif event.type == "response.completed":
            if event.response.usage:
                tokens = event.response.usage.total_tokens
    print()

    elapsed = time.time() - start
    html_content = "".join(html_chunks).strip()

    if html_content.startswith("```"):
        lines = html_content.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        html_content = "\n".join(lines)

    html_content = html_content.replace("IMAGE_DATA_URI", image_data_uri)

    if output_path is None:
        name = os.path.splitext(image_filename)[0]
        output_path = f"{name}_grounded.html"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n  Done in {elapsed:.1f}s")
    print(f"  Tokens: {tokens:,}")
    print(f"  Output: {output_path} ({len(html_content) / 1024:.1f} KB)")
    print(f"  Open in browser: file://{os.path.abspath(output_path)}")

    return output_path


if __name__ == "__main__":
    if "MODEL_API_KEY" not in os.environ:
        print("Set MODEL_API_KEY to run.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Generate interactive HTML overlays from images"
    )
    parser.add_argument("image", help="Path to the image file")
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Dietary/analysis prompt",
    )
    parser.add_argument("--output", default=None, help="Output HTML file path")
    args = parser.parse_args()

    if not os.path.isfile(args.image):
        print(f"Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    run_perception(args.image, prompt=args.prompt, output_path=args.output)
