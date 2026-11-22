/* 门诊知识助手 MVP 前端逻辑：登录态 / 问答(RAG+LLM流式) / 知识库 / Wiki图谱 / 管理后台 */
"use strict";

/* ---------- 全局状态 ---------- */
const state = { token: null, user: null, models: [], chart: null };

/* 云服务客户端：endpoint + publishableKey 全部来自 publicConfig（开通时下发） */
const cloud = WorkBuddyCloud.createWorkBuddyCloud({
  endpoint: window.PUBLIC_CONFIG.endpoint,
  publishableKey: window.PUBLIC_CONFIG.publishableKey,
});

/* ---------- 工具函数 ---------- */
const $ = (id) => document.getElementById(id); // 简写取元素

async function api(path, body, method) {
  /* 统一请求后端：自动带 Token，解析统一返回结构。
     入参：path 接口路径；body 请求体；method 方法。
     出参：data 部分。失败时抛出带 msg 的 Error。 */
  const headers = { "Content-Type": "application/json" };
  if (state.token) {
    headers["Authorization"] = "Bearer " + state.token; // 标准凭证头
    headers["X-Auth-Token"] = state.token; // 备用凭证头（防部分网关改写 Authorization）
  }
  const res = await fetch(path, {
    method: method || (body ? "POST" : "GET"),
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json(); // 后端统一 {"ok","data","error"}
  if (!json.ok) throw new Error((json.error && json.error.msg) || "请求失败");
  return json.data;
}

const tierLabel = (t) => ["层级1-普通", "层级2-高级", "层级3-内部"][t - 1] || "层级" + t; // 层级文案

/* ---------- 登录 / 退出 ---------- */
async function doLogin() {
  /* 登录：调 /api/auth/login，保存 Token 与用户信息。 */
  const username = $("loginUser").value.trim();
  const password = $("loginPwd").value;
  if (!username || !password) { $("loginMsg").textContent = "请输入用户名和密码"; return; }
  try {
    const data = await api("/api/auth/login", { username, password });
    state.token = data.token; // 存 Token
    state.user = data.user; // 存用户
    localStorage.setItem("mvp_token", data.token); // 持久化，刷新不丢
    enterApp(); // 进入主界面
  } catch (e) {
    $("loginMsg").textContent = e.message; // 显示错误
  }
}

function doLogout() {
  /* 退出：清状态回登录页。 */
  state.token = null; state.user = null;
  localStorage.removeItem("mvp_token");
  $("appView").classList.add("hidden");
  $("loginView").classList.remove("hidden");
}

async function tryResume() {
  /* 刷新后恢复登录态：用旧 Token 调 /api/auth/me。 */
  const t = localStorage.getItem("mvp_token");
  if (!t) return false;
  state.token = t;
  try { state.user = await api("/api/auth/me"); return true; }
  catch (e) { state.token = null; localStorage.removeItem("mvp_token"); return false; }
}

/* ---------- 主界面进入与页签 ---------- */
function enterApp() {
  /* 切到主界面并按角色装配功能。 */
  $("loginView").classList.add("hidden");
  $("appView").classList.remove("hidden");
  const u = state.user;
  $("userLabel").textContent = u.display_name + " · " + (u.role === "admin" ? "SaaS管理员" : tierLabel(u.tier));
  if (u.role === "admin") document.querySelectorAll(".admin-only").forEach(el => el.classList.remove("hidden")); // 管理员才显示后台
  switchTab("chat"); // 默认问答页
}

function switchTab(name) {
  /* 页签切换。 */
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".page").forEach(p => p.classList.add("hidden"));
  $("tab-" + name).classList.remove("hidden");
  if (name === "kb") loadKb();
  if (name === "wiki") loadWiki();
  if (name === "admin") loadAdmin();
}

/* ---------- 问答（RAG + 云端 LLM 流式） ---------- */
async function ensureModels() {
  /* 拉取可用模型列表（只取第一个可用模型）。 */
  if (state.models.length) return;
  const list = await cloud.llm.models.list();
  state.models = (list || []).filter(m => m.disabled !== true); // 过滤掉禁用模型
}

function addBubble(role, text) {
  /* 追加一条气泡，返回该元素以便流式追加内容。 */
  const div = document.createElement("div");
  div.className = "bubble " + (role === "user" ? "user" : "bot");
  div.textContent = text;
  $("chatList").appendChild(div);
  $("chatList").scrollTop = $("chatList").scrollHeight; // 滚到底
  return div;
}

async function sendQuestion() {
  /* 问答主流程：1) RAG 检索 → 2) 拼 Prompt 调云端 LLM 流式生成 → 3) 展示引用来源 → 4) 留痕。 */
  const input = $("chatInput");
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  $("chatSend").disabled = true;
  addBubble("user", q);
  let chunks = [];
  try {
    const data = await api("/api/rag/search", { query: q, top_k: 4 }); // 第一步：后端 RAG 检索
    chunks = data.chunks || [];
  } catch (e) {
    addBubble("bot", "检索失败：" + e.message);
    $("chatSend").disabled = false;
    return;
  }
  const bubble = addBubble("bot", "（正在结合知识库生成回答……）"); // 占位气泡
  let answer = "";
  const sources = chunks.map(c => c.title);
  try {
    await ensureModels(); // 确保模型列表就绪
    if (!state.models.length) throw new Error("当前应用没有可用模型");
    const model = state.models[0]; // 取第一个可用模型
    const context = chunks.length
      ? chunks.map((c, i) => `【资料${i + 1}·${c.title}】\n${c.content}`).join("\n\n")
      : "（知识库中未检索到直接相关资料）";
    const messages = [
      { role: "system", content: "你是门诊预约与分诊协作知识助手。必须严格依据用户消息中的【资料】回答问题；资料不足以回答时，明确说明\"知识库中暂无相关资料\"。回答用简体中文，条理清晰，不超过 300 字。" },
      { role: "user", content: `【资料】\n${context}\n\n【问题】\n${q}` },
    ];
    for await (const chunk of cloud.llm.chat.completions.create({
      model: model.id, messages, stream: true, temperature: 0.5,
    })) {
      const delta = chunk.choices && chunk.choices[0] && chunk.choices[0].delta; // 流式增量
      if (delta && delta.content) {
        if (!answer) bubble.textContent = ""; // 首个增量时清掉占位文案
        answer += delta.content;
        bubble.textContent = answer;
        $("chatList").scrollTop = $("chatList").scrollHeight;
      }
    }
  } catch (e) {
    // 模型通道失败时的兜底：直接摘录检索到的资料片段，保证问答不中断
    if (!answer) {
      answer = chunks.length
        ? "模型通道暂不可用，以下为知识库检索结果摘录：\n\n" +
          chunks.map(c => `• ${c.title}：${c.content.slice(0, 120)}…`).join("\n\n")
        : "模型通道暂不可用，且知识库中未检索到相关资料。";
      bubble.textContent = answer;
    }
  }
  if (chunks.length) { // 展示引用来源
    $("sourceBox").classList.remove("hidden");
    $("sourceBox").innerHTML = "<b>引用来源（RAG 检索）：</b>" +
      chunks.map((c, i) => `${i + 1}. ${c.title}（${c.category}，相关度 ${c.score}）`).join("　");
  } else {
    $("sourceBox").classList.add("hidden");
  }
  try { await api("/api/rag/log", { question: q, sources: sources.join("；") }); } catch (e) { /* 留痕失败不影响展示 */ }
  $("chatSend").disabled = false;
}

/* ---------- 知识库页 ---------- */
async function loadKb() {
  /* 拉取并渲染当前用户可见的知识条目。 */
  const list = await api("/api/kb/list");
  const box = $("kbList");
  box.innerHTML = "";
  list.forEach(e => {
    const div = document.createElement("div");
    div.className = "kb-item";
    div.innerHTML = `<div class="kb-head"><h3></h3>
        <span class="chip cat"></span>
        <span class="chip t${e.tier_required}">${tierLabel(e.tier_required)}起可见</span></div><p></p>`;
    div.querySelector("h3").textContent = e.title;
    div.querySelector(".chip.cat").textContent = e.category;
    div.querySelector("p").textContent = e.content;
    box.appendChild(div);
  });
  if (!list.length) box.innerHTML = '<div class="note">暂无可见知识条目。</div>';
}

/* ---------- Wiki 图谱页 ---------- */
const CAT_COLORS = ["#534AB7", "#0F6E56", "#BA7517", "#993556", "#A32D2D", "#185FA5"]; // 六分类配色

async function loadWiki() {
  /* 拉取图谱数据并用 ECharts 力导向图渲染。 */
  const g = await api("/api/wiki/graph");
  const dom = $("wikiChart");
  if (state.chart) { state.chart.dispose(); state.chart = null; } // 重建避免残影
  state.chart = echarts.init(dom);
  const data = g.nodes.map(n => ({
    name: n.name,
    category: n.category,
    symbolSize: n.symbolSize,
    itemStyle: n.isCategory ? { borderWidth: 2, borderColor: "#fff" } : undefined,
    label: { show: true, fontSize: n.isCategory ? 13 : 11 },
  }));
  state.chart.setOption({
    legend: [{ data: g.categories, textStyle: { color: "#666", fontSize: 12 } }],
    series: [{
      type: "graph", layout: "force", roam: true, draggable: true,
      data, links: g.links.map(l => ({ source: l.source, target: l.target, value: l.relation })),
      categories: g.categories.map((c, i) => ({ name: c, itemStyle: { color: CAT_COLORS[i % CAT_COLORS.length] } })),
      force: { repulsion: 320, edgeLength: 90, gravity: 0.08 },
      lineStyle: { color: "#bbb", curveness: 0.1 },
      edgeLabel: { show: true, formatter: "{c}", fontSize: 10, color: "#999" },
      emphasis: { focus: "adjacency" },
      label: { position: "right" },
    }],
  });
  // 自定义图例：分类 + 关系说明
  $("wikiLegend").innerHTML = g.categories.map((c, i) =>
    `<span><span class="dot" style="background:${CAT_COLORS[i % CAT_COLORS.length]}"></span>${c}</span>`).join("") +
    '<span>边上的字 = 关系（属于/依据/触发/支撑/约束/量化/互补）</span>';
}

/* ---------- 管理后台页 ---------- */
async function loadAdmin() {
  /* 管理员后台：用户表 + 知识库表 + 问答留痕。 */
  const users = await api("/api/admin/users");
  const ut = $("userTable");
  ut.innerHTML = "<table><tr><th>ID</th><th>用户名</th><th>角色</th><th>显示名</th><th>层级（下拉即改）</th></tr>" +
    users.map(u => `<tr><td>${u.id}</td><td>${u.username}</td><td>${u.role === "admin" ? "管理员" : "用户"}</td>
      <td>${u.display_name}</td>
      <td><select class="tier-sel" data-uid="${u.id}" ${u.role === "admin" ? "disabled" : ""}>
        ${[1, 2, 3].map(t => `<option value="${t}" ${u.tier === t ? "selected" : ""}>${tierLabel(t)}</option>`).join("")}
      </select></td></tr>`).join("") + "</table>";
  ut.querySelectorAll(".tier-sel").forEach(sel => sel.addEventListener("change", async () => {
    try {
      await api("/api/admin/users/update", { id: Number(sel.dataset.uid), tier: Number(sel.value) });
      $("adminMsg").className = "msg ok"; $("adminMsg").textContent = "层级已更新";
    } catch (e) { $("adminMsg").className = "msg err"; $("adminMsg").textContent = e.message; }
  }));

  const kbAll = await api("/api/kb/list"); // 管理员看到全部条目
  const kt = $("kbAdminTable");
  kt.innerHTML = "<table><tr><th>ID</th><th>标题</th><th>分类</th><th>可见层级</th><th>操作</th></tr>" +
    kbAll.map(e => `<tr><td>${e.id}</td><td>${e.title}</td><td>${e.category}</td><td>${e.tier_required}</td>
      <td><button class="btn ghost sm" data-del="${e.id}">删除</button></td></tr>`).join("") + "</table>";
  kt.querySelectorAll("[data-del]").forEach(btn => btn.addEventListener("click", async () => {
    if (!confirm("确定删除该条目？其关联关系会一并删除。")) return;
    try {
      await api("/api/kb/delete", { id: Number(btn.dataset.del) });
      loadAdmin(); // 刷新
    } catch (e) { $("adminMsg").className = "msg err"; $("adminMsg").textContent = e.message; }
  }));

  const logs = await api("/api/admin/chatlogs");
  $("logTable").innerHTML = logs.length
    ? "<table><tr><th>用户</th><th>问题</th><th>引用来源</th><th>时间</th></tr>" +
      logs.map(l => `<tr><td>${l.username}</td><td>${escapeHtml(l.question)}</td>
        <td>${escapeHtml(l.sources || "-")}</td>
        <td>${new Date(l.created_at * 1000).toLocaleString("zh-CN")}</td></tr>`).join("") + "</table>"
    : '<div class="note">暂无问答记录，去问答页问一句再回来看。</div>';
}

function escapeHtml(s) {
  /* 防注入：转义 HTML 特殊字符后再插入表格。 */
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* ---------- 事件绑定与启动 ---------- */
$("loginBtn").addEventListener("click", doLogin);
$("loginPwd").addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
$("logoutBtn").addEventListener("click", doLogout);
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => switchTab(t.dataset.tab)));
$("chatSend").addEventListener("click", sendQuestion);
$("chatInput").addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) sendQuestion(); });
$("nuCreate").addEventListener("click", async () => {
  /* 新建用户（管理员）。 */
  try {
    await api("/api/admin/users/create", {
      username: $("nuUser").value.trim(), password: $("nuPwd").value,
      role: $("nuRole").value, tier: Number($("nuTier").value),
    });
    $("adminMsg").className = "msg ok"; $("adminMsg").textContent = "用户已创建";
    $("nuUser").value = ""; $("nuPwd").value = "";
    loadAdmin();
  } catch (e) { $("adminMsg").className = "msg err"; $("adminMsg").textContent = e.message; }
});
$("nkCreate").addEventListener("click", async () => {
  /* 新增知识条目（管理员）。 */
  try {
    await api("/api/kb/create", {
      title: $("nkTitle").value.trim(), content: $("nkContent").value.trim(),
      category: $("nkCat").value.trim() || "未分类", tier_required: Number($("nkTier").value),
    });
    $("adminMsg").className = "msg ok"; $("adminMsg").textContent = "条目已新增";
    $("nkTitle").value = ""; $("nkContent").value = ""; $("nkCat").value = "";
    loadAdmin();
  } catch (e) { $("adminMsg").className = "msg err"; $("adminMsg").textContent = e.message; }
});

(async function boot() {
  /* 启动：尝试恢复登录态。 */
  if (await tryResume()) enterApp();
})();
