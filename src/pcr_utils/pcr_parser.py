"""
PCR Parser - Extract incident times from EMS dispatch documents using OpenAI Vision API
"""

import os
import json
import base64
from pathlib import Path
from typing import Dict, Any, Optional
import fitz  # PyMuPDF
from openai import OpenAI


class PCRParser:
    """
    Parser for extracting structured data from EMS dispatch PDF documents.

    Uses OpenAI's Vision API to analyze scanned/image-based PDF documents
    and extract incident times and other critical information.
    """

    def __init__(self, api_key: Optional[str] = None, prompt_file: Optional[str] = None):
        """
        Initialize the PCR Parser.

        Args:
            api_key: OpenAI API key. If None, will read from OPENAI_API_KEY env variable
            prompt_file: Path to the prompt file. If None, uses default prompt file

        Raises:
            ValueError: If API key is not provided and not found in environment
        """
        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found. Provide via api_key parameter or "
                "set OPENAI_API_KEY environment variable"
            )

        # Initialize OpenAI client
        self.client = OpenAI(api_key=self.api_key)

        # Load prompt
        if prompt_file is None:
            # Default to prompt file in same directory as this script
            prompt_file = Path(__file__).parent / 'pcr_parse_prompt.md'

        self.prompt_file = Path(prompt_file)
        if not self.prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        with open(self.prompt_file, 'r') as f:
            self.prompt = f.read()

    def pdf_to_images_base64(self, pdf_path: str) -> list[str]:
        """
        Convert PDF pages to base64-encoded PNG images.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of base64-encoded image strings

        Raises:
            FileNotFoundError: If PDF file doesn't exist
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        doc = fitz.open(str(pdf_path))
        images_base64 = []

        for page_num in range(len(doc)):
            # Get page
            page = doc[page_num]

            # Render page to image at 2x resolution for better OCR
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PNG bytes
            img_bytes = pix.pil_tobytes(format="PNG")

            # Encode to base64
            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
            images_base64.append(img_base64)

        doc.close()
        return images_base64

    def parse_pdf(self, pdf_path: str, model: str = "gpt-4o") -> Dict[str, Any]:
        """
        Parse a PDF document and extract incident times.

        Args:
            pdf_path: Path to the PDF file to parse
            model: OpenAI model to use (default: gpt-4o for vision support)

        Returns:
            Dictionary containing parsed incident data or error information

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            Exception: If API call fails
        """
        # Convert PDF to images
        images_base64 = self.pdf_to_images_base64(pdf_path)

        # Build messages with images
        # For multi-page documents, we'll send the first page (typically contains all needed info)
        # If needed, can be extended to handle multiple pages
        content = [
            {
                "type": "text",
                "text": self.prompt
            }
        ]

        # Add all pages as images (in case data spans multiple pages)
        for img_b64 in images_base64:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_b64}",
                    "detail": "high"
                }
            })

        # Call OpenAI API
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                max_tokens=1000,
                temperature=0  # Use 0 for deterministic outputs
            )

            # Extract response
            result_text = response.choices[0].message.content

            # Get token usage information
            usage = response.usage
            token_info = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens
            }

            # Parse JSON from response
            # The model should return pure JSON, but handle cases where it adds explanation
            result_text = result_text.strip()

            # Try to find JSON in the response
            if result_text.startswith('```json'):
                # Remove markdown code blocks
                result_text = result_text.replace('```json', '').replace('```', '').strip()
            elif result_text.startswith('```'):
                result_text = result_text.replace('```', '').strip()

            parsed_data = json.loads(result_text)

            # Add token usage to the response
            parsed_data["_token_usage"] = token_info

            return parsed_data

        except json.JSONDecodeError as e:
            return {
                "error": f"Failed to parse JSON response: {str(e)}",
                "raw_response": result_text
            }
        except Exception as e:
            return {
                "error": f"API call failed: {str(e)}"
            }

    def parse_pdf_to_json_string(self, pdf_path: str, model: str = "gpt-4o", indent: int = 2) -> str:
        """
        Parse a PDF and return the result as a formatted JSON string.

        Args:
            pdf_path: Path to the PDF file to parse
            model: OpenAI model to use
            indent: JSON indentation level

        Returns:
            Formatted JSON string
        """
        result = self.parse_pdf(pdf_path, model)
        return json.dumps(result, indent=indent)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pcr_parser.py <pdf_file_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    # Create parser (will use OPENAI_API_KEY from environment)
    parser = PCRParser()

    # Parse the PDF
    result = parser.parse_pdf(pdf_path)

    # Extract token usage before saving/printing
    token_usage = result.pop("_token_usage", None)

    # Determine output JSON file path (same name as PDF but with .json extension)
    pdf_path_obj = Path(pdf_path)
    json_output_path = pdf_path_obj.with_suffix('.json')

    # Save to JSON file
    with open(json_output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Saved JSON output to: {json_output_path}")
    print()

    # Print result to console
    print(json.dumps(result, indent=2))

    # Print token usage at the end
    if token_usage:
        print("\n" + "="*50)
        print("TOKEN USAGE:")
        print(f"  Prompt tokens:     {token_usage['prompt_tokens']:,}")
        print(f"  Completion tokens: {token_usage['completion_tokens']:,}")
        print(f"  Total tokens:      {token_usage['total_tokens']:,}")
        print("="*50)
