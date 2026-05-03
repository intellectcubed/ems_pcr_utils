# EMS Dispatch Document Parser

You are analyzing an EMS dispatch document (rip-and-run) and need to extract specific information into a structured JSON format.

## EXTRACTION RULES

### 1. CAD/Incident Number
- Locate the incident number field (commonly labeled as "CAD", "Incident #", or similar)
- Extract this value as the "cad" field

### 2. Unit Dispatched
- Find the "Unit Dispatched" field in the document
- Extract the unit identifier (e.g., "43C1", "43B1")
- This is the primary unit for this incident

### 3. Incident Type
- Find the "Incident Type" field in the document
- Extract the value as-is (e.g., "EMS", "FIRE", "MEDICAL")
- This indicates the type of emergency response

### 4. Dispatch Time
- Find the datetime under "Dispatch Time"
- This maps to "notifiedByDispatch" in the output
- Split into separate "date" (mm/dd/yyyy) and "time" (hh:mm:ss) fields

### 5. Location Parsing
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

### 6. Unit Activity Table
- Find the table (typically at bottom of page) with columns: "Unit ID", "Date / Time", "Status", "Dispatcher"
- The table often contains rows for **multiple responding units** — only extract rows where the Unit ID exactly matches "Unit Dispatched" (step 2); ignore all other units
- Extract Date/Time values in format mm/dd/yyyy hh:mm:ss and split into separate "date" and "time" fields
- Ignore the "Dispatcher" column

**Example** — Unit Dispatched is `43BLS2`:

| Unit   | Date/Time           | Status | Dispatcher |
|--------|---------------------|--------|------------|
| 43C1   | 05/01/2026 23:30:33 | RESP   |            |
| 43BLS2 | 05/01/2026 23:31:33 | RESP   |            |
| 43BLS2 | 05/01/2026 23:31:31 | ONLOC  |            |
| 43C1   | 05/01/2026 23:30:33 | ONLOC  |            |
| 43BLS2 | 05/01/2026 23:41:33 | CLEAR  |            |

All `43C1` rows are ignored. Only the three `43BLS2` rows are extracted.

### 7. Status Mapping
Map these STATUS values to JSON fields — the STATUS column text must match exactly:
- `RESP` → enRoute
- `ONLOC` → onScene
- `TO HOSP` → leftScene *(crew leaving the scene to transport patient to hospital)*
- `AT HOSP` → ptArrivedAtDestination *(crew arrives at hospital with patient)*
- `LV HOSP` → crewLeftDestination *(crew leaving the hospital after dropping off patient — do NOT map this to leftScene)*
- `CLEAR` → backInService

**Critical distinction — `TO HOSP` vs `LV HOSP`:**
- `TO HOSP` = the unit is departing the incident scene heading to the hospital → `leftScene`
- `LV HOSP` = the unit is departing the hospital after delivering the patient → `crewLeftDestination`
- These are two different events. Never map `LV HOSP` to `leftScene`.

**Note on hospital transport:** Not all responses involve transporting to the hospital. RESP and CLEAR will always appear. ONLOC, TO HOSP, AT HOSP, and LV HOSP may be absent if they were not captured or did not occur.

- Only include `leftScene` if a `TO HOSP` row is explicitly present in the Unit Activity Table. Never calculate, infer, or copy another time into `leftScene`.
- If TO HOSP is not present, omit `leftScene`, `ptArrivedAtDestination`, `destinationPatientTransferOfCare`, and `crewLeftDestination` entirely.
- A typical transport response: RESP → ONLOC → TO HOSP → AT HOSP → LV HOSP → CLEAR
- A typical non-transport response: RESP → ONLOC → CLEAR

### 8. Multiple Occurrences
- If a status appears multiple times, use the FIRST occurrence

### 9. Missing Statuses
- If a status is not found in the table, omit that field from the JSON

## REQUIRED OUTPUT FORMAT

Return ONLY valid JSON in this exact structure (omit fields that are not found):

```json
{
  "incidentTimes": {
    "cad": "string",
    "unit_dispatched": "string",
    "incident_type": "string",
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
