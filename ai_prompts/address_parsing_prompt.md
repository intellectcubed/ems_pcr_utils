# Location Parsing (Token-Optimized)

Extract location text under **"Location"** from PDF.

### Output
`incidentLocation` object:
- `raw`: exact text
- Optional: `territory`, `location_name`, `street_address`, `apartment`

### Rules
1. `territory` = first 1–2 words.
2. Remaining segment parsed by symbols:
   - `/` → split into `location_name` (before `/`) and address (after `/`).  
     - If `#` in address → split into `street_address` (before `#`) and `apartment` (after `#`).
     - Else: `street_address` = address.
   - `&` (no `/`) → intersection.  
     - `street_address` = entire segment after territory.
   - `#` (no `/`) → address + apartment.  
     - Split before/after `#`.
   - No `/`, `&`, `#` → entire segment = `street_address`.

### Examples
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
