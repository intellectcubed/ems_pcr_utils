"""
Example script for reading a rip-and-run PDF document
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pcr_utils import RipAndRunReader


def main():
    """Main example function"""
    # Replace with your PDF file path
    pdf_path = "document.pdf"

    try:
        # Initialize the reader
        reader = RipAndRunReader(pdf_path)

        print(f"PDF has {reader.num_pages} page(s)\n")

        # Method 1: Print all text at once
        print("=== Method 1: Extract all text ===")
        full_text = reader.extract_all_text()
        print(full_text)
        print("\n")

        # Method 2: Iterate through pages
        print("=== Method 2: Iterate through pages ===")
        for i in range(reader.num_pages):
            page_text = reader.extract_page_text(i)
            print(f"--- Page {i + 1} ---")
            print(page_text)
            print()

        # Method 3: Using the convenience print method
        print("=== Method 3: Using print_all_text() ===")
        reader.print_all_text()

    except FileNotFoundError as e:
        print(f"Error: {e}")
        print(f"Please provide a valid PDF file path")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
