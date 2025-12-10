# Supabase Integration Requirement

## Overview
Integrate Supabase database storage for parsed PCR (Patient Care Report) data. Currently, `pcr_parser.py` processes EMS dispatch PDFs and outputs JSON to files. This enhancement will also persist the parsed data to a Supabase database.

## Current State

### PCR Parser (`pcr_parser.py`)
- **Input**: EMS dispatch PDF documents (rip-and-run sheets)
- **Processing**: Uses OpenAI Vision API to extract structured data
- **Output**:
  - JSON file saved alongside PDF (e.g., `document.pdf` → `document.json`)
  - Console output of parsed data

### JSON Output Structure
The parser produces JSON with this structure:
```json
{
  "incidentTimes": {
    "cad": "string",
    "times": {
      "notifiedByDispatch": {"date": "mm/dd/yyyy", "time": "hh:mm:ss"},
      "enRoute": {"date": "mm/dd/yyyy", "time": "hh:mm:ss"},
      "onScene": {"date": "mm/dd/yyyy", "time": "hh:mm:ss"},
      "arrivedAtPatient": {"date": "mm/dd/yyyy", "time": "hh:mm:ss"},
      "leftScene": {"date": "mm/dd/yyyy", "time": "hh:mm:ss"},
      "ptArrivedAtDestination": {"date": "mm/dd/yyyy", "time": "hh:mm:ss"},
      "destinationPatientTransferOfCare": {"date": "mm/dd/yyyy", "time": "hh:mm:ss"},
      "backInService": {"date": "mm/dd/yyyy", "time": "hh:mm:ss"}
    }
  },
  "incidentLocation": {
    "raw": "string",
    "territory": "string",
    "location_name": "string",
    "street_address": "string",
    "apartment": "string"
  },
  "parsingErrors": [
    {"field": "string", "error": "description"}
  ]
}
```

## Required Changes

### 1. Database Table Schema
**File**: `src/pcr_utils/supabase/rip_and_runs.sql`

**Status**: Table already exists in Supabase

Schema:
```sql
create table public.rip_and_runs (
  incident_number   bigint        not null,
  unit_id           text          not null,
  created_date      timestamptz   not null default now(),
  content           text          not null,
  incident_date     timestamptz   not null,
  location          varchar(300),
  incident_type     varchar(20),

  constraint rip_and_runs_pkey primary key (incident_number, unit_id)
);
```

**Column Mapping**:
- `incident_number`: Maps to `incidentTimes.cad` (CAD number)
- `unit_id`: **Needs clarification** - not in current PCR JSON structure
- `content`: Full parsed JSON as TEXT (JSON.dumps)
- `incident_date`: Extract from `incidentTimes.times.notifiedByDispatch`
- `location`: Maps to `incidentLocation.raw`
- `incident_type`: **Needs clarification** - not in current PCR JSON structure

### 2. Create Supabase Gateway Class
**File**: `src/pcr_utils/supabase_gateway.py`

Create a new class that handles all Supabase database operations:

**Requirements**:
- Initialize connection to Supabase using credentials (URL, API key)
- Method to insert parsed PCR JSON into `rip_and_runs` table
- Method to transform JSON structure to database row format
- Handle database errors gracefully
- Support both environment variables and explicit credentials
- Include logging for debugging

**Class Interface** (suggested):
```python
class SupabaseGateway:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        """Initialize Supabase connection"""

    def upsert_pcr_data(self, pcr_json: Dict[str, Any]) -> bool:
        """Insert or update parsed PCR data in rip_and_runs table"""

    def _prepare_record(self, pcr_json: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare record for database insertion with content as JSONB"""
```

**Implementation Notes**:
- Store entire parsed JSON in `content` column as TEXT (use `json.dumps()`)
- Extract `incident_number` from `incidentTimes.cad`
- Extract `incident_date` from `incidentTimes.times.notifiedByDispatch` (combine date + time)
- Extract `location` from `incidentLocation.raw`
- Use upsert operation via Supabase `.upsert()` method
- Handle missing `unit_id` - may need default value or extraction logic
- Convert date/time strings (mm/dd/yyyy + hh:mm:ss) to TIMESTAMP WITH TIME ZONE

### 3. Integrate Gateway into PCR Parser
**File**: `src/pcr_utils/pcr_parser.py`

Modify the `__main__` section to:
1. After successfully parsing PDF and saving JSON file
2. Create SupabaseGateway instance
3. Insert the parsed data into database
4. Handle database insertion errors without breaking existing file output
5. Add optional command-line flag to skip database insertion (for testing)

### 4. Update Package Exports
**File**: `src/pcr_utils/__init__.py`

Add SupabaseGateway to package exports so it can be used independently.

### 5. Configuration
Add environment variables for Supabase connection:
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_KEY`: Supabase API key (service role or anon key)

Document these in README.md or .env.example file.

**Action Items**:
- Create `.env.example` with required variables
- `.env` already in `.gitignore` ✓

## Database Schema Decisions - RESOLVED

1. **Timestamp storage**: Use TIMESTAMP WITH TIME ZONE (database timestamps, not text) ✓
2. **Location storage**: Stored in TEXT `content` column as part of full JSON ✓
3. **Duplicate handling**: UPSERT - overwrite existing records with same (incident_number, unit_id) ✓
4. **Source tracking**: NOT tracking original PDF filename ✓
5. **Error storage**: Stored in `content` column as part of full JSON ✓
6. **Data format**: Entire parsed JSON is stored in `content` column as TEXT (JSON string) ✓

## Outstanding Questions

1. **unit_id**: What value should be used for `unit_id`? Options:
   - Extract from PCR if it contains unit information
   - Use a default value (e.g., "UNKNOWN" or "PARSER")
   - Make it configurable via parameter

2. **incident_type**: What value should be used for `incident_type`? Options:
   - Leave as NULL (it's optional)
   - Extract from PCR if available
   - Default to a standard value

## Success Criteria

1. Database table created with appropriate schema
2. SupabaseGateway class can successfully connect to Supabase
3. Parsed PCR JSON is correctly transformed and inserted into database
4. Existing file output functionality remains unchanged
5. Database insertion errors are logged but don't crash the parser
6. Can be used both from command line and as importable module

## Testing Considerations

1. Test with valid PCR JSON from successful parse
2. Test with JSON containing parsingErrors
3. Test with duplicate CAD numbers
4. Test database connection failures
5. Test credential validation
6. Verify data integrity in database matches JSON output

## Dependencies

- `supabase-py`: Python client library for Supabase
- Add to `requirements.txt`

## Future Enhancements (Out of Scope)

- Query methods to retrieve PCR data from database
- Batch upload of multiple PCRs
- Update existing records
- Data validation before database insertion
- Retry logic for failed insertions
