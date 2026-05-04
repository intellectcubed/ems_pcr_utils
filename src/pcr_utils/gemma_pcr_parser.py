"""
Gemma PCR Parser - Parse PCR PDFs via Gemma (Ollama) and compare against Supabase records
"""

import json
import logging
import sys
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
import ollama
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GemmaPCRParser:
    """
    Parse EMS dispatch PDFs using a Gemma model via Ollama, then compare
    the extracted data against the corresponding Supabase record.
    """

    def __init__(self, model: str, prompt_file: Optional[str] = None):
        """
        Args:
            model: Ollama model name (e.g. "gemma3", "gemma3:27b")
            prompt_file: Path to prompt file; defaults to pcr_parse_prompt.md in this directory
        """
        self.model = model

        if prompt_file is None:
            prompt_file = Path(__file__).parent / 'pcr_parse_prompt.md'

        self.prompt_file = Path(prompt_file)
        if not self.prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {self.prompt_file}")

        with open(self.prompt_file, 'r') as f:
            self.prompt = f.read()

    # ------------------------------------------------------------------
    # PDF → image bytes
    # ------------------------------------------------------------------

    def pdf_to_images_bytes(self, pdf_path: str) -> List[bytes]:
        """Convert every page of a PDF to PNG bytes at 2× resolution."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        doc = fitz.open(str(pdf_path))
        images: List[bytes] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            images.append(pix.pil_tobytes(format="PNG"))

        doc.close()
        return images

    # ------------------------------------------------------------------
    # Gemma / Ollama call
    # ------------------------------------------------------------------

    def parse_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        Send the PDF (as page images) to Gemma via Ollama and return parsed JSON.

        Returns a dict with the parsed data, or one containing an "error" key on failure.
        """
        images = self.pdf_to_images_bytes(pdf_path)
        logger.info(f"Sending {len(images)} page(s) to {self.model} via Ollama…")

        raw_text = ""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': self.prompt,
                    'images': images,
                }]
            )
            raw_text = response['message']['content'].strip()

            # Strip optional markdown code fences
            if raw_text.startswith('```json'):
                raw_text = raw_text[7:]
            if raw_text.startswith('```'):
                raw_text = raw_text[3:]
            if raw_text.endswith('```'):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            return json.loads(raw_text)

        except json.JSONDecodeError as e:
            return {'error': f'Failed to parse JSON response: {e}', 'raw_response': raw_text}
        except Exception as e:
            return {'error': f'Ollama call failed: {e}'}

    # ------------------------------------------------------------------
    # Comparison helpers
    # ------------------------------------------------------------------

    def _flatten(self, obj: Any, prefix: str = '') -> Dict[str, str]:
        """Recursively flatten a nested structure to dotted key → str-value pairs."""
        items: Dict[str, str] = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                child = f"{prefix}.{k}" if prefix else k
                items.update(self._flatten(v, child))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                items.update(self._flatten(v, f"{prefix}[{i}]"))
        else:
            items[prefix] = str(obj) if obj is not None else ''
        return items

    _EXCLUDE_KEYS = {'_token_usage', 'parsingErrors'}

    def _scrub(self, d: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in d.items() if k not in self._EXCLUDE_KEYS}

    def compare(
        self,
        gemma_result: Dict[str, Any],
        db_content: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Field-by-field comparison of Gemma output vs database content."""
        gemma_flat = self._flatten(self._scrub(gemma_result))
        db_flat = self._flatten(self._scrub(db_content))
        all_keys = sorted(set(gemma_flat) | set(db_flat))

        matches: List[str] = []
        mismatches: List[Dict[str, Any]] = []
        only_gemma: List[Dict[str, Any]] = []
        only_db: List[Dict[str, Any]] = []

        for key in all_keys:
            in_g = key in gemma_flat
            in_d = key in db_flat

            if in_g and in_d:
                if gemma_flat[key] == db_flat[key]:
                    matches.append(key)
                else:
                    mismatches.append({
                        'field': key,
                        'gemma': gemma_flat[key],
                        'database': db_flat[key],
                    })
            elif in_g:
                only_gemma.append({'field': key, 'value': gemma_flat[key]})
            else:
                only_db.append({'field': key, 'value': db_flat[key]})

        return {
            'match_count': len(matches),
            'mismatch_count': len(mismatches),
            'only_in_gemma_count': len(only_gemma),
            'only_in_db_count': len(only_db),
            'matched_fields': matches,
            'mismatches': mismatches,
            'only_in_gemma': only_gemma,
            'only_in_db': only_db,
        }

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def run(self, pdf_path: str) -> int:
        """
        Full pipeline: parse → fetch from DB → compare → print report.

        Returns:
            0  all fields match
            1  one or more discrepancies found
            2  fatal error (parse failure, no DB record, etc.)
        """
        W = 60
        print(f"\n{'=' * W}")
        print(f"  Gemma PCR Parser")
        print(f"  Model : {self.model}")
        print(f"  PDF   : {pdf_path}")
        print(f"{'=' * W}\n")

        # --- Step 1: parse with Gemma ---
        print("Step 1: Parsing PDF with Gemma…")
        gemma_result = self.parse_pdf(pdf_path)

        if 'error' in gemma_result:
            print(f"  ERROR: {gemma_result['error']}")
            if 'raw_response' in gemma_result:
                print(f"  Raw response:\n{gemma_result['raw_response']}")
            return 2

        cad = gemma_result.get('incidentTimes', {}).get('cad')
        if not cad:
            print("  ERROR: Could not extract CAD/incident number from Gemma output")
            print(json.dumps(gemma_result, indent=2))
            return 2

        try:
            incident_number = int(cad)
        except (ValueError, TypeError):
            print(f"  ERROR: CAD '{cad}' is not a valid integer")
            return 2

        print(f"  Incident number : {incident_number}")
        if 'parsingErrors' in gemma_result:
            print(f"  Gemma parsing errors: {gemma_result['parsingErrors']}")

        # --- Step 2: fetch from Supabase ---
        print(f"\nStep 2: Fetching incident {incident_number} from Supabase…")
        try:
            from .supabase_gateway import SupabaseGateway

            gateway = SupabaseGateway()
            db_record = gateway.get_incident_by_number(incident_number)

        except ValueError as e:
            print(f"  ERROR: Supabase configuration error: {e}")
            return 2
        except Exception as e:
            print(f"  ERROR: Supabase connection failed: {e}")
            return 2

        if db_record is None:
            print(f"  No record found for incident {incident_number}")
            print("\n  Gemma parsed output:")
            print(json.dumps(gemma_result, indent=2))
            return 2

        content_str = db_record.get('content', '')
        if not content_str:
            print(f"  ERROR: Record for incident {incident_number} has an empty content column")
            return 2

        try:
            db_content = json.loads(content_str)
        except json.JSONDecodeError as e:
            print(f"  ERROR: Database content is not valid JSON: {e}")
            return 2

        print(f"  Record found for incident {incident_number}")

        # --- Step 3: compare ---
        print(f"\nStep 3: Comparing results…\n")
        cmp = self.compare(gemma_result, db_content)

        print(f"{'=' * W}")
        print("COMPARISON RESULTS")
        print(f"{'=' * W}")
        print(f"  Matched fields   : {cmp['match_count']}")
        print(f"  Mismatches       : {cmp['mismatch_count']}")
        print(f"  Only in Gemma    : {cmp['only_in_gemma_count']}")
        print(f"  Only in Database : {cmp['only_in_db_count']}")

        if cmp['mismatches']:
            print(f"\n  {'MISMATCHES':^56}")
            print(f"  {'-' * 56}")
            for m in cmp['mismatches']:
                print(f"  Field    : {m['field']}")
                print(f"  Gemma    : {m['gemma']}")
                print(f"  Database : {m['database']}")
                print()

        if cmp['only_in_gemma']:
            print(f"  {'ONLY IN GEMMA':^56}")
            print(f"  {'-' * 56}")
            for item in cmp['only_in_gemma']:
                print(f"  {item['field']}: {item['value']}")
            print()

        if cmp['only_in_db']:
            print(f"  {'ONLY IN DATABASE':^56}")
            print(f"  {'-' * 56}")
            for item in cmp['only_in_db']:
                print(f"  {item['field']}: {item['value']}")
            print()

        total_issues = cmp['mismatch_count'] + cmp['only_in_gemma_count'] + cmp['only_in_db_count']

        print(f"{'=' * W}")
        if total_issues == 0:
            print("RESULT: MATCH — all fields agree")
            print(f"{'=' * W}\n")
            return 0
        else:
            print(f"RESULT: {total_issues} DISCREPANCY/IES FOUND")
            print(f"{'=' * W}\n")
            return 1


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser(
        description='Parse a PCR PDF with Gemma (via Ollama) and compare against the Supabase record'
    )
    arg_parser.add_argument(
        'pdf',
        help='Path to the PCR PDF file'
    )
    arg_parser.add_argument(
        '--model',
        default='gemma3',
        help='Ollama model to use (default: gemma3). Examples: gemma3, gemma3:27b, gemma3:12b'
    )
    arg_parser.add_argument(
        '--prompt-file',
        default=None,
        help='Path to prompt file (default: pcr_parse_prompt.md in this directory)'
    )

    args = arg_parser.parse_args()

    try:
        parser = GemmaPCRParser(model=args.model, prompt_file=args.prompt_file)
        exit_code = parser.run(args.pdf)
        sys.exit(exit_code)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(2)
