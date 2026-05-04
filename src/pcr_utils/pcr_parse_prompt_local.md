Look at this EMS dispatch document image and extract the following fields. Output only valid JSON, no explanation.

Read every value directly from the document. Do not invent or assume any values.

Extract these fields:

1. "cad" - the CAD or incident number printed on the document
2. "unit_dispatched" - the unit ID in the "Unit Dispatched" field
3. "incident_type" - the value in the "Incident Type" field
4. "dispatch_date" and "dispatch_time" - the date and time next to "Dispatch Time" (format: mm/dd/yyyy and hh:mm:ss)
5. "location_raw" - the exact text in the "Location" field, copied word for word
6. From the activity table at the bottom, find all rows matching the unit_dispatched unit ID and extract the date/time for each of these statuses: RESP, ONLOC, TO HOSP, AT HOSP, CLEAR

Return this JSON structure using only values found in the document:

{
  "incidentTimes": {
    "cad": "...",
    "unit_dispatched": "...",
    "incident_type": "...",
    "times": {
      "notifiedByDispatch": { "date": "mm/dd/yyyy", "time": "hh:mm:ss" },
      "enRoute":            { "date": "mm/dd/yyyy", "time": "hh:mm:ss" },
      "onScene":            { "date": "mm/dd/yyyy", "time": "hh:mm:ss" },
      "leftScene":          { "date": "mm/dd/yyyy", "time": "hh:mm:ss" },
      "ptArrivedAtDestination": { "date": "mm/dd/yyyy", "time": "hh:mm:ss" },
      "backInService":      { "date": "mm/dd/yyyy", "time": "hh:mm:ss" }
    }
  },
  "incidentLocation": {
    "raw": "..."
  }
}

Rules:
- notifiedByDispatch = Dispatch Time
- enRoute = RESP row
- onScene = ONLOC row
- leftScene = TO HOSP row
- ptArrivedAtDestination = AT HOSP row
- backInService = CLEAR row
- Only include a time field if that status appears in the document
- Only output JSON, nothing else
