# Nature-track

Nature-track is a local literature radar for Earth-system, ecology, conservation, and remote-sensing researchers. It helps you scan new papers from selected journals, filter them by keyword and time window, open the papers that matter, and save AI-assisted reading notes into Obsidian.

The project is intentionally kept as a local Streamlit tool. The earlier web prototype has been removed from the repository so the codebase stays focused on the desktop/local workflow.

## What the Tool Does

- Tracks selected journals from the Nature family, Science family, and major Earth/environment titles.
- Searches recent publications with a more resilient Crossref + OpenAlex workflow.
- Filters by publication window, article type, abstract availability, research-like records, keyword logic, and title/abstract scope.
- Supports keyword expressions such as phrase queries, `OR`, `NOT`, `all`, and `any`.
- Keeps your last keyword query and remembers frequently used keywords.
- Opens DOI/publisher pages and downloads open-access PDFs when available.
- Uses DeepSeek to generate Heilmeier-style paper summaries when you choose to summarize a paper.
- Exports paper notes to Obsidian with linked `topic`, `method`, `data`, and `journal` nodes for knowledge-graph navigation.
- Sends manual or scheduled email digests from your own mailbox credentials.

## Version folders

- `nature_track_v0/` is the `v1.0.0` baseline release. It contains the original local Streamlit literature tracker with OpenAlex search and email digests.
- `nature_track_v1/` is the current `v1.1.0` local-tool release. It adds resilient Crossref + OpenAlex search, better keyword behavior, DeepSeek summaries, Obsidian knowledge-graph export, local startup scripts, and tests.

## Version Updates

### v1.1.0

- Added Crossref fallback/supplemental search so keyword results are less dependent on OpenAlex availability.
- Improved keyword matching for phrases such as `protected area`, including plural and hyphen variants.
- Added selectable time-window units: days, weeks, months, and years.
- Added DeepSeek AI summaries following a Heilmeier seven-question structure.
- Added Obsidian paper notes and graph links for topics, methods, data, and journals.
- Added local Streamlit startup/watch scripts and a notes panel inside the tool.
- Removed the early web/API/miniprogram prototype from the main source tree after deciding to keep the local tool workflow.

### v1.0.0

- Initial local Streamlit literature tracker.
- OpenAlex-based journal search, basic filters, article detail cards, DOI/PDF links, local settings, and email digests.

## Releases

- [v1.0.0 - Local literature tracker baseline](https://github.com/SunMX-2024/Nature-track/releases/tag/v1.0.0)
- [v1.1.0 - AI notes and resilient local search](https://github.com/SunMX-2024/Nature-track/releases/tag/v1.1.0)

## Run the current local tool

```powershell
cd nature_track_v1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

The older version can be run the same way from `nature_track_v0/`.
