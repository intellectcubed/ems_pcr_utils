"""
PCR Parser - Polling service to extract incident times from EMS dispatch documents using OpenAI Vision API
"""

import os
import json
import base64
import time
import signal
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import fitz  # PyMuPDF
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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


class PCRPollingService:
    """
    Polling service that monitors a directory for PDF files, processes them,
    saves to database, and removes the files.
    """

    def __init__(
        self,
        watch_dir: Optional[str] = None,
        poll_interval: Optional[int] = None
    ):
        """
        Initialize the polling service.

        Args:
            watch_dir: Directory to watch for PDF files. If None, reads from WATCH_DIR env variable
            poll_interval: Seconds between polls. If None, reads from POLL_INTERVAL_SECONDS env variable (default: 30)

        Raises:
            ValueError: If watch directory is not configured or doesn't exist
        """
        # Get watch directory from parameter or environment
        self.watch_dir = Path(watch_dir or os.getenv('WATCH_DIR', ''))
        if not self.watch_dir or str(self.watch_dir) == '':
            raise ValueError(
                "Watch directory not configured. Provide via watch_dir parameter or "
                "set WATCH_DIR environment variable"
            )

        if not self.watch_dir.exists():
            raise ValueError(f"Watch directory does not exist: {self.watch_dir}")

        if not self.watch_dir.is_dir():
            raise ValueError(f"Watch directory is not a directory: {self.watch_dir}")

        # Get poll interval
        self.poll_interval = poll_interval or int(os.getenv('POLL_INTERVAL_SECONDS', '30'))

        # Create error directory (sibling to watch directory)
        # e.g., if watch_dir is /data/watch, error_dir is /data/errors
        self.error_dir = self.watch_dir.parent / 'errors'
        self.error_dir.mkdir(exist_ok=True)

        # Initialize parser
        self.parser = PCRParser()

        # Flag for graceful shutdown
        self.running = False

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(f"PCR Polling Service initialized")
        logger.info(f"  Watch directory: {self.watch_dir}")
        logger.info(f"  Error directory: {self.error_dir}")
        logger.info(f"  Poll interval: {self.poll_interval} seconds")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def _get_pdf_files(self) -> list[Path]:
        """
        Get list of PDF files in watch directory, sorted by modification time (oldest first).

        Returns:
            List of Path objects for PDF files
        """
        pdf_files = list(self.watch_dir.glob('*.pdf'))
        # Sort by modification time (oldest first)
        pdf_files.sort(key=lambda p: p.stat().st_mtime)
        return pdf_files

    def _move_to_error_dir(self, pdf_path: Path, error_msg: str):
        """
        Move a PDF file to the error directory with timestamp and error info.

        Args:
            pdf_path: Path to the PDF file
            error_msg: Error message to save
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        error_filename = f"{pdf_path.stem}_{timestamp}{pdf_path.suffix}"
        error_path = self.error_dir / error_filename

        # Move the PDF
        pdf_path.rename(error_path)
        logger.info(f"  Moved to error directory: {error_path.name}")

        # Save error info
        error_info_path = error_path.with_suffix('.error.txt')
        with open(error_info_path, 'w') as f:
            f.write(f"Error occurred at: {datetime.now().isoformat()}\n")
            f.write(f"Original file: {pdf_path.name}\n")
            f.write(f"\nError message:\n{error_msg}\n")

    def _process_pdf(self, pdf_path: Path) -> bool:
        """
        Process a single PDF file: parse, save to database, and delete.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            True if processing succeeded, False otherwise
        """
        logger.info(f"Processing: {pdf_path.name}")

        try:
            # Parse the PDF
            result = self.parser.parse_pdf(str(pdf_path))

            # Check for parsing errors
            if 'error' in result:
                error_msg = result['error']
                logger.error(f"  Parse failed: {error_msg}")
                self._move_to_error_dir(pdf_path, error_msg)
                return False

            # Extract token usage for logging
            token_usage = result.pop("_token_usage", None)
            if token_usage:
                logger.info(f"  Tokens used: {token_usage['total_tokens']:,}")

            # Save to database
            try:
                # Try relative import first, then absolute import
                try:
                    from .supabase_gateway import SupabaseGateway
                except ImportError:
                    from supabase_gateway import SupabaseGateway

                gateway = SupabaseGateway()
                db_result = gateway.upsert_pcr_data(result)

                if db_result.get('success'):
                    logger.info(f"  Database saved: Incident {db_result.get('incident_number')}, Unit {db_result.get('unit_id')}")
                else:
                    error_msg = f"Database save failed: {db_result.get('error')}"
                    logger.error(f"  {error_msg}")
                    self._move_to_error_dir(pdf_path, error_msg)
                    return False

            except ImportError as e:
                error_msg = f"Import error: {e}\nInstall missing packages: pip install -r requirements.txt"
                logger.error(f"  {error_msg}")
                self._move_to_error_dir(pdf_path, error_msg)
                return False
            except ValueError as e:
                error_msg = f"Configuration error: {e}\nSet SUPABASE_URL and SUPABASE_KEY in .env file"
                logger.error(f"  {error_msg}")
                self._move_to_error_dir(pdf_path, error_msg)
                return False
            except Exception as e:
                error_msg = f"Unexpected database error: {e}"
                logger.error(f"  {error_msg}")
                self._move_to_error_dir(pdf_path, error_msg)
                return False

            # Success! Delete the PDF
            pdf_path.unlink()
            logger.info(f"  Deleted: {pdf_path.name}")
            return True

        except Exception as e:
            error_msg = f"Unexpected processing error: {e}"
            logger.error(f"  {error_msg}")
            self._move_to_error_dir(pdf_path, error_msg)
            return False

    def run(self):
        """
        Start the polling service. Runs until interrupted (Ctrl+C or SIGTERM).
        """
        self.running = True
        logger.info("PCR Polling Service started. Press Ctrl+C to stop.")

        while self.running:
            try:
                # Get PDF files in watch directory
                pdf_files = self._get_pdf_files()

                if pdf_files:
                    logger.info(f"Found {len(pdf_files)} PDF file(s) to process")
                    for pdf_file in pdf_files:
                        if not self.running:
                            break
                        self._process_pdf(pdf_file)
                else:
                    logger.debug(f"No PDF files found in {self.watch_dir}")

                # Sleep until next poll
                if self.running:
                    time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Unexpected error in polling loop: {e}", exc_info=True)
                # Continue running despite errors
                if self.running:
                    time.sleep(self.poll_interval)

        logger.info("PCR Polling Service stopped.")


if __name__ == "__main__":
    import argparse

    # Set up argument parser
    parser_args = argparse.ArgumentParser(
        description='PCR Polling Service - Monitor directory for PDF files and process them automatically'
    )
    parser_args.add_argument(
        '--watch-dir',
        default=None,
        help='Directory to watch for PDF files (default: from WATCH_DIR env variable)'
    )
    parser_args.add_argument(
        '--poll-interval',
        type=int,
        default=None,
        help='Seconds between directory polls (default: from POLL_INTERVAL_SECONDS env variable, or 30)'
    )

    args = parser_args.parse_args()

    try:
        # Create and start the polling service
        service = PCRPollingService(
            watch_dir=args.watch_dir,
            poll_interval=args.poll_interval
        )
        service.run()

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        exit(1)
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
        exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        exit(1)
