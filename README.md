# SagaQuill

SagaQuill 是一个面向长篇网文生产的本地流水线：输入一个书名或完整 brief，系统会自动完成项目补全、全书策划、设定圣经、分卷蓝图、章节计划、正文生成、审校、连续性记忆、终审和交付打包。

它不是“一次 API 调用吐完一本书”的玩具，而是把长篇拆成可续跑、可审计、可回修的工程流程。默认使用本机 Codex provider 配置，也可以在 Web 面板里为当前项目单独配置 OpenAI 兼容、Responses 兼容或 Anthropic/Claude 兼容中转。

[English README](README.en.md)

## 核心能力

- 单书生成：稀疏输入只填标题也能启动，完整输入可控制题材、受众、字数、卷章、风格、禁写项和结局方式。
- 批量调度：CSV 提案可批量导入，按并发上限自动排队、启动、暂停、恢复和失败重跑。
- 平台模式：支持 `起点长篇` 和 `番茄爆款` 两套节奏取向。
- 升级模式：支持软升级，也支持硬境界、资源、敌人梯度、突破节点这类明确升级系统。
- 长线一致性：维护 style bible、角色声线卡、承诺账本、因果图、连续性状态和长线记忆。
- 自动回修：章节审校、本地质量门、卷级逻辑审计、窗口回修、结构修复和上游重试都有兜底。
- 可解释质检：生成 `quality-report.json` 和 `quality-report.md`，按红线、失败项、警告项展示连续性、人物、时间线、重复率、篇幅、术语密度和升级系统风险。
- 多模型路由：旗舰模型负责规划/正文/复杂审校，轻量模型负责结构修复、连续性、记忆和包装。
- Web 面板：本地浏览器里配置 provider、开书、批量导入、看进度、暂停恢复和导出交付包。
- 交付增强：生成 `novel.md`、`novel.txt`、`book-summary.md`、分卷 Markdown、目录、交付说明、质检报告、EPUB 和 manifest。
- 多语言输出：项目可选择输出语言，当前内置简体中文、English、日本語、한국어、Español、Français、Deutsch 及自定义语言码。

## 适合什么

- 想用 API 自动跑长篇网文草稿、设定、章节和交付包。
- 想批量验证题材、钩子、前期节奏和中长篇结构。
- 想把起点式长线规划、番茄式前期爆点、硬升级体系拆成可控参数。
- 想在本地或自己的服务器上运行，不把 key 放到第三方 SaaS。

不适合：

- 期望一次请求直接生成几十万字。
- 期望完全不审稿、不调参就稳定产出可直接商业发布的终稿。
- 把无鉴权面板暴露到公网。

## 质检报告

每本完成的书都会产出可解释质检报告：

- `data/quality-report.json`：机器可读的完整报告。
- `delivery/quality-report.md`：交付包里的可读报告。
- Web 面板完成态会显示质检状态和质检分，并提供“打开质检报告”入口。

质检报告会按 `red`、`fail`、`warn`、`info` 标注问题，并给出证据和修复动作。覆盖维度包括清稿卫生、重复率/水文、篇幅控制、术语密度、连续性、人物设定、时间线、硬升级系统和结尾闭环。

详细规则见 [docs/QUALITY.md](docs/QUALITY.md)。

## 快速开始

### Docker

最简单的方式是 Docker。启动后面板会出现在本机 `http://127.0.0.1:8765`。

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

如果你已经 clone 了仓库：

```bash
cp .env.example .env
docker compose up -d
```

常用操作：

```bash
docker logs -f sagaquill
docker rm -f sagaquill
```

### Python 本地运行

```bash
git clone https://github.com/goodgoodstudyboy/sagaquill-longform-lab.git sagaquill
cd sagaquill
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m sagaquill doctor
python -m sagaquill serve --host 127.0.0.1 --port 8765
```

Windows PowerShell：

```powershell
git clone https://github.com/goodgoodstudyboy/sagaquill-longform-lab.git sagaquill
cd sagaquill
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m sagaquill doctor
python -m sagaquill serve --host 127.0.0.1 --port 8765
```

打开：

```text
http://127.0.0.1:8765
```

### Linux systemd 一键部署

适合部署到自己的 Linux 服务器并常驻运行：

```bash
curl -fsSL https://raw.githubusercontent.com/goodgoodstudyboy/sagaquill-longform-lab/main/scripts/bootstrap-linux.sh | sudo bash
```

默认安装到 `/opt/sagaquill`，服务名是 `sagaquill.service`。

如果需要对外访问，必须设置 token：

```bash
curl -fsSL https://raw.githubusercontent.com/goodgoodstudyboy/sagaquill-longform-lab/main/scripts/bootstrap-linux.sh | sudo env \
  SAGAQUILL_HOST=0.0.0.0 \
  SAGAQUILL_ACCESS_TOKEN=change-me-long-random-token \
  bash
```

常用命令：

```bash
sudo systemctl status sagaquill
sudo systemctl restart sagaquill
sudo journalctl -u sagaquill -f
```

## Provider 配置

SagaQuill 会按以下顺序读取 provider：

- 当前项目 `.sagaquill/provider.json`
- 环境变量，如 `SAGAQUILL_BASE_URL`、`SAGAQUILL_MODEL`、`OPENAI_API_KEY`、`ANTHROPIC_AUTH_TOKEN`
- 本机 Codex 配置，如 `~/.codex/config.toml` 和 `~/.codex/auth.json`

面板里的 Provider 配置支持测试连接、保存当前项目覆盖、恢复默认 provider。

常见环境变量：

```bash
SAGAQUILL_BASE_URL=https://your-gateway.example
SAGAQUILL_WIRE_API=responses
SAGAQUILL_MODEL=gpt-5.4
SAGAQUILL_LIGHT_MODEL=gpt-5.4-mini
SAGAQUILL_REVIEW_MODEL=gpt-5.4
OPENAI_API_KEY=sk-...
SAGAQUILL_CONTINUATION_MODE=hybrid
```

Claude/Anthropic 兼容线路：

```bash
ANTHROPIC_BASE_URL=https://your-anthropic-gateway.example
ANTHROPIC_AUTH_TOKEN=<anthropic-token>
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
```

不要把真实 key 写进 README、issue、commit 或公开镜像。项目默认 `.gitignore` 会忽略 `.sagaquill/provider.json`、`.novelforge/`、`runs/` 等本地状态。

## 多语言小说

现在项目有真实的 `output_language` 配置，不只是 README 文案。

可选语言：

- `zh-Hans`：简体中文，默认，当前调校最充分。
- `en`：English。
- `ja`：日本語。
- `ko`：한국어。
- `es`：Español。
- `fr`：Français。
- `de`：Deutsch。
- 其他自定义语言码：会透传给提示词和交付元数据，但稳定性取决于模型能力。

Web 面板里可以在单书和批量任务中选择“输出语言”。JSON 输入也可以写：

```json
{
  "title": "Night Courier",
  "output_language": "en",
  "genre": "urban fantasy",
  "market_profile": "tomato_mass",
  "target_total_chars": 2000000
}
```

多语言适配包括：

- 项目补全、规划、正文、审校、成书简介提示会要求目标语言。
- 非中文项目不会默认带入“中文读者/中文强剧情小说” fallback。
- `novel.md`、`novel.txt`、分卷 Markdown、目录、交付说明和 EPUB 会使用匹配的章节壳与语言元数据。
- JSON 字段名仍保持英文 snake_case，这是系统内部协议，不代表正文语言。

限制：

- 中文网文模式迁移到英文、日文、韩文等语言时，节奏方法会保留，但文化表达需要模型自然本地化。
- 章节字数统计仍按字符数做工程控制，不等同于英文 word count。
- 非中文质量门已可运行，但最充分的实战调校仍是中文长篇。

## 输入格式

最少只需要：

```json
{
  "title": "潮汐尽头的修表匠"
}
```

完整字段示例：

```json
{
  "title": "我送外卖，专给怪谈送最后一单",
  "output_language": "zh-Hans",
  "genre": "都市怪谈爽文",
  "audience": "喜欢低门槛、高钩子、短周期回报的番茄读者",
  "tone": "接地气、紧张、章尾强钩子",
  "premise": "外卖员接到只给死人和怪谈下单的夜班系统，每送完最后一单，就能拿到一条活人世界的隐藏线索。",
  "hook": "第一单送到已经拆掉三年的小区，收餐人却正在门后等他。",
  "market_profile": "tomato_mass",
  "progression_mode": "soft_progression",
  "target_total_chars": 2000000,
  "target_chars_per_chapter": 2500,
  "ending_mode": "standalone",
  "must_include": ["每单一个强钩子", "职业代入", "短周期回报"],
  "avoid": ["开局解释太多设定", "连续多章没有新订单"]
}
```

常用字段：

- `title`
- `output_language`
- `genre`
- `audience`
- `tone`
- `premise`
- `theme`
- `hook`
- `setting`
- `protagonist`
- `outline_hint`
- `world_hint`
- `ending_mode`
- `pov`
- `market_profile`
- `progression_mode`
- `progression_flavor`
- `power_system_hint`
- `target_total_chars`
- `target_chars_per_chapter`
- `chapter_count`
- `volume_count`
- `style_examples`
- `must_include`
- `avoid`
- `character_seeds`

## 批量模式

面板的“批量控制台”可以导入 CSV 提案并创建批次。批量层只负责导入、排队、并发、暂停、恢复和重跑；每一本书仍走完整单书流水线。

默认支持的中文 CSV 列：

- `编号`
- `书名`
- `赛道`
- `平台适配`
- `参考需求`
- `一句话钩子`
- `平台简介`
- `故事核心`
- `主题`
- `世界场景`
- `世界观`
- `风格`
- `前30章`
- `卷纲`
- `人物表`
- `备注`

批量参数包括：

- 并发上限
- 总字数
- 章均字数
- 章节数
- 卷数
- 结局方式
- 叙事视角
- 输出语言
- 平台模式
- 升级模式
- provider snapshot

批次会固化创建时的 provider snapshot，恢复批次时默认继续使用当时的模型、中转、key 和续接模式，避免中途修改全局 provider 后污染旧批次。

## 输出产物

一次完整运行会在输出目录写出：

```text
runs/<book>/
  novel.md
  novel.txt
  book-summary.md
  data/
    project-input.json
    project-spec.json
    story-room.json
    world-bible.json
    style-bible.json
    voice-cards.json
    book-outline.json
    power-system-bible.json
    promise-ledger.json
    causality-graph.json
    final-review.json
    book-package.json
    run-summary.json
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

`delivery/` 是更适合交付或打包的目录，包含 manifest、分卷、EPUB 和说明文件。

## 安全

- 默认只建议监听 `127.0.0.1`。
- 如果监听 `0.0.0.0`，必须设置 `SAGAQUILL_ACCESS_TOKEN`。
- 不要把面板无鉴权暴露到公网。
- 不要提交 `.sagaquill/provider.json`、`.novelforge/`、`runs/`、`.env`、key 文件或任何真实 API token。
- Docker volume 里会保存运行产物和 provider 覆盖，迁移或公开前要检查。

## 开发与测试

```bash
python -m unittest discover -s tests -v
```

发版脚本会更新版本号、跑测试、提交、打 tag、推 GitHub Release，并触发 Docker 镜像发布：

```bash
export GITHUB_TOKEN=<github-token>
python scripts/release.py 0.7.3 --wait-docker
```

PowerShell：

```powershell
python scripts/release.py 0.7.3 --token-file C:\path\to\github-token.txt --wait-docker
```

## License

See [LICENSE](LICENSE).
