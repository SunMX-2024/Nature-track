# Nature-track

Nature-track is a local literature-tracking tool for Earth and environmental science journals. It searches recent publications, filters by journal, date window, keywords, and article type, then shows a compact list in the format:

`first author_corresponding author_journal_title`

The current MVP uses [OpenAlex](https://openalex.org/) as the open metadata source. When an open-access PDF URL is available, the app exposes a direct download/open action; otherwise it links to the DOI page.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Features

- Track target journals with quick-add buttons and custom journal names.
- Select a publication date window.
- Match keywords locally against article abstracts after journal/date/type filtering.
- Filter by article type, including article, review, editorial, letter, and others supported by OpenAlex.
- Expand each result to view DOI, abstract, authors, open-access status, DOI link, and PDF link when available.
- Save tracker settings locally.
- Send a digest email immediately from the UI or schedule it with Windows Task Scheduler.
- Configure scheduled digest content separately from the manual on-screen search.

## Email Digest

1. Open the app and choose your sender email provider.
2. Fill in sender email, mailbox authorization code/app password, and recipient email.
2. Click `Save settings`.
3. Click `Send test digest` to verify delivery.
4. For scheduled delivery, create a Windows scheduled task that runs:

```powershell
.\.venv\Scripts\python.exe scripts\send_digest.py
```

Or register it from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_windows_task.ps1 -Frequency weekly -WeeklyDay Monday -Time 08:00
```

The script reads `data/settings.json`, fetches the latest matching articles, and sends the same compact list to the configured recipient.

## Notes

- OpenAlex metadata can be incomplete. If a corresponding author is unavailable, Nature-track falls back to the last author and marks it as inferred in the expanded details.
- Publisher downloads are only available when OpenAlex exposes an open-access PDF URL.
- Nature-track does not include a shared built-in sender account. A local sender account needs your mailbox SMTP authorization code because public embedded credentials would be insecure and quickly blocked.
