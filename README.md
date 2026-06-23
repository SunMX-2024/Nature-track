# Nature-track

This repository keeps two source snapshots side by side so the older local tool and the newer AI-assisted version are easy to inspect separately.

## Version folders

- `nature_track_v0/` is the `v1.0.0` baseline release: the original local Streamlit literature tracker with OpenAlex search and email digests.
- `nature_track_v1/` is the `v1.1.0` release: resilient Crossref + OpenAlex search, DeepSeek Heilmeier-style summaries, Obsidian knowledge-graph export, local app startup scripts, tests, and a web preview scaffold.

## Releases

- [v1.0.0 - Local literature tracker baseline](https://github.com/SunMX-2024/Nature-track/releases/tag/v1.0.0)
- [v1.1.0 - AI notes, resilient search, and web preview](https://github.com/SunMX-2024/Nature-track/releases/tag/v1.1.0)

## Run the current local tool

```powershell
cd nature_track_v1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

The older version can be run the same way from `nature_track_v0/`.
