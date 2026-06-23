# Changelog

## v1.1.0 - AI notes and resilient local search

This release keeps the local Streamlit tool as the primary workflow while adding a more robust paper discovery and note-taking layer.

### Added

- Added Crossref-backed candidate search as a fallback and supplement to OpenAlex, reducing empty results when OpenAlex is rate-limited or keyword search is too narrow.
- Added DeepSeek-powered paper summaries with a Heilmeier-style seven-question structure.
- Added Obsidian export for paper notes, including linked topic, method, data, and journal notes for graph navigation.
- Added full-text/landing-page reading helpers so AI notes can use available publisher text when accessible.
- Added a compact in-app notes panel for browsing generated Obsidian paper notes from the local tool.
- Added keyword usage memory with a denser shortcut list.
- Added selectable time-window units: days, weeks, months, and years.
- Added scripts for starting and monitoring the local Streamlit app.
- Added unit tests for keyword filtering, multi-provider search, Crossref parsing, AI summaries, and Obsidian export.

### Changed

- Improved phrase keyword matching, including plural and hyphen variants such as `protected area` and `protected-area`.
- Improved keyword query behavior for `all`, `any`, `OR`, `NOT`, and title/abstract scopes.
- Saved the last keyword query as the default instead of resetting to a hard-coded term.
- Reworked the article details section so detailed cards remain visible below the summary table.
- Expanded settings persistence for journals, keyword scope, time windows, AI settings, and Obsidian settings.
- Updated README with local Streamlit startup instructions.

### Fixed

- Fixed empty result cases caused by over-reliance on OpenAlex keyword search.
- Fixed frequent keyword shortcut clicks that could trigger Streamlit state errors.
- Fixed missing article details after scrolling below the result table.
- Fixed local app restart friction by adding dedicated startup/watch scripts.

### Verification

- `python -m unittest discover -s tests -v`
- `python -m py_compile app.py nature_track\ai_summary.py nature_track\obsidian.py`

## v1.0.0 - Local literature tracker baseline

Initial local Streamlit release for tracking high-impact Earth and environmental science publications.

### Included

- Journal-based literature tracking through OpenAlex metadata.
- Publication-window, article-type, and abstract-based filtering.
- Compact article list and expandable article detail cards.
- DOI and PDF links when available.
- Local settings persistence.
- Manual and scheduled email digests using the user's own mailbox credentials.
