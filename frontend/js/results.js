// results.js — render the BrandForge pipeline results into the DOM

const CHANNEL_META = {
  linkedin:  { icon: "🔷", label: "LinkedIn",   textareaRows: 18 },
  instagram: { icon: "📸", label: "Instagram",  textareaRows: 8  },
  youtube:   { icon: "▶",  label: "YouTube",    textareaRows: 14 },
  google_ad: { icon: "🎯", label: "Google Ads", textareaRows: 8  },
};

window.renderResults = function (result) {
  if (!result) return;

  const {
    thread_id, final_content = {}, brand_guidelines = {},
    evaluation_result = {}, iteration_count = 0,
    rag_stats = {}, selected_channels = [],
  } = result;

  const isRetry  = iteration_count > 1;

  // ── Thread ID ────────────────────────────────────────────────────────────
  document.getElementById("thread-display").textContent = `thread_id: ${thread_id || "—"}`;

  // ── Metrics ──────────────────────────────────────────────────────────────
  const metrics = [
    { label: "Iterations",         value: iteration_count,                           color: "#ffffff" },
    { label: "Rewrite Loop",       value: isRetry ? "Active" : "Not used",          color: isRetry ? "#a78bfa" : "#3a3a60" },
    { label: "Channels Generated", value: selected_channels.length, color: "#ffffff" },
    { label: "Chunks in Qdrant",   value: rag_stats.chunks || "—",                  color: "#7c6dfa" },
  ];
  document.getElementById("metrics-row").innerHTML = metrics.map(m => `
    <div class="metric-card">
      <div class="metric-label">${m.label}</div>
      <div class="metric-value" style="color:${m.color}">${m.value}</div>
    </div>
  `).join("");

  // ── Loop info ─────────────────────────────────────────────────────────────
  const loopInfo = document.getElementById("loop-info");
  if (isRetry) {
    loopInfo.classList.remove("hidden");
    loopInfo.innerHTML = `↻ Agent 4 evaluated the drafts and structurally corrected Agent 3. The <strong>LangGraph conditional rewrite loop</strong> ran ${iteration_count} iteration(s) to reach this final output.`;
  } else {
    loopInfo.classList.add("hidden");
  }

  // ── Content tabs + panels ─────────────────────────────────────────────────
  const tabsEl   = document.getElementById("content-tabs");
  const panelsEl = document.getElementById("content-panels");
  tabsEl.innerHTML   = "";
  panelsEl.innerHTML = "";

  const orderedChannels = ["linkedin", "instagram", "youtube", "google_ad"].filter(k => selected_channels.includes(k));

  orderedChannels.forEach((key, i) => {
    const meta      = CHANNEL_META[key] || { icon: "·", label: key, textareaRows: 10 };
    const text      = final_content[key] || "";
    const isActive  = i === 0;

    // Tab
    const tab = document.createElement("button");
    tab.className   = `content-tab${isActive ? " active" : ""}`;
    tab.id          = `tab-${key}`;
    tab.dataset.tab = key;
    tab.innerHTML   = `${meta.icon} ${meta.label}`;
    tab.addEventListener("click", () => {
      document.querySelectorAll(".content-tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".content-panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`panel-${key}`).classList.add("active");
    });
    tabsEl.appendChild(tab);

    // Panel
    const panel = document.createElement("div");
    panel.className = `content-panel${isActive ? " active" : ""}`;
    panel.id        = `panel-${key}`;
    

      const prevDraft = (result.previous_content_drafts || {})[key];
      let diffHtml = "";
      if (prevDraft && prevDraft !== text) {
          diffHtml = `<details style="margin-top:10px; font-size:12px;"><summary style="cursor:pointer; color:var(--text-4);">View Previous Variant</summary><div style="margin-top:8px; padding:10px; background:var(--bg); border:1px dashed var(--border); color:var(--text-4); white-space:pre-wrap;">${prevDraft}</div></details>`;
      }

      const isApproved = window._approvedChannels && window._approvedChannels.has(key);
      const btnText = isApproved ? "🎉 Approved (Undo)" : "✅ Approve Channel";
      const btnStyle = isApproved ? "background:#34d399;color:#0f172a" : "border-color:#34d399;color:#34d399";
      const hideFeedback = isApproved ? "display:none;" : "";

      panel.innerHTML = `
        <div class="content-panel-header">
          <div class="content-panel-label">${meta.icon} ${meta.label}</div>
          <div style="display:flex; gap:8px;">
            <button class="copy-btn" data-target="textarea-${key}">Copy</button>
          </div>
        </div>
        <textarea id="textarea-${key}" class="content-textarea" rows="${meta.textareaRows}">${text}</textarea>
        ${diffHtml}
        
        <div class="ch-hitl-box" id="ch-hitl-${key}" style="margin-top:16px; padding:16px; background:rgba(124,109,250,0.05); border:1px dashed rgba(124,109,250,0.3); border-radius:8px;">
          <div style="display:flex; align-items:center; gap: 12px; margin-bottom: 12px;">
             <button class="btn-secondary ch-approve-btn" data-ch="${key}" id="approve-${key}" style="${btnStyle}; font-size:12px; padding:6px 14px; min-width:140px;">${btnText}</button>
             <span style="font-size:12px; color:var(--text-3); ${hideFeedback}" id="req-rev-text-${key}">or request revisions:</span>
          </div>
          <textarea id="ch-feedback-${key}" style="${hideFeedback}" class="field-textarea" rows="2" placeholder="e.g. Write this in a punchier, more direct tone..."></textarea>
        </div>
      `;

      panelsEl.appendChild(panel);
  });
  
  if (!window._approvedChannels) {
      window._approvedChannels = new Set();
  }
  
  // Attach listeners to per-channel approve buttons
  document.querySelectorAll(".ch-approve-btn").forEach(btn => {
     const ch = btn.dataset.ch;
     
     btn.addEventListener("click", () => {
         if (window._approvedChannels.has(ch)) {
             // Undo Approval
             window._approvedChannels.delete(ch);
             btn.innerHTML = "✅ Approve Channel";
             btn.style.backgroundColor = "transparent";
             btn.style.color = "#34d399";
             document.getElementById(`ch-feedback-${ch}`).style.display = "block";
             document.getElementById(`req-rev-text-${ch}`).style.display = "inline";
         } else {
             // Set Approval
             window._approvedChannels.add(ch);
             btn.innerHTML = "🎉 Approved (Undo)";
             btn.style.backgroundColor = "#34d399";
             btn.style.color = "#0f172a";
             const ta = document.getElementById(`ch-feedback-${ch}`);
             if (ta) ta.style.display = "none";
             const sp = document.getElementById(`req-rev-text-${ch}`);
             if (sp) sp.style.display = "none";
         }
     });
  });

  // Copy buttons
  document.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const ta = document.getElementById(btn.dataset.target);
      if (!ta) return;
      navigator.clipboard.writeText(ta.value).then(() => {
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy"; }, 2000);
      });
    });
  });

  // ── Evaluation cards removed for HITL manual review approach ──────────────

  // ── Brand guidelines ──────────────────────────────────────────────────────
  const guideBody = document.getElementById("guidelines-body");
  guideBody.innerHTML = `
    <div class="guidelines-grid">
      <div>
        <div class="guideline-section">
          <div class="guideline-title">Brand Voice (Contextual)</div>
          <div class="guideline-text">${brand_guidelines.brand_voice_summary || "—"}</div>
        </div>
        <div class="guideline-section">
          <div class="guideline-title">Marketing Strategy</div>
          <div class="guideline-text">${brand_guidelines.marketing_context_summary || "—"}</div>
        </div>
        <div class="guideline-section">
          <div class="guideline-title">CTA Style</div>
          <div class="guideline-text">${brand_guidelines.cta_style || "—"}</div>
        </div>
      </div>
      <div>
        ${renderList("Tone Rules",             brand_guidelines.tone_rules,            "purple")}
        ${renderList("Forbidden Phrases",      brand_guidelines.forbidden_phrases,     "red")}
        ${renderList("Differentiation Angles", brand_guidelines.differentiation_angles,"green")}
        ${renderList("Content Pillars",        brand_guidelines.content_pillars,       "blue")}
      </div>
    </div>`;

  // ── Feedback expander ─────────────────────────────────────────────────────
  if (result.evaluation_feedback && iteration_count > 1) {
    const fbExp = document.getElementById("feedback-expander");
    fbExp.classList.remove("hidden");
    document.getElementById("feedback-body").textContent = result.evaluation_feedback;
  }

  // ── Raw JSON ──────────────────────────────────────────────────────────────
  document.getElementById("raw-json").textContent = JSON.stringify(result, null, 2);
};

function renderList(title, items, colorClass) {
  if (!items || !items.length) return "";
  const arrows = { purple: "→", red: "✗", green: "✓", blue: "·" };
  const arr = arrows[colorClass] || "·";
  return `
    <div class="guideline-section">
      <div class="guideline-title">${title}</div>
      ${items.map(r => `<div class="guideline-item ${colorClass}">${arr} ${r}</div>`).join("")}
    </div>`;
}
