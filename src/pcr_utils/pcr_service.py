"""
PCR Service - Unified polling service for processing EMS dispatch PDFs.

Select backend via PARSER_BACKEND environment variable or --backend flag:
  openai  OpenAI Vision API (default) — PDF sent as images to GPT-4o
  azure   Azure Document Intelligence + OpenAI text — better OCR, cheaper tokens

Normal mode   : parse → confidence report → write JSON → upload PDF → upsert Supabase → delete file
Validate mode : parse → confidence report → write JSON → compare vs existing Supabase record (read-only)
"""

import os
import json
import time
import signal
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

_DEFAULT_MODELS: Dict[str, str] = {
    'openai': 'gpt-4o',
    'azure': 'gpt-4o-mini',
}

# Chronological order used for time validation
_TIME_ORDER = [
    'notifiedByDispatch',
    'enRoute',
    'onScene',
    'arrivedAtPatient',
    'leftScene',
    'ptArrivedAtDestination',
    'destinationPatientTransferOfCare',
    'crewLeftDestination',
    'backInService',
]

# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

_EXCLUDE_KEYS = {'_token_usage', 'parsingErrors', 'confidence', '_azure_confidence'}


def _flatten(obj: Any, prefix: str = '') -> Dict[str, str]:
    items: Dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            child = f'{prefix}.{k}' if prefix else k
            items.update(_flatten(v, child))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            items.update(_flatten(v, f'{prefix}[{i}]'))
    else:
        items[prefix] = str(obj) if obj is not None else ''
    return items


def compare_results(parsed: Dict[str, Any], db_content: Dict[str, Any]) -> Dict[str, Any]:
    """Return a structured field-by-field diff between parsed output and database content."""
    def scrub(d):
        return {k: v for k, v in d.items() if k not in _EXCLUDE_KEYS}

    p_flat = _flatten(scrub(parsed))
    d_flat = _flatten(scrub(db_content))
    all_keys = sorted(set(p_flat) | set(d_flat))

    matches: List[str] = []
    mismatches: List[Dict[str, Any]] = []
    only_parsed: List[Dict[str, Any]] = []
    only_db: List[Dict[str, Any]] = []

    for key in all_keys:
        in_p, in_d = key in p_flat, key in d_flat
        if in_p and in_d:
            if p_flat[key] == d_flat[key]:
                matches.append(key)
            else:
                mismatches.append({'field': key, 'parsed': p_flat[key], 'database': d_flat[key]})
        elif in_p:
            only_parsed.append({'field': key, 'value': p_flat[key]})
        else:
            only_db.append({'field': key, 'value': d_flat[key]})

    return {
        'match_count': len(matches),
        'mismatch_count': len(mismatches),
        'only_in_parsed_count': len(only_parsed),
        'only_in_db_count': len(only_db),
        'matched_fields': matches,
        'mismatches': mismatches,
        'only_in_parsed': only_parsed,
        'only_in_db': only_db,
    }


def print_comparison(pdf_name: str, incident_number: int, cmp: Dict[str, Any]) -> None:
    W = 60
    print(f"\n{'=' * W}")
    print(f"  {pdf_name}  —  incident {incident_number}")
    print(f"{'=' * W}")
    print(f"  Matched fields   : {cmp['match_count']}")
    print(f"  Mismatches       : {cmp['mismatch_count']}")
    print(f"  Only in parsed   : {cmp['only_in_parsed_count']}")
    print(f"  Only in database : {cmp['only_in_db_count']}")

    if cmp['mismatches']:
        print(f"\n  {'MISMATCHES':^56}")
        print(f"  {'-' * 56}")
        for m in cmp['mismatches']:
            print(f"  Field    : {m['field']}")
            print(f"  Parsed   : {m['parsed']}")
            print(f"  Database : {m['database']}")
            print()

    if cmp['only_in_parsed']:
        print(f"  {'ONLY IN PARSED':^56}")
        print(f"  {'-' * 56}")
        for item in cmp['only_in_parsed']:
            print(f"  {item['field']}: {item['value']}")
        print()

    if cmp['only_in_db']:
        print(f"  {'ONLY IN DATABASE':^56}")
        print(f"  {'-' * 56}")
        for item in cmp['only_in_db']:
            print(f"  {item['field']}: {item['value']}")
        print()

    total_issues = cmp['mismatch_count'] + cmp['only_in_parsed_count'] + cmp['only_in_db_count']
    if total_issues == 0:
        print(f"  RESULT: MATCH — all fields agree")
    else:
        print(f"  RESULT: {total_issues} DISCREPANCY/IES FOUND")
    print(f"{'=' * W}")


# ---------------------------------------------------------------------------
# Unified polling service
# ---------------------------------------------------------------------------

class PCRPollingService:
    """
    Backend-agnostic polling service. Accepts any parser that implements:
        parse_pdf(pdf_path: str, model: str) -> dict

    Instantiate with a PCRParser (openai) or AzurePCRParser (azure) instance.
    """

    def __init__(
        self,
        parser: Any,
        backend: str = 'openai',
        watch_dir: Optional[str] = None,
        poll_interval: Optional[int] = None,
        model: Optional[str] = None,
        validate_existing: bool = False,
        output_dir: str = 'output',
        dry_run: bool = False,
        with_confidence: bool = False,
        max_retries: int = 3,
    ):
        self.parser = parser
        self.backend = backend
        self.model = model or _DEFAULT_MODELS.get(backend, 'gpt-4o')
        self.validate_existing = validate_existing
        self.dry_run = dry_run
        self.with_confidence = with_confidence
        self.max_retries = max_retries

        self.watch_dir = Path(watch_dir or os.getenv('WATCH_DIR', ''))
        if not self.watch_dir or str(self.watch_dir) == '':
            raise ValueError(
                "Watch directory not configured. Provide via --watch-dir or "
                "set WATCH_DIR environment variable"
            )
        if not self.watch_dir.exists():
            raise ValueError(f"Watch directory does not exist: {self.watch_dir}")
        if not self.watch_dir.is_dir():
            raise ValueError(f"Watch directory is not a directory: {self.watch_dir}")

        self.poll_interval = poll_interval or int(os.getenv('POLL_INTERVAL_SECONDS', '30'))

        self.error_dir = self.watch_dir.parent / 'errors'
        self.error_dir.mkdir(exist_ok=True)

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.running = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if validate_existing:
            mode = 'VALIDATE (read-only)'
        elif dry_run:
            mode = 'DRY RUN (no DB write, no PDF upload)'
        else:
            mode = 'NORMAL (upsert)'
        logger.info("PCR Service initialized")
        logger.info(f"  Backend         : {backend}")
        logger.info(f"  Model           : {self.model}")
        logger.info(f"  Mode            : {mode}")
        logger.info(f"  Watch directory : {self.watch_dir}")
        logger.info(f"  Error directory : {self.error_dir}")
        logger.info(f"  Output directory: {self.output_dir}")
        logger.info(f"  Poll interval   : {self.poll_interval}s")

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully…")
        self.running = False

    def _get_pdf_files(self) -> List[Path]:
        pdf_files = list(self.watch_dir.glob('*.pdf'))
        pdf_files.sort(key=lambda p: p.stat().st_mtime)
        return pdf_files

    def _move_to_error_dir(self, pdf_path: Path, error_msg: str):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        error_path = self.error_dir / f'{pdf_path.stem}_{timestamp}{pdf_path.suffix}'
        pdf_path.rename(error_path)
        logger.info(f"  Moved to error directory: {error_path.name}")
        with open(error_path.with_suffix('.error.txt'), 'w') as f:
            f.write(f"Error occurred at: {datetime.now().isoformat()}\n")
            f.write(f"Original file: {pdf_path.name}\n")
            f.write(f"\nError message:\n{error_msg}\n")

    def _get_gateway(self):
        try:
            from .supabase_gateway import SupabaseGateway
        except ImportError:
            from supabase_gateway import SupabaseGateway
        return SupabaseGateway()

    def _add_minutes(self, time_dict: Dict[str, str], minutes: int) -> Dict[str, str]:
        from datetime import timedelta
        dt = datetime.strptime(f"{time_dict['date']} {time_dict['time']}", '%m/%d/%Y %H:%M:%S')
        dt += timedelta(minutes=minutes)
        return {'date': dt.strftime('%m/%d/%Y'), 'time': dt.strftime('%H:%M:%S')}

    def _post_process_result(self, result: Dict[str, Any]) -> int:
        """
        Mutates result in place. Handles:
        - Pops and logs _token_usage
        - Strips _azure_confidence when with_confidence is False
        - Applies Python-side calculated fields (arrivedAtPatient, destinationPatientTransferOfCare)
          as a fallback when the LLM omits them

        Returns total token count (0 if not present).
        """
        token_usage = result.pop('_token_usage', None)
        total_tokens = 0
        if token_usage:
            total_tokens = token_usage.get('total_tokens', 0)
            logger.info(
                f"  Tokens — prompt: {token_usage.get('prompt_tokens', 0):,}  "
                f"completion: {token_usage.get('completion_tokens', 0):,}  "
                f"total: {total_tokens:,}"
            )

        if not self.with_confidence:
            result.pop('_azure_confidence', None)

        # Calculated fields fallback + sort times into canonical order
        incident_times = result.get('incidentTimes', {})
        times = incident_times.get('times', {})
        try:
            if 'onScene' in times and 'arrivedAtPatient' not in times:
                times['arrivedAtPatient'] = self._add_minutes(times['onScene'], 2)
                logger.info("  arrivedAtPatient calculated (onScene + 2 min)")
            if 'ptArrivedAtDestination' in times and 'destinationPatientTransferOfCare' not in times:
                times['destinationPatientTransferOfCare'] = self._add_minutes(times['ptArrivedAtDestination'], 5)
                logger.info("  destinationPatientTransferOfCare calculated (ptArrivedAtDestination + 5 min)")
        except Exception as e:
            logger.warning(f"  Could not apply calculated fields: {e}")

        # Remove spurious hospital-transport fields when there is no hospital evidence.
        # leftScene must come from an explicit TO HOSP row; if neither ptArrivedAtDestination
        # nor crewLeftDestination is present, the unit did not transport — strip leftScene.
        hospital_evidence = {'ptArrivedAtDestination', 'crewLeftDestination'}
        if 'leftScene' in times and not hospital_evidence.intersection(times):
            del times['leftScene']
            logger.info("  Removed spurious leftScene — no hospital transport evidence")

        # Reorder times keys into canonical order (unknown keys appended at end)
        known = {k: times[k] for k in _TIME_ORDER if k in times}
        unknown = {k: v for k, v in times.items() if k not in _TIME_ORDER}
        incident_times['times'] = {**known, **unknown}

        return total_tokens

    def _validate_result(self, result: Dict[str, Any]) -> List[str]:
        """
        Validate the parsed result. Returns a list of error strings; empty means valid.

        Checks:
        - All timestamps parse cleanly
        - Times are in chronological order across the expected sequence
        - Dates span at most 2 calendar days (single midnight crossing allowed)
        """
        errors: List[str] = []
        times = result.get('incidentTimes', {}).get('times', {})

        # Parse all present timestamps into datetime objects
        parsed: Dict[str, datetime] = {}
        for field in _TIME_ORDER:
            t = times.get(field)
            if t and t.get('date') and t.get('time'):
                try:
                    parsed[field] = datetime.strptime(
                        f"{t['date']} {t['time']}", '%m/%d/%Y %H:%M:%S'
                    )
                except ValueError as e:
                    errors.append(f"{field}: unparseable date/time — {e}")

        present = [(f, parsed[f]) for f in _TIME_ORDER if f in parsed]

        # Chronological order check
        for i in range(len(present) - 1):
            fname, fdt = present[i]
            nname, ndt = present[i + 1]
            if fdt > ndt:
                errors.append(
                    f"Out-of-order: {fname} ({fdt.strftime('%m/%d/%Y %H:%M:%S')}) "
                    f"is after {nname} ({ndt.strftime('%m/%d/%Y %H:%M:%S')})"
                )

        # Date consistency check: at most 2 calendar dates (one midnight crossing)
        if present:
            unique_dates = sorted({dt.date() for _, dt in present})
            if len(unique_dates) > 2:
                errors.append(
                    f"Timestamps span {len(unique_dates)} calendar dates "
                    f"({unique_dates[0]} → {unique_dates[-1]}); expected at most 2"
                )
            for i in range(len(unique_dates) - 1):
                gap = (unique_dates[i + 1] - unique_dates[i]).days
                if gap > 1:
                    errors.append(
                        f"Date gap of {gap} days between {unique_dates[i]} and {unique_dates[i + 1]}"
                    )

        return errors

    def _parse_with_retry(self, pdf_path: Path) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """
        Parse a PDF, applying post-processing and validation after each attempt.
        Retries up to self.max_retries times on validation failure.

        Returns (result, errors):
          - (result, [])          — success; result is valid
          - (result, [errors...]) — retries exhausted but a result exists; proceed with warning
          - (None,   [errors...]) — LLM failed to produce any JSON at all; cannot proceed
        """
        last_result: Optional[Dict[str, Any]] = None
        last_errors: List[str] = []

        for attempt in range(1, self.max_retries + 1):
            if attempt > 1:
                logger.info(f"  Retry attempt {attempt}/{self.max_retries}…")

            result = self.parser.parse_pdf(str(pdf_path), model=self.model)

            if 'error' in result:
                logger.error(f"  Parse error (attempt {attempt}): {result['error']}")
                last_errors = [result['error']]
                continue

            self._post_process_result(result)

            errors = self._validate_result(result)
            if not errors:
                if attempt > 1:
                    logger.info(f"  Validation passed on attempt {attempt}")
                return result, []

            last_result = result
            last_errors = errors
            logger.warning(f"  Validation failed (attempt {attempt}/{self.max_retries}):")
            for err in errors:
                logger.warning(f"    - {err}")

        if last_result is not None:
            logger.warning(
                f"  Proceeding with best available result after {self.max_retries} attempt(s) — "
                f"{len(last_errors)} validation issue(s) will be recorded"
            )
            return last_result, last_errors

        logger.error(f"  LLM failed to produce a usable result after {self.max_retries} attempt(s)")
        return None, last_errors

    def _print_confidence_report(self, result: Dict[str, Any]) -> None:
        """Print LLM + Azure DI confidence side-by-side. No-op if no confidence data present."""
        llm_conf: Dict[str, str] = result.get('confidence', {})
        azure_conf: Dict[str, Any] = result.get('_azure_confidence', {})

        all_fields = sorted(set(list(llm_conf) + list(azure_conf)))
        if not all_fields:
            return

        col1, col2, col3 = 32, 10, 12
        print(f"\n  CONFIDENCE REPORT")
        print(f"  {'Field':<{col1}} {'LLM':<{col2}} {'Azure DI OCR':<{col3}}")
        print(f"  {'-' * col1} {'-' * col2} {'-' * col3}")
        for field in all_fields:
            llm = llm_conf.get(field, '—')
            az = azure_conf.get(field)
            az_str = f'{az:.3f}' if az is not None else '—'
            print(f"  {field:<{col1}} {llm:<{col2}} {az_str:<{col3}}")
        print()

    def _write_output(self, pdf_path: Path, result: Dict[str, Any]) -> None:
        epoch = int(datetime.now().timestamp())
        model_dir = self.output_dir / f'{self.backend}_{self.model}'
        model_dir.mkdir(parents=True, exist_ok=True)
        out_path = model_dir / f'{pdf_path.stem}_{epoch}.json'
        with open(out_path, 'w') as f:
            json.dump(result, f, indent=2)
        logger.info(f"  Written to: {out_path}")

    # ------------------------------------------------------------------
    # Normal processing
    # ------------------------------------------------------------------

    def _process_pdf_normal(self, pdf_path: Path) -> bool:
        logger.info(f"Processing: {pdf_path.name}")
        try:
            result, validation_errors = self._parse_with_retry(pdf_path)

            if result is None:
                error_msg = f"LLM failed to produce usable JSON after {self.max_retries} attempt(s)"
                self._move_to_error_dir(pdf_path, error_msg)
                return False

            parse_errors_str = '\n'.join(validation_errors) if validation_errors else None

            self._print_confidence_report(result)
            self._write_output(pdf_path, result)

            if self.dry_run:
                logger.info("  Dry run — skipping PDF upload and database write")
                pdf_path.unlink()
                logger.info(f"  Deleted: {pdf_path.name}")
                return True

            try:
                gateway = self._get_gateway()

                cad = result.get('incidentTimes', {}).get('cad')
                pdf_url = None
                if cad:
                    try:
                        pdf_url = gateway.upload_pdf(str(pdf_path), int(cad))
                    except Exception as e:
                        logger.warning(f"  PDF upload skipped: {e}")

                db_result = gateway.upsert_pcr_data(result, pdf_url=pdf_url, parse_errors=parse_errors_str)

                if db_result.get('success'):
                    logger.info(
                        f"  Database saved: Incident {db_result.get('incident_number')}, "
                        f"Unit {db_result.get('unit_id')}"
                    )
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

            pdf_path.unlink()
            logger.info(f"  Deleted: {pdf_path.name}")
            return True

        except Exception as e:
            error_msg = f"Unexpected processing error: {e}"
            logger.error(f"  {error_msg}")
            self._move_to_error_dir(pdf_path, error_msg)
            return False

    # ------------------------------------------------------------------
    # Validate processing (read-only)
    # ------------------------------------------------------------------

    def _process_pdf_validate(self, pdf_path: Path) -> bool:
        logger.info(f"Validating: {pdf_path.name}")
        try:
            result, validation_errors = self._parse_with_retry(pdf_path)

            if result is None:
                logger.error(f"  LLM failed to produce usable JSON after {self.max_retries} attempt(s)")
                return False

            if validation_errors:
                logger.warning(f"  Proceeding with {len(validation_errors)} unresolved validation issue(s)")

            self._print_confidence_report(result)
            self._write_output(pdf_path, result)

            cad = result.get('incidentTimes', {}).get('cad')
            if not cad:
                logger.error("  Could not extract CAD number from parsed result")
                return False

            try:
                incident_number = int(cad)
            except (ValueError, TypeError):
                logger.error(f"  CAD '{cad}' is not a valid integer")
                return False

            try:
                gateway = self._get_gateway()
                db_record = gateway.get_incident_by_number(incident_number)
            except ImportError as e:
                logger.error(f"  Import error: {e}")
                return False
            except ValueError as e:
                logger.error(f"  Supabase configuration error: {e}")
                return False
            except Exception as e:
                logger.error(f"  Supabase error: {e}")
                return False

            if db_record is None:
                logger.warning(f"  No Supabase record found for incident {incident_number}")
                return False

            content_str = db_record.get('content', '')
            if not content_str:
                logger.error(f"  Supabase record for incident {incident_number} has empty content")
                return False

            try:
                db_content = json.loads(content_str)
            except json.JSONDecodeError as e:
                logger.error(f"  Supabase content is not valid JSON: {e}")
                return False

            cmp = compare_results(result, db_content)
            print_comparison(pdf_path.name, incident_number, cmp)
            return cmp['mismatch_count'] == 0

        except Exception as e:
            logger.error(f"  Unexpected error: {e}")
            return False

    # ------------------------------------------------------------------
    # Dispatch and run loop
    # ------------------------------------------------------------------

    def _process_pdf(self, pdf_path: Path) -> bool:
        if self.validate_existing:
            return self._process_pdf_validate(pdf_path)
        return self._process_pdf_normal(pdf_path)

    def run(self):
        self.running = True
        mode = 'validate' if self.validate_existing else 'normal'
        logger.info(
            f"PCR Service started ({self.backend} backend, {mode} mode). "
            "Press Ctrl+C to stop."
        )

        while self.running:
            try:
                pdf_files = self._get_pdf_files()
                if pdf_files:
                    logger.info(f"Found {len(pdf_files)} PDF file(s) to process")
                    for pdf_file in pdf_files:
                        if not self.running:
                            break
                        self._process_pdf(pdf_file)
                else:
                    logger.debug(f"No PDF files found in {self.watch_dir}")

                if self.running:
                    time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Unexpected error in polling loop: {e}", exc_info=True)
                if self.running:
                    time.sleep(self.poll_interval)

        logger.info("PCR Service stopped.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    arg_parser = argparse.ArgumentParser(
        description=(
            'PCR Service — monitor a directory for EMS dispatch PDFs and process them.\n'
            '\n'
            'Normal mode   : parse → write JSON → upload PDF → upsert Supabase → delete file\n'
            'Validate mode : parse → write JSON → compare vs existing Supabase record (read-only)\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    arg_parser.add_argument(
        '--backend',
        default=None,
        choices=['openai', 'azure'],
        help='Parser backend (default: PARSER_BACKEND env variable, or openai)'
    )
    arg_parser.add_argument(
        '--watch-dir',
        default=None,
        help='Directory to watch for PDF files (default: WATCH_DIR env variable)'
    )
    arg_parser.add_argument(
        '--poll-interval',
        type=int,
        default=None,
        help='Seconds between polls (default: POLL_INTERVAL_SECONDS env variable, or 30)'
    )
    arg_parser.add_argument(
        '--model',
        default=None,
        help='Model override. openai default: gpt-4o  azure default: gpt-4o-mini'
    )
    arg_parser.add_argument(
        '--validate_existing',
        action='store_true',
        help='Read-only mode: compare fresh parse against existing Supabase record'
    )
    arg_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Parse and write JSON output, but skip PDF upload and database write. File is still deleted after processing.'
    )
    arg_parser.add_argument(
        '--with-confidence',
        action='store_true',
        help='Append confidence rating instructions to the prompt, adding a per-field confidence object to the JSON output. Can also set WITH_CONFIDENCE=true in .env'
    )
    arg_parser.add_argument(
        '--max-retries',
        type=int,
        default=None,
        help='Max LLM retry attempts when validation fails (default: MAX_PARSE_RETRIES env var, or 3)'
    )
    arg_parser.add_argument(
        '--output-dir',
        default='output',
        help='Directory to write parsed JSON files (default: output)'
    )

    args = arg_parser.parse_args()
    backend = args.backend or os.getenv('PARSER_BACKEND', 'openai')
    with_confidence = args.with_confidence or os.getenv('WITH_CONFIDENCE', '').lower() in ('1', 'true', 'yes')

    # Build prompt text, optionally appending the confidence section
    _here = Path(__file__).parent
    with open(_here / 'pcr_parse_prompt.md', 'r') as f:
        prompt_text = f.read()
    if with_confidence:
        with open(_here / 'pcr_confidence_prompt.md', 'r') as f:
            prompt_text += '\n\n' + f.read()

    try:
        if backend == 'azure':
            try:
                from azure_pcr_parser import AzurePCRParser
            except ImportError:
                from pcr_utils.azure_pcr_parser import AzurePCRParser
            parser = AzurePCRParser(prompt_text=prompt_text)
        else:
            try:
                from pcr_parser import PCRParser
            except ImportError:
                from pcr_utils.pcr_parser import PCRParser
            parser = PCRParser(prompt_text=prompt_text)
    except Exception as e:
        logger.error(f"Failed to initialize {backend} parser: {e}")
        exit(1)

    try:
        max_retries = args.max_retries or int(os.getenv('MAX_PARSE_RETRIES', '3'))

        service = PCRPollingService(
            parser=parser,
            backend=backend,
            watch_dir=args.watch_dir,
            poll_interval=args.poll_interval,
            model=args.model,
            validate_existing=args.validate_existing,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            with_confidence=with_confidence,
            max_retries=max_retries,
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
