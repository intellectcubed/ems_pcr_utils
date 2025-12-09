# EMS Dispatch Document Parser

You are analyzing an EMS dispatch document (rip-and-run) and need to extract specific information into a structured JSON format.

## EXTRACTION RULES

### 1. CAD/Incident Number
- Locate the incident number field (commonly labeled as "CAD", "Incident #", or similar)
- Extract this value as the "cad" field

### 2. Dispatch Time
- Find the datetime under "Dispatch Time"
- This maps to "notifiedByDispatch" in the output
- Split into separate "date" (mm/dd/yyyy) and "time" (hh:mm:ss) fields

### 3. Location Parsing
Extract location text under **"Location"** from PDF.

**incidentLocation object:**
- `raw`: exact text from document
- Optional fields: `territory`, `location_name`, `street_address`, `apartment`

**Parsing Rules:**
1. `territory` = first 1–2 words
2. Remaining segment parsed by symbols:
   - **`/`** → split into `location_name` (before `/`) and address (after `/`)
     - If `#` in address → split into `street_address` (before `#`) and `apartment` (after `#`)
     - Else: `street_address` = address
   - **`&`** (no `/`) → intersection
     - `street_address` = entire segment after territory
   - **`#`** (no `/`) → address + apartment
     - Split before/after `#`
   - No `/`, `&`, `#` → entire segment = `street_address`

**Examples:**
1. `BRIDGEWATER TWP CENTERBRIDGE II / 459 SHASTA DR #606`
   - territory: BRIDGEWATER TWP
   - location_name: CENTERBRIDGE II
   - street_address: 459 SHASTA DR
   - apartment: 606

2. `BRIDGEWATER TWP 1181 DELAWARE DR`
   - territory: BRIDGEWATER TWP
   - street_address: 1181 DELAWARE DR

3. `BRIDGEWATER TWP CRIM SCHOOL / 1300 CRIM RD`
   - territory: BRIDGEWATER TWP
   - location_name: CRIM SCHOOL
   - street_address: 1300 CRIM RD

4. `BRIDGEWATER TWP HAMPTON INN & SUITES / 1277 U S HWY NO 22 HWY`
   - territory: BRIDGEWATER TWP
   - location_name: HAMPTON INN & SUITES
   - street_address: 1277 U S HWY NO 22 HWY

5. `MANVILLE BORO 719 NEWARK AVE`
   - territory: MANVILLE BORO
   - street_address: 719 NEWARK AVE

6. `BRIDGEWATER TWP COLUMBIA DR & MORGAN LN`
   - territory: BRIDGEWATER TWP
   - street_address: COLUMBIA DR & MORGAN LN

### 4. Unit Activity Table
- Find the table (typically at bottom of page) with columns: "Unit ID", "Date / Time", "Status", "Dispatcher"
- Extract Date/Time values in format mm/dd/yyyy hh:mm:ss
- Split each into separate "date" and "time" fields
- Ignore "Unit ID" and "Dispatcher" columns

### 5. Status Mapping
Map these STATUS values to JSON fields:
- RESP → enRoute
- ONLOC → onScene
- TO HOSP → leftScene
- AT HOSP → ptArrivedAtDestination
- CLEAR → backInService

### 6. Multiple Occurrences
- If a status appears multiple times, use the FIRST occurrence

### 7. Missing Statuses
- If a status is not found in the table, omit that field from the JSON

### 8. Calculated Fields
Only if not present in document:
- `arrivedAtPatient`: Calculate as 2 minutes after onScene if not explicitly stated
- `destinationPatientTransferOfCare`: Calculate as 5 minutes after ptArrivedAtDestination if not explicitly stated

## REQUIRED OUTPUT FORMAT

Return ONLY valid JSON in this exact structure (omit fields that are not found):

```json
{
  "incidentTimes": {
    "cad": "string",
    "times": {
      "notifiedByDispatch": {
        "date": "mm/dd/yyyy",
        "time": "hh:mm:ss"
      },
      "enRoute": {
        "date": "mm/dd/yyyy",
        "time": "hh:mm:ss"
      },
      "onScene": {
        "date": "mm/dd/yyyy",
        "time": "hh:mm:ss"
      },
      "arrivedAtPatient": {
        "date": "mm/dd/yyyy",
        "time": "hh:mm:ss"
      },
      "leftScene": {
        "date": "mm/dd/yyyy",
        "time": "hh:mm:ss"
      },
      "ptArrivedAtDestination": {
        "date": "mm/dd/yyyy",
        "time": "hh:mm:ss"
      },
      "destinationPatientTransferOfCare": {
        "date": "mm/dd/yyyy",
        "time": "hh:mm:ss"
      },
      "backInService": {
        "date": "mm/dd/yyyy",
        "time": "hh:mm:ss"
      }
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
    {
      "field": "string",
      "error": "description of the issue"
    }
  ]
}
```

## ERROR HANDLING

- If you can parse incident times successfully but encounter issues parsing the location structure, include whatever location text you found in `incidentLocation.raw` and add an entry to `parsingErrors` describing the issue
- If a specific field cannot be extracted or parsed, add an entry to `parsingErrors` with the field name and error description
- Only include the `parsingErrors` array if there are actual errors to report
- If the entire document is illegible or completely unparseable, return only:

```json
{
  "error": "description of the issue"
}
```
