from __future__ import annotations

import html
import json
import re
import time
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import BookOutline, BookPackage, ChapterResult, FinalReview, ProjectSpec
from .util import ensure_directory, slugify


def build_delivery_artifacts(
    output_dir: str | Path,
    *,
    spec: ProjectSpec,
    book_outline: BookOutline,
    chapters: list[ChapterResult],
    book_package: BookPackage,
    final_review: FinalReview,
    total_chars: int,
) -> dict[str, Any]:
    root = Path(output_dir)
    delivery_dir = ensure_directory(root / "delivery")
    volumes_dir = ensure_directory(delivery_dir / "volumes")

    ordered = sorted(chapters, key=lambda item: item.index)
    volume_paths = _write_volume_markdown(volumes_dir, spec, book_outline, ordered)
    toc_path = _write_table_of_contents(delivery_dir, spec, book_outline, ordered, book_package)
    guide_path = _write_submission_guide(delivery_dir, spec, book_outline, ordered, book_package, final_review, total_chars)
    epub_path = _write_epub(delivery_dir, spec, book_outline, ordered, book_package)

    manifest = {
        "title": spec.title,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chapter_count": len(ordered),
        "volume_count": spec.volume_count,
        "total_chars": total_chars,
        "market_profile": spec.market_profile,
        "progression_mode": spec.progression_mode,
        "files": {
            "novel_md": "../novel.md",
            "novel_txt": "../novel.txt",
            "book_summary": "../book-summary.md",
            "table_of_contents": _relative_to(toc_path, delivery_dir),
            "submission_guide": _relative_to(guide_path, delivery_dir),
            "epub": _relative_to(epub_path, delivery_dir),
            "volumes": [_relative_to(path, delivery_dir) for path in volume_paths],
        },
    }
    manifest_path = delivery_dir / "delivery-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _write_volume_markdown(
    volumes_dir: Path,
    spec: ProjectSpec,
    book_outline: BookOutline,
    chapters: list[ChapterResult],
) -> list[Path]:
    by_volume: dict[int, list[ChapterResult]] = {}
    for chapter in chapters:
        by_volume.setdefault(chapter.volume_index, []).append(chapter)
    volume_titles = {volume.index: volume.title for volume in book_outline.volumes}
    paths: list[Path] = []
    for volume_index in sorted(by_volume):
        volume_chapters = sorted(by_volume[volume_index], key=lambda item: item.index)
        title = volume_titles.get(volume_index) or f"第{volume_index}卷"
        body = [f"# {spec.title}", "", f"## 第{volume_index}卷 {title}", ""]
        for chapter in volume_chapters:
            body.extend([f"### 第{chapter.index}章 {chapter.title}", "", chapter.draft.strip(), ""])
        path = volumes_dir / f"volume-{volume_index:02d}-{slugify(title)}.md"
        path.write_text("\n".join(body).strip() + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _write_table_of_contents(
    delivery_dir: Path,
    spec: ProjectSpec,
    book_outline: BookOutline,
    chapters: list[ChapterResult],
    book_package: BookPackage,
) -> Path:
    volume_titles = {volume.index: volume.title for volume in book_outline.volumes}
    lines = [
        f"# {spec.title} 目录",
        "",
        f"- 字数：{book_package.total_chars}",
        f"- 章节：{book_package.chapter_count}",
        f"- 分卷：{book_package.volume_count}",
        "",
    ]
    current_volume = None
    for chapter in sorted(chapters, key=lambda item: item.index):
        if current_volume != chapter.volume_index:
            current_volume = chapter.volume_index
            lines.extend(["", f"## 第{current_volume}卷 {volume_titles.get(current_volume, '')}".rstrip(), ""])
        lines.append(f"- 第{chapter.index}章 {chapter.title}")
    path = delivery_dir / "table-of-contents.md"
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def _write_submission_guide(
    delivery_dir: Path,
    spec: ProjectSpec,
    book_outline: BookOutline,
    chapters: list[ChapterResult],
    book_package: BookPackage,
    final_review: FinalReview,
    total_chars: int,
) -> Path:
    lines = [
        f"# {spec.title} 交付说明",
        "",
        "## 基本信息",
        "",
        f"- 题材：{spec.genre}",
        f"- 受众：{spec.audience}",
        f"- 平台模式：{spec.market_profile}",
        f"- 升级模式：{spec.progression_mode}",
        f"- 字数：{total_chars}",
        f"- 章节：{len(chapters)}",
        f"- 分卷：{spec.volume_count}",
        f"- 终审分：{final_review.score}",
        "",
        "## 一句话卖点",
        "",
        book_package.marketing_blurb or spec.hook or spec.premise,
        "",
        "## 剧情简介",
        "",
        book_package.factual_summary or book_outline.one_line_summary,
        "",
        "## 文件清单",
        "",
        "- `../novel.md`：整书 Markdown",
        "- `../novel.txt`：整书纯文本",
        "- `../book-summary.md`：成书简介与目录",
        "- `table-of-contents.md`：独立目录",
        "- `volumes/`：分卷 Markdown",
        "- `epub/`：EPUB 文件",
    ]
    path = delivery_dir / "submission-guide.md"
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def _write_epub(
    delivery_dir: Path,
    spec: ProjectSpec,
    book_outline: BookOutline,
    chapters: list[ChapterResult],
    book_package: BookPackage,
) -> Path:
    epub_dir = ensure_directory(delivery_dir / "epub")
    epub_path = epub_dir / f"{slugify(spec.title)}.epub"
    chapter_files = [f"chapter-{chapter.index:04d}.xhtml" for chapter in chapters]
    with zipfile.ZipFile(epub_path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _epub_container_xml())
        archive.writestr("OEBPS/content.opf", _epub_content_opf(spec, book_package, chapter_files))
        archive.writestr("OEBPS/nav.xhtml", _epub_nav_xhtml(spec, book_outline, chapters, chapter_files))
        for chapter, filename in zip(chapters, chapter_files):
            archive.writestr(f"OEBPS/{filename}", _chapter_xhtml(spec, chapter))
    return epub_path


def _epub_container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _epub_content_opf(spec: ProjectSpec, book_package: BookPackage, chapter_files: list[str]) -> str:
    items = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
    spine = []
    for index, filename in enumerate(chapter_files, start=1):
        item_id = f"chapter-{index:04d}"
        items.append(f'<item id="{item_id}" href="{filename}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{item_id}"/>')
    description = html.escape(book_package.marketing_blurb or spec.hook or spec.premise)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="book-id" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{html.escape(slugify(spec.title))}</dc:identifier>
    <dc:title>{html.escape(spec.title)}</dc:title>
    <dc:language>zh-CN</dc:language>
    <dc:creator>{html.escape(spec.protagonist or "SagaQuill")}</dc:creator>
    <dc:description>{description}</dc:description>
    <meta property="dcterms:modified">{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}</meta>
  </metadata>
  <manifest>
    {chr(10).join(items)}
  </manifest>
  <spine>
    {chr(10).join(spine)}
  </spine>
</package>
"""


def _epub_nav_xhtml(
    spec: ProjectSpec,
    book_outline: BookOutline,
    chapters: list[ChapterResult],
    chapter_files: list[str],
) -> str:
    volume_titles = {volume.index: volume.title for volume in book_outline.volumes}
    lines = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<!DOCTYPE html>",
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN">',
        "<head><title>目录</title></head>",
        "<body>",
        '<nav epub:type="toc" id="toc">',
        f"<h1>{html.escape(spec.title)}</h1>",
        "<ol>",
    ]
    current_volume = None
    for chapter, filename in zip(chapters, chapter_files):
        if current_volume != chapter.volume_index:
            current_volume = chapter.volume_index
            lines.append(f"<li>{html.escape('第' + str(current_volume) + '卷 ' + volume_titles.get(current_volume, '').strip())}</li>")
        lines.append(f'<li><a href="{filename}">第{chapter.index}章 {html.escape(chapter.title)}</a></li>')
    lines.extend(["</ol>", "</nav>", "</body>", "</html>"])
    return "\n".join(lines)


def _chapter_xhtml(spec: ProjectSpec, chapter: ChapterResult) -> str:
    paragraphs = [_markdown_line_to_html(line) for line in chapter.draft.splitlines() if line.strip()]
    body = "\n".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN">
<head><title>第{chapter.index}章 {html.escape(chapter.title)}</title></head>
<body>
<h1>{html.escape(spec.title)}</h1>
<h2>第{chapter.index}章 {html.escape(chapter.title)}</h2>
{body}
</body>
</html>
"""


def _markdown_line_to_html(line: str) -> str:
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", line.strip())
    return html.escape(cleaned)


def _relative_to(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
