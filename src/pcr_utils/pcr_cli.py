"""
PCR CLI - Parse an EMS dispatch PDF using a local Gemma4 model via Ollama.

Usage:
    python -m src.pcr_utils.pcr_cli <path/to/dispatch.pdf>
    python -m src.pcr_utils.pcr_cli <path/to/dispatch.pdf> --model gemma4:latest
    python -m src.pcr_utils.pcr_cli <path/to/dispatch.pdf> --ollama-url http://localhost:11434
"""

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import fitz  # PyMuPDF


OLLAMA_DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:latest"

PROMPT_FILE = Path(__file__).parent / "pcr_parse_prompt_local.md"


def pdf_to_images_base64(pdf_path: Path) -> list[str]:
    """Convert each PDF page to a base64-encoded PNG string."""
    doc = fitz.open(str(pdf_path))
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        images.append(base64.b64encode(pix.pil_tobytes(format="PNG")).decode())
    doc.close()
    return images


def call_ollama(prompt: str, images_b64: list[str], model: str, base_url: str) -> str:
    """Send prompt + images to Ollama and return the raw response text."""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": images_b64,
            }
        ],
        "stream": False,
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
            return body["message"]["content"]
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Ollama at {base_url}: {e}") from e


def clean_json_response(text: str) -> str:
    """Strip markdown code fences if the model wrapped its JSON output."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Parse an EMS dispatch PDF using a local Gemma4 model via Ollama."
    )
    parser.add_argument("pdf", help="Path to the PDF file to parse")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--ollama-url",
        default=OLLAMA_DEFAULT_URL,
        help=f"Ollama base URL (default: {OLLAMA_DEFAULT_URL})",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw LLM response instead of parsed JSON",
    )
    parser.add_argument(
        "--vision-check",
        action="store_true",
        help="Send a simple 'describe this image' prompt to verify the model can see the PDF",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    if not PROMPT_FILE.exists():
        print(f"ERROR: Prompt file not found: {PROMPT_FILE}", file=sys.stderr)
        sys.exit(1)

    prompt = PROMPT_FILE.read_text()

    print(f"Converting PDF to images: {pdf_path.name}", file=sys.stderr)
    images_b64 = pdf_to_images_base64(pdf_path)
    print(f"  {len(images_b64)} page(s) extracted", file=sys.stderr)

    if args.vision_check:
        print("Vision check: asking model to describe the first page...", file=sys.stderr)
        description = call_ollama(
            "Describe exactly what text and fields you can see in this image. Be specific.",
            images_b64[:1],
            args.model,
            args.ollama_url,
        )
        print(description)
        return

    print(f"Sending to {args.model} via Ollama...", file=sys.stderr)
    raw_response = call_ollama(prompt, images_b64, args.model, args.ollama_url)

    if args.raw:
        print(raw_response)
        return

    cleaned = clean_json_response(raw_response)
    try:
        parsed = json.loads(cleaned)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError as e:
        print(f"WARNING: Could not parse response as JSON: {e}", file=sys.stderr)
        print(f"Raw response:\n{raw_response}")
        sys.exit(1)


if __name__ == "__main__":
    main()
