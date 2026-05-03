"""
Azure PCR Parser - Extracts incident data from EMS dispatch PDFs using Azure Document
Intelligence for OCR and OpenAI (text-only) for JSON parsing.

Two-stage pipeline:
  1. Azure Document Intelligence (prebuilt-layout) extracts text and tables directly
     from the PDF — no image conversion required.
  2. Extracted text is sent to OpenAI with the azure_pcr_parse_prompt.md prompt.
     Text-only tokens are far cheaper than vision tokens.

This module provides AzurePCRParser, a pure parsing class.
The polling service and CLI entry point live in pcr_service.py.
"""

import os
import json
import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class AzurePCRParser:
    """
    Extract structured data from EMS dispatch PDFs.

    Azure Document Intelligence handles OCR; OpenAI (text-only) handles
    semantic parsing into the required JSON schema.
    """

    def __init__(
        self,
        azure_endpoint: Optional[str] = None,
        azure_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        prompt_file: Optional[str] = None,
        prompt_text: Optional[str] = None,
    ):
        # Azure Document Intelligence client
        self.azure_endpoint = azure_endpoint or os.getenv('AZURE_DI_ENDPOINT')
        self.azure_key = azure_key or os.getenv('AZURE_DI_KEY')

        if not self.azure_endpoint:
            raise ValueError(
                "Azure DI endpoint not found. Provide via azure_endpoint parameter or "
                "set AZURE_DI_ENDPOINT environment variable"
            )
        if not self.azure_key:
            raise ValueError(
                "Azure DI key not found. Provide via azure_key parameter or "
                "set AZURE_DI_KEY environment variable"
            )

        self.di_client = DocumentAnalysisClient(
            endpoint=self.azure_endpoint,
            credential=AzureKeyCredential(self.azure_key),
        )

        # OpenAI client (text-only — no images sent)
        openai_key = openai_api_key or os.getenv('OPENAI_API_KEY')
        if not openai_key:
            raise ValueError(
                "OpenAI API key not found. Provide via openai_api_key parameter or "
                "set OPENAI_API_KEY environment variable"
            )
        self.openai_client = OpenAI(api_key=openai_key)

        # Prompt
        if prompt_text is not None:
            self.prompt = prompt_text
        else:
            if prompt_file is None:
                prompt_file = Path(__file__).parent / 'pcr_parse_prompt.md'
            self.prompt_file = Path(prompt_file)
            if not self.prompt_file.exists():
                raise FileNotFoundError(f"Prompt file not found: {self.prompt_file}")
            with open(self.prompt_file, 'r') as f:
                self.prompt = f.read()

    # ------------------------------------------------------------------
    # Azure DI extraction
    # ------------------------------------------------------------------

    def _format_table(self, table) -> str:
        """Render an Azure DI table object as a pipe-delimited text block."""
        grid: Dict[int, Dict[int, str]] = {}
        for cell in table.cells:
            grid.setdefault(cell.row_index, {})[cell.column_index] = cell.content or ''

        lines = []
        for row_idx in sorted(grid):
            row = grid[row_idx]
            max_col = max(row) + 1
            lines.append(' | '.join(row.get(c, '') for c in range(max_col)))

        return '\n'.join(lines)

    def _analyze_with_azure(self, pdf_path: Path) -> Tuple[str, Dict[str, List[float]]]:
        """
        Call Azure Document Intelligence once and return:
          - formatted text string (passed to OpenAI)
          - word confidence index: {lowercase_word: [confidence, ...]}
        """
        logger.info(f"Sending {pdf_path.name} to Azure Document Intelligence…")

        with open(pdf_path, 'rb') as f:
            poller = self.di_client.begin_analyze_document('prebuilt-layout', f)

        result = poller.result()

        # Build page-indexed text and table blocks
        page_text: Dict[int, List[str]] = {}
        for page in result.pages:
            pn = page.page_number
            page_text[pn] = [line.content for line in (page.lines or [])]

        page_tables: Dict[int, List[str]] = {}
        for table in (result.tables or []):
            regions = table.bounding_regions or []
            pn = regions[0].page_number if regions else 1
            page_tables.setdefault(pn, []).append(self._format_table(table))

        parts: List[str] = []
        all_pages = sorted(set(list(page_text) + list(page_tables)))
        for pn in all_pages:
            parts.append(f'--- Page {pn} ---')
            if pn in page_text:
                parts.append('\n'.join(page_text[pn]))
            for tbl in page_tables.get(pn, []):
                parts.append(f'\n[TABLE]\n{tbl}\n[/TABLE]')

        extracted = '\n'.join(parts)
        logger.info(f"  Extracted {len(extracted):,} characters across {len(all_pages)} page(s)")

        # Build word confidence index from all page words
        word_index: Dict[str, List[float]] = {}
        for page in result.pages:
            for word in (page.words or []):
                key = word.content.lower().strip()
                if key:
                    word_index.setdefault(key, []).append(word.confidence)

        return extracted, word_index

    def extract_document_content(self, pdf_path: str) -> str:
        """Return extracted text from Azure DI (public helper — text only)."""
        p = Path(pdf_path)
        if not p.exists():
            raise FileNotFoundError(f"PDF file not found: {p}")
        text, _ = self._analyze_with_azure(p)
        return text

    # ------------------------------------------------------------------
    # Azure DI word confidence helpers
    # ------------------------------------------------------------------

    def _field_azure_confidence(
        self, value: str, word_index: Dict[str, List[float]]
    ) -> Optional[float]:
        """
        Return the minimum Azure DI word confidence for the tokens in a field value.
        Returns None if no tokens could be matched in the word index.
        Min is used so the score reflects the weakest link in the OCR chain.
        """
        normalized = value.lower().strip()

        # Try the whole value first (e.g. a date like "12/08/2025" may be one word)
        if normalized in word_index:
            return round(min(word_index[normalized]), 3)

        # Otherwise split on whitespace and common delimiters
        tokens = [t for t in re.split(r'[\s/:.\-]+', normalized) if t]
        confidences: List[float] = []
        for token in tokens:
            if token in word_index:
                confidences.append(min(word_index[token]))

        return round(min(confidences), 3) if confidences else None

    def _compute_azure_field_confidence(
        self, parsed: Dict[str, Any], word_index: Dict[str, List[float]]
    ) -> Dict[str, Optional[float]]:
        """
        Walk the parsed result and compute Azure DI OCR confidence for each
        extracted field value.  Keys match the LLM confidence block.
        """
        conf: Dict[str, Optional[float]] = {}

        incident_times = parsed.get('incidentTimes', {})
        for field in ('cad', 'unit_dispatched', 'incident_type'):
            val = incident_times.get(field)
            if val is not None:
                conf[field] = self._field_azure_confidence(str(val), word_index)

        times = incident_times.get('times', {})
        for time_field, time_data in times.items():
            if isinstance(time_data, dict):
                combined = f"{time_data.get('date', '')} {time_data.get('time', '')}".strip()
                if combined:
                    conf[time_field] = self._field_azure_confidence(combined, word_index)

        location = parsed.get('incidentLocation', {})
        loc_key_map = {
            'raw': 'location_raw',
            'territory': 'territory',
            'location_name': 'location_name',
            'street_address': 'street_address',
            'apartment': 'apartment',
        }
        for json_key, conf_key in loc_key_map.items():
            val = location.get(json_key)
            if val is not None:
                conf[conf_key] = self._field_azure_confidence(str(val), word_index)

        return conf

    # ------------------------------------------------------------------
    # OpenAI text parsing
    # ------------------------------------------------------------------

    def parse_extracted_content(self, extracted_text: str, model: str = 'gpt-4o-mini') -> Dict[str, Any]:
        """Send extracted text + prompt to OpenAI (text-only) and return parsed JSON."""
        user_message = (
            f"{self.prompt}\n\n"
            "The following text was extracted from the EMS dispatch document by "
            "Azure Document Intelligence OCR:\n\n"
            f"{extracted_text}"
        )

        result_text = ''
        try:
            response = self.openai_client.chat.completions.create(
                model=model,
                messages=[{'role': 'user', 'content': user_message}],
                max_tokens=1500,
                temperature=0,
            )

            result_text = response.choices[0].message.content.strip()
            usage = response.usage
            token_info = {
                'prompt_tokens': usage.prompt_tokens,
                'completion_tokens': usage.completion_tokens,
                'total_tokens': usage.total_tokens,
            }

            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.startswith('```'):
                result_text = result_text[3:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            result_text = result_text.strip()

            parsed = json.loads(result_text)
            parsed['_token_usage'] = token_info
            return parsed

        except json.JSONDecodeError as e:
            return {'error': f'Failed to parse JSON response: {e}', 'raw_response': result_text}
        except Exception as e:
            return {'error': f'OpenAI call failed: {e}'}

    # ------------------------------------------------------------------
    # Combined pipeline
    # ------------------------------------------------------------------

    def parse_pdf(self, pdf_path: str, model: str = 'gpt-4o-mini') -> Dict[str, Any]:
        """Full pipeline: Azure DI OCR → OpenAI text parse → structured JSON + confidence."""
        p = Path(pdf_path)
        if not p.exists():
            return {'error': f'PDF file not found: {pdf_path}'}

        try:
            extracted_text, word_index = self._analyze_with_azure(p)
        except Exception as e:
            return {'error': f'Azure Document Intelligence failed: {e}'}

        result = self.parse_extracted_content(extracted_text, model=model)

        if 'error' not in result:
            result['_azure_confidence'] = self._compute_azure_field_confidence(result, word_index)

        return result

