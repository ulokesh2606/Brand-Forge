// app.js — BrandForge wizard navigation + SSE pipeline streaming

const STEPS = ["brand", "campaign", "context", "channels", "progress", "results"];
const STEP_LABELS = ["Brand", "Campaign", "Context", "Channels"];

let currentStep = 1;

// ── Auth ────────────────────────────────────────────────────────────────────
function checkAuth() {
  const user = sessionStorage.getItem("bf-user");
  if (user) {
    document.getElementById("auth-overlay").style.display = "none";
    document.getElementById("app-wrap").classList.remove("blurred");
    document.getElementById("user-display").textContent = "SaaS Account: " + user;
    return true;
  }
  return false;
}

async function loginUser(username, password) {
  try {
    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    if (!res.ok) throw new Error("Invalid login");
    const data = await res.json();
    sessionStorage.setItem("bf-token", data.token);
    sessionStorage.setItem("bf-user", data.username);
    checkAuth();
  } catch (err) {
    alert("Login failed. Use admin / password123");
  }
}

function logout() {
  sessionStorage.clear();
  location.reload();
}

// ── Progress bar init ───────────────────────────────────────────────────────
function buildProgressBar() {
  const wrap = document.getElementById("progress-steps");
  wrap.innerHTML = "";
  STEP_LABELS.forEach((label, i) => {
    const n = i + 1;
    const dot  = document.createElement("div");
    dot.className = "pb-step";
    dot.id = `pb-step-${n}`;
    dot.innerHTML = `<div class="pb-dot" id="pb-dot-${n}">${n}</div><div class="pb-label" id="pb-label-${n}">${label}</div>`;
    wrap.appendChild(dot);
    if (i < STEP_LABELS.length - 1) {
      const line = document.createElement("div");
      line.className = "pb-line"; line.id = `pb-line-${n}`;
      wrap.appendChild(line);
    }
  });
}

function updateProgressBar(step) {
  for (let n = 1; n <= STEP_LABELS.length; n++) {
    const dot   = document.getElementById(`pb-dot-${n}`);
    const label = document.getElementById(`pb-label-${n}`);
    const line  = document.getElementById(`pb-line-${n}`);
    if (!dot) continue;
    dot.className   = n < step ? "pb-dot done" : n === step ? "pb-dot active" : "pb-dot";
    label.className = n < step ? "pb-label done" : n === step ? "pb-label active" : "pb-label";
    if (line) line.className = n < step ? "pb-line done" : "pb-line";
    dot.textContent = n < step ? "✓" : n;
  }
  // Hide progress bar on step 5 (progress) and 6 (results)
  document.getElementById("progress-bar-wrap").style.display = (step >= 5) ? "none" : "flex";
}

function goToStep(n) {
  document.querySelectorAll(".step").forEach(s => s.classList.add("hidden"));
  const target = document.getElementById(`step-${n}`);
  if (target) { target.classList.remove("hidden"); target.scrollIntoView({ behavior: "smooth", block: "start" }); }
  currentStep = n;
  updateProgressBar(n);
}

// ── Sample loading ──────────────────────────────────────────────────────────
function loadSample(key) {
  const s = window.SAMPLES[key];
  if (!s) return;

  setValue("url",                s.url);
  setValue("website-content",    s.websiteContent || "");
  setValue("campaign-goal",      s.campaignGoal);
  setValue("target-audience",    s.targetAudience);
  setValue("tone-keywords",      s.toneKeywords);
  setValue("current-channels",   s.currentChannels);
  setValue("current-messaging",  s.currentMessaging);
  setValue("current-campaigns",  s.currentCampaigns);
  setValue("what-worked",        s.whatWorked);
  setValue("what-not-worked",    s.whatNotWorked);
  setValue("competitors",        s.competitors);

  // Set channels
  document.querySelectorAll(".channel-card").forEach(card => {
    const ch    = card.dataset.channel;
    const isOn  = s.channels.includes(ch);
    const cb    = card.querySelector("input[type=checkbox]");
    cb.checked  = isOn;
    card.classList.toggle("selected", isOn);
  });

  // Mark active pill
  document.querySelectorAll(".sample-pill").forEach(p => {
    p.classList.toggle("active", p.dataset.sample === key);
  });
}

function setValue(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

// ── Channel toggles ─────────────────────────────────────────────────────────
function getSelectedChannels() {
  return [...document.querySelectorAll(".channel-card.selected")].map(c => c.dataset.channel);
}

function setChannels(channels) {
  document.querySelectorAll(".channel-card").forEach(card => {
    const on = channels.includes(card.dataset.channel);
    card.querySelector("input").checked = on;
    card.classList.toggle("selected", on);
  });
}

// ── Brief summary ───────────────────────────────────────────────────────────
function buildSummary() {
  const url  = document.getElementById("url").value || "(pasted content)";
  const goal = document.getElementById("campaign-goal").value || "—";
  const aud  = document.getElementById("target-audience").value || "—";
  const chs  = getSelectedChannels().join(", ") || "None";
  document.getElementById("brief-summary").innerHTML = `
    <div><div class="summary-item-label">URL</div><div class="summary-item-value">${url}</div></div>
    <div><div class="summary-item-label">Audience</div><div class="summary-item-value">${aud}</div></div>
    <div style="grid-column:1/-1"><div class="summary-item-label">Goal</div><div class="summary-item-value">${goal}</div></div>
    <div><div class="summary-item-label">Channels selected</div><div class="summary-item-value accent">${chs}</div></div>
  `;
}

// ── Agent progress helpers ──────────────────────────────────────────────────
function setAgentState(id, state, msg) {
  const row    = document.getElementById(`ap-${id}`);
  const status = row?.querySelector(".agent-status");
  if (!row) return;
  row.className = `agent-row ${state}`;
  if (status) { status.textContent = msg; status.className = `agent-status ${state}`; }
}

function setAgentBadge(id, text, color) {
  const badge = document.getElementById(`badge-${id}`);
  if (!badge) return;
  badge.textContent = text;
  badge.style.cssText = `background:${color}22;border:1px solid ${color}44;color:${color};`;
}

function resetAgentPipeline() {
  ["scraper","rag","brand_interpreter","content_strategist","content_writer","brand_voice_evaluator"].forEach(id => {
    setAgentState(id, "", "Waiting...");
    const badge = document.getElementById(`badge-${id}`);
    if (badge) { badge.textContent = ""; badge.style.cssText = ""; }
  });
  document.getElementById("rag-info").style.display = "none";
  
  // Reset the HITL Panel for Step 6 explicitly
  const hitlPanel = document.getElementById("hitl-panel");
  if (hitlPanel) hitlPanel.classList.remove("hidden");
  
  const approveBtn = document.getElementById("hitl-approve-btn");
  if (approveBtn) {
    approveBtn.innerHTML = "✅ Approve Content";
    approveBtn.style.backgroundColor = "transparent";
    approveBtn.style.color = "#34d399";
  }
  
  const resumeBtn = document.getElementById("hitl-resume-btn");
  if (resumeBtn) resumeBtn.style.display = "inline-flex";
  
  const feedbackEl = document.getElementById("hitl-feedback");
  if (feedbackEl) {
    feedbackEl.style.display = "block";
    feedbackEl.value = "";
  }

  document.querySelector(".hitl-sub").textContent = "Provide feedback below and the AI will reprioritize to rewrite the content.";
  document.getElementById("progress-sub").textContent = "Initialising...";
}

// ── Build request body ──────────────────────────────────────────────────────
function buildRequest() {
  const toneRaw = document.getElementById("tone-keywords").value;
  const chRaw   = document.getElementById("current-channels").value;
  const compRaw = document.getElementById("competitors").value;

  return {
    url:              document.getElementById("url").value || "https://example.com",
    website_content:  document.getElementById("website-content").value.trim(),
    campaign_goal:    document.getElementById("campaign-goal").value,
    target_audience:  document.getElementById("target-audience").value,
    tone_keywords:    toneRaw.split(",").map(s => s.trim()).filter(Boolean),
    current_channels: chRaw.split(",").map(s => s.trim()).filter(Boolean),
    current_messaging:  document.getElementById("current-messaging").value,
    current_campaigns:  document.getElementById("current-campaigns").value,
    what_has_worked:    document.getElementById("what-worked").value,
    what_hasnt_worked:  document.getElementById("what-not-worked").value,
    competitors:        compRaw.split(",").map(s => s.trim()).filter(Boolean),
    selected_channels:  getSelectedChannels(),
  };
}

// ── SSE streaming pipeline ──────────────────────────────────────────────────
async function consumeStream(response) {
  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer    = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const payload = JSON.parse(line.slice(6));
        handleSSEEvent(payload);
      } catch (e) { }
    }
  }
}

async function runPipeline() {
  const req = buildRequest();
  goToStep(5);
  resetAgentPipeline();
  window._approvedChannels = new Set();

  try {
    const response = await fetch("/api/v1/generate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    
    setAgentState("scraper", "running", "Starting...");
    await consumeStream(response);

  } catch (err) {
    document.getElementById("progress-sub").textContent = `Error: ${err.message}`;
  }
}

async function resumePipeline(feedback, approveAsIs = false) {
  const threadId = sessionStorage.getItem("current-thread");
  
  // Transition back to step 5
  goToStep(5);
  resetAgentPipeline();
  setAgentState("scraper", "done", "Skipped");
  setAgentBadge("scraper", "Done", "#34d399");
  setAgentState("rag", "done", "Reusing Index");
  setAgentBadge("rag", "Done", "#7c6dfa");
  setAgentState("brand_interpreter", "done", "Skipped");
  setAgentBadge("brand_interpreter", "Done", "#34d399");
  setAgentState("content_strategist", "done", "Skipped");
  setAgentBadge("content_strategist", "Done", "#34d399");
  
  document.getElementById("progress-sub").textContent = "Injected human feedback. Resuming...";

  try {
    const response = await fetch("/api/v1/generate/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: threadId,
        human_feedback: feedback,
        approve_as_is: approveAsIs
      }),
    });
    if (!response.ok) throw new Error("Resume failed");
    await consumeStream(response);
  } catch (err) {
    alert("Resume failed: " + err.message);
  }
}

function handleSSEEvent(payload) {
  const { event, step, message, chunks, collection, thread_id } = payload;
  if (thread_id) sessionStorage.setItem("current-thread", thread_id);
  
  document.getElementById("progress-sub").textContent = message || "";

  if (event === "wait_for_human") {
    // Legacy support, should not be hit with updated backend
    return;
  }

  if (event === "progress") {
    if (step === "scraper") setAgentState("scraper", "running", message);
    if (step === "rag")     setAgentState("rag", "running", message);
  }

  if (event === "rag_done") {
    setAgentState("scraper", "done", "Complete");
    setAgentBadge("scraper", "Done", "#34d399");
    setAgentState("rag", "done", `${chunks} chunks indexed`);
    setAgentBadge("rag", `${chunks} chunks`, "#7c6dfa");
    const ri = document.getElementById("rag-info");
    ri.style.display = "grid";
    document.getElementById("rag-collection").textContent = collection;
    document.getElementById("rag-chunks").textContent     = chunks;
  }

  if (event === "agent_done") {
    const id      = step;
    const iter    = payload.iteration || 1;
    const isRetry = iter > 1;

    setAgentState(id, "done", `Done${isRetry ? ` (iter ${iter})` : ""}`);
    setAgentBadge(id, isRetry ? `↻ iter ${iter}` : "✓ Done", isRetry ? "#fbbf24" : "#34d399");

    if (id === "brand_voice_evaluator" && payload.message && payload.message.includes("feedback")) {
      setAgentState(id, "warn", "Rejected — sending feedback to Agent 3");
      setAgentBadge(id, "↻ Retry", "#fbbf24");
      setAgentState("content_writer", "running", "Rewriting with structured feedback...");
    }
  }

  if (event === "complete") {
    lastResult = payload.result;
    window.renderResults(lastResult);
    goToStep(6);
  }

  if (event === "error") {
    document.getElementById("progress-sub").textContent = `Error: ${message}`;
  }
}

// ── DOM ready ───────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // SaaS Auth: Check if logged in. If not, don't run buildProgressBar yet.
  if (checkAuth()) {
    buildProgressBar();
    goToStep(1);
  }

  // --- Auth Listeners ---
  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      loginUser(document.getElementById("login-user").value, document.getElementById("login-pass").value);
    });
  }

  const logoutBtn = document.getElementById("logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", logout);

  // --- Wizard Logic (only runs if Auth passes later) ---
  buildProgressBar();
  
  document.getElementById("hitl-resume-btn").addEventListener("click", () => {
    const feedbackData = { approved: [], feedback: {}, edits: {} };
    const channels = getSelectedChannels();
    
    let allApproved = true;
    let hasRegenFeedback = false;

    for (const ch of channels) {
       const mainTa = document.getElementById(`textarea-${ch}`);
       if (mainTa) {
           feedbackData.edits[ch] = mainTa.value; // Store edited draft unconditionally 
       }
       
       if (window._approvedChannels && window._approvedChannels.has(ch)) {
           feedbackData.approved.push(ch);
       } else {
           allApproved = false;
           const ta = document.getElementById(`ch-feedback-${ch}`);
           if (ta && ta.value.trim()) {
               feedbackData.feedback[ch] = ta.value.trim();
               hasRegenFeedback = true;
           }
       }
    }
    
    if (allApproved) {
       alert("🎉 All channels are approved! Content is finalized.");
       const btn = document.getElementById("hitl-resume-btn");
       btn.innerHTML = "🎉 All Content Approved & Saved!";
       btn.style.backgroundColor = "#34d399";
       btn.style.color = "#0f172a";
       document.querySelector(".hitl-sub").textContent = "This content has been finalized and saved to your project.";
       // Force a backend send if possible to save any possible manual edits, closing the loop.
       resumePipeline(JSON.stringify(feedbackData), true);
       return;
    }
    
    if (!hasRegenFeedback) {
        alert("Please write your suggestions in the revision box for the unapproved channels to regenerate, or approve them!");
        return;
    }
    
    resumePipeline(JSON.stringify(feedbackData), false);
  });

  // Step navigation
  document.getElementById("step1-next").addEventListener("click", () => {
    if (!document.getElementById("url").value && !document.getElementById("website-content").value.trim()) {
      alert("Please enter a URL or paste brand content to continue.");
      return;
    }
    goToStep(2);
  });

  document.getElementById("step2-next").addEventListener("click", () => {
    if (!document.getElementById("campaign-goal").value) { alert("Please enter a campaign goal."); return; }
    if (!document.getElementById("target-audience").value) { alert("Please enter a target audience."); return; }
    goToStep(3);
  });

  document.getElementById("step3-next").addEventListener("click", () => {
    buildSummary();
    goToStep(4);
  });

  document.getElementById("generate-btn").addEventListener("click", () => {
    if (getSelectedChannels().length === 0) { alert("Please select at least one channel."); return; }
    runPipeline();
  });

  document.getElementById("restart-btn").addEventListener("click", () => {
    document.querySelectorAll(".sample-pill").forEach(p => p.classList.remove("active"));
    goToStep(1);
  });

  // Back buttons
  document.querySelectorAll("[data-back]").forEach(btn => {
    btn.addEventListener("click", () => goToStep(parseInt(btn.dataset.back)));
  });

  // Sample pills
  document.querySelectorAll(".sample-pill").forEach(pill => {
    pill.addEventListener("click", () => loadSample(pill.dataset.sample));
  });

  // Channel cards
  document.querySelectorAll(".channel-card").forEach(card => {
    card.addEventListener("click", () => {
      const cb = card.querySelector("input");
      cb.checked = !cb.checked;
      card.classList.toggle("selected", cb.checked);
    });
  });

  // Combo buttons
  document.querySelectorAll(".combo-btn").forEach(btn => {
    btn.addEventListener("click", () => setChannels(btn.dataset.channels.split(",")));
  });
});
