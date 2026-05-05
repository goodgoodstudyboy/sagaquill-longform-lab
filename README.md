# SagaQuill

SagaQuill 是一个中文长篇小说自动生产和交付流水线，支持单书生成、批量调度、本地 Web 面板、断点续跑、模型审校、本地质量门、EPUB/Markdown/TXT 交付包。公开接口统一使用 `SagaQuill / sagaquill / .sagaquill / SAGAQUILL_*`。

`SagaQuill` 是一个面向中文长篇小说的生产流水线。它默认读取 `~/.codex/config.toml` 和 `~/.codex/auth.json`，复用这台机器上 Codex 已配置好的模型地址、模型名和鉴权信息；如果你想给当前项目单独切换中转站、密钥或模型，也可以在面板里保存本地覆盖到 `.sagaquill/provider.json`。

这个版本不再把“长上下文”理解成把整本书硬塞进一次请求，而是改成更稳的工程化方案：

- 输入层允许只填标题，也允许把题材、人物、世界观、结局方式、目标字数等全填满
- 流水线按 `项目补全 -> 全书策划会 -> 设定圣经 -> 分卷蓝图 -> 当前卷章节目标 -> 场景卡 -> 章节写前会 -> 正文 -> 审校 -> 连续性记忆 -> 终审` 运行
- 连续性靠结构化状态维护，不靠把全书原文反复塞回上下文
- 0.2 在连续性之外新增 `style bible / 角色声线卡 / 承诺账本 / 因果图 / 卷级硬闸门 / 多章回修`
- 默认 `ending_mode=standalone`，最终章必须闭环，不能用“门外又来了个新东西”冒充结尾

为了兼容常见中转网关，客户端默认透传稳定的核心字段；如果 provider 配置里带了 `reasoning_effort`、`service_tier` 这类高级字段，也会按 wire API 适配后透传：`responses` 使用 `reasoning: { effort: ... }`，`chat-completions` 使用 `reasoning_effort`；`fast` 会映射为 OpenAI 兼容接口普遍接受的 `priority`。默认模式仍是本地历史回放：把历史 `user` 和 `assistant output_text` 重新拼回 `input`，由客户端自己维护会话连续性。0.2 额外支持 `previous_response_id` 续接模式，适合支持原生 continuation 的 provider。0.4.2 起再加 `hybrid`：Responses 请求会同时携带压缩后的本地 replay 和 `previous_response_id`，让支持 continuation 的中转尽量吃到原生续接，不支持时也不至于完全丢掉本地上下文。0.3.1 起，客户端还会按 run 目录和 agent session 自动发送稳定的 `session_id` header，方便 `sub2api` 这类支持粘性路由的中转把同一本书的请求尽量路由到同一上游账号。

## 能力

- 稀疏输入：只给标题也能自动补全成可执行项目
- 详细输入：题材、字数、风格、人物、世界观、必写/避写都能控制
- 长篇结构：支持按卷规划，再按章和场景展开
- 多 agent 协作：全书策划会和章节写前会都会给后续生成器施加共识约束
- 风格记忆：独立 style bible、总锚 + 卷间权重校准、章节风格检索和角色声线卡共同约束文风
- 长线记忆：承诺账本和因果图持续累积并在写章前检索
- 卷级闸门：每卷结束先做逻辑审计，审计不过不会进入下一卷
- 多章返修：卷级问题可回滚一个窗口内的多章并重建连续性状态
- SSE 流式输出：正文生成时可实时看到增量文本
- 断点续跑：长任务中断后可基于已落盘章节继续跑
- 双重自检：模型审校 + 本地规则检查
- 完结护栏：最终章若像半截连载尾钩，终审会卡住
- 本地面板：浏览器里直接填表、发任务、看状态、看正文预览
- 零第三方依赖：只用 Python 标准库

## 目录

```text
sagaquill/
  cli.py
  client.py
  codex.py
  pipeline.py
  projectio.py
  prompts.py
  quality.py
  server.py
  webui.py
examples/specs/
tests/
runs/
```

## 快速开始

### 本地安装

```bash
git clone https://github.com/goodgoodstudyboy/sagaquill-longform-lab.git sagaquill
cd sagaquill
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

先确认 Codex 配置可被识别：

```bash
python -m sagaquill doctor
```

生成一份详细输入模板：

```bash
python -m sagaquill init-spec --output examples/specs/my-novel.json
```

用详细输入直接生成：

```bash
python -m sagaquill generate --spec examples/specs/urban-echo.json --output-dir runs/urban-echo --no-stream
```

如果上一次长任务中断，可以直接续跑：

```bash
python -m sagaquill generate --spec examples/specs/urban-echo.json --output-dir runs/urban-echo --resume --no-stream
```

只给标题也能启动：

```bash
python -m sagaquill generate --spec examples/specs/title-only.json --output-dir runs/title-only --no-stream
```

启动本地面板：

```bash
python -m sagaquill serve --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765`。

### Linux 一键部署

适合把面板部署到 Linux 服务器并用 systemd 常驻运行：

```bash
curl -fsSL https://raw.githubusercontent.com/goodgoodstudyboy/sagaquill-longform-lab/main/scripts/bootstrap-linux.sh | sudo bash
```

默认安装到 `/opt/sagaquill`，配置写到 `/etc/sagaquill/sagaquill.env`，服务名是 `sagaquill.service`。

如果仓库仍是 private，或者服务器不能访问 `raw.githubusercontent.com`，用 clone 方式安装：

```bash
git clone https://github.com/goodgoodstudyboy/sagaquill-longform-lab.git sagaquill
cd sagaquill
sudo bash scripts/install-linux.sh
```

一行安装支持这些环境变量覆盖：

```bash
curl -fsSL https://raw.githubusercontent.com/goodgoodstudyboy/sagaquill-longform-lab/main/scripts/bootstrap-linux.sh | sudo env SAGAQUILL_HOST=0.0.0.0 SAGAQUILL_ACCESS_TOKEN=change-me-long-random-token bash
```

可用环境变量包括 `SAGAQUILL_REPO_URL`、`SAGAQUILL_REF`、`APP_DIR`、`ENV_DIR`、`SERVICE_NAME`、`SAGAQUILL_HOST`、`SAGAQUILL_PORT`、`SAGAQUILL_ACCESS_TOKEN`、`SAGAQUILL_BASE_URL`、`SAGAQUILL_MODEL`、`OPENAI_API_KEY`、`ANTHROPIC_AUTH_TOKEN` 等。首次安装时这些值会写入 `/etc/sagaquill/sagaquill.env`。

常用命令：

```bash
sudo systemctl status sagaquill
sudo systemctl restart sagaquill
sudo journalctl -u sagaquill -f
```

默认监听 `127.0.0.1:8765`。如果要对外开放，编辑 `/etc/sagaquill/sagaquill.env`：

```bash
SAGAQUILL_HOST=0.0.0.0
SAGAQUILL_PORT=8765
SAGAQUILL_ACCESS_TOKEN=请换成足够长的随机字符串
SAGAQUILL_CONTINUATION_MODE=hybrid
```

然后执行：

```bash
sudo systemctl restart sagaquill
```

远程访问时必须带 token，可用反向代理追加 `Authorization: Bearer <token>`，也可以请求时带 `X-SagaQuill-Token: <token>`。不建议把面板无鉴权暴露到公网，因为面板可以保存 provider key、启动任务和删除任务。

### Docker 部署

公开镜像发布后，可以不 clone 项目，直接运行：

```bash
docker run -d \
  --name sagaquill \
  --restart unless-stopped \
  -p 8765:8765 \
  -e SAGAQUILL_ACCESS_TOKEN=change-me-long-random-token \
  -v sagaquill-runs:/app/runs \
  -v sagaquill-state:/app/.sagaquill \
  ghcr.io/goodgoodstudyboy/sagaquill-longform-lab:latest
```

如果要复用宿主机上的 Codex provider 配置，再挂载 `~/.codex`：

```bash
docker run -d \
  --name sagaquill \
  --restart unless-stopped \
  -p 8765:8765 \
  -e SAGAQUILL_ACCESS_TOKEN=change-me-long-random-token \
  -v sagaquill-runs:/app/runs \
  -v sagaquill-state:/app/.sagaquill \
  -v "$HOME/.codex:/root/.codex:ro" \
  ghcr.io/goodgoodstudyboy/sagaquill-longform-lab:latest
```

也可以直接通过环境变量传 provider：

```bash
docker run -d \
  --name sagaquill \
  --restart unless-stopped \
  -p 8765:8765 \
  -e SAGAQUILL_ACCESS_TOKEN=change-me-long-random-token \
  -e SAGAQUILL_BASE_URL=https://your-provider.example \
  -e SAGAQUILL_MODEL=your-model \
  -e OPENAI_API_KEY=your-api-key \
  -v sagaquill-runs:/app/runs \
  -v sagaquill-state:/app/.sagaquill \
  ghcr.io/goodgoodstudyboy/sagaquill-longform-lab:latest
```

如果仓库或镜像仍是 private，需要先登录 GitHub Container Registry：

```bash
echo <github-token> | docker login ghcr.io -u <github-username> --password-stdin
```

如果你已经 clone 了项目，也可以用 compose：

```bash
cp .env.example .env
# 编辑 .env，至少修改 SAGAQUILL_ACCESS_TOKEN
docker compose up -d
```

容器会挂载：

- `./runs:/app/runs`
- `./.sagaquill:/app/.sagaquill`
- `${HOME}/.codex:/root/.codex:ro`

如果你不用 Codex 配置，也可以在 `.env` 里直接配置 `SAGAQUILL_BASE_URL`、`SAGAQUILL_MODEL`、`OPENAI_API_KEY`、`ANTHROPIC_AUTH_TOKEN` 等环境变量，再在面板里保存 provider 覆盖。

面板里的 `Provider 配置` 支持：

- 修改当前项目的 `base URL / API key / flagship model / light model / wire_api / continuation_mode`
- 先测试当前表单配置，再决定是否保存
- 一键恢复到 Codex 默认 provider

本地覆盖只影响当前项目目录，不会改写 `~/.codex`。

## 批量模式

0.5 起，面板新增 `批量控制台`，可以把提案 CSV 导入成一批待生产的小说任务，再按并发上限自动调度到现有单书流水线。

设计上，批量模式不是直接“同时起 100 本”，而是：

- 先把 CSV 每一行映射成 `Proposal`
- 再由你勾选、设置篇幅和并发
- 最后创建 `Batch`
- 由调度器按 `max_concurrent` 自动派发单书 job

这层只负责导入、排队、监控和失败重试；真正写小说的仍然是现有单书 `sagaquill` 流程，所以不会绕开已有的连续性、长线记忆、终审和交付逻辑。

### 支持的 CSV 列

当前默认映射这份提案模板中的中文列名：

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

系统会把它们标准化成单书 `ProjectInput`，再继续进入现有小说流水线。

### 批量导入方式

面板里有两种导入方式：

- 直接选择本地 CSV 文件
- 填入项目内相对路径，例如 `material/爆款故事提案模板-100行.csv`

导入后会先显示 `Proposal` 列表，不会立刻开写。

### 批量启动参数

批量控制台目前支持这些批量级参数：

- `并发上限`
- `总字数`
- `章均字数`
- `章节数`
- `卷数`
- `结局方式`
- `叙事视角`

此外，批量任务会固化一份 `provider snapshot`，包括：

- `base_url`
- `api_key`
- `wire_api`
- `flagship_model`
- `light_model`
- `continuation_mode`

这样同一批任务在后续恢复时，仍按创建批次时的 provider 配置继续跑，不会因为你中途修改项目级 provider 而把这批任务的模型或中转站全部切掉。

### 批次调度规则

批量模式当前有这些运行规则：

- 单书 job 仍然独立隔离，互不串上下文
- 每个 batch 有自己的 `max_concurrent`
- 服务端还会受全局并发上限保护
- 当某本书完成或失败后，调度器会自动补位队列中的下一本
- 批次暂停只会暂停“继续派发新任务”；已经在跑的单书 job 仍可单独暂停
- 批次恢复后，会继续从 `queued` 项里派发
- 批次失败重试只重试失败项，不会把整批重开

### 批量产物

批次元数据写在：

```text
.sagaquill/batches/<batch_id>/
  batch.json
  proposals.json
  items.json
  export.json
```

每一本实际成书仍然落到 `runs/<title>-<timestamp>-<job_id>/`。

### 当前推荐

如果你走的是 `sub2api + responses`，批量任务的推荐续接模式是：

- `continuation_mode = hybrid`

这样每本书都会同时带：

- `previous_response_id`
- 压缩后的本地 replay 上下文

在支持原生续接的中转上尽量吃到 continuation，不支持时也保留本地上下文兜底。

## 输入格式

最少只要：

```json
{
  "title": "潮汐尽头的修表匠"
}
```

也可以填满这些字段：

- `title`
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
- `target_total_chars`
- `target_chars_per_chapter`
- `chapter_count`
- `volume_count`
- `style_examples`
- `must_include`
- `avoid`
- `character_seeds`

## 输出产物

一次运行会在输出目录写出：

- `data/project-input.json`
- `data/project-spec.json`
- `data/story-room.json`
- `data/world-bible.json`
- `data/style-bible.json`
- `data/style-bible.anchor.json`
- `data/style-bible.calibration.json`
- `data/voice-cards.json`
- `data/book-outline.json`
- `data/promise-ledger.json`
- `data/causality-graph.json`
- `volumes/volume-01.outline.json`
- `plans/chapter-01.plan.json`
- `chapters/chapter-01.md`
- `reviews/chapter-01.review.json`
- `state/chapter-01.room.json`
- `state/chapter-01.continuity.json`
- `state/chapter-01.memory.json`
- `audits/volume-01.logic-audit.json`
- `data/continuity-state.json`
- `data/final-review.json`
- `data/run-summary.json`
- `data/book-package.json`
- `book-summary.md`
- `novel.txt`
- `novel.md`

## 关于“100 万字一次性写完”

如果你的意思是“一次 API 调用直接吐出 100 万字”，这在现实里不可行，输出上限和稳定性都不支持。

如果你的意思是“我提交一次任务，让系统自己把 100 万字长篇工程跑完”，现在的架构就是朝这个方向设计的：

- 用 `target_total_chars` 指定总规模
- 自动推导章节数和卷数
- 先由 world_architect / character_director / plot_architect 形成全书级共识
- 每次只展开当前卷和当前章
- 每章写之前，再由 continuity_guard / drama_editor / style_guard 做一次写前会
- 用连续性状态保存角色、时间线、伏笔和未解决线程
- 运行过程中持续落盘，必要时可从已完成章节断点续跑
- 最终靠分层规划而不是超长原文上下文维持一致性

## 0.2 长线一致性

0.2 额外加了 8 个长篇增强点：

- `Style Bible`：单独生成语气、节奏、对白、禁句和范文样例
- `角色声线卡`：为核心人物保存说话节奏、常用词和禁止偏移点
- `承诺账本`：记录伏笔/承诺从哪章开始、预期在哪卷兑现、当前状态是否逾期
- `因果图`：记录结果背后的前置条件，以及后续必须兑现的后果
- `风格检索`：每章写前都会从 style bible 和近章正文里抽最相关的风格样本
- `卷级硬闸门`：每卷结束必须先过逻辑审计，没过就触发回修，下一卷不会继续开写
- `多章级返修`：卷审发现的问题可针对一个章节窗口连续回修，而不是只修单章
- `provider continuation`：配置为 `previous_response_id` 时，Responses 请求会尽量只依赖上游原生续接；配置为 `hybrid` 时，会同时带 `previous_response_id` 和本地 replay 上下文
- `sticky routing`：如果中转支持 `session_id` 粘性会话，SagaQuill 会自动按 run+agent 发送稳定的 `session_id` header

这些能力会在运行目录里留下可审计的中间产物，不是纯 prompt 黑盒。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 说明

- 默认使用 `~/.codex/config.toml` 的 `model_provider`、`model`、`light_model`、`review_model`、`base_url`、`wire_api`
- 默认使用 `~/.codex/auth.json` 中的 `OPENAI_API_KEY`
- 如果项目根目录存在 `.sagaquill/provider.json`，则优先使用这份本地覆盖；未覆盖字段继续回退到 Codex 默认
- 两档模型路由里，`旗舰模型` 负责规划、正文、审校、终审和复杂返修；`轻量模型` 负责连续性提取、长线记忆更新、卷间风格/声线校准和成书包装
- 客户端会先试 `base_url/responses`，再试 `base_url/v1/responses`
- Responses 流式模式会消费 `response.output_text.delta` 事件并实时拼接正文
- 对 `524` 等临时性上游超时会自动重试，对 `502/503/504` 会优先切换备用 endpoint
- 如果代理层不支持可靠的服务端线程续接，客户端会自动退回本地历史回放
- 可用环境变量 `SAGAQUILL_CONTINUATION_MODE=previous_response_id` 或 `SAGAQUILL_CONTINUATION_MODE=hybrid`，也可以在 Codex provider 配置里写 `continuation_mode = "previous_response_id"` / `"hybrid"`
