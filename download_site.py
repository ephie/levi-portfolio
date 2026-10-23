"""Capture this authorized public site and its publicly referenced resources."""

import asyncio
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlsplit

from playwright.async_api import Error, async_playwright

ROOT = Path(__file__).resolve().parent
ORIGIN = "https://goldschmidt-levi.base44.app"
ALLOWED_HOSTS = {
    urlsplit(ORIGIN).hostname,
    "media.base44.com",
    "base44.app",
    "app.base44.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "img.youtube.com",
}
URL_PATTERN = re.compile(r'https?://[^\s"<>\\]+')


async def main():
    entries = {}
    if (ROOT / "manifest.json").exists():
        previous = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        entries = {
            url: entry for url, entry in previous["resources"].items()
            if (ROOT / entry["file"]).is_file()
        }
    errors = []
    pages = []
    media_urls = set()
    pending = []

    def discover(text):
        for match in URL_PATTERN.findall(text):
            url = match.rstrip("');,}")
            parts = urlsplit(url)
            if parts.hostname in ALLOWED_HOSTS and (
                "/public/" in parts.path
                or parts.hostname in {
                    "fonts.googleapis.com", "fonts.gstatic.com", "img.youtube.com"
                }
            ):
                media_urls.add(url)

    async def save_response(response):
        url = urldefrag(response.url)[0]
        if response.request.method != "GET":
            return
        if urlsplit(url).hostname not in ALLOWED_HOSTS:
            return
        if response.status == 206:
            media_urls.add(url)
            return
        if not 200 <= response.status < 300:
            if response.status >= 400:
                errors.append({"url": url, "status": response.status})
            return
        try:
            body = await response.body()
        except Error as exc:
            errors.append({"url": url, "error": str(exc)})
            return
        save(url, body, response.headers)

    def save(url, body, headers):
        content_type = headers.get("content-type", "application/octet-stream")
        parts = urlsplit(url)
        filename = Path(unquote(parts.path)).name or "index.html"
        filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)[:120]
        if "." not in filename:
            filename += mimetypes.guess_extension(content_type.split(";")[0]) or ".bin"
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        relative = Path("archive") / parts.netloc / f"{digest}-{filename}"
        destination = ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        entries[url] = {"file": str(relative), "content_type": content_type}
        if any(kind in content_type for kind in ("json", "javascript", "css", "html")):
            discover(body.decode("utf-8", errors="replace"))

    def on_response(response):
        task = asyncio.create_task(save_response(response))
        pending.append(task)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        context.on("response", on_response)
        page = await context.new_page()
        queue = ["/", "/projets", "/photos", "/videos", "/cv"]
        visited = set()
        while queue:
            path = queue.pop(0)
            if path in visited:
                continue
            if len(visited) >= 150:
                raise RuntimeError("Page limit reached; inspect the discovered links.")
            visited.add(path)
            print(f"Capturing {path}", flush=True)
            await page.goto(ORIGIN + path, wait_until="networkidle", timeout=90000)
            await page.locator("main").wait_for(timeout=30000)
            # Trigger lazy images throughout the page, not just in the viewport.
            await page.evaluate(
                """async () => {
                    for (let y = 0; y < document.body.scrollHeight; y += 800) {
                        scrollTo(0, y);
                        await new Promise(resolve => setTimeout(resolve, 120));
                    }
                    scrollTo(0, 0);
                }"""
            )
            await page.wait_for_timeout(800)
            links = await page.locator("a[href]").evaluate_all(
                "(links) => links.map(link => link.href)"
            )
            linked_assets = await page.locator("link[href]").evaluate_all(
                "(links) => links.map(link => link.href)"
            )
            for asset in linked_assets:
                if urlsplit(asset).hostname in ALLOWED_HOSTS:
                    media_urls.add(urldefrag(asset)[0])
            for link in links:
                parts = urlsplit(link)
                if f"{parts.scheme}://{parts.netloc}" != ORIGIN:
                    continue
                if parts.path.startswith(("/api/", "/assets/", "/login", "/admin")):
                    continue
                if Path(parts.path).suffix:
                    media_urls.add(urldefrag(link)[0])
                    continue
                candidate = parts.path + (f"?{parts.query}" if parts.query else "")
                if candidate not in visited and candidate not in queue:
                    queue.append(candidate)
            embeds = await page.locator("iframe[src]").evaluate_all(
                "(frames) => frames.map(frame => frame.src)"
            )
            snapshot = Path("snapshots") / (path.strip("/").replace("/", "_") or "home")
            snapshot = snapshot.with_suffix(".html")
            (ROOT / snapshot).parent.mkdir(exist_ok=True)
            (ROOT / snapshot).write_text(await page.content(), encoding="utf-8")
            pages.append(
                {"path": path, "title": await page.title(), "snapshot": str(snapshot),
                 "external_embeds": embeds}
            )
            if path == "/":
                await page.screenshot(path=str(ROOT / "preview.png"), full_page=True)
        if pending:
            await asyncio.gather(*list(pending))

        # JSON responses include full-resolution photos, PDFs and videos that
        # may only be requested after opening a gallery or pressing a button.
        attempted = set(entries)
        semaphore = asyncio.Semaphore(3)

        async def download(url):
            async with semaphore:
                print(f"Downloading {url}", flush=True)
                try:
                    response = await context.request.get(url, timeout=180000)
                    if response.ok:
                        save(url, await response.body(), response.headers)
                    else:
                        errors.append({"url": url, "status": response.status})
                    await response.dispose()
                except Error as exc:
                    errors.append({"url": url, "error": str(exc)})

        while unseen := sorted(media_urls - attempted):
            attempted.update(unseen)
            await asyncio.gather(*(download(url) for url in unseen))
        if pending:
            await asyncio.gather(*list(pending))
        await browser.close()

    # A failed browser body read can subsequently succeed via a direct download.
    errors = [error for error in errors if error["url"] not in entries]
    manifest = {"origin": ORIGIN, "pages": pages, "resources": entries, "errors": errors}
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved {len(pages)} pages and {len(entries)} resources; {len(errors)} errors.")
    if errors:
        print("See manifest.json for the exact unavailable resources.")


if __name__ == "__main__":
    asyncio.run(main())
