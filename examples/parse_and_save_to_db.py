"""
Example script demonstrating how to parse a PCR PDF and save to Supabase database.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import pcr_utils
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from pcr_utils.pcr_parser import PCRParser
from pcr_utils.supabase_gateway import SupabaseGateway


def main():
    """
    Example usage of PCRParser with SupabaseGateway.

    Before running:
    1. Set the OPENAI_API_KEY environment variable
    2. Set the SUPABASE_URL environment variable
    3. Set the SUPABASE_KEY environment variable
    4. Update the pdf_path below to point to your PDF file
    """

    # Check if API keys are set
    if not os.getenv('OPENAI_API_KEY'):
        print("ERROR: OPENAI_API_KEY environment variable not set")
        print("\nSet it using:")
        print("  export OPENAI_API_KEY='your-api-key-here'")
        sys.exit(1)

    if not os.getenv('SUPABASE_URL') or not os.getenv('SUPABASE_KEY'):
        print("ERROR: SUPABASE_URL and/or SUPABASE_KEY environment variables not set")
        print("\nSet them using:")
        print("  export SUPABASE_URL='https://your-project.supabase.co'")
        print("  export SUPABASE_KEY='your-supabase-key-here'")
        sys.exit(1)

    # Path to your PDF file
    pdf_path = "/path/to/your/dispatch_document.pdf"

    # Check if file exists
    if not Path(pdf_path).exists():
        print(f"ERROR: PDF file not found: {pdf_path}")
        print("\nUpdate the pdf_path variable in this script to point to your PDF file")
        sys.exit(1)

    print(f"Parsing PDF: {pdf_path}")
    print("-" * 70)

    # Step 1: Parse the PDF
    parser = PCRParser()
    result = parser.parse_pdf(pdf_path)

    # Check for parsing errors
    if "error" in result:
        print("ERROR occurred during parsing:")
        print(result)
        sys.exit(1)

    print("Successfully parsed incident data")
    print()

    # Step 2: Save to Supabase database
    print("Saving to Supabase database...")
    gateway = SupabaseGateway()

    # unit_id will be automatically extracted from the parsed data (unit_dispatched)
    # You can also specify a custom unit_id if needed: unit_id="MEDIC-1"
    db_result = gateway.upsert_pcr_data(result)

    if db_result.get('success'):
        print("=" * 70)
        print("DATABASE SAVE: SUCCESS")
        print(f"  Incident Number: {db_result.get('incident_number')}")
        print(f"  Unit ID: {db_result.get('unit_id')}")
        print("=" * 70)
    else:
        print("=" * 70)
        print("DATABASE SAVE: FAILED")
        print(f"  Error: {db_result.get('error')}")
        print("=" * 70)
        sys.exit(1)

    # Step 3: Display parsed data
    print("\nParsed Incident Data:")
    print("-" * 70)

    if "incidentTimes" in result:
        incident_data = result["incidentTimes"]
        print(f"CAD Number: {incident_data.get('cad', 'N/A')}")

        if "times" in incident_data:
            times = incident_data["times"]
            print("\nTimeline:")
            for event, time_data in times.items():
                if isinstance(time_data, dict):
                    date = time_data.get('date', '')
                    time = time_data.get('time', '')
                    print(f"  {event}: {date} {time}")

    if "incidentLocation" in result:
        location = result["incidentLocation"]
        print(f"\nLocation: {location.get('raw', 'N/A')}")
        if location.get('territory'):
            print(f"  Territory: {location.get('territory')}")
        if location.get('location_name'):
            print(f"  Location Name: {location.get('location_name')}")
        if location.get('street_address'):
            print(f"  Street Address: {location.get('street_address')}")
        if location.get('apartment'):
            print(f"  Apartment: {location.get('apartment')}")


if __name__ == "__main__":
    main()
