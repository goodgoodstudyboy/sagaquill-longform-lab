from __future__ import annotations


def panel_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SagaQuill Panel</title>
  <style>
    :root {
      --bg: #f4efe6;
      --bg-soft: #fbf7f1;
      --ink: #1b2a2f;
      --muted: #607176;
      --line: rgba(27, 42, 47, 0.16);
      --card: rgba(255, 252, 247, 0.88);
      --accent: #0f766e;
      --accent-2: #c96f3b;
      --shadow: 0 24px 60px rgba(15, 32, 36, 0.12);
      --radius: 22px;
      --mono: "IBM Plex Mono", "JetBrains Mono", "SFMono-Regular", monospace;
      --sans: "IBM Plex Sans", "Noto Sans SC", "Segoe UI", sans-serif;
      --serif: "IBM Plex Serif", "Noto Serif SC", Georgia, serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--sans);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(201,111,59,0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(15,118,110,0.14), transparent 26%),
        linear-gradient(180deg, #faf6ef 0%, #f0e8dc 100%);
      min-height: 100vh;
    }
    .wrap {
      width: min(1420px, calc(100vw - 24px));
      margin: 24px auto 40px;
      display: grid;
      grid-template-columns: minmax(0, 1.03fr) minmax(380px, 0.97fr);
      gap: 18px;
    }
    .hero, .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
      overflow: hidden;
    }
    .hero {
      padding: 28px;
      position: relative;
    }
    .hero::after {
      content: "";
      position: absolute;
      inset: auto -12% -34% 30%;
      height: 220px;
      background: radial-gradient(circle, rgba(15,118,110,0.18), transparent 62%);
      pointer-events: none;
    }
    h1, h2 {
      margin: 0;
      font-family: var(--serif);
      font-weight: 600;
      letter-spacing: -0.02em;
    }
    h1 { font-size: clamp(34px, 5vw, 60px); line-height: 0.96; }
    h2 { font-size: 22px; }
    p { margin: 0; color: var(--muted); line-height: 1.65; }
    .hero-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 18px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(15,118,110,0.1);
      color: var(--accent);
      font-size: 13px;
      font-weight: 600;
    }
    .hero-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 22px;
    }
    .stat {
      padding: 14px;
      border-radius: 18px;
      background: rgba(255,255,255,0.72);
      border: 1px solid rgba(27,42,47,0.09);
      animation: rise .45s ease both;
    }
    .stat strong { display: block; font-size: 24px; margin-bottom: 4px; }
    .stack {
      display: grid;
      gap: 20px;
      align-content: start;
    }
    .card { padding: 22px; animation: rise .45s ease both; }
    .fold-card {
      padding: 0;
    }
    .fold-card summary {
      list-style: none;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 22px;
      cursor: pointer;
      user-select: none;
    }
    .fold-card summary::-webkit-details-marker { display: none; }
    .fold-card summary::marker { content: ""; }
    .fold-head {
      display: grid;
      gap: 6px;
    }
    .fold-arrow {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: 999px;
      background: rgba(27,42,47,0.08);
      color: var(--ink);
      font-size: 15px;
      font-weight: 700;
      transition: transform .18s ease, background .18s ease;
    }
    .fold-card[open] .fold-arrow {
      transform: rotate(90deg);
      background: rgba(15,118,110,0.12);
      color: var(--accent);
    }
    .fold-content {
      padding: 0 22px 22px;
    }
    .fold-meta {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .field { display: grid; gap: 8px; }
    .field.span-2 { grid-column: 1 / -1; }
    label {
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.02em;
      color: var(--ink);
      text-transform: uppercase;
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid rgba(27,42,47,0.15);
      border-radius: 16px;
      padding: 12px 14px;
      background: rgba(255,255,255,0.8);
      color: var(--ink);
      font: inherit;
      outline: none;
      transition: border-color .2s ease, transform .2s ease, box-shadow .2s ease;
    }
    input:focus, textarea:focus, select:focus {
      border-color: rgba(15,118,110,0.55);
      box-shadow: 0 0 0 4px rgba(15,118,110,0.08);
      transform: translateY(-1px);
    }
    textarea { min-height: 110px; resize: vertical; }
    .help { font-size: 12px; color: var(--muted); }
    .preset-box {
      padding: 16px;
      border-radius: 18px;
      background: rgba(15,118,110,0.06);
      border: 1px solid rgba(15,118,110,0.12);
    }
    .preset-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .preset-note {
      margin-top: 10px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.6;
    }
    .preset-preview {
      min-height: 72px;
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.78);
      border: 1px solid rgba(27,42,47,0.1);
      font-size: 13px;
      color: var(--muted);
      line-height: 1.6;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 18px;
    }
    button, .link-btn {
      appearance: none;
      border: 0;
      border-radius: 999px;
      padding: 12px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform .2s ease, opacity .2s ease;
      text-decoration: none;
    }
    button:hover, .link-btn:hover { transform: translateY(-1px); }
    .primary { background: var(--accent); color: white; }
    .secondary { background: rgba(27,42,47,0.08); color: var(--ink); }
    .danger { background: rgba(169, 40, 40, 0.12); color: #8f1d1d; }
    .link-btn { background: rgba(201,111,59,0.12); color: var(--accent-2); }
    .status {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--line);
      margin-bottom: 14px;
    }
    .status strong { font-size: 20px; }
    .mono { font-family: var(--mono); font-size: 12px; }
    .log, .preview, .jobs {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.74);
      padding: 14px;
    }
    .log {
      max-height: 260px;
      overflow: auto;
      display: grid;
      gap: 10px;
    }
    .log-item {
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(15,118,110,0.06);
      border: 1px solid rgba(15,118,110,0.08);
    }
    .jobs {
      display: grid;
      gap: 10px;
    }
    .job {
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.8);
      cursor: pointer;
      transition: transform .2s ease, border-color .2s ease;
    }
    .job:hover { transform: translateY(-1px); border-color: rgba(15,118,110,0.35); }
    .job.active {
      border-color: rgba(15,118,110,0.45);
      box-shadow: inset 0 0 0 1px rgba(15,118,110,0.12);
    }
    .job.hidden { opacity: 0.84; }
    .job strong { display: block; margin-bottom: 6px; }
    .job-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }
    .job-actions {
      display: inline-flex;
      gap: 8px;
      flex-shrink: 0;
    }
    .mini-btn {
      padding: 7px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }
    .toggle-line {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
    }
    .toggle-line label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      text-transform: none;
      font-size: 13px;
      letter-spacing: 0;
      cursor: pointer;
    }
    .filter-tabs {
      display: inline-flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .filter-tabs button.active {
      background: var(--accent);
      color: #f8f4eb;
      border-color: var(--accent);
    }
    .preview {
      max-height: 520px;
      overflow: auto;
      white-space: pre-wrap;
      line-height: 1.7;
    }
    .log:empty,
    .preview:empty,
    .jobs:empty,
    .batch-list:empty {
      min-height: 0;
    }
    .meta {
      margin-top: 8px;
      color: var(--muted);
    }
    .summary-box {
      padding: 14px;
      border-radius: 18px;
      background: rgba(201,111,59,0.08);
      border: 1px solid rgba(201,111,59,0.16);
      margin-bottom: 14px;
    }
    .batch-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .batch-grid {
      display: grid;
      gap: 14px;
    }
    .batch-summary {
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(15,118,110,0.06);
      border: 1px solid rgba(15,118,110,0.12);
      white-space: pre-wrap;
      line-height: 1.6;
    }
    .batch-table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.72);
    }
    .batch-table {
      width: 100%;
      border-collapse: collapse;
      min-width: 860px;
      font-size: 13px;
    }
    .batch-table th,
    .batch-table td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(27,42,47,0.08);
      vertical-align: top;
      text-align: left;
    }
    .batch-table th {
      background: rgba(15,118,110,0.05);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }
    .batch-table tr:last-child td { border-bottom: 0; }
    .batch-list {
      display: grid;
      gap: 10px;
    }
    .batch-card {
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.8);
      cursor: pointer;
      transition: transform .2s ease, border-color .2s ease;
    }
    .batch-card.hidden { opacity: 0.84; }
    .batch-card:hover { transform: translateY(-1px); border-color: rgba(15,118,110,0.35); }
    .batch-card.active {
      border-color: rgba(15,118,110,0.45);
      box-shadow: inset 0 0 0 1px rgba(15,118,110,0.12);
    }
    .batch-card strong { display: block; margin-bottom: 6px; }
    .batch-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }
    .batch-actions {
      display: inline-flex;
      gap: 8px;
      flex-shrink: 0;
    }
    .batch-counts {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }
    .batch-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(27,42,47,0.08);
      font-size: 12px;
      font-weight: 700;
    }
    .batch-title-line {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .batch-runtime-meta {
      display: grid;
      gap: 4px;
      min-width: 260px;
    }
    .batch-runtime-actions {
      display: inline-flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .batch-progress {
      display: grid;
      gap: 6px;
      min-width: 260px;
    }
    .batch-progress-track {
      position: relative;
      height: 10px;
      border-radius: 999px;
      background: rgba(27,42,47,0.12);
      overflow: hidden;
    }
    .batch-progress-fill {
      position: absolute;
      inset: 0 auto 0 0;
      width: 0;
      background: linear-gradient(90deg, var(--accent), #39a98a);
      border-radius: 999px;
    }
    .batch-progress-marker {
      position: absolute;
      top: -2px;
      bottom: -2px;
      width: 0;
      border-left: 2px dashed rgba(201,111,59,0.9);
      opacity: 0.95;
    }
    .batch-progress-text {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 12px;
      color: var(--muted);
      font-family: var(--mono);
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 64px;
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(27,42,47,0.08);
      font-size: 12px;
      font-weight: 700;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(14px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @media (max-width: 980px) {
      .wrap { grid-template-columns: 1fr; }
      .hero-grid, .grid { grid-template-columns: 1fr; }
      .field.span-2 { grid-column: auto; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="stack">
      <details class="card fold-card" open>
        <summary>
          <div class="fold-head">
            <h2>Provider 配置</h2>
            <p>默认读取 Codex。保存后只覆盖当前项目，不会改你的 <span class="mono">~/.codex</span>。</p>
          </div>
          <div style="display:flex;align-items:center;gap:12px;">
            <div id="provider-source" class="mono"></div>
            <span class="fold-arrow">›</span>
          </div>
        </summary>
        <div class="fold-content">
          <div class="grid" id="provider-form">
            <div class="field span-2">
              <label for="provider_base_url">Base URL</label>
              <input id="provider_base_url" placeholder="https://relay.example.com/v1">
            </div>
            <div class="field">
              <label for="provider_model">旗舰模型</label>
              <input id="provider_model" placeholder="gpt-5.4">
            </div>
            <div class="field">
              <label for="provider_light_model">轻量模型</label>
              <input id="provider_light_model" placeholder="gpt-5.4-mini / haiku">
            </div>
            <div class="field">
              <label for="provider_review_model">审校模型</label>
              <input id="provider_review_model" placeholder="可留空，默认跟轻量模型一致">
            </div>
            <div class="field">
              <label for="provider_wire_api">Wire API</label>
              <select id="provider_wire_api">
                <option value="responses">responses</option>
                <option value="chat-completions">chat-completions</option>
                <option value="anthropic-messages">anthropic-messages</option>
              </select>
            </div>
            <div class="field">
              <label for="provider_gateway_profile">网关 Profile</label>
              <input id="provider_gateway_profile" placeholder="auto / sub2api / generic">
            </div>
            <div class="field">
              <label for="provider_continuation_mode">续接模式</label>
              <select id="provider_continuation_mode">
                <option value="replay">replay</option>
                <option value="hybrid">hybrid</option>
                <option value="previous_response_id">previous_response_id</option>
              </select>
            </div>
            <div class="field">
              <label for="provider_flagship_reasoning_effort">旗舰推理强度</label>
              <input id="provider_flagship_reasoning_effort" placeholder="xhigh / high / medium">
            </div>
            <div class="field">
              <label for="provider_flagship_service_tier">旗舰 Service Tier</label>
              <input id="provider_flagship_service_tier" placeholder="priority / flex / default / auto (fast=priority)">
            </div>
            <div class="field">
              <label for="provider_light_reasoning_effort">轻量推理强度</label>
              <input id="provider_light_reasoning_effort" placeholder="留空表示回退到共享或默认">
            </div>
            <div class="field">
              <label for="provider_light_service_tier">轻量 Service Tier</label>
              <input id="provider_light_service_tier" placeholder="留空表示回退到共享或默认">
            </div>
            <div class="field span-2">
              <label for="provider_api_key">API Key</label>
              <input id="provider_api_key" type="password" placeholder="留空表示沿用已保存值或 Codex auth">
              <div id="provider-key-hint" class="help">当前未检测到可用密钥。</div>
            </div>
            <div class="field span-2">
              <div id="provider-override-path" class="mono"></div>
              <div id="provider-test-status" class="help">保存后，新启动的任务会使用这里的配置；测试连接会使用当前表单值发一个极小请求。</div>
            </div>
          </div>
          <div class="actions">
            <button type="button" class="secondary" id="test-provider">测试连接</button>
            <button type="button" class="primary" id="save-provider">保存覆盖</button>
            <button type="button" class="secondary" id="reset-provider">恢复 Codex 默认</button>
          </div>
        </div>
      </details>

      <section class="hero">
        <div class="hero-top">
          <div>
            <div class="pill">Local Panel / Codex Config / Long-Form Pipeline / <span id="version-tag">detecting...</span></div>
            <h1>SagaQuill</h1>
          </div>
          <div id="provider" class="mono"></div>
        </div>
        <p>支持标题直写，也支持详细填写题材、字数、风格、人物、世界观和结局模式。任务启动后会按“项目补全 → 设定圣经 → 分卷蓝图 → 章节 → 连续性记忆 → 终审”自动跑完整链路。</p>
        <div class="hero-grid">
          <div class="stat"><strong>1</strong><span>标题可直接起步</span></div>
          <div class="stat"><strong>4</strong><span>分层到卷 / 章 / 场景</span></div>
          <div class="stat"><strong>∞</strong><span>靠结构化记忆扩展长篇</span></div>
        </div>
      </section>

      <details class="card fold-card" open>
        <summary>
          <div class="fold-head">
            <h2>项目输入</h2>
            <p>只填标题也能跑；填得越细，控制越稳。</p>
          </div>
          <div class="fold-meta">
            <span class="fold-arrow">›</span>
          </div>
        </summary>
        <div class="fold-content">
        <div style="display:flex;justify-content:flex-end;align-items:center;gap:12px;margin-bottom:18px;">
          <button type="button" class="secondary" id="load-template">填入示例</button>
        </div>
        <form id="project-form" class="grid">
          <div class="field span-2">
            <label for="title">标题</label>
            <input id="title" name="title" placeholder="例如：雾港回声">
          </div>
          <div class="field span-2 preset-box">
            <div style="display:flex;justify-content:space-between;align-items:end;gap:16px;flex-wrap:wrap;">
              <div>
                <label style="margin-bottom:6px;">小白预设</label>
                <div class="help">默认不会自动填。选好后点“套用预设”，只补空白字段，并把约束列表去重合并进当前表单。</div>
              </div>
              <button type="button" class="secondary" id="apply-presets">套用预设</button>
            </div>
            <div class="preset-grid" style="margin-top:14px;">
              <div class="field">
                <label for="audience_preset">受众预设</label>
                <select id="audience_preset" name="audience_preset">
                  <option value="">不使用，自己填写</option>
                </select>
                <div id="audience-preset-preview" class="preset-preview">给完全不知道“受众怎么写”的人准备。会帮你把读者定位和相关约束一起补进去。</div>
              </div>
              <div class="field">
                <label for="style_preset">文风预设</label>
                <select id="style_preset" name="style_preset">
                  <option value="">不使用，自己填写</option>
                </select>
                <div id="style-preset-preview" class="preset-preview">不是只改一个 tone，而是同时影响节奏、回报、挂钩方式和避坑项。</div>
              </div>
            </div>
            <div class="preset-note">高级用户可以完全忽略这一区域，直接手填。想走“文学感 + 产品节奏”混合路线，也可以直接选对应文风预设。</div>
          </div>
          <div class="field">
            <label for="genre">题材</label>
            <input id="genre" name="genre" placeholder="都市奇谭 / 科幻 / 仙侠 / 悬疑">
          </div>
          <div class="field">
            <label for="output_language">输出语言</label>
            <select id="output_language" name="output_language"></select>
          </div>
          <div class="field">
            <label for="audience">受众</label>
            <input id="audience" name="audience" placeholder="喜欢强剧情推进的中文读者">
          </div>
          <div class="field">
            <label for="target_total_chars">总字数</label>
            <input id="target_total_chars" name="target_total_chars" inputmode="numeric" placeholder="12000 / 1000000">
          </div>
          <div class="field">
            <label for="target_chars_per_chapter">每章目标字数</label>
            <input id="target_chars_per_chapter" name="target_chars_per_chapter" inputmode="numeric" placeholder="2000">
          </div>
          <div class="field">
            <label for="chapter_count">目标章节数（可浮动）</label>
            <input id="chapter_count" name="chapter_count" inputmode="numeric" placeholder="可留空，故事驱动会按预算和节奏推导">
          </div>
          <div class="field">
            <label for="volume_count">目标卷数（可浮动）</label>
            <input id="volume_count" name="volume_count" inputmode="numeric" placeholder="可留空，故事驱动会按阶段密度推导">
          </div>
          <div class="field">
            <label for="structure_mode">结构模式</label>
            <select id="structure_mode" name="structure_mode">
              <option value="story_driven">故事驱动（推荐）</option>
              <option value="legacy">兼容旧模式</option>
            </select>
          </div>
          <div class="field">
            <label for="market_profile">平台模式</label>
            <select id="market_profile" name="market_profile"></select>
          </div>
          <div class="field">
            <label for="progression_mode">升级模式</label>
            <select id="progression_mode" name="progression_mode"></select>
          </div>
          <div class="field">
            <label for="progression_flavor">升级风格</label>
            <select id="progression_flavor" name="progression_flavor"></select>
          </div>
          <div class="field">
            <label for="progression_pacing">升级节奏</label>
            <select id="progression_pacing" name="progression_pacing"></select>
          </div>
          <div class="field">
            <label for="ending_mode">结局模式</label>
            <select id="ending_mode" name="ending_mode">
              <option value="standalone">完整单本</option>
              <option value="series">系列延展</option>
            </select>
          </div>
          <div class="field">
            <label for="pov">视角</label>
            <input id="pov" name="pov" placeholder="第三人称有限视角">
          </div>
          <div class="field span-2">
            <label for="tone">文风 / 气质</label>
            <input id="tone" name="tone" placeholder="克制、潮湿、冷峻；或者热烈、快节奏、强对抗">
          </div>
          <div class="field span-2">
            <label for="premise">故事前提</label>
            <textarea id="premise" name="premise" placeholder="主角遇到了什么，整个故事的独特机制或冲突是什么。"></textarea>
          </div>
          <div class="field">
            <label for="theme">主题</label>
            <textarea id="theme" name="theme" placeholder="这部小说真正想讲什么。"></textarea>
          </div>
          <div class="field">
            <label for="hook">一句话钩子</label>
            <textarea id="hook" name="hook" placeholder="用一句话说明为什么读者会想往下读。"></textarea>
          </div>
          <div class="field span-2">
            <label for="setting">世界 / 场景</label>
            <textarea id="setting" name="setting" placeholder="时代、空间、社会关系、力量系统、现实底色。"></textarea>
          </div>
          <div class="field span-2">
            <label for="protagonist">主角</label>
            <textarea id="protagonist" name="protagonist" placeholder="主角是谁，最想要什么，最怕什么。"></textarea>
          </div>
          <div class="field span-2">
            <label for="outline_hint">大纲提示</label>
            <textarea id="outline_hint" name="outline_hint" placeholder="如果你已经有想法，可以写整体走向、转折点或结尾要求。"></textarea>
          </div>
          <div class="field span-2">
            <label for="world_hint">世界观提示</label>
            <textarea id="world_hint" name="world_hint" placeholder="补充规则、禁区、历史背景、职业细节。"></textarea>
          </div>
          <div class="field span-2">
            <label for="power_system_hint">升级体系提示</label>
            <textarea id="power_system_hint" name="power_system_hint" placeholder="只有写硬升级文时再填：例如境界名、突破条件、资源路线、强敌台阶、每阶段目标。"></textarea>
          </div>
          <div class="field">
            <label for="style_examples">风格要求</label>
            <textarea id="style_examples" name="style_examples" placeholder="每行一条，例如：对白短、动作驱动、最终章必须闭环。"></textarea>
          </div>
          <div class="field">
            <label for="must_include">必写元素</label>
            <textarea id="must_include" name="must_include" placeholder="每行一条。"></textarea>
          </div>
          <div class="field">
            <label for="avoid">避写元素</label>
            <textarea id="avoid" name="avoid" placeholder="每行一条。"></textarea>
          </div>
          <div class="field">
            <label for="character_seeds">人物种子</label>
            <textarea id="character_seeds" name="character_seeds" placeholder="每行一个角色，用 | 分隔：名字 | 角色 | 目标 | 冲突 | 备注"></textarea>
          </div>
          <div class="field span-2">
            <div class="help">只写标题也能提交。长篇工程不要指望一次模型调用吐出 100 万字，面板会把它拆成可持续写作的分卷任务，由结构化记忆维持一致性。</div>
          </div>
        </form>
        <div class="actions">
          <button class="primary" id="submit-job" type="button">启动任务</button>
          <button class="secondary" id="clear-form" type="button">清空</button>
        </div>
        </div>
      </details>

      <details class="card fold-card" open>
        <summary>
          <div class="fold-head">
            <h2>批量控制台</h2>
            <p>导入提案 CSV，先生成批次，再按并发上限派发到单书流水线。批次恢复和重试时会使用你当前表单里的 provider，便于中途换 key 或模型。</p>
          </div>
          <div class="fold-meta">
            <div id="batch-status-pill" class="pill">Batch Idle</div>
            <span class="fold-arrow">›</span>
          </div>
        </summary>
        <div class="fold-content">
        <div class="grid">
          <div class="field span-2">
            <label for="batch_name">批次名称</label>
            <input id="batch_name" placeholder="例如：爆款短篇首批">
          </div>
          <div class="field span-2">
            <label for="batch_csv_path">CSV 文件路径</label>
            <input id="batch_csv_path" placeholder="material/爆款故事提案模板-100行.csv">
            <div class="help">本地运行时可直接填相对路径；如果不填，也可以在下面选择本地 CSV 文件。</div>
          </div>
          <div class="field span-2">
            <label for="batch_csv_file">或选择 CSV 文件</label>
            <input id="batch_csv_file" type="file" accept=".csv,text/csv">
          </div>
          <div class="field">
            <label for="batch_max_concurrent">并发数</label>
            <input id="batch_max_concurrent" inputmode="numeric" value="2">
          </div>
          <div class="field">
            <label for="batch_target_total_chars">目标总字数</label>
            <input id="batch_target_total_chars" inputmode="numeric" value="1000000">
          </div>
          <div class="field">
            <label for="batch_run_to_completion">完成方式</label>
            <select id="batch_run_to_completion">
              <option value="true">写完整本</option>
              <option value="false">达到字数自动暂停</option>
            </select>
          </div>
          <div class="field span-2" id="batch_pause_at_chars_field" style="display:none;">
            <label for="batch_pause_at_chars">自动暂停字数</label>
            <input id="batch_pause_at_chars" inputmode="numeric" value="300000">
            <div class="help">这个阈值只影响运行时自动暂停，不会参与任何 agent 规划，也不会改变目标总字数。</div>
          </div>
          <div class="field">
            <label for="batch_target_chars_per_chapter">每章目标字数</label>
            <input id="batch_target_chars_per_chapter" inputmode="numeric" value="2000">
          </div>
          <div class="field">
            <label for="batch_chapter_count">目标章节数（可浮动）</label>
            <input id="batch_chapter_count" inputmode="numeric" placeholder="可留空，默认按总字数和节奏推导">
          </div>
          <div class="field">
            <label for="batch_volume_count">目标卷数（可浮动）</label>
            <input id="batch_volume_count" inputmode="numeric" placeholder="可留空，默认按总字数和阶段推导">
          </div>
          <div class="field">
            <label for="batch_structure_mode">结构模式</label>
            <select id="batch_structure_mode">
              <option value="story_driven">故事驱动（推荐）</option>
              <option value="legacy">兼容旧模式</option>
            </select>
          </div>
          <div class="field">
            <label for="batch_market_profile">平台模式</label>
            <select id="batch_market_profile"></select>
          </div>
          <div class="field">
            <label for="batch_output_language">输出语言</label>
            <select id="batch_output_language"></select>
          </div>
          <div class="field">
            <label for="batch_progression_mode">升级模式</label>
            <select id="batch_progression_mode"></select>
          </div>
          <div class="field">
            <label for="batch_progression_flavor">升级风格</label>
            <select id="batch_progression_flavor"></select>
          </div>
          <div class="field">
            <label for="batch_progression_pacing">升级节奏</label>
            <select id="batch_progression_pacing"></select>
          </div>
          <div class="field">
            <label for="batch_ending_mode">结局模式</label>
            <select id="batch_ending_mode">
              <option value="">自动（推荐）</option>
              <option value="standalone">完整单本</option>
              <option value="series">系列延展</option>
            </select>
            <div class="help">留空时会自动判断：批量试跑默认按长篇/系列写，不再默认锚成单卷短篇。</div>
          </div>
          <div class="field span-2">
            <label for="batch_pov">视角</label>
            <input id="batch_pov" value="第三人称有限视角">
          </div>
          <div class="field span-2">
            <label for="batch_power_system_hint">升级体系提示</label>
            <textarea id="batch_power_system_hint" placeholder="批量硬升级文时填写：境界、资源、试炼、敌人台阶和阶段目标。"></textarea>
          </div>
        </div>
        <div class="batch-toolbar">
          <button class="secondary" id="batch-reset" type="button">空白新批次</button>
          <button class="primary" id="batch-import" type="button">导入提案 CSV</button>
          <button class="secondary" id="batch-launch" type="button">启动勾选提案</button>
          <button class="secondary" id="batch-pause" type="button">暂停批次</button>
          <button class="secondary" id="batch-resume" type="button">恢复暂停项</button>
          <button class="secondary" id="batch-retry" type="button">重试失败项</button>
          <button class="secondary" id="batch-resume-all" type="button">全量检查并续跑</button>
          <button class="link-btn" id="batch-open-folder" type="button">打开当前批次文件夹</button>
          <button class="secondary" id="batch-export" type="button">导出批次汇总</button>
        </div>
        <div id="batch-summary" class="batch-summary" style="margin-top:14px;">还没有批次。</div>
        <div class="batch-table-wrap" style="margin-top:14px;">
          <table class="batch-table">
            <thead>
              <tr>
                <th style="width:52px;">选中</th>
                <th style="min-width:180px;">书名</th>
                <th style="width:96px;">状态</th>
                <th style="min-width:280px;">字数进度</th>
                <th style="min-width:280px;">运行详情</th>
                <th style="min-width:130px;">操作</th>
                <th style="min-width:120px;">Job</th>
              </tr>
            </thead>
            <tbody id="batch-proposals">
              <tr><td colspan="7" class="help">先导入一份 CSV。</td></tr>
            </tbody>
          </table>
        </div>
        </div>
      </details>
    </div>

    <div class="stack">
      <details class="card fold-card" open>
        <summary>
          <div class="fold-head">
            <h2>当前任务</h2>
            <p id="job-status-text">还没有运行中的任务。</p>
          </div>
          <div class="fold-meta">
            <div id="job-badge" class="pill">Idle</div>
            <span class="fold-arrow">›</span>
          </div>
        </summary>
        <div class="fold-content">
          <div id="job-meta" class="mono meta" style="margin-bottom:14px;"></div>
          <div id="job-provider-meta" class="mono meta" style="margin-bottom:14px;"></div>
          <div id="job-summary" class="summary-box" style="display:none;"></div>
          <div class="actions" style="margin-top:0;margin-bottom:14px;">
            <button id="resume-job" class="secondary" type="button" style="display:none;">恢复运行</button>
            <button id="pause-job" class="secondary" type="button" style="display:none;">暂停</button>
            <button id="toggle-hide-job" class="secondary" type="button" style="display:none;">隐藏</button>
            <button id="delete-job" class="danger" type="button" style="display:none;">删除项目</button>
            <a id="novel-link" class="link-btn" href="#" target="_blank" style="display:none;">打开生成文本</a>
            <a id="quality-report-link" class="link-btn" href="#" target="_blank" style="display:none;">打开质检报告</a>
            <button id="open-folder" class="link-btn" type="button" style="display:none;">打开生成文件夹</button>
            <button id="delivery-cleanup" class="link-btn" type="button" style="display:none;">交付清理</button>
          </div>
          <div class="log" id="job-log"></div>
        </div>
      </details>

      <details class="card fold-card" open>
        <summary>
          <div class="fold-head">
            <h2>生成预览</h2>
            <p>运行中会显示已落盘章节预览，完成后显示整本正文预览和产物路径。</p>
          </div>
          <div style="display:flex;align-items:center;gap:12px;">
            <div id="job-path" class="mono"></div>
            <span class="fold-arrow">›</span>
          </div>
        </summary>
        <div class="fold-content">
          <div id="job-preview" class="preview"></div>
        </div>
      </details>

      <details class="card fold-card" open>
        <summary>
          <div class="fold-head">
            <h2>最近任务</h2>
            <p>这里只显示单独任务。批量任务的运行进度和控制统一放在批量控制台里。</p>
          </div>
          <div class="fold-meta">
            <span class="fold-arrow">›</span>
          </div>
        </summary>
        <div class="fold-content">
          <div class="toggle-line">
            <div></div>
            <div class="filter-tabs">
              <label><input id="show-hidden" type="checkbox"> 显示隐藏任务</label>
            </div>
          </div>
          <div id="jobs" class="jobs"></div>
        </div>
      </details>

      <details class="card fold-card" open>
        <summary>
          <div class="fold-head">
            <h2>批次列表</h2>
            <p>点中一个批次后，下方批量控制台会切换到这批书的实时运行视图。</p>
          </div>
          <div class="fold-meta">
            <div id="batch-list-meta" class="mono"></div>
            <span class="fold-arrow">›</span>
          </div>
        </summary>
        <div class="fold-content">
          <div class="toggle-line">
            <div></div>
            <div class="filter-tabs">
              <label><input id="show-hidden-batches" type="checkbox"> 显示隐藏批次</label>
            </div>
          </div>
          <div id="batch-list" class="batch-list"></div>
        </div>
      </details>
    </div>
  </div>

  <script>
    const state = {
      currentJobId: null,
      currentBatchId: null,
      timer: null,
      batchTimer: null,
      showHidden: false,
      showHiddenBatches: false,
      jobFilter: "all",
      hiddenCount: 0,
      hiddenBatchCount: 0,
      jobs: new Map(),
      batches: new Map(),
      currentBatch: null,
      template: null,
      presets: { audience_presets: [], style_presets: [] },
      outputLanguages: [],
      marketProfiles: [],
      provider: null,
    };

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || response.statusText);
      }
      const contentType = response.headers.get("Content-Type") || "";
      return contentType.includes("application/json") ? response.json() : response.text();
    }

    function lines(value) {
      return value.split(/\\r?\\n/).map(item => item.trim()).filter(Boolean);
    }

    function uniqueLines(items) {
      const result = [];
      for (const item of items) {
        const text = String(item || "").trim();
        if (!text || result.includes(text)) continue;
        result.push(text);
      }
      return result;
    }

    function parseCharacters(value) {
      return lines(value).map(line => {
        const parts = line.split("|").map(item => item.trim());
        return {
          name: parts[0] || "",
          role: parts[1] || "",
          goal: parts[2] || "",
          conflict: parts[3] || "",
          notes: parts[4] || "",
        };
      }).filter(item => item.name);
    }

    function numeric(value) {
      const text = value.trim();
      return text ? Number(text) : null;
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function collectPayload() {
      return {
        title: document.querySelector("#title").value.trim(),
        output_language: document.querySelector("#output_language").value || "zh-Hans",
        genre: document.querySelector("#genre").value.trim() || null,
        audience: document.querySelector("#audience").value.trim() || null,
        tone: document.querySelector("#tone").value.trim() || null,
        premise: document.querySelector("#premise").value.trim() || null,
        theme: document.querySelector("#theme").value.trim() || null,
        hook: document.querySelector("#hook").value.trim() || null,
        setting: document.querySelector("#setting").value.trim() || null,
        protagonist: document.querySelector("#protagonist").value.trim() || null,
        outline_hint: document.querySelector("#outline_hint").value.trim() || null,
        world_hint: document.querySelector("#world_hint").value.trim() || null,
        ending_mode: document.querySelector("#ending_mode").value,
        pov: document.querySelector("#pov").value.trim() || "第三人称有限视角",
        target_total_chars: numeric(document.querySelector("#target_total_chars").value),
        target_chars_per_chapter: numeric(document.querySelector("#target_chars_per_chapter").value),
        chapter_count: numeric(document.querySelector("#chapter_count").value),
        volume_count: numeric(document.querySelector("#volume_count").value),
        structure_mode: document.querySelector("#structure_mode").value || "story_driven",
        market_profile: document.querySelector("#market_profile").value || "qidian_longform",
        progression_mode: document.querySelector("#progression_mode").value || "soft_progression",
        progression_flavor: document.querySelector("#progression_flavor").value || "",
        progression_pacing: document.querySelector("#progression_pacing").value || "steady",
        power_system_hint: document.querySelector("#power_system_hint").value.trim() || null,
        style_examples: lines(document.querySelector("#style_examples").value),
        must_include: lines(document.querySelector("#must_include").value),
        avoid: lines(document.querySelector("#avoid").value),
        character_seeds: parseCharacters(document.querySelector("#character_seeds").value),
      };
    }

    function fillForm(payload) {
      for (const [key, value] of Object.entries(payload)) {
        const node = document.querySelector(`#${key}`);
        if (!node) continue;
        if (Array.isArray(value)) {
          if (key === "character_seeds") {
            node.value = value.map(item => [item.name, item.role, item.goal, item.conflict, item.notes].join(" | ")).join("\\n");
          } else {
            node.value = value.join("\\n");
          }
          continue;
        }
        if (key === "output_language" || key === "market_profile" || key === "progression_mode" || key === "progression_flavor" || key === "progression_pacing") {
          node.dataset.currentValue = value ?? "";
        }
        node.value = value ?? "";
      }
    }

    function renderPresetOptions(catalog = {}) {
      state.presets = {
        audience_presets: Array.isArray(catalog.audience_presets) ? catalog.audience_presets : [],
        style_presets: Array.isArray(catalog.style_presets) ? catalog.style_presets : [],
      };
      const audienceSelect = document.querySelector("#audience_preset");
      const styleSelect = document.querySelector("#style_preset");
      audienceSelect.innerHTML = `<option value="">不使用，自己填写</option>${state.presets.audience_presets.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("")}`;
      styleSelect.innerHTML = `<option value="">不使用，自己填写</option>${state.presets.style_presets.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("")}`;
      updatePresetPreview("audience");
      updatePresetPreview("style");
    }

    function renderMarketProfileOptions(options = []) {
      state.marketProfiles = Array.isArray(options) && options.length
        ? options
        : [
            { id: "qidian_longform", label: "起点长篇" },
            { id: "tomato_mass", label: "番茄爆款" },
          ];
      const defaultId = state.marketProfiles[0]?.id || "qidian_longform";
      ["#market_profile", "#batch_market_profile"].forEach(selector => {
        const node = document.querySelector(selector);
        if (!node) return;
        const previous = node.value || node.dataset.currentValue || defaultId;
        node.innerHTML = state.marketProfiles
          .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
          .join("");
        node.value = state.marketProfiles.some(item => item.id === previous) ? previous : defaultId;
        node.dataset.currentValue = node.value;
      });
    }

    function renderOutputLanguageOptions(options = []) {
      state.outputLanguages = Array.isArray(options) && options.length
        ? options
        : [
            { id: "zh-Hans", label: "简体中文" },
            { id: "en", label: "English" },
          ];
      const defaultId = state.outputLanguages.find(item => item.id === "zh-Hans")?.id || state.outputLanguages[0]?.id || "zh-Hans";
      ["#output_language", "#batch_output_language"].forEach(selector => {
        const node = document.querySelector(selector);
        if (!node) return;
        const previous = node.value || node.dataset.currentValue || defaultId;
        node.innerHTML = state.outputLanguages
          .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
          .join("");
        node.value = state.outputLanguages.some(item => item.id === previous) ? previous : defaultId;
        node.dataset.currentValue = node.value;
      });
    }

    function renderProgressionModeOptions(options = []) {
      state.progressionModes = Array.isArray(options) && options.length
        ? options
        : [
            { id: "soft_progression", label: "叙事升级" },
            { id: "hard_realm_progression", label: "硬境界升级" },
          ];
      const defaultId = state.progressionModes[0]?.id || "soft_progression";
      ["#progression_mode", "#batch_progression_mode"].forEach(selector => {
        const node = document.querySelector(selector);
        if (!node) return;
        const previous = node.value || node.dataset.currentValue || defaultId;
        node.innerHTML = state.progressionModes
          .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
          .join("");
        node.value = state.progressionModes.some(item => item.id === previous) ? previous : defaultId;
        node.dataset.currentValue = node.value;
      });
    }

    function renderProgressionFlavorOptions(options = []) {
      state.progressionFlavors = Array.isArray(options) && options.length
        ? options
        : [
            { id: "", label: "自动（按题材）" },
            { id: "xuanhuan_fast", label: "玄幻快升流" },
            { id: "xianxia_steady", label: "仙侠稳升流" },
            { id: "sci_fi_evolution", label: "科幻进化流" },
          ];
      const defaultId = state.progressionFlavors[0]?.id || "";
      ["#progression_flavor", "#batch_progression_flavor"].forEach(selector => {
        const node = document.querySelector(selector);
        if (!node) return;
        const previous = node.value || node.dataset.currentValue || defaultId;
        node.innerHTML = state.progressionFlavors
          .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
          .join("");
        node.value = state.progressionFlavors.some(item => item.id === previous) ? previous : defaultId;
        node.dataset.currentValue = node.value;
      });
    }

    function renderProgressionPacingOptions(options = []) {
      state.progressionPacings = Array.isArray(options) && options.length
        ? options
        : [
            { id: "fast", label: "快" },
            { id: "steady", label: "稳" },
            { id: "slow", label: "慢" },
          ];
      const defaultId = state.progressionPacings.find(item => item.id === "steady")?.id || state.progressionPacings[0]?.id || "steady";
      ["#progression_pacing", "#batch_progression_pacing"].forEach(selector => {
        const node = document.querySelector(selector);
        if (!node) return;
        const previous = node.value || node.dataset.currentValue || defaultId;
        node.innerHTML = state.progressionPacings
          .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
          .join("");
        node.value = state.progressionPacings.some(item => item.id === previous) ? previous : defaultId;
        node.dataset.currentValue = node.value;
      });
    }

    function marketProfileLabel(profileId) {
      const current = state.marketProfiles.find(item => item.id === profileId);
      return current ? current.label : (profileId === "tomato_mass" ? "番茄爆款" : "起点长篇");
    }

    function outputLanguageLabel(languageId) {
      const current = (state.outputLanguages || []).find(item => item.id === languageId);
      return current ? current.label : (languageId || "简体中文");
    }

    function progressionModeLabel(modeId) {
      const current = (state.progressionModes || []).find(item => item.id === modeId);
      return current ? current.label : (modeId === "hard_realm_progression" ? "硬境界升级" : "叙事升级");
    }

    function findPreset(kind, presetId) {
      const key = kind === "audience" ? "audience_presets" : "style_presets";
      return (state.presets[key] || []).find(item => item.id === presetId) || null;
    }

    function updatePresetPreview(kind) {
      const presetId = document.querySelector(kind === "audience" ? "#audience_preset" : "#style_preset").value;
      const target = document.querySelector(kind === "audience" ? "#audience-preset-preview" : "#style-preset-preview");
      const preset = findPreset(kind, presetId);
      if (!preset) {
        target.textContent = kind === "audience"
          ? "给完全不知道“受众怎么写”的人准备。会帮你把读者定位和相关约束一起补进去。"
          : "不是只改一个 tone，而是同时影响节奏、回报、挂钩方式和避坑项。";
        return;
      }
      const fields = preset.fields || {};
      const bullets = [];
      if (fields.audience) bullets.push(`受众：${fields.audience}`);
      if (fields.tone) bullets.push(`气质：${fields.tone}`);
      if (Array.isArray(fields.style_examples) && fields.style_examples.length) bullets.push(`风格约束：${fields.style_examples.slice(0, 2).join("；")}`);
      if (Array.isArray(fields.must_include) && fields.must_include.length) bullets.push(`必含：${fields.must_include.slice(0, 2).join("；")}`);
      target.textContent = `${preset.description} ${bullets.join(" | ")}`.trim();
    }

    function applyPresetFields(fields) {
      const scalarKeys = ["audience", "tone", "outline_hint"];
      for (const key of scalarKeys) {
        if (!fields[key]) continue;
        const node = document.querySelector(`#${key}`);
        if (!node) continue;
        const current = node.value.trim();
        if (!current) {
          node.value = String(fields[key]).trim();
          continue;
        }
        if (key === "outline_hint" && !current.includes(String(fields[key]).trim())) {
          node.value = `${current}\n\n预设约束：${String(fields[key]).trim()}`;
        }
      }
      const listKeys = ["style_examples", "must_include", "avoid"];
      for (const key of listKeys) {
        if (!Array.isArray(fields[key]) || !fields[key].length) continue;
        const node = document.querySelector(`#${key}`);
        if (!node) continue;
        const merged = uniqueLines([...lines(node.value), ...fields[key]]);
        node.value = merged.join("\\n");
      }
    }

    function collectProviderPayload() {
      return {
        base_url: document.querySelector("#provider_base_url").value.trim() || null,
        api_key: document.querySelector("#provider_api_key").value.trim() || null,
        model: document.querySelector("#provider_model").value.trim() || null,
        light_model: document.querySelector("#provider_light_model").value.trim() || null,
        review_model: document.querySelector("#provider_review_model").value.trim() || null,
        wire_api: document.querySelector("#provider_wire_api").value || null,
        gateway_profile: document.querySelector("#provider_gateway_profile").value.trim() || null,
        continuation_mode: document.querySelector("#provider_continuation_mode").value || null,
        flagship_reasoning_effort: document.querySelector("#provider_flagship_reasoning_effort").value.trim() || null,
        flagship_service_tier: document.querySelector("#provider_flagship_service_tier").value.trim() || null,
        light_reasoning_effort: document.querySelector("#provider_light_reasoning_effort").value.trim() || null,
        light_service_tier: document.querySelector("#provider_light_service_tier").value.trim() || null,
      };
    }

    function collectBatchPayload() {
      return {
        batch_name: document.querySelector("#batch_name").value.trim() || null,
        csv_path: document.querySelector("#batch_csv_path").value.trim() || null,
        max_concurrent: numeric(document.querySelector("#batch_max_concurrent").value) || 2,
        target_total_chars: numeric(document.querySelector("#batch_target_total_chars").value),
        run_to_completion: (document.querySelector("#batch_run_to_completion").value || "true") !== "false",
        pause_at_chars: numeric(document.querySelector("#batch_pause_at_chars").value) || 300000,
        target_chars_per_chapter: numeric(document.querySelector("#batch_target_chars_per_chapter").value),
        chapter_count: numeric(document.querySelector("#batch_chapter_count").value),
        volume_count: numeric(document.querySelector("#batch_volume_count").value),
        structure_mode: document.querySelector("#batch_structure_mode").value || "story_driven",
        output_language: document.querySelector("#batch_output_language").value || "zh-Hans",
        market_profile: document.querySelector("#batch_market_profile").value || "qidian_longform",
        progression_mode: document.querySelector("#batch_progression_mode").value || "soft_progression",
        progression_flavor: document.querySelector("#batch_progression_flavor").value || "",
        progression_pacing: document.querySelector("#batch_progression_pacing").value || "steady",
        power_system_hint: document.querySelector("#batch_power_system_hint").value.trim() || null,
        ending_mode: document.querySelector("#batch_ending_mode").value || null,
        pov: document.querySelector("#batch_pov").value.trim() || "第三人称有限视角",
        provider: collectProviderPayload(),
      };
    }

    function collectBatchRuntimePayload() {
      return {
        max_concurrent: numeric(document.querySelector("#batch_max_concurrent").value) || 2,
        run_to_completion: (document.querySelector("#batch_run_to_completion").value || "true") !== "false",
        pause_at_chars: numeric(document.querySelector("#batch_pause_at_chars").value) || 300000,
        provider: collectProviderPayload(),
      };
    }

    function setBatchPlanningLocked(locked) {
      [
        "#batch_target_total_chars",
        "#batch_target_chars_per_chapter",
        "#batch_chapter_count",
        "#batch_volume_count",
        "#batch_structure_mode",
        "#batch_output_language",
        "#batch_market_profile",
        "#batch_progression_mode",
        "#batch_progression_flavor",
        "#batch_progression_pacing",
        "#batch_ending_mode",
        "#batch_pov",
        "#batch_power_system_hint",
      ].forEach(selector => {
        const node = document.querySelector(selector);
        if (node) node.disabled = Boolean(locked);
      });
    }

    function syncBatchRunMode() {
      const runToCompletion = (document.querySelector("#batch_run_to_completion").value || "true") !== "false";
      const field = document.querySelector("#batch_pause_at_chars_field");
      const input = document.querySelector("#batch_pause_at_chars");
      field.style.display = runToCompletion ? "none" : "";
      input.disabled = runToCompletion;
    }

    async function readBatchCsvInput() {
      const fileInput = document.querySelector("#batch_csv_file");
      const pathValue = document.querySelector("#batch_csv_path").value.trim();
      if (fileInput.files && fileInput.files[0]) {
        const file = fileInput.files[0];
        return {
          csv_text: await file.text(),
          source_name: file.name,
        };
      }
      if (pathValue) {
        return {
          csv_path: pathValue,
          source_name: pathValue.split(/[/\\\\]/).pop() || "batch.csv",
        };
      }
      throw new Error("先填写 CSV 文件路径，或选择一个本地 CSV 文件。");
    }

    function selectedProposalIds() {
      return Array.from(document.querySelectorAll("#batch-proposals input[type='checkbox'][data-proposal-id]:checked"))
        .map(node => node.dataset.proposalId)
        .filter(Boolean);
    }

    function renderBatchList(items) {
      const target = document.querySelector("#batch-list");
      const hiddenSuffix = state.hiddenBatchCount ? ` · 隐藏 ${state.hiddenBatchCount}` : "";
      document.querySelector("#batch-list-meta").textContent = `${items.length} 个批次${hiddenSuffix}`;
      if (!items.length) {
        target.innerHTML = "<p>暂无批次。</p>";
        return;
      }
      target.innerHTML = items.map(item => {
        const counts = item.counts || {};
        return `
          <div class="batch-card ${item.batch_id === state.currentBatchId ? "active" : ""} ${item.hidden ? "hidden" : ""}" data-batch-id="${item.batch_id}">
            <div class="batch-head">
              <div>
                <strong>${escapeHtml(item.name)}</strong>
                <div>${escapeHtml(item.status)} · 并发 ${item.max_concurrent}</div>
              </div>
              <div class="batch-actions">
                <button type="button" class="secondary mini-btn" data-action="toggle-hide-batch" data-batch-id="${item.batch_id}">${item.hidden ? "取消隐藏" : "隐藏"}</button>
                <button type="button" class="danger mini-btn" data-action="delete-batch" data-batch-id="${item.batch_id}">删除</button>
              </div>
            </div>
            <div class="mono">${escapeHtml(item.source_name || "")}</div>
            <div class="batch-counts">
              <span class="batch-chip">总 ${counts.total || 0}</span>
              <span class="batch-chip">队列 ${counts.queued || 0}</span>
              <span class="batch-chip">运行 ${counts.running || 0}</span>
              <span class="batch-chip">暂停 ${counts.paused || 0}</span>
              <span class="batch-chip">完成 ${counts.completed || 0}</span>
              <span class="batch-chip">失败 ${counts.failed || 0}</span>
            </div>
          </div>
        `;
      }).join("");
      target.querySelectorAll(".batch-card").forEach(node => {
        node.addEventListener("click", async event => {
          if (event.target.closest("button")) {
            return;
          }
          state.currentBatchId = node.dataset.batchId;
          await refreshCurrentBatch(false);
        });
      });
      target.querySelectorAll("[data-action='toggle-hide-batch']").forEach(node => {
        node.addEventListener("click", async event => {
          event.stopPropagation();
          const batch = state.batches.get(node.dataset.batchId);
          if (!batch) return;
          const path = batch.hidden ? "unhide" : "hide";
          await api(`/api/batches/${batch.batch_id}/${path}`, { method: "POST", body: "{}" });
          if (!state.showHiddenBatches && path === "hide" && state.currentBatchId === batch.batch_id) {
            state.currentBatchId = null;
            clearCurrentBatchView();
          }
          await refreshBatches();
        });
      });
      target.querySelectorAll("[data-action='delete-batch']").forEach(node => {
        node.addEventListener("click", async event => {
          event.stopPropagation();
          const batch = state.batches.get(node.dataset.batchId);
          if (!batch) return;
          if (!confirm(`删除批次《${batch.name}》及其批次记录？\\n运行中的批次无法删除。`)) {
            return;
          }
          await api(`/api/batches/${batch.batch_id}/delete`, { method: "POST", body: "{}" });
          if (state.currentBatchId === batch.batch_id) {
            state.currentBatchId = null;
            resetBatchDraftForm();
            clearCurrentBatchView();
          }
          await refreshBatches();
        });
      });
    }

    function formatCharsShort(value) {
      const chars = Number(value || 0);
      if (!chars) return "0";
      if (chars >= 100000000) return `${(chars / 100000000).toFixed(2)}亿`;
      if (chars >= 10000) return `${(chars / 10000).toFixed(1)}万`;
      return `${chars}`;
    }

    function renderBatchProgress(item) {
      const written = Number(item.written_chars || 0);
      const total = Math.max(Number(item.target_total_chars || 0), 1);
      const pauseAt = Number(item.pause_at_chars || 0);
      const fillPct = Math.max(0, Math.min(100, (written / total) * 100));
      const markerPct = pauseAt > 0 ? Math.max(0, Math.min(100, (pauseAt / total) * 100)) : 0;
      const suffix = pauseAt > 0 ? ` · 暂停线 ${formatCharsShort(pauseAt)}` : "";
      return `
        <div class="batch-progress">
          <div class="batch-progress-track">
            <div class="batch-progress-fill" style="width:${fillPct}%"></div>
            ${pauseAt > 0 ? `<div class="batch-progress-marker" style="left:${markerPct}%"></div>` : ""}
          </div>
          <div class="batch-progress-text">
            <span>已写 ${formatCharsShort(written)}</span>
            <span>目标 ${formatCharsShort(total)}${suffix}</span>
          </div>
        </div>
      `;
    }

    function renderBatchItemActions(batch, proposal, item) {
      const status = item.status || proposal.status || "draft";
      const proposalId = proposal.proposal_id;
      if (status === "completed") {
        return `<span class="help">已完成</span>`;
      }
      if (status === "running" || status === "launching") {
        return `<button type="button" class="secondary mini-btn" data-action="pause-batch-item" data-proposal-id="${proposalId}">暂停</button>`;
      }
      return `<button type="button" class="secondary mini-btn" data-action="resume-batch-item" data-proposal-id="${proposalId}">继续</button>`;
    }

    function renderBatchProposals(batch) {
      const proposals = Array.isArray(batch.proposals) ? batch.proposals : [];
      const itemMap = new Map((batch.items || []).map(item => [item.proposal_id, item]));
      const runtimeMode = (batch.counts && ((batch.counts.running || 0) + (batch.counts.paused || 0) + (batch.counts.completed || 0) + (batch.counts.failed || 0) > 0)) || batch.status !== "draft";
      const target = document.querySelector("#batch-proposals");
      if (!proposals.length) {
        target.innerHTML = `<tr><td colspan="7" class="help">当前批次没有提案。</td></tr>`;
        return;
      }
      target.innerHTML = proposals.map(proposal => {
        const item = itemMap.get(proposal.proposal_id) || {};
        const checked = item.selected !== false ? "checked" : "";
        const runtimeMeta = item.job_id
          ? `
              <div class="batch-runtime-meta">
                <div>${escapeHtml(item.step || item.status || "-")} ${item.upstream_retry_count ? `· upstream ${item.upstream_retry_count}` : ""}</div>
                <div class="help">${escapeHtml(item.message || "-")}</div>
              </div>
            `
          : `
              <div class="batch-runtime-meta">
                <div>${escapeHtml(item.status || proposal.status || "draft")}</div>
                <div class="help">${escapeHtml([proposal.track, proposal.platform_fit].filter(Boolean).join(" / ") || proposal.hook || "-")}</div>
              </div>
            `;
        const titleExtra = runtimeMode
          ? ""
          : `<div class="help" style="margin-top:6px;">${escapeHtml([proposal.track, proposal.platform_fit, proposal.style_seed].filter(Boolean).join(" / ") || proposal.hook || "-")}</div>`;
        return `
          <tr>
            <td><input type="checkbox" data-proposal-id="${proposal.proposal_id}" ${checked}></td>
            <td>
              <div class="batch-title-line">
                <strong>${escapeHtml(proposal.title)}</strong>
              </div>
              ${titleExtra}
            </td>
            <td><span class="status-badge">${escapeHtml(item.status || proposal.status || "draft")}</span></td>
            <td>${renderBatchProgress(item)}</td>
            <td>${runtimeMeta}</td>
            <td><div class="batch-runtime-actions">${renderBatchItemActions(batch, proposal, item)}</div></td>
            <td class="mono">${escapeHtml(item.job_id || "-")}</td>
          </tr>
        `;
      }).join("");
      target.querySelectorAll("[data-action='pause-batch-item']").forEach(node => {
        node.addEventListener("click", async event => {
          event.stopPropagation();
          await api(`/api/batches/${batch.batch_id}/items/${node.dataset.proposalId}/pause`, { method: "POST", body: "{}" });
          await refreshCurrentBatch(false);
        });
      });
      target.querySelectorAll("[data-action='resume-batch-item']").forEach(node => {
        node.addEventListener("click", async event => {
          event.stopPropagation();
          await api(`/api/batches/${batch.batch_id}/items/${node.dataset.proposalId}/resume`, {
            method: "POST",
            body: JSON.stringify(collectBatchRuntimePayload()),
          });
          await refreshCurrentBatch(false);
        });
      });
    }

    function clearCurrentBatchView() {
      state.currentBatch = null;
      document.querySelector("#batch-status-pill").textContent = "Batch Idle";
      document.querySelector("#batch-summary").textContent = "还没有选中批次。";
      document.querySelector("#batch-proposals").innerHTML = `<tr><td colspan="7" class="help">点下面的批次卡片后，这里会显示该批次的运行进度。</td></tr>`;
      setBatchPlanningLocked(false);
    }

    function resetBatchDraftForm() {
      state.currentBatchId = null;
      state.currentBatch = null;
      document.querySelector("#batch_name").value = "";
      document.querySelector("#batch_csv_path").value = "";
      document.querySelector("#batch_csv_file").value = "";
      document.querySelector("#batch_max_concurrent").value = "2";
      document.querySelector("#batch_target_total_chars").value = "1000000";
      document.querySelector("#batch_run_to_completion").value = "true";
      document.querySelector("#batch_pause_at_chars").value = "300000";
      document.querySelector("#batch_target_chars_per_chapter").value = "";
      document.querySelector("#batch_chapter_count").value = "";
      document.querySelector("#batch_volume_count").value = "";
      document.querySelector("#batch_structure_mode").value = "story_driven";
      document.querySelector("#batch_output_language").value = "zh-Hans";
      document.querySelector("#batch_output_language").dataset.currentValue = "zh-Hans";
      document.querySelector("#batch_market_profile").value = "qidian_longform";
      document.querySelector("#batch_market_profile").dataset.currentValue = "qidian_longform";
      document.querySelector("#batch_progression_mode").value = "soft_progression";
      document.querySelector("#batch_progression_mode").dataset.currentValue = "soft_progression";
      document.querySelector("#batch_progression_flavor").value = "";
      document.querySelector("#batch_progression_flavor").dataset.currentValue = "";
      document.querySelector("#batch_progression_pacing").value = "steady";
      document.querySelector("#batch_progression_pacing").dataset.currentValue = "steady";
      document.querySelector("#batch_ending_mode").value = "";
      document.querySelector("#batch_pov").value = "第三人称有限视角";
      document.querySelector("#batch_power_system_hint").value = "";
      syncBatchRunMode();
      setBatchPlanningLocked(false);
      clearCurrentBatchView();
      renderBatchList(Array.from(state.batches.values()));
    }

    async function refreshBatches() {
      const query = state.showHiddenBatches ? "?include_hidden=1" : "";
      const payload = await api(`/api/batches${query}`);
      const items = payload.batches || [];
      state.hiddenBatchCount = payload.hidden_count || 0;
      state.batches = new Map(items.map(item => [item.batch_id, item]));
      renderBatchList(items);
      if (!items.length) {
        state.currentBatchId = null;
        clearCurrentBatchView();
        return;
      }
      if (state.currentBatchId && !items.some(item => item.batch_id === state.currentBatchId)) {
        state.currentBatchId = null;
        clearCurrentBatchView();
      }
      if (state.currentBatchId) {
        await refreshCurrentBatch(false);
      }
    }

    async function refreshCurrentBatch(refreshList = true) {
      if (!state.currentBatchId) {
        clearCurrentBatchView();
        return;
      }
      const batch = await api(`/api/batches/${state.currentBatchId}`);
      state.currentBatch = batch;
      document.querySelector("#batch-status-pill").textContent = batch.status || "Batch Idle";
      const provider = batch.provider_snapshot || {};
      const counts = batch.counts || {};
      const batchMode = batch.config && batch.config.run_to_completion === false
        ? `达到 ${batch.config.pause_at_chars || 300000} 字自动暂停（不影响规划）`
        : "写完整本";
      const marketProfile = marketProfileLabel(batch.config && batch.config.market_profile);
      const outputLanguage = outputLanguageLabel(batch.config && batch.config.output_language);
      const progressionMode = progressionModeLabel(batch.config && batch.config.progression_mode);
      const planningLocked = (batch.status || "draft") !== "draft";
      document.querySelector("#batch-summary").textContent =
        `批次：${batch.name}\n状态：${batch.status} ${batch.paused ? "（已暂停调度）" : ""}\n来源：${batch.source_name || "-"}\n并发：${batch.max_concurrent}\n完成方式：${batchMode}\n输出语言：${outputLanguage}\n平台模式：${marketProfile}\n升级模式：${progressionMode}\n规划参数：${planningLocked ? "已冻结（总字数/输出语言/平台模式/升级模式/结构/结局/卷章/章节字数不可再改）" : "可编辑"}\nProvider：${provider.model || "-"} / ${provider.light_model || "-"} / ${provider.review_model || provider.light_model || "-"} / ${provider.continuation_mode || "-"}\n计数：总 ${counts.total || 0} · 选中 ${counts.selected || 0} · 队列 ${counts.queued || 0} · 运行 ${counts.running || 0} · 暂停 ${counts.paused || 0} · 完成 ${counts.completed || 0} · 失败 ${counts.failed || 0}`;
      renderBatchProposals(batch);
      if (batch.config) {
        document.querySelector("#batch_name").value = batch.name || "";
        document.querySelector("#batch_max_concurrent").value = batch.max_concurrent || 2;
        document.querySelector("#batch_target_total_chars").value = batch.config.target_total_chars || "";
        document.querySelector("#batch_run_to_completion").value = batch.config.run_to_completion === false ? "false" : "true";
        document.querySelector("#batch_pause_at_chars").value = batch.config.pause_at_chars || 300000;
        document.querySelector("#batch_target_chars_per_chapter").value = batch.config.target_chars_per_chapter || "";
        document.querySelector("#batch_chapter_count").value = batch.config.chapter_count || "";
        document.querySelector("#batch_volume_count").value = batch.config.volume_count || "";
        document.querySelector("#batch_structure_mode").value = batch.config.structure_mode || "story_driven";
        document.querySelector("#batch_output_language").value = batch.config.output_language || "zh-Hans";
        document.querySelector("#batch_output_language").dataset.currentValue = batch.config.output_language || "zh-Hans";
        document.querySelector("#batch_market_profile").value = batch.config.market_profile || "qidian_longform";
        document.querySelector("#batch_market_profile").dataset.currentValue = batch.config.market_profile || "qidian_longform";
        document.querySelector("#batch_progression_mode").value = batch.config.progression_mode || "soft_progression";
        document.querySelector("#batch_progression_mode").dataset.currentValue = batch.config.progression_mode || "soft_progression";
        document.querySelector("#batch_progression_flavor").value = batch.config.progression_flavor || "";
        document.querySelector("#batch_progression_flavor").dataset.currentValue = batch.config.progression_flavor || "";
        document.querySelector("#batch_progression_pacing").value = batch.config.progression_pacing || "steady";
        document.querySelector("#batch_progression_pacing").dataset.currentValue = batch.config.progression_pacing || "steady";
        document.querySelector("#batch_ending_mode").value = batch.config.ending_mode || "";
        document.querySelector("#batch_pov").value = batch.config.pov || "第三人称有限视角";
        document.querySelector("#batch_power_system_hint").value = batch.config.power_system_hint || "";
        syncBatchRunMode();
      }
      setBatchPlanningLocked(planningLocked);
      clearTimeout(state.batchTimer);
      if (batch.status === "running") {
        state.batchTimer = setTimeout(() => refreshCurrentBatch(false).catch(console.error), 3000);
      }
      if (refreshList) {
        await refreshBatches();
      }
    }

    function setProviderStatus(message, tone = "muted") {
      const target = document.querySelector("#provider-test-status");
      target.textContent = message;
      target.style.color = tone === "error"
        ? "#8f1d1d"
        : tone === "warning"
          ? "#9a5a19"
        : tone === "success"
          ? "var(--accent)"
          : "var(--muted)";
    }

    function renderProviderSettings(payload) {
      state.provider = payload;
      const form = payload.form || {};
      document.querySelector("#provider_base_url").value = form.base_url || "";
      document.querySelector("#provider_api_key").value = "";
      document.querySelector("#provider_model").value = form.model || "";
      document.querySelector("#provider_light_model").value = form.light_model || form.review_model || "";
      document.querySelector("#provider_review_model").value = form.review_model || form.light_model || form.model || "";
      document.querySelector("#provider_wire_api").value = form.wire_api || "responses";
      document.querySelector("#provider_gateway_profile").value = form.gateway_profile || "";
      document.querySelector("#provider_continuation_mode").value = form.continuation_mode || "replay";
      document.querySelector("#provider_flagship_reasoning_effort").value = form.flagship_reasoning_effort || "";
      document.querySelector("#provider_flagship_service_tier").value = form.flagship_service_tier || "";
      document.querySelector("#provider_light_reasoning_effort").value = form.light_reasoning_effort || "";
      document.querySelector("#provider_light_service_tier").value = form.light_service_tier || "";
      document.querySelector("#provider-source").textContent = `${payload.provider_source === "override" ? "项目覆盖中" : "Codex 默认"} · ${payload.effective?.wire_api || "-"}`;
      document.querySelector("#provider-override-path").textContent = payload.override_path || "";
      const keyHint = document.querySelector("#provider-key-hint");
      const apiKeySource = form.api_key_source === "override" ? "项目覆盖" : "Codex";
      keyHint.textContent = form.api_key_present
        ? `当前检测到可用密钥，来源：${apiKeySource}。留空保存时会保留现有密钥来源。`
        : "当前未检测到可用密钥。";
      setProviderStatus(
        payload.provider_source === "override"
          ? "当前项目正在使用本地 provider 覆盖。保存会更新覆盖，恢复默认会回退到 Codex。"
          : "当前项目使用 Codex 默认 provider。保存后，本项目后续任务会切到本地覆盖。",
        payload.provider_source === "override" ? "success" : "muted"
      );
    }

    async function refreshProviderSettings() {
      const payload = await api("/api/provider");
      renderProviderSettings(payload);
      return payload;
    }

    async function loadTemplateData() {
      const template = await api("/api/template");
      state.template = template;
      renderPresetOptions(template.preset_catalog || {});
      renderOutputLanguageOptions(template.output_language_options || []);
      renderMarketProfileOptions(template.market_profile_options || []);
      renderProgressionModeOptions(template.progression_mode_options || []);
      renderProgressionFlavorOptions(template.progression_flavor_options || []);
      renderProgressionPacingOptions(template.progression_pacing_options || []);
      return template;
    }

    function renderLog(items) {
      const target = document.querySelector("#job-log");
      target.innerHTML = items.length ? items.map(item => `<div class="log-item"><strong>${item.step}</strong><div>${item.message}</div></div>`).join("") : "<p>等待任务开始。</p>";
    }

    function renderJobs(items) {
      const target = document.querySelector("#jobs");
      if (!items.length) {
        target.innerHTML = state.hiddenCount && !state.showHidden
          ? `<p>暂无可见任务。当前有 ${state.hiddenCount} 个隐藏任务，勾选“显示隐藏任务”可查看。</p>`
          : `<p>当前没有单独任务。</p>`;
        return;
      }
      target.innerHTML = items.map(item => `
        <div class="job ${item.job_id === state.currentJobId ? "active" : ""} ${item.hidden ? "hidden" : ""}" data-job-id="${item.job_id}">
          <div class="job-head">
            <div>
              <strong>${escapeHtml(item.title)}</strong>
              <div>${escapeHtml(item.job_kind === "batch" ? "批量" : "单独")} · ${escapeHtml(item.status)} / ${escapeHtml(item.step || "-")}${item.hidden ? " · 已隐藏" : ""}</div>
            </div>
            <div class="job-actions">
              <button type="button" class="secondary mini-btn" data-action="toggle-hide" data-job-id="${item.job_id}">${item.hidden ? "取消隐藏" : "隐藏"}</button>
              <button type="button" class="danger mini-btn" data-action="delete" data-job-id="${item.job_id}">删除</button>
            </div>
          </div>
          <div class="mono">attempt ${item.attempt_count || 0} · auto ${item.auto_resume_count || 0}</div>
          <div class="mono">${escapeHtml(item.output_dir || "")}</div>
        </div>
      `).join("");
      target.querySelectorAll(".job").forEach(node => {
        node.addEventListener("click", event => {
          if (event.target.closest("button")) {
            return;
          }
          state.currentJobId = node.dataset.jobId;
          refreshCurrentJob();
        });
      });
      target.querySelectorAll("[data-action='toggle-hide']").forEach(node => {
        node.addEventListener("click", async event => {
          event.stopPropagation();
          const job = state.jobs.get(node.dataset.jobId);
          if (!job) return;
          const path = job.hidden ? "unhide" : "hide";
          await api(`/api/jobs/${job.job_id}/${path}`, { method: "POST", body: "{}" });
          if (job.hidden && !state.showHidden) {
            state.currentJobId = null;
          }
          await refreshJobs();
          if (state.currentJobId) {
            await refreshCurrentJob(false);
          }
        });
      });
      target.querySelectorAll("[data-action='delete']").forEach(node => {
        node.addEventListener("click", async event => {
          event.stopPropagation();
          const job = state.jobs.get(node.dataset.jobId);
          if (!job) return;
          await requestDelete(job);
        });
      });
    }

    async function refreshInfo() {
      const info = await api("/api/info");
      const source = info.provider_source === "override" ? "override" : "codex";
      document.querySelector("#provider").textContent = `${info.model} @ ${info.base_url} · ${source}`;
      document.querySelector("#version-tag").textContent = `${info.version || "unknown"} (${info.revision || "unknown"})`;
    }

    function formatTime(timestamp) {
      if (!timestamp) return "未知";
      return new Date(timestamp * 1000).toLocaleString("zh-CN", { hour12: false });
    }

    async function refreshJobs() {
      const params = new URLSearchParams();
      if (state.showHidden) params.set("include_hidden", "1");
      params.set("kind", "single");
      const query = params.toString() ? `?${params.toString()}` : "";
      const jobs = await api(`/api/jobs${query}`);
      const items = jobs.jobs || [];
      state.hiddenCount = jobs.hidden_count || 0;
      state.jobs = new Map(items.map(item => [item.job_id, item]));
      renderJobs(items);
      if (!items.length) return;
      const currentExists = state.currentJobId && items.some(item => item.job_id === state.currentJobId);
      if (!currentExists) {
        const preferred = items.find(item => item.status === "running" || item.status === "queued" || item.status === "waiting_retry") || items[0];
        if (preferred) {
          state.currentJobId = preferred.job_id;
          await refreshCurrentJob(false);
        }
      }
    }

    async function refreshCurrentJob(refreshList = true) {
      if (!state.currentJobId) return;
      const data = await api(`/api/jobs/${state.currentJobId}`);
      document.querySelector("#job-status-text").textContent = data.message || data.status;
      document.querySelector("#job-badge").textContent = data.status;
      const nextRetrySuffix = data.upstream_next_retry_at ? ` · 下次上游重试 ${formatTime(data.upstream_next_retry_at)}` : "";
      document.querySelector("#job-meta").textContent = `step ${data.step || "-"} · attempt ${data.attempt_count || 0} · auto ${data.auto_resume_count || 0} · upstream ${data.upstream_retry_count || 0} · 上次更新 ${formatTime(data.updated_at)}${data.status === "running" ? ` · 静默 ${data.stalled_for_seconds || 0}s` : ""}${nextRetrySuffix}`;
      const provider = data.provider_snapshot || {};
      const providerParts = [];
      if (provider.wire_api) {
        providerParts.push(provider.wire_api);
      }
      if (provider.model || provider.light_model) {
        providerParts.push(`${provider.model || "-"} / ${provider.light_model || provider.model || "-"} / ${provider.review_model || provider.light_model || provider.model || "-"}`);
      }
      if (provider.continuation_mode) {
        providerParts.push(provider.continuation_mode);
      }
      if (provider.base_url) {
        providerParts.push(provider.base_url);
      }
      if (provider.source) {
        providerParts.push(provider.source === "job_snapshot" ? "任务快照" : "当前默认");
      }
      document.querySelector("#job-provider-meta").textContent = providerParts.length
        ? `provider ${providerParts.join(" · ")}`
        : "";
      document.querySelector("#job-path").textContent = data.output_dir || "";
      renderLog(data.log || []);
      const preview = document.querySelector("#job-preview");
      preview.textContent = data.novel_preview || "任务尚未生成正文。";
      const summary = document.querySelector("#job-summary");
      if (data.summary) {
        summary.style.display = "block";
        const qualityParts = [];
        if (data.summary.quality_status) {
          qualityParts.push(`质检 ${data.summary.quality_status}`);
        }
        if (data.summary.quality_score !== undefined && data.summary.quality_score !== null) {
          qualityParts.push(`质检分 ${data.summary.quality_score}`);
        }
        const qualityText = qualityParts.length ? `  ${qualityParts.join(" · ")}` : "";
        summary.textContent = `${data.summary.final_summary}  终审分 ${data.summary.final_score ?? "-"}${qualityText}`;
      } else if (data.error) {
        summary.style.display = "block";
        summary.textContent = data.message || data.error;
      } else {
        summary.style.display = "none";
      }
      const resumeButton = document.querySelector("#resume-job");
      const pauseButton = document.querySelector("#pause-job");
      const hideButton = document.querySelector("#toggle-hide-job");
      const deleteButton = document.querySelector("#delete-job");
      hideButton.style.display = "inline-flex";
      hideButton.textContent = data.hidden ? "取消隐藏" : "隐藏";
      resumeButton.textContent = "恢复运行";
      if (data.status === "completed") {
        resumeButton.style.display = "none";
        pauseButton.style.display = "none";
        deleteButton.style.display = "inline-flex";
      } else if (data.status === "queued" || data.status === "running" || data.status === "waiting_retry") {
        resumeButton.style.display = "none";
        pauseButton.style.display = "inline-flex";
        deleteButton.style.display = "none";
      } else {
        resumeButton.style.display = "inline-flex";
        pauseButton.style.display = "none";
        deleteButton.style.display = "inline-flex";
      }
      const link = document.querySelector("#novel-link");
      const qualityLink = document.querySelector("#quality-report-link");
      const folderButton = document.querySelector("#open-folder");
      const cleanupButton = document.querySelector("#delivery-cleanup");
      if (data.status === "completed") {
        link.style.display = "inline-flex";
        link.href = `/api/jobs/${data.job_id}/novel`;
        qualityLink.style.display = "inline-flex";
        qualityLink.href = `/api/jobs/${data.job_id}/quality-report`;
      } else {
        link.style.display = "none";
        qualityLink.style.display = "none";
      }
      folderButton.style.display = data.output_dir ? "inline-flex" : "none";
      cleanupButton.style.display = data.status === "completed" ? "inline-flex" : "none";
      if (data.status === "queued" || data.status === "running" || data.status === "waiting_retry") {
        clearTimeout(state.timer);
        state.timer = setTimeout(refreshCurrentJob, 2500);
      }
      if (refreshList) {
        await refreshJobs();
      }
    }

    async function requestDelete(job) {
      if (job.status === "queued" || job.status === "running") {
        alert("请先暂停任务，再执行删除。");
        return;
      }
      if (!confirm(`这会永久删除整个项目目录：\\n${job.output_dir}\\n\\n删除后无法恢复。是否继续？`)) {
        return;
      }
      const confirmTitle = window.prompt(`第一次确认：请输入任务标题\\n${job.title}`);
      if (confirmTitle !== job.title) {
        alert("标题不匹配，已取消删除。");
        return;
      }
      const confirmJobId = window.prompt(`第二次确认：请输入任务 ID\\n${job.job_id}`);
      if (confirmJobId !== job.job_id) {
        alert("任务 ID 不匹配，已取消删除。");
        return;
      }
      if (!confirm(`最后确认：立即永久删除《${job.title}》及其全部产物？`)) {
        return;
      }
      await api(`/api/jobs/${job.job_id}/delete`, {
        method: "POST",
        body: JSON.stringify({ confirm_title: confirmTitle, confirm_job_id: confirmJobId }),
      });
      if (state.currentJobId === job.job_id) {
        state.currentJobId = null;
      }
      await refreshJobs();
      if (state.currentJobId) {
        await refreshCurrentJob(false);
      } else {
        document.querySelector("#job-status-text").textContent = "还没有运行中的任务。";
        document.querySelector("#job-badge").textContent = "Idle";
        document.querySelector("#job-meta").textContent = "";
        document.querySelector("#job-path").textContent = "";
        document.querySelector("#job-summary").style.display = "none";
        document.querySelector("#job-preview").textContent = "任务尚未生成正文。";
        renderLog([]);
      }
    }

    document.querySelector("#test-provider").addEventListener("click", async () => {
      try {
        setProviderStatus("正在测试当前表单配置...", "muted");
        const result = await api("/api/provider/test", {
          method: "POST",
          body: JSON.stringify(collectProviderPayload()),
        });
        const flagship = result.tests?.flagship;
        const light = result.tests?.light;
        const review = result.tests?.review;
        const flagshipText = flagship
          ? flagship.ok
            ? `旗舰模型 ${flagship.model}：${flagship.elapsed_ms} ms，返回 ${flagship.reply || "(empty)"}`
            : `旗舰模型 ${flagship.model}：失败，${flagship.error || "unknown error"}`
          : `旗舰模型 ${result.resolved.model}：${result.elapsed_ms} ms，返回 ${result.reply || "(empty)"}`;
        const lightText = light
          ? light.reused
            ? light.ok
              ? `轻量模型 ${light.model}：与旗舰模型相同，复用本次探测结果`
              : `轻量模型 ${light.model}：与旗舰模型相同，复用失败结果`
            : light.ok
              ? `轻量模型 ${light.model}：${light.elapsed_ms} ms，返回 ${light.reply || "(empty)"}`
              : `轻量模型 ${light.model}：失败，${light.error || "unknown error"}`
          : `轻量模型 ${result.resolved.light_model || result.resolved.review_model || result.resolved.model}：未单独探测`;
        const reviewText = review
          ? review.reused
            ? review.ok
              ? `审校模型 ${review.model}：与其他探测模型相同，复用本次探测结果`
              : `审校模型 ${review.model}：与其他探测模型相同，复用失败结果`
            : review.ok
              ? `审校模型 ${review.model}：${review.elapsed_ms} ms，返回 ${review.reply || "(empty)"}`
              : `审校模型 ${review.model}：失败，${review.error || "unknown error"}`
          : `审校模型 ${result.resolved.review_model || result.resolved.light_model || result.resolved.model}：未单独探测`;
        const tone = result.ok ? "success" : result.partial ? "warning" : "error";
        const prefix = result.ok ? "连接成功" : result.partial ? "部分成功" : "连接失败";
        setProviderStatus(
          `${prefix}，总耗时 ${result.elapsed_ms} ms。${flagshipText}；${lightText}；${reviewText}。当前网关 ${result.resolved.base_url}`,
          tone
        );
      } catch (error) {
        setProviderStatus(`连接失败：${error.message}`, "error");
      }
    });

    document.querySelector("#save-provider").addEventListener("click", async () => {
      try {
        const result = await api("/api/provider", {
          method: "POST",
          body: JSON.stringify(collectProviderPayload()),
        });
        renderProviderSettings(result);
        document.querySelector("#provider_api_key").value = "";
        await refreshInfo();
        setProviderStatus("本地 provider 覆盖已保存。新启动的任务会使用这套配置。", "success");
      } catch (error) {
        setProviderStatus(`保存失败：${error.message}`, "error");
      }
    });

    document.querySelector("#reset-provider").addEventListener("click", async () => {
      if (!confirm("这会删除当前项目的 provider 覆盖文件，并回退到 Codex 默认配置。是否继续？")) {
        return;
      }
      try {
        const result = await api("/api/provider/reset", { method: "POST", body: "{}" });
        renderProviderSettings(result);
        document.querySelector("#provider_api_key").value = "";
        await refreshInfo();
        setProviderStatus("已清除项目覆盖，当前回退到 Codex 默认 provider。", "success");
      } catch (error) {
        setProviderStatus(`恢复默认失败：${error.message}`, "error");
      }
    });

    document.querySelector("#load-template").addEventListener("click", async () => {
      const template = state.template || await loadTemplateData();
      fillForm(template);
    });

    document.querySelector("#batch_run_to_completion").addEventListener("change", syncBatchRunMode);

    document.querySelector("#clear-form").addEventListener("click", () => {
      document.querySelector("#project-form").reset();
      document.querySelector("#audience_preset").value = "";
      document.querySelector("#style_preset").value = "";
      document.querySelector("#output_language").value = "zh-Hans";
      document.querySelector("#market_profile").value = "qidian_longform";
      document.querySelector("#progression_mode").value = "soft_progression";
      document.querySelector("#progression_flavor").value = "";
      document.querySelector("#progression_pacing").value = "steady";
      document.querySelector("#character_seeds").value = "";
      document.querySelector("#style_examples").value = "";
      document.querySelector("#must_include").value = "";
      document.querySelector("#avoid").value = "";
      document.querySelector("#power_system_hint").value = "";
      updatePresetPreview("audience");
      updatePresetPreview("style");
    });

    syncBatchRunMode();

    document.querySelector("#audience_preset").addEventListener("change", () => updatePresetPreview("audience"));
    document.querySelector("#style_preset").addEventListener("change", () => updatePresetPreview("style"));

    document.querySelector("#apply-presets").addEventListener("click", () => {
      const audiencePreset = findPreset("audience", document.querySelector("#audience_preset").value);
      const stylePreset = findPreset("style", document.querySelector("#style_preset").value);
      if (!audiencePreset && !stylePreset) {
        alert("先选一个受众预设或文风预设。");
        return;
      }
      if (!confirm("预设会补空白字段，并把风格约束去重合并进当前表单。是否继续？")) {
        return;
      }
      if (audiencePreset) {
        applyPresetFields(audiencePreset.fields || {});
      }
      if (stylePreset) {
        applyPresetFields(stylePreset.fields || {});
      }
    });

    document.querySelector("#submit-job").addEventListener("click", async () => {
      const payload = collectPayload();
      if (!payload.title) {
        alert("至少要填标题。");
        return;
      }
      const result = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
      state.currentJobId = result.job_id;
      await refreshCurrentJob();
    });

    document.querySelector("#batch-import").addEventListener("click", async () => {
      try {
        const csvPayload = await readBatchCsvInput();
        const payload = { ...collectBatchPayload(), ...csvPayload };
        const batch = await api("/api/batches/import-csv", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        state.currentBatchId = batch.batch_id;
        await refreshCurrentBatch();
      } catch (error) {
        alert(`导入批次失败：${error.message}`);
      }
    });

    document.querySelector("#batch-reset").addEventListener("click", () => {
      resetBatchDraftForm();
    });

    document.querySelector("#batch-launch").addEventListener("click", async () => {
      if (!state.currentBatchId) {
        alert("先导入一个批次。");
        return;
      }
      const selected = selectedProposalIds();
      if (!selected.length) {
        alert("至少勾选一条提案。");
        return;
      }
      const batch = await api(`/api/batches/${state.currentBatchId}/launch`, {
        method: "POST",
        body: JSON.stringify({
          ...collectBatchPayload(),
          selected_proposal_ids: selected,
          provider: collectProviderPayload(),
        }),
      });
      state.currentBatchId = batch.batch_id;
      await refreshCurrentBatch();
      await refreshJobs();
    });

    document.querySelector("#batch-pause").addEventListener("click", async () => {
      if (!state.currentBatchId) return;
      await api(`/api/batches/${state.currentBatchId}/pause`, { method: "POST", body: "{}" });
      await refreshCurrentBatch();
    });

    document.querySelector("#batch-resume").addEventListener("click", async () => {
      if (!state.currentBatchId) return;
      await api(`/api/batches/${state.currentBatchId}/resume`, {
        method: "POST",
        body: JSON.stringify(collectBatchRuntimePayload()),
      });
      await refreshCurrentBatch();
    });

    document.querySelector("#batch-retry").addEventListener("click", async () => {
      if (!state.currentBatchId) return;
      await api(`/api/batches/${state.currentBatchId}/retry-failed`, {
        method: "POST",
        body: JSON.stringify(collectBatchRuntimePayload()),
      });
      await refreshCurrentBatch();
    });

    document.querySelector("#batch-resume-all").addEventListener("click", async () => {
      if (!state.currentBatchId) return;
      await api(`/api/batches/${state.currentBatchId}/resume-all`, {
        method: "POST",
        body: JSON.stringify(collectBatchRuntimePayload()),
      });
      await refreshCurrentBatch();
      await refreshJobs();
    });

    document.querySelector("#batch-export").addEventListener("click", async () => {
      if (!state.currentBatchId) return;
      const result = await api(`/api/batches/${state.currentBatchId}/export`);
      const counts = result.counts || {};
      alert(`已导出批次汇总。总 ${counts.total || 0} 条，完成 ${counts.completed || 0} 条，失败 ${counts.failed || 0} 条。`);
    });

    document.querySelector("#batch-open-folder").addEventListener("click", async () => {
      if (!state.currentBatchId) {
        alert("先选中一个批次。");
        return;
      }
      await api(`/api/batches/${state.currentBatchId}/open-folder`, { method: "POST", body: "{}" });
    });

    document.querySelector("#pause-job").addEventListener("click", async () => {
      if (!state.currentJobId) return;
      await api(`/api/jobs/${state.currentJobId}/pause`, { method: "POST", body: "{}" });
      await refreshCurrentJob();
    });

    document.querySelector("#resume-job").addEventListener("click", async () => {
      if (!state.currentJobId) return;
      await api(`/api/jobs/${state.currentJobId}/resume`, {
        method: "POST",
        body: JSON.stringify({ provider: collectProviderPayload() }),
      });
      await refreshCurrentJob();
    });

    document.querySelector("#toggle-hide-job").addEventListener("click", async () => {
      if (!state.currentJobId) return;
      const current = state.jobs.get(state.currentJobId) || await api(`/api/jobs/${state.currentJobId}`);
      const path = current.hidden ? "unhide" : "hide";
      await api(`/api/jobs/${state.currentJobId}/${path}`, { method: "POST", body: "{}" });
      if (path === "hide" && !state.showHidden) {
        state.currentJobId = null;
      }
      await refreshJobs();
      if (state.currentJobId) {
        await refreshCurrentJob(false);
      }
    });

    document.querySelector("#delete-job").addEventListener("click", async () => {
      if (!state.currentJobId) return;
      const current = state.jobs.get(state.currentJobId) || await api(`/api/jobs/${state.currentJobId}`);
      await requestDelete(current);
    });

    document.querySelector("#open-folder").addEventListener("click", async () => {
      if (!state.currentJobId) return;
      await api(`/api/jobs/${state.currentJobId}/open-folder`, { method: "POST", body: "{}" });
    });

    document.querySelector("#delivery-cleanup").addEventListener("click", async () => {
      if (!state.currentJobId) return;
      if (!confirm("这会删除已完稿项目中的失败快照和终审预览缓存，并保留正式成书文件。是否继续？")) {
        return;
      }
      const result = await api(`/api/jobs/${state.currentJobId}/delivery-cleanup`, { method: "POST", body: "{}" });
      alert(`交付清理完成：移除 ${result.report.removed_count} 个调试快照。`);
      await refreshCurrentJob();
    });

    document.querySelector("#show-hidden").addEventListener("change", async event => {
      state.showHidden = event.target.checked;
      await refreshJobs();
      if (state.currentJobId) {
        await refreshCurrentJob(false);
      }
    });

    document.querySelector("#show-hidden-batches").addEventListener("change", async event => {
      state.showHiddenBatches = event.target.checked;
      await refreshBatches();
      if (state.currentBatchId) {
        await refreshCurrentBatch(false);
      }
    });

    clearCurrentBatchView();
    refreshInfo().catch(console.error);
    refreshProviderSettings().catch(console.error);
    loadTemplateData().catch(console.error);
    refreshJobs().catch(console.error);
    refreshBatches().catch(console.error);
  </script>
</body>
</html>"""
