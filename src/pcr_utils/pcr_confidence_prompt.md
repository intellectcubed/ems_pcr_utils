## CONFIDENCE RATINGS

For every field you extract, rate your confidence in the extracted value:
- **"high"**: Clearly visible and unambiguous
- **"medium"**: Readable but with some uncertainty (e.g., partially obscured, ambiguous handwriting, unusual format)
- **"low"**: Difficult to read, partially missing, or inferred/estimated

Include a flat `confidence` object at the top level of your JSON output. Only include keys for fields that were actually extracted.

```json
{
  "confidence": {
    "cad": "high | medium | low",
    "unit_dispatched": "high | medium | low",
    "incident_type": "high | medium | low",
    "notifiedByDispatch": "high | medium | low",
    "enRoute": "high | medium | low",
    "onScene": "high | medium | low",
    "arrivedAtPatient": "high | medium | low",
    "leftScene": "high | medium | low",
    "ptArrivedAtDestination": "high | medium | low",
    "destinationPatientTransferOfCare": "high | medium | low",
    "crewLeftDestination": "high | medium | low",
    "backInService": "high | medium | low",
    "location_raw": "high | medium | low",
    "territory": "high | medium | low",
    "location_name": "high | medium | low",
    "street_address": "high | medium | low",
    "apartment": "high | medium | low"
  }
}
```
