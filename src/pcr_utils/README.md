  ## Basic usage (OpenAI Vision, normal mode)
  ```python pcr_service.py --watch-dir ./pdfs```

### Azure backend
  `python pcr_service.py --backend azure --watch-dir ./pdfs`

  ---
  ## All flags
  
| Flag  | Default | Description |
|--|--|--|
| \-\-backend  | openai |  openai or azure. Can also set PARSER_BACKEND in .env |
| \-\-watch-dir | WATCH_DIR env | Directory to poll for incoming PDFs |
| \-\-poll-interval | 30 | Seconds between directory scans |
| \-\-model | gpt-4o (openai) / gpt-4o-mini (azure) | Override the OpenAI model  |
| \-\-validate_existing | off | Read-only mode — re-parses PDFs and diffs against what's in Supabase |
| \-\-dry-run | false | Parse the .pdf and write output but do not update Supabase |
| \-\-output-dir | output |Where to write filename_<epoch>.json files|
| \-\-with_confidence | false | Add a confidence section to the resulting json that shows the model's confidence in the fields
  ---
  ### Examples

  ### OpenAI backend, poll ./pdfs every 60s, save JSON to ./results
  `python pcr_service.py --watch-dir ./pdfs --poll-interval 60 --output-dir ./results`

  ### Azure backend with a specific model
  `python pcr_service.py --backend azure --watch-dir ./pdfs --model gpt-4o`

  ### Validate mode: re-parse everything in ./pdfs and compare against Supabase (no DB writes)
  `python pcr_service.py --backend azure --watch-dir ./pdfs --validate_existing`

  ---
  ## Environment Variables
  Via environment variables instead of flags (useful in Docker/production):
```
  PARSER_BACKEND=azure
  WATCH_DIR=/data/incoming
  POLL_INTERVAL_SECONDS=60
```
Then just:
`python pcr_service.py`


> Written with [StackEdit](https://stackedit.io/).