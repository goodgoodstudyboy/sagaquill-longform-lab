# SagaQuill

SagaQuill is a local long-form web novel production pipeline. Give it a title or a complete project brief, and it can run project intake, story planning, world bible generation, volume outlines, chapter plans, prose drafting, review, continuity memory, final review, and delivery packaging.

It is not a “one API call writes a whole book” toy. It treats long fiction as a resumable, auditable, repairable workflow. By default it reads your local Codex provider configuration, but the Web UI can also save a project-local provider override for OpenAI-compatible, Responses-compatible, or Anthropic/Claude-compatible gateways.

[中文 README](README.md)

## Features

- Single-book generation from a sparse title or a detailed brief.
- Batch scheduling from CSV proposals with concurrency, pause, resume, and retry.
- Market profiles for long-form Qidian-style planning and Tomato-style high-hook pacing.
- Soft progression and hard realm progression with tiers, resources, enemy bands, and breakthrough milestones.
- Long-range consistency through style bible, character voice cards, promise ledger, causality graph, continuity state, and long memory.
- Automatic recovery through model review, local quality gates, volume-level logic audits, window repair, structured-output repair, and upstream retries.
- Explainable quality reports with red lines, failures, warnings, evidence, and repair actions for continuity, character consistency, timeline, repetition, length, terminology density, and progression risks.
- Multi-model routing where the flagship model handles planning/prose/review and the light model handles normalization, continuity, memory, and packaging.
- Local Web UI for provider config, book launch, batch import, task status, pause/resume, preview, and delivery export.
- Delivery artifacts including `novel.md`, `novel.txt`, `book-summary.md`, volume Markdown, table of contents, submission guide, quality report, EPUB, and manifest.
- Multi-language output for Simplified Chinese, English, Japanese, Korean, Spanish, French, German, and custom language codes.

## Quick Start

### Docker

The panel will be available at `http://127.0.0.1:8765`.

```bash
TOKEN=$(openssl rand -hex 24)
docker run -d --name sagaquill --restart unless-stopped \
  -p 8765:8765 \
  -e SAGAQUILL_ACCESS_TOKEN="$TOKEN" \
  -v sagaquill-runs:/app/runs \
  -v sagaquill-state:/app/.sagaquill \
  ghcr.io/goodgoodstudyboy/sagaquill-longform-lab:latest
echo "http://127.0.0.1:8765  token=$TOKEN"
```

If you cloned the repository:

```bash
cp .env.example .env
docker compose up -d
```

### Local Python

```bash
git clone https://github.com/goodgoodstudyboy/sagaquill-longform-lab.git sagaquill
cd sagaquill
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m sagaquill doctor
python -m sagaquill serve --host 127.0.0.1 --port 8765
```

Windows PowerShell:

```powershell
git clone https://github.com/goodgoodstudyboy/sagaquill-longform-lab.git sagaquill
cd sagaquill
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m sagaquill doctor
python -m sagaquill serve --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

## Quality Reports

Completed books include explainable quality artifacts:

- `data/quality-report.json`: machine-readable full report.
- `delivery/quality-report.md`: human-readable report in the delivery package.
- The Web UI completed-task panel shows quality status and score, with a direct report link.

The report groups issues by `red`, `fail`, `warn`, and `info`, and includes evidence plus suggested repair actions. It covers cleanup hygiene, repetition/wateriness, length control, terminology density, continuity, character consistency, timeline, hard progression, and ending closure. See [docs/QUALITY.md](docs/QUALITY.md) for the current policy.

### Linux systemd Install

```bash
curl -fsSL https://raw.githubusercontent.com/goodgoodstudyboy/sagaquill-longform-lab/main/scripts/bootstrap-linux.sh | sudo bash
```

To expose the panel beyond localhost, set an access token:

```bash
curl -fsSL https://raw.githubusercontent.com/goodgoodstudyboy/sagaquill-longform-lab/main/scripts/bootstrap-linux.sh | sudo env \
  SAGAQUILL_HOST=0.0.0.0 \
  SAGAQUILL_ACCESS_TOKEN=change-me-long-random-token \
  bash
```

Common commands:

```bash
sudo systemctl status sagaquill
sudo systemctl restart sagaquill
sudo journalctl -u sagaquill -f
```

## Provider Configuration

SagaQuill resolves provider settings in this order:

- Project-local `.sagaquill/provider.json`
- Environment variables such as `SAGAQUILL_BASE_URL`, `SAGAQUILL_MODEL`, `OPENAI_API_KEY`, `ANTHROPIC_AUTH_TOKEN`
- Local Codex configuration such as `~/.codex/config.toml` and `~/.codex/auth.json`

Example OpenAI-compatible / Responses-compatible setup:

```bash
SAGAQUILL_BASE_URL=https://your-gateway.example
SAGAQUILL_WIRE_API=responses
SAGAQUILL_MODEL=gpt-5.4
SAGAQUILL_LIGHT_MODEL=gpt-5.4-mini
SAGAQUILL_REVIEW_MODEL=gpt-5.4
OPENAI_API_KEY=sk-...
SAGAQUILL_CONTINUATION_MODE=hybrid
```

Example Anthropic-compatible setup:

```bash
ANTHROPIC_BASE_URL=https://your-anthropic-gateway.example
ANTHROPIC_AUTH_TOKEN=<anthropic-token>
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
```

Do not commit real keys. The default `.gitignore` excludes `.sagaquill/provider.json`, `.novelforge/`, `runs/`, and other local state.

## Multi-Language Output

SagaQuill has a real `output_language` field. It is not only documentation.

Supported built-in options:

- `zh-Hans`: Simplified Chinese, default and best tuned.
- `en`: English.
- `ja`: Japanese.
- `ko`: Korean.
- `es`: Spanish.
- `fr`: French.
- `de`: German.
- Custom language codes: passed through to prompts and metadata, with quality depending on the selected model.

Example:

```json
{
  "title": "Night Courier",
  "output_language": "en",
  "genre": "urban fantasy",
  "market_profile": "tomato_mass",
  "target_total_chars": 2000000
}
```

What is adapted:

- Planning, drafting, review, packaging prompts ask for the target language.
- Non-Chinese projects no longer inherit Chinese reader / Chinese genre fallbacks.
- `novel.md`, `novel.txt`, volume Markdown, table of contents, submission guide, and EPUB metadata use language-aware structural labels.
- Internal JSON field names remain English snake_case as part of the system protocol.

Limitations:

- Chinese web-fiction pacing can be transferred to other languages, but cultural expression still depends on model quality.
- Character-count controls are engineering controls, not English word counts.
- The Chinese long-form path remains the most tested profile.

## Project Input

Minimal:

```json
{
  "title": "The Watchmaker At The End Of The Tide"
}
```

Detailed:

```json
{
  "title": "Night Courier",
  "output_language": "en",
  "genre": "urban fantasy",
  "audience": "fast-paced web fiction readers",
  "tone": "grounded, tense, high-hook",
  "premise": "A courier delivers final orders to haunted addresses and receives one clue about the living world after every completed job.",
  "hook": "The first order goes to an apartment block demolished three years ago, but the customer is waiting behind the door.",
  "market_profile": "tomato_mass",
  "progression_mode": "soft_progression",
  "target_total_chars": 2000000,
  "target_chars_per_chapter": 2500,
  "ending_mode": "standalone",
  "must_include": ["one strong hook per delivery", "working-class job texture", "short-cycle rewards"],
  "avoid": ["too much opening exposition", "multiple chapters without a new delivery"]
}
```

## Batch Mode

The Web UI can import CSV proposals and create a batch. The batch layer only handles import, queueing, concurrency, pause, resume, and retry. Each book still runs through the full single-book pipeline.

Batch-level settings include concurrency, total length, chapter length, chapter count, volume count, ending mode, POV, output language, market profile, progression mode, and provider snapshot.

The provider snapshot is intentionally frozen when the batch is created, so resuming an old batch does not accidentally switch its gateway/model/key because the global provider changed later.

## Delivery Artifacts

Each completed run writes:

```text
runs/<book>/
  novel.md
  novel.txt
  book-summary.md
  data/
  volumes/
  plans/
  chapters/
  reviews/
  state/
  audits/
  delivery/
    delivery-manifest.json
    table-of-contents.md
    submission-guide.md
    volumes/
    epub/
```

`delivery/` is the most convenient directory for packaging or handoff.

## Security

- Keep the panel on `127.0.0.1` unless you know what you are doing.
- If binding to `0.0.0.0`, set `SAGAQUILL_ACCESS_TOKEN`.
- Do not expose the panel to the public internet without authentication.
- Do not commit `.sagaquill/provider.json`, `.novelforge/`, `runs/`, `.env`, key files, or real API tokens.

## Development

```bash
python -m unittest discover -s tests -v
```

Release:

```bash
export GITHUB_TOKEN=<github-token>
python scripts/release.py 0.7.3 --wait-docker
```

## License

See [LICENSE](LICENSE).
