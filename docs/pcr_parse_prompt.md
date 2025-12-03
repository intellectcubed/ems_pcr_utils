# Create a python script that will scrape the text from a pdf that is an image of a document.
The script will load the .pdf, post it to ChatGPT with instructions on how to parse it and return a json object.

- The prompt text shall be separate from the script in its own file that is loaded.  This will facilitate changing the prompt.
- The ChatGPT API key should be obtained from the environment variables


## Parsing rules

### CAD/Incident Number
- Locate the incident number field in the document (commonly labeled as "CAD", "Incident #", or similar)
- Extract this value as the "cad" field

### Dispatch Time
- There is a datetime under "Dispatch Time"
- This will map to the "notifiedByDispatch" value in the resultant JSON
- Split into separate "date" and "time" fields in mm/dd/yyyy and hh:mm:ss format

### Unit Activity Table
- There is a table (typically at the bottom of the page) with columns: "Unit ID", "Date / Time", "Status", "Dispatcher"
- The Date/Time will be in the format mm/dd/yyyy hh:mm:ss
- Split each Date/Time into separate "date" and "time" fields for the JSON output
- Ignore the "Unit ID" and "Dispatcher" columns

### Status Mapping
Map the STATUS values from the table to the Response JSON fields as follows:
- RESP → enRoute
- ONLOC → onScene
- TO HOSP → leftScene
- AT HOSP → ptArrivedAtDestination
- CLEAR → backInService

**Handling multiple occurrences:** If a status appears multiple times, use the **first occurrence** of that status.

**Missing statuses:** If a status is not found in the table, omit that field from the JSON output.

### Calculated Fields (if not present in document)
- **arrivedAtPatient**: If this timestamp is not explicitly in the document, calculate it as 2 minutes after onScene
- **destinationPatientTransferOfCare**: If this timestamp is not explicitly in the document, calculate it as 5 minutes after ptArrivedAtDestination

### Error Handling
- If the document is illegible or malformed, return an error message in the format: `{"error": "description of issue"}`
- If required fields (cad, notifiedByDispatch, or critical statuses) are missing, include what was found and note missing fields in an "errors" array

## Response JSON:
```
{
  "incidentTimes": {
    "cad": "123456789",
    "times": {
      "notifiedByDispatch": {
        "date": "11/20/2025",
        "time": "00:01:15"
      },
      "enRoute": {
        "date": "11/20/2025",
        "time": "00:06:45"
      },
      "onScene": {
        "date": "11/20/2025",
        "time": "00:18:30"
      },
      "arrivedAtPatient": {
        "date": "11/20/2025",
        "time": "00:23:10"
      },
      "leftScene": {
        "date": "11/20/2025",
        "time": "00:41:00"
      },
      "ptArrivedAtDestination": {
        "date": "11/20/2025",
        "time": "01:02:25"
      },
      "destinationPatientTransferOfCare": {
        "date": "11/20/2025",
        "time": "01:19:40"
      },
      "backInService": {
        "date": "11/20/2025",
        "time": "01:31:15"
      }
    }
  }
}```