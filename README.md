# Goldschmidt Levi website archive

Public browser-delivered files captured with Python Playwright from
<https://goldschmidt-levi.base44.app/> on 2026-10-23, with the owner's permission.

## Open the local website

From this folder:

```sh
source .venv/bin/activate
python serve.py
```

Open <http://127.0.0.1:8000/>. Stop the server with Ctrl+C.
Use `python serve.py --port 8001` if port 8000 is occupied.

The preview requires this server, not opening `index.html` directly or using
`python -m http.server`. A service worker routes the original application's
resource requests to the local archive. Media URLs are rewritten when served so
PDF viewers, new tabs and downloads also stay local. Saved original files are
not modified.

## Contents

- `archive/`: 532 resources, including the production JavaScript/CSS, public
  API responses, images, fonts, 23 PDFs and one MP4.
- `snapshots/`: rendered HTML snapshots of 19 routes: home, projects, photos,
  videos, CV and 14 project detail pages.
- `manifest.json`: original URL to local file mappings, page inventory and
  exact resource download failures.
- `preview.png`: full-page screenshot of the original homepage.
- `download_site.py`: reusable Playwright capture script.
- `serve.py`, `mirror-sw.js`, `index.html`: read-only local preview.
- `.venv/`, `requirements.txt`: project-local Python environment and pinned
  Playwright dependency.

## Recreate the environment or refresh the capture

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python download_site.py
```

The capture revisits public linked pages and downloads their resources,
including media referenced in public JSON responses and JavaScript. Previously
saved resources are reused when not requested again by the browser.
Stop and restart the preview after refreshing its manifest.

## Scope and known limitations

This is a functional public frontend archive, not the original editable
React/Base44 project or its server-side source. No account credentials or
private/admin pages were accessed. The local server makes no upstream requests;
write requests, including analytics, are explicitly rejected with HTTP 405.
Outbound links to other websites are not archived.

Two publicly referenced PDFs returned HTTP 403 on the source website, including
on retry, and could not be downloaded:

- `82637d3bf_MAEUProjectfinalpresentation.pdf`
- `a6182fb28_StatiqueAvecFrottementsLviGOLDSCHMIDTLevi1er7.pdf`

Their exact original URLs are listed in `manifest.json`. No access controls
were bypassed. Those document links remain unavailable locally.

YouTube thumbnails are saved, but YouTube-hosted streams and players are not
included. Embedded YouTube playback is therefore unavailable in this offline
archive. The site's directly hosted MP4 is included and plays locally.

The original site has an empty cover image URL for "S2 Projet 1 : the room";
that original issue is preserved.

## Verification

Using Python Playwright with upstream requests blocked, all 19 local routes
matched the rendered main content of their saved snapshots. All nonempty main
image URLs decoded successfully; the CV download produced a valid PDF, and
the archived MP4 played successfully. No JavaScript exceptions or upstream
requests occurred during those checks.
