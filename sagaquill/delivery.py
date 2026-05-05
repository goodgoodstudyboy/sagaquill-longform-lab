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
from .projectio import is_chinese_output_language, normalized_output_language
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
        "output_language": spec.output_language,
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
        title = volume_titles.get(volume_index) or _volume_fallback_title(spec, volume_index)
        body = [f"# {spec.title}", "", f"## {_volume_heading(spec, volume_index, title)}", ""]
        for chapter in volume_chapters:
            body.extend([f"### {_chapter_heading(spec, chapter.index, chapter.title)}", "", chapter.draft.strip(), ""])
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
    terms = _terms(spec)
    lines = [
        f"# {spec.title} {terms['toc']}",
        "",
        _kv(terms["total_chars"], book_package.total_chars, spec),
        _kv(terms["chapters"], book_package.chapter_count, spec),
        _kv(terms["volumes"], book_package.volume_count, spec),
        "",
    ]
    current_volume = None
    for chapter in sorted(chapters, key=lambda item: item.index):
        if current_volume != chapter.volume_index:
            current_volume = chapter.volume_index
            title = volume_titles.get(current_volume, "")
            lines.extend(["", f"## {_volume_heading(spec, current_volume, title)}".rstrip(), ""])
        lines.append(f"- {_chapter_heading(spec, chapter.index, chapter.title)}")
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
    terms = _terms(spec)
    lines = [
        f"# {spec.title} {terms['submission_guide']}",
        "",
        f"## {terms['basic_info']}",
        "",
        _kv(terms["genre"], spec.genre, spec),
        _kv(terms["audience"], spec.audience, spec),
        _kv(terms["output_language"], spec.output_language, spec),
        _kv(terms["market_profile"], spec.market_profile, spec),
        _kv(terms["progression_mode"], spec.progression_mode, spec),
        _kv(terms["total_chars"], total_chars, spec),
        _kv(terms["chapters"], len(chapters), spec),
        _kv(terms["volumes"], spec.volume_count, spec),
        _kv(terms["final_score"], final_review.score, spec),
        "",
        f"## {terms['marketing_hook']}",
        "",
        book_package.marketing_blurb or spec.hook or spec.premise,
        "",
        f"## {terms['synopsis']}",
        "",
        book_package.factual_summary or book_outline.one_line_summary,
        "",
        f"## {terms['files']}",
        "",
        _file_item("../novel.md", terms["novel_md"], spec),
        _file_item("../novel.txt", terms["novel_txt"], spec),
        _file_item("../book-summary.md", terms["book_summary"], spec),
        _file_item("table-of-contents.md", terms["toc_file"], spec),
        _file_item("volumes/", terms["volumes_file"], spec),
        _file_item("epub/", terms["epub_file"], spec),
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
    <dc:language>{html.escape(_epub_language(spec))}</dc:language>
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
    lang = html.escape(_html_language(spec))
    terms = _terms(spec)
    lines = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<!DOCTYPE html>",
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}">',
        f"<head><title>{html.escape(terms['toc'])}</title></head>",
        "<body>",
        '<nav epub:type="toc" id="toc">',
        f"<h1>{html.escape(spec.title)}</h1>",
        "<ol>",
    ]
    current_volume = None
    for chapter, filename in zip(chapters, chapter_files):
        if current_volume != chapter.volume_index:
            current_volume = chapter.volume_index
            lines.append(f"<li>{html.escape(_volume_heading(spec, current_volume, volume_titles.get(current_volume, '').strip()))}</li>")
        lines.append(f'<li><a href="{filename}">{html.escape(_chapter_heading(spec, chapter.index, chapter.title))}</a></li>')
    lines.extend(["</ol>", "</nav>", "</body>", "</html>"])
    return "\n".join(lines)


def _chapter_xhtml(spec: ProjectSpec, chapter: ChapterResult) -> str:
    paragraphs = [_markdown_line_to_html(line) for line in chapter.draft.splitlines() if line.strip()]
    body = "\n".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
    lang = html.escape(_html_language(spec))
    heading = html.escape(_chapter_heading(spec, chapter.index, chapter.title))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="{lang}">
<head><title>{heading}</title></head>
<body>
<h1>{html.escape(spec.title)}</h1>
<h2>{heading}</h2>
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


def _is_zh(spec: ProjectSpec) -> bool:
    return is_chinese_output_language(spec.output_language)


def _epub_language(spec: ProjectSpec) -> str:
    value = normalized_output_language(spec.output_language)
    mapping = {
        "zh-Hans": "zh-CN",
        "zh-CN": "zh-CN",
        "zh-Hant": "zh-TW",
        "zh-TW": "zh-TW",
        "en": "en",
        "ja": "ja",
        "ko": "ko",
        "es": "es",
        "fr": "fr",
        "de": "de",
    }
    return mapping.get(value, value or "zh-CN")


def _html_language(spec: ProjectSpec) -> str:
    return _epub_language(spec)


def _chapter_heading(spec: ProjectSpec, index: object, title: object) -> str:
    title_text = str(title or "").strip()
    return _format_term(spec, "chapter_heading", index=index, title=title_text)


def _volume_fallback_title(spec: ProjectSpec, index: object) -> str:
    return _format_term(spec, "volume_fallback", index=index)


def _volume_heading(spec: ProjectSpec, index: object, title: object) -> str:
    title_text = str(title or "").strip()
    return _format_term(spec, "volume_heading", index=index, title=title_text)


def _kv(label: str, value: object, spec: ProjectSpec) -> str:
    return f"- {label}：{value}" if _is_zh(spec) else f"- {label}: {value}"


def _file_item(path: str, description: str, spec: ProjectSpec) -> str:
    return f"- `{path}`：{description}" if _is_zh(spec) else f"- `{path}`: {description}"


def _terms(spec: ProjectSpec) -> dict[str, str]:
    language_id = normalized_output_language(spec.output_language)
    tables: dict[str, dict[str, str]] = {
        "zh-Hans": {
            "toc": "目录",
            "total_chars": "字数",
            "chapters": "章节",
            "volumes": "分卷",
            "submission_guide": "交付说明",
            "basic_info": "基本信息",
            "genre": "题材",
            "audience": "受众",
            "output_language": "输出语言",
            "market_profile": "平台模式",
            "progression_mode": "升级模式",
            "final_score": "终审分",
            "marketing_hook": "一句话卖点",
            "synopsis": "剧情简介",
            "files": "文件清单",
            "novel_md": "整书 Markdown",
            "novel_txt": "整书纯文本",
            "book_summary": "成书简介与目录",
            "toc_file": "独立目录",
            "volumes_file": "分卷 Markdown",
            "epub_file": "EPUB 文件",
            "chapter_heading": "第{index}章 {title}",
            "volume_heading": "第{index}卷 {title}",
            "volume_fallback": "第{index}卷",
        },
        "en": {
            "toc": "Table Of Contents",
            "total_chars": "Total characters",
            "chapters": "Chapters",
            "volumes": "Volumes",
            "submission_guide": "Submission Guide",
            "basic_info": "Basic Info",
            "genre": "Genre",
            "audience": "Audience",
            "output_language": "Output language",
            "market_profile": "Market profile",
            "progression_mode": "Progression mode",
            "final_score": "Final review score",
            "marketing_hook": "One-Line Hook",
            "synopsis": "Synopsis",
            "files": "Files",
            "novel_md": "Full novel in Markdown",
            "novel_txt": "Full novel in plain text",
            "book_summary": "Book summary and table of contents",
            "toc_file": "Standalone table of contents",
            "volumes_file": "Volume Markdown files",
            "epub_file": "EPUB files",
            "chapter_heading": "Chapter {index}: {title}",
            "volume_heading": "Volume {index}: {title}",
            "volume_fallback": "Volume {index}",
        },
        "ja": {
            "toc": "目次",
            "total_chars": "文字数",
            "chapters": "章数",
            "volumes": "巻数",
            "submission_guide": "提出ガイド",
            "basic_info": "基本情報",
            "genre": "ジャンル",
            "audience": "読者層",
            "output_language": "出力言語",
            "market_profile": "市場プロファイル",
            "progression_mode": "成長モード",
            "final_score": "最終評価点",
            "marketing_hook": "一文フック",
            "synopsis": "あらすじ",
            "files": "ファイル一覧",
            "novel_md": "全編 Markdown",
            "novel_txt": "全編プレーンテキスト",
            "book_summary": "作品資料と目次",
            "toc_file": "独立目次",
            "volumes_file": "巻別 Markdown",
            "epub_file": "EPUB ファイル",
            "chapter_heading": "第{index}章 {title}",
            "volume_heading": "第{index}巻 {title}",
            "volume_fallback": "第{index}巻",
        },
        "ko": {
            "toc": "목차",
            "total_chars": "글자 수",
            "chapters": "화수",
            "volumes": "권수",
            "submission_guide": "제출 안내",
            "basic_info": "기본 정보",
            "genre": "장르",
            "audience": "독자층",
            "output_language": "출력 언어",
            "market_profile": "시장 모드",
            "progression_mode": "성장 모드",
            "final_score": "최종 검토 점수",
            "marketing_hook": "한 줄 훅",
            "synopsis": "줄거리",
            "files": "파일 목록",
            "novel_md": "전체 소설 Markdown",
            "novel_txt": "전체 소설 텍스트",
            "book_summary": "작품 요약과 목차",
            "toc_file": "독립 목차",
            "volumes_file": "권별 Markdown",
            "epub_file": "EPUB 파일",
            "chapter_heading": "{index}장 {title}",
            "volume_heading": "{index}권 {title}",
            "volume_fallback": "{index}권",
        },
        "es": {
            "toc": "Índice",
            "total_chars": "Caracteres",
            "chapters": "Capítulos",
            "volumes": "Volúmenes",
            "submission_guide": "Guía de entrega",
            "basic_info": "Información básica",
            "genre": "Género",
            "audience": "Audiencia",
            "output_language": "Idioma de salida",
            "market_profile": "Perfil de mercado",
            "progression_mode": "Modo de progresión",
            "final_score": "Puntuación final",
            "marketing_hook": "Gancho en una línea",
            "synopsis": "Sinopsis",
            "files": "Archivos",
            "novel_md": "Novela completa en Markdown",
            "novel_txt": "Novela completa en texto plano",
            "book_summary": "Resumen y tabla de contenidos",
            "toc_file": "Índice independiente",
            "volumes_file": "Markdown por volumen",
            "epub_file": "Archivos EPUB",
            "chapter_heading": "Capítulo {index}: {title}",
            "volume_heading": "Volumen {index}: {title}",
            "volume_fallback": "Volumen {index}",
        },
        "fr": {
            "toc": "Table des matières",
            "total_chars": "Caractères",
            "chapters": "Chapitres",
            "volumes": "Volumes",
            "submission_guide": "Guide de livraison",
            "basic_info": "Informations de base",
            "genre": "Genre",
            "audience": "Public",
            "output_language": "Langue de sortie",
            "market_profile": "Profil de marché",
            "progression_mode": "Mode de progression",
            "final_score": "Score final",
            "marketing_hook": "Accroche en une phrase",
            "synopsis": "Synopsis",
            "files": "Fichiers",
            "novel_md": "Roman complet en Markdown",
            "novel_txt": "Roman complet en texte brut",
            "book_summary": "Résumé et table des matières",
            "toc_file": "Table des matières autonome",
            "volumes_file": "Markdown par volume",
            "epub_file": "Fichiers EPUB",
            "chapter_heading": "Chapitre {index} : {title}",
            "volume_heading": "Volume {index} : {title}",
            "volume_fallback": "Volume {index}",
        },
        "de": {
            "toc": "Inhaltsverzeichnis",
            "total_chars": "Zeichen",
            "chapters": "Kapitel",
            "volumes": "Bände",
            "submission_guide": "Übergabeanleitung",
            "basic_info": "Basisdaten",
            "genre": "Genre",
            "audience": "Zielgruppe",
            "output_language": "Ausgabesprache",
            "market_profile": "Marktprofil",
            "progression_mode": "Progressionsmodus",
            "final_score": "Abschlusswertung",
            "marketing_hook": "Ein-Satz-Aufhänger",
            "synopsis": "Zusammenfassung",
            "files": "Dateien",
            "novel_md": "Vollständiger Roman als Markdown",
            "novel_txt": "Vollständiger Roman als Text",
            "book_summary": "Zusammenfassung und Inhaltsverzeichnis",
            "toc_file": "Eigenes Inhaltsverzeichnis",
            "volumes_file": "Markdown-Dateien pro Band",
            "epub_file": "EPUB-Dateien",
            "chapter_heading": "Kapitel {index}: {title}",
            "volume_heading": "Band {index}: {title}",
            "volume_fallback": "Band {index}",
        },
    }
    return tables.get(language_id, tables["en"])


def _format_term(spec: ProjectSpec, key: str, **values: object) -> str:
    return _terms(spec)[key].format(**values).strip()
