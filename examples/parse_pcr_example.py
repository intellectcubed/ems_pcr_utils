"""
Example script demonstrating how to use the PCR Parser to extract
incident times from EMS dispatch PDF documents.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import pcr_utils
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from pcr_utils.pcr_parser import PCRParser


def main():
    """
    Example usage of PCRParser.

    Before running:
    1. Set the OPENAI_API_KEY environment variable
    2. Update the pdf_path below to point to your PDF file
    """

    # Check if API key is set
    if not os.getenv('OPENAI_API_KEY'):
        print("ERROR: OPENAI_API_KEY environment variable not set")
        print("\nSet it using:")
        print("  export OPENAI_API_KEY='your-api-key-here'")
        sys.exit(1)

    # Path to your PDF file
    pdf_path = "/path/to/your/dispatch_document.pdf"

    # Check if file exists
    if not Path(pdf_path).exists():
        print(f"ERROR: PDF file not found: {pdf_path}")
        print("\nUpdate the pdf_path variable in this script to point to your PDF file")
        sys.exit(1)

    print(f"Parsing PDF: {pdf_path}")
    print("-" * 50)

    # Create parser instance
    # API key will be read from OPENAI_API_KEY environment variable
    parser = PCRParser()

    # Parse the PDF
    result = parser.parse_pdf(pdf_path)

    # Display results
    if "error" in result:
        print("ERROR occurred during parsing:")
        print(result)
    else:
        print("Successfully parsed incident data:")
        print()

        # Pretty print the results
        import json
        print(json.dumps(result, indent=2))

        # Access specific fields
        if "incidentTimes" in result:
            incident_data = result["incidentTimes"]

            print("\n" + "=" * 50)
            print("SUMMARY")
            print("=" * 50)

            print(f"CAD Number: {incident_data.get('cad', 'N/A')}")

            if "times" in incident_data:
                times = incident_data["times"]

                print("\nTimeline:")
                for event, time_data in times.items():
                    if isinstance(time_data, dict):
                        date = time_data.get('date', '')
                        time = time_data.get('time', '')
                        print(f"  {event}: {date} {time}")


if __name__ == "__main__":
    main()
