# PCR Utils

Utilities for creating and processing EMS Patient Care Reports (PCRs).

## Features

- **Rip-and-Run Reader**: Extract text from PDF rip-and-run documents using PyPDF2

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Reading a Rip-and-Run PDF

```python
from pcr_utils import RipAndRunReader

# Initialize the reader
reader = RipAndRunReader("path/to/document.pdf")

# Extract all text
full_text = reader.extract_all_text()
print(full_text)

# Extract text from a specific page
page_text = reader.extract_page_text(0)  # First page

# Get text from all pages as a list
pages = reader.get_pages_text()
for i, page in enumerate(pages):
    print(f"Page {i + 1}: {page}")

# Print all text to stdout
reader.print_all_text()
```

## Project Structure

```
pcr_utils/
├── src/
│   └── pcr_utils/
│       ├── __init__.py
│       └── rip_and_run.py
├── tests/
│   └── __init__.py
├── examples/
├── docs/
├── requirements.txt
└── README.md
```

## Development

### Running Tests

```bash
pytest tests/
```

## License

TBD

## Contributing

TBD
