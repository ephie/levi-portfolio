#!/usr/bin/env python3
"""One-time migration: Base44 capture (manifest.json + archive/) -> content/*.json + media/.

After this has run, content/ and media/ are the source of truth and this script is
no longer needed. Re-running it overwrites content/ and media/.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
MEDIA = ROOT / "media"
API = "https://goldschmidt-levi.base44.app/api/apps/6a188961cb313af9686e2905/"

HIDDEN_TITLES = {"SmartRun", "F1 in Schools — Finale Française 2025", "STEM Racing — World Finals 2025"}
PROJECT_CATEGORIES = ["Architecture", "Lycée"]
PHOTO_CATEGORIES = ["Architecture", "2026", "A1387"]

IMAGE_FIELDS = {
    "process": "process_images",
    "plans": "plans_images",
    "models": "models_images",
    "renders": "renders_images",
    "building": "building_images",
    "gallery": "gallery_images",
    "enterprise": "enterprise_portfolio_images",
    "management": "management_portfolio_images",
    "pit": "pit_display_images",
}
DEFAULT_LABELS = {
    "texte": "Texte",
    "process": "Processus / Croquis",
    "plans": "Plans & Coupes",
    "models": "Maquettes",
    "renders": "Rendus 3D",
    "building": "Bâtiment",
    "gallery": "Images",
    "video": "Vidéo",
    "social": "Réseaux sociaux",
    "pdfs": "PDF",
}
DEFAULT_HEADINGS = {"building": "Images du Bâtiment"}
ORDER = {
    "Architecture": ["texte", "process", "plans", "models", "renders", "building", "gallery", "video", "pdfs"],
    "Lycée": ["texte", "gallery", "video", "pdfs"],
}
COLOR_SECTIONS = {"Architecture": {"plans", "building", "gallery"}, "Lycée": set()}

# Per-project layouts that differ from the category defaults (taken from the live site).
OVERRIDES = {
    "6ac91cdaf5d8c0a29f64dace": {  # S2 Intensif structure
        "order": ["gallery", "models", "video", "pdfs"],
        "labels": {"gallery": "Compte rendu", "models": "Maquette"},
    },
    "6a4fb9fc36f3d781488766d7": {  # Enigmati'X
        "order": ["gallery", "plans", "process", "renders", "video", "pdfs"],
        "labels": {"plans": "Rubee X", "process": "Statique avec Frottement", "renders": "Présentation Finale"},
        "cover_scale": 1.5,
    },
    "6acced17fd972c4b34bf42e6": {  # Steam Racing World Finals Singapour 2025
        "order": ["texte", "renders", "plans", "process", "enterprise", "management", "video", "pit", "social", "pdfs"],
        "labels": {
            "renders": "RENDU 3D",
            "plans": "ENGINEERING DRAWING",
            "process": "ENGINEERING PORTFOLIO",
            "enterprise": "ENTERPRISE PORTFOLIO",
            "management": "MANAGEMENT PORTFOLIO",
            "pit": "Pit display",
        },
        "social": {
            "https://www.instagram.com/aeris.racing/": "Instagram — @aeris.racing",
            "https://www.linkedin.com/company/aeris-racing": "LinkedIn — AERIS RACING",
            "https://www.youtube.com/@AerisF1inschoolyoutube/videos": "YouTube — @AerisF1inschoolyoutube",
            "https://www.stemracing.com/": "STEM Racing — stemracing.com",
        },
    },
}

warnings: list[str] = []
resources = json.loads((ROOT / "manifest.json").read_text())["resources"]


def api_json(fragment: str):
    for url, entry in resources.items():
        if url.startswith(API) and fragment in url:
            return json.loads((ROOT / entry["file"]).read_text())
    raise KeyError(fragment)


def archived(url: str) -> Path | None:
    entry = resources.get(url)
    return ROOT / entry["file"] if entry else None


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"


def readable_name(url: str) -> str:
    name = urlparse(url).path.rsplit("/", 1)[-1]
    return re.sub(r"^[0-9a-f]{9}_", "", name) or name


class MediaFolder:
    """Copies archived files into media/<folder>/ with readable, unique names."""

    def __init__(self, folder: str):
        self.folder = folder
        self.by_url: dict[str, str] = {}
        self.used: set[str] = set()

    def add(self, url: str, name: str | None = None) -> str | None:
        if url in self.by_url:
            return self.by_url[url]
        src = archived(url)
        if src is None or not src.exists():
            warnings.append(f"missing from archive, skipped: {url}")
            return None
        stem, dot, ext = (name or readable_name(url)).rpartition(".")
        if not dot:
            stem, ext = ext, ""
        candidate, n = f"{stem}.{ext}" if ext else stem, 2
        while candidate.lower() in self.used:
            candidate = f"{stem}-{n}.{ext}" if ext else f"{stem}-{n}"
            n += 1
        self.used.add(candidate.lower())
        rel = f"{self.folder}/{candidate}"
        (MEDIA / self.folder).mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, MEDIA / rel)
        self.by_url[url] = rel
        return rel


def youtube_video(url: str) -> dict | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if parsed.netloc.endswith("youtu.be"):
        vid = parsed.path.strip("/")
    elif "v" in query:
        vid = query["v"][0]
    else:
        match = re.search(r"/(?:live|embed|shorts)/([\w-]{6,})", parsed.path)
        vid = match.group(1) if match else None
    if not vid:
        warnings.append(f"not a YouTube video URL, skipped: {url}")
        return None
    video = {"youtube": vid}
    start = query.get("t", [""])[0].rstrip("s")
    if start.isdigit() and int(start) > 1:
        video["start"] = int(start)
    return video


def youtube_thumbnail(vid: str) -> str | None:
    for quality in ("maxresdefault", "hqdefault", "sddefault", "mqdefault"):
        url = f"https://img.youtube.com/vi/{vid}/{quality}.jpg"
        if url in resources:
            return thumbs.add(url, f"{vid}.jpg")
    warnings.append(f"no archived thumbnail for YouTube video {vid}")
    return None


thumbs = MediaFolder("videos")


def export_projects() -> dict:
    listing = api_json("entities/Project?sort=-order")
    projects, slugs = [], set()
    for category in PROJECT_CATEGORIES:
        for item in listing:
            if item.get("category") != category or item["title"] in HIDDEN_TITLES:
                continue
            try:
                record = api_json(f"entities/Project/{item['id']}")
            except KeyError:
                record = item
            projects.append(export_project(record, category, slugs))
    return {"categories": PROJECT_CATEGORIES, "projects": projects}


def export_project(rec: dict, category: str, slugs: set[str]) -> dict:
    slug = base = slugify(rec["title"])
    n = 2
    while slug in slugs:
        slug, n = f"{base}-{n}", n + 1
    slugs.add(slug)
    media = MediaFolder(f"projets/{slug}")
    override = OVERRIDES.get(rec["id"], {})
    labels = {**DEFAULT_LABELS, **override.get("labels", {})}
    colored = COLOR_SECTIONS[category]

    project = {
        "id": rec["id"],
        "slug": slug,
        "title": rec["title"],
        "category": category,
        "year": rec.get("year") or "",
        "cover": media.add(rec["cover_image"]) if rec.get("cover_image") else None,
    }
    if override.get("cover_scale"):
        project["cover_scale"] = override["cover_scale"]

    sections = []
    for sid in override.get("order", ORDER[category]):
        section = {"id": sid, "label": labels[sid]}
        if sid in DEFAULT_HEADINGS and sid not in override.get("labels", {}):
            section["heading"] = DEFAULT_HEADINGS[sid]
        if sid == "texte":
            if not (rec.get("description") or "").strip():
                continue
            section.update(type="text", text=rec["description"].strip())
        elif sid in IMAGE_FIELDS:
            images = [p for p in (media.add(u) for u in rec.get(IMAGE_FIELDS[sid]) or []) if p]
            if not images:
                continue
            section.update(type="images", grayscale=sid not in colored, images=images)
        elif sid == "video":
            urls = ([rec["youtube_url"]] if rec.get("youtube_url") else []) + (rec.get("video_urls") or [])
            videos = []
            for url in urls:
                video = youtube_video(url)
                if video:
                    video["thumbnail"] = youtube_thumbnail(video["youtube"])
                    videos.append(video)
            if not videos:
                continue
            section.update(type="videos", grayscale=True, videos=videos)
        elif sid == "social":
            names = override.get("social", {})
            links = [{"label": names.get(u, u), "url": u} for u in rec.get("links") or []]
            if not links:
                continue
            section.update(type="links", links=links)
        elif sid == "pdfs":
            files = []
            for url, viewable in [(u, True) for u in rec.get("pdf_files") or []] + [
                (u, False) for u in rec.get("downloadable_files") or []
            ]:
                path = media.add(url)
                if path:
                    files.append({"file": path, "name": readable_name(url).lower(), "viewable": viewable})
            if not files:
                continue
            section.update(type="pdfs", files=files, images_zip=True)
        sections.append(section)
    project["sections"] = sections
    return project


def export_photos() -> dict:
    collections = api_json("entities/PhotoCollection?sort=-order")
    categories = []
    for name in PHOTO_CATEGORIES:
        media = MediaFolder(f"photos/{slugify(name)}")
        items = []
        for col in (c for c in collections if c.get("category") == name):
            for url in col.get("images") or ([col["cover_image"]] if col.get("cover_image") else []):
                path = media.add(url)
                if path:
                    kind = "video" if path.lower().endswith((".mp4", ".webm", ".mov")) else "image"
                    items.append({"title": col["title"], "file": path, "type": kind})
        categories.append({"name": name, "items": items})
    return {"categories": categories}


def export_videos() -> dict:
    data = api_json("entities/Video/v2/list")
    videos = []
    for item in sorted(data["items"], key=lambda v: v.get("order", 0)):
        video = youtube_video(item["youtube_url"])
        if video:
            video = {"title": item["title"], **video, "thumbnail": youtube_thumbnail(video["youtube"])}
            videos.append(video)
    return {"videos": videos}


class CVParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.contact = ""
        self.sections: list[dict] = []
        self.buf: list[str] | None = None
        self.kind = ""
        self.inside_cv = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "cv":
            self.inside_cv = True
        elif attrs.get("id") == "pdf":
            self.inside_cv = False
        if not self.inside_cv:
            return
        if tag == "p" and "font-body" in (attrs.get("class") or "") and not self.contact:
            self.buf, self.kind = [], "contact"
        elif tag == "h3":
            self.buf, self.kind = [], "h3"
        elif tag == "li":
            self.buf, self.kind = [], "li"

    def handle_endtag(self, tag):
        if self.buf is None or tag not in {"p", "h3", "li"}:
            return
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if self.kind == "contact" and tag == "p":
            self.contact = text
        elif self.kind == "h3" and tag == "h3":
            self.sections.append({"title": text, "items": []})
        elif self.kind == "li" and tag == "li":
            self.sections[-1]["items"].append(text)
        else:
            return
        self.buf = None

    def handle_data(self, data):
        if self.buf is not None:
            self.buf.append(data)


def export_cv() -> dict:
    page = (ROOT / "snapshots" / "home.html").read_text()
    parser = CVParser()
    parser.feed(page)
    media = MediaFolder("cv")
    hero = re.search(r'<main.*?<img src="([^"]+)"', page, re.S).group(1)
    pdf = re.search(r'https://media\.base44\.com/files/public/[^"\s]+_CV\.pdf', json.dumps(resources))
    pdf_url = pdf.group(0) if pdf else None
    return {
        "hero": media.add(html.unescape(hero)),
        "hero_alt": "Goldschmidt Levi",
        "contact": parser.contact,
        "sections": parser.sections,
        "pdf": {"file": media.add(pdf_url), "name": "cv.pdf"} if pdf_url else None,
    }


def export_site() -> dict:
    media = MediaFolder("site")
    logo = "https://media.base44.com/images/public/6a188961cb313af9686e2905/d0fd4840f_logo.png"
    return {
        "name": "GOLDSCHMIDT LEVI",
        "description": "Portfolio de Lévi Goldschmidt — architecture, projets, photographies et vidéos.",
        "language": "fr",
        "base_url": "",
        "logo": media.add(logo, "logo.png"),
        "nav": [
            {"label": "PROJETS", "href": "projets/"},
            {"label": "PHOTOS", "href": "photos/"},
            {"label": "VIDÉOS", "href": "videos/"},
            {"label": "CV", "href": "cv/"},
        ],
    }


def main() -> int:
    for path in (CONTENT, MEDIA):
        if path.exists():
            shutil.rmtree(path)
    CONTENT.mkdir()
    outputs = {
        "site.json": export_site(),
        "projects.json": export_projects(),
        "photos.json": export_photos(),
        "videos.json": export_videos(),
        "cv.json": export_cv(),
    }
    for name, data in outputs.items():
        (CONTENT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    files = [p for p in MEDIA.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    print(f"content/: {', '.join(outputs)}")
    print(f"media/: {len(files)} files, {size / 1e6:.1f} MB")
    for warning in dict.fromkeys(warnings):
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
