"""
Supabase Gateway - Interface for saving parsed PCR data to Supabase database
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SupabaseGateway:
    """
    Gateway class for interacting with Supabase database.

    Handles insertion and updating of parsed PCR data into the rip_and_runs table.
    """

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        """
        Initialize the Supabase gateway.

        Args:
            url: Supabase project URL. If None, will read from SUPABASE_URL env variable
            key: Supabase API key. If None, will read from SUPABASE_KEY env variable

        Raises:
            ValueError: If credentials are not provided and not found in environment
        """
        # Get credentials from parameters or environment
        self.url = url or os.getenv('SUPABASE_URL')
        self.key = key or os.getenv('SUPABASE_KEY')

        if not self.url:
            raise ValueError(
                "Supabase URL not found. Provide via url parameter or "
                "set SUPABASE_URL environment variable"
            )

        if not self.key:
            raise ValueError(
                "Supabase API key not found. Provide via key parameter or "
                "set SUPABASE_KEY environment variable"
            )

        # Initialize Supabase client
        try:
            self.client: Client = create_client(self.url, self.key)
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            raise

    def upsert_pcr_data(self, pcr_json: Dict[str, Any], unit_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Insert or update parsed PCR data in the rip_and_runs table.

        Uses upsert operation - if a record with the same (incident_number, unit_id)
        exists, it will be updated. Otherwise, a new record is inserted.

        Args:
            pcr_json: Parsed PCR data as returned by PCRParser
            unit_id: Unit identifier. If None, will extract from pcr_json['incidentTimes']['unit_dispatched']

        Returns:
            Dict containing:
                - success: bool indicating if operation succeeded
                - incident_number: the CAD/incident number
                - error: error message if success is False
        """
        try:
            # Extract unit_id from PCR data if not provided
            if unit_id is None:
                incident_times = pcr_json.get('incidentTimes', {})
                unit_id = incident_times.get('unit_dispatched')

                if not unit_id:
                    raise KeyError('incidentTimes.unit_dispatched not found and unit_id not provided')

            # Prepare the record for database insertion
            record = self._prepare_record(pcr_json, unit_id)

            logger.info(f"Upserting PCR data for incident {record['incident_number']}, unit {unit_id}")

            # Perform upsert operation
            response = self.client.table('rip_and_runs').upsert(record).execute()

            logger.info(f"Successfully upserted record for incident {record['incident_number']}")

            return {
                'success': True,
                'incident_number': record['incident_number'],
                'unit_id': unit_id
            }

        except KeyError as e:
            error_msg = f"Missing required field in PCR JSON: {e}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"Database operation failed: {e}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

    def _prepare_record(self, pcr_json: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
        """
        Transform PCR JSON to database record format.

        Args:
            pcr_json: Parsed PCR data
            unit_id: Unit identifier

        Returns:
            Dictionary with fields matching the rip_and_runs table schema

        Raises:
            KeyError: If required fields are missing from PCR JSON
        """
        # Extract incident times section
        incident_times = pcr_json.get('incidentTimes', {})

        # Extract incident_number (CAD number) - convert to integer
        cad = incident_times.get('cad')
        if cad is None:
            raise KeyError('incidentTimes.cad')

        # Convert CAD to integer (it might be a string)
        try:
            incident_number = int(cad)
        except (ValueError, TypeError):
            raise ValueError(f"CAD number '{cad}' cannot be converted to integer")

        # Extract times section
        times = incident_times.get('times', {})

        # Extract incident_date from notifiedByDispatch
        notified_by_dispatch = times.get('notifiedByDispatch', {})
        if not notified_by_dispatch:
            raise KeyError('incidentTimes.times.notifiedByDispatch')

        date_str = notified_by_dispatch.get('date')
        time_str = notified_by_dispatch.get('time')

        if not date_str or not time_str:
            raise KeyError('notifiedByDispatch.date or notifiedByDispatch.time')

        incident_date = self._parse_datetime(date_str, time_str)

        # Extract location (optional)
        incident_location = pcr_json.get('incidentLocation', {})
        location = incident_location.get('raw')

        # Truncate location to 300 characters if needed (database constraint)
        if location and len(location) > 300:
            location = location[:300]

        # Extract incident_type (optional)
        incident_type = incident_times.get('incident_type')

        # Truncate incident_type to 20 characters if needed (database constraint)
        if incident_type and len(incident_type) > 20:
            incident_type = incident_type[:20]

        # Serialize entire JSON to content field
        content = json.dumps(pcr_json)

        # Build the database record
        record = {
            'incident_number': incident_number,
            'unit_id': unit_id,
            'content': content,
            'incident_date': incident_date,
            'location': location,
            'incident_type': incident_type
        }

        return record

    def _parse_datetime(self, date_str: str, time_str: str) -> str:
        """
        Convert date and time strings to ISO 8601 timestamp.

        Args:
            date_str: Date in mm/dd/yyyy format
            time_str: Time in hh:mm:ss format

        Returns:
            ISO 8601 formatted timestamp string (e.g., "2025-12-08T14:30:00")

        Raises:
            ValueError: If date/time strings cannot be parsed
        """
        try:
            # Combine date and time strings
            datetime_str = f"{date_str} {time_str}"

            # Parse using strptime
            dt = datetime.strptime(datetime_str, "%m/%d/%Y %H:%M:%S")

            # Return ISO format (PostgreSQL accepts this)
            return dt.isoformat()

        except ValueError as e:
            raise ValueError(f"Failed to parse datetime '{date_str} {time_str}': {e}")


if __name__ == "__main__":
    # Example usage
    print("SupabaseGateway - Database interface for PCR data")
    print("\nUsage:")
    print("  from pcr_utils.supabase_gateway import SupabaseGateway")
    print("  gateway = SupabaseGateway()")
    print("  result = gateway.upsert_pcr_data(pcr_json, unit_id='MEDIC-1')")
