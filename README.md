# ai-audio-transcriber
An end-to-end, multi-agent pipeline that turns raw interview audio into structured qualitative insights.

## QA Validation

The quality assurance utility in `tools/quality_assurance_tools.py` validates
transcription JSON produced by the pipeline.

### Function

- `validate_json_structure(transcription: str) -> str`

### Accepted Input

- Plain JSON text
- JSON wrapped in Markdown code fences (for example, ```json ... ```)
- Mixed text where a JSON object/array can be extracted

### Expected Top-Level Shape

The validator expects a top-level JSON object. It checks these keys when
present:

- `transcription`: string
- `text`: string
- `summary`: string or list of strings
- `segments`: list of segment objects

Each segment object may include:

- `text`: string
- `speaker`: string
- `start`: number
- `end`: number (must be greater than or equal to `start`)

### Validation Output

The function returns a status string:

- `Invalid JSON: ...` for parse failures or empty input
- `Invalid JSON structure: ...` for schema/type/order violations
- `JSON structure is valid with warnings: ...` when JSON is valid but expected
	content keys are missing
- `JSON structure is valid` when all checks pass
