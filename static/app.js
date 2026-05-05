/* === Mental Health Tracker v4 — micro check-ins + slider + match_method === */

async function api(url, opts = {}) {
    const res = await fetch(url, { headers: {'Content-Type':'application/json'}, ...opts });
    if (!res.ok) { const e = await res.json().catch(()=>({error:res.statusText})); throw new Error(e.error||'fail'); }
    return res.json();
}

// ─── Match Method Registry ──────────────────────────────────

const MATCH_METHODS = {
    zero_nonzero_v1(value, args) {
        if (args.when === 'zero') return value === 0;
        if (args.when === 'nonzero') return value > 0 && value != null;
        return false;
    },
    range_v1(value, args) {
        return value >= (args.min ?? 0) && value <= (args.max ?? 100);
    },
};

// ─── FlowSession ────────────────────────────────────────────

class FlowSession {
    constructor({ flowId, sessionId, order, qDefs, gapHours }) {
        this.flowId = flowId;
        this.sessionId = sessionId;
        this.order = order;
        this.qDefs = qDefs;
        this.step = 0;
        this.entryIds = {};
        this.startedAt = {};
        this.answers = {};
        this.sources = {};
        this.contradictions = [];
        this.linksEnabled = true;
        this.gapHours = gapHours || 24;

        this.allLinks = [];
        const loadedQIds = new Set(Object.keys(qDefs));
        for (const qDef of Object.values(qDefs)) {
            for (const link of (qDef.answer_links || [])) {
                if (loadedQIds.has(link.source.questionnaire) && loadedQIds.has(link.target.questionnaire))
                    this.allLinks.push(link);
            }
        }
        this.allLinks = this._dedup(this.allLinks);

        for (const qid of order) {
            this.answers[qid] = {};
            this.sources[qid] = {};
            this.entryIds[qid] = crypto.randomUUID();
            this.startedAt[qid] = new Date().toISOString();
        }
        this._validateGraph();
    }

    currentQDef() { return this.qDefs[this.order[this.step]] || null; }
    currentQId() { return this.order[this.step] || null; }
    currentEntryId() { return this.entryIds[this.currentQId()]; }
    currentStartedAt() { return this.startedAt[this.currentQId()]; }

    setAnswer(questionnaireId, questionId, value) {
        if (!this.answers[questionnaireId]) this.answers[questionnaireId] = {};
        if (!this.sources[questionnaireId]) this.sources[questionnaireId] = {};
        const prev = this.answers[questionnaireId][questionId];
        const prevSrc = this.sources[questionnaireId][questionId];
        this.answers[questionnaireId][questionId] = value;
        // Re-clicking a link-implied value is confirmation, not a manual override
        if (!(prevSrc === 'link' && prev === value))
            this.sources[questionnaireId][questionId] = 'manual';
        if (this.linksEnabled) this._cascade(questionnaireId, questionId);
    }

    getAnswer(qId, questionId) { return (this.answers[qId]||{})[questionId] ?? null; }
    getSource(qId, questionId) { return (this.sources[qId]||{})[questionId] ?? null; }
    isImplied(qId, questionId) { return this.getSource(qId, questionId) === 'link'; }

    visibleQuestions(qId) {
        const qDef = this.qDefs[qId];
        if (!qDef) return [];
        const ans = this.answers[qId] || {};
        return qDef.questions.filter(q => this._shouldShow(q, ans));
    }

    optionLabel(qId, questionId, optId) {
        const q = this._findQ(qId, questionId);
        if (!q || !q.options) return String(optId);
        const o = q.options.find(x => x.id === optId);
        return o ? o.label : String(optId);
    }

    questionText(qId, questionId) {
        const q = this._findQ(qId, questionId);
        return q ? q.text : questionId;
    }

    getContradictionsFor(qnId) { return this.contradictions.filter(c => c.tgtQuestionId === qnId); }
    hasContradiction(qnId) { return this.contradictions.some(c => c.tgtQuestionId === qnId); }

    resolveContradictions(keepQId, keepQnId) {
        for (const c of this.contradictions) {
            const tgtQId = c.link.target.questionnaire, tgtQnId = c.tgtQuestionId;
            if (tgtQId !== keepQId || tgtQnId !== keepQnId) {
                delete this.answers[tgtQId][tgtQnId]; delete this.sources[tgtQId][tgtQnId];
            }
            const srcQId = c.link.source.questionnaire, srcQnId = c.link.source.question;
            if ((srcQId !== keepQId || srcQnId !== keepQnId) && this.sources[srcQId] && this.sources[srcQId][srcQnId] === 'manual') {
                delete this.answers[srcQId][srcQnId]; delete this.sources[srcQId][srcQnId];
            }
        }
        this.contradictions = [];
        this._cascade(keepQId, keepQnId);
    }

    getIncompatibleOptions(questionnaireId, questionId) {
        if (!this.linksEnabled) return new Set();
        const incompatible = new Set();
        const question = this._findQ(questionnaireId, questionId);
        if (!question || !question.options) return incompatible;
        for (const opt of question.options) {
            for (const link of this.allLinks) {
                if (link.target.questionnaire !== questionnaireId || link.target.question !== questionId) continue;
                if (!this._sourceMatches(link, this.answers)) continue;
                if (!this._targetCompatible(link, opt.id))
                    incompatible.add(opt.id);
            }
        }
        return incompatible;
    }

    dismissContradictions() { this.linksEnabled = false; this.contradictions = []; }

    advanceStep() {
        this.step++;
        if (this.step < this.order.length) {
            const qid = this.currentQId();
            if (!this.entryIds[qid]) this.entryIds[qid] = crypto.randomUUID();
            if (!this.startedAt[qid]) this.startedAt[qid] = new Date().toISOString();
        }
    }
    goToStep(s) { this.step = s; }
    isComplete() { return this.step >= this.order.length; }

    toStagingPayload() { return this.toStagingPayloadForQ(this.currentQId(), this.step); }

    toStagingPayloadForQ(qid, stepIdx) {
        const impl = [];
        for (const [k, src] of Object.entries(this.sources[qid] || {})) { if (src === 'link') impl.push(k); }
        return {
            entry_id: this.entryIds[qid], questionnaire_id: qid,
            responses: this.answers[qid], current_index: 0,
            started_at: this.startedAt[qid],
            flow_id: this.flowId, flow_step: stepIdx,
            flow_session_id: this.sessionId, implied_questions: impl,
            gap_hours: this.gapHours,
        };
    }

    // ── Source matching (supports both option-ID and match_method) ──

    _sourceMatches(link, answersMap) {
        const srcQId = link.source.questionnaire;
        const srcQnId = link.source.question;
        const srcVal = (answersMap[srcQId] || {})[srcQnId];
        if (srcVal == null) return false;

        if (link.source.match_method) {
            const fn = MATCH_METHODS[link.source.match_method];
            if (!fn) return false; // unknown method → skip
            return fn(srcVal, link.source.match_args || {});
        }
        // Classic option-ID matching
        return link.source.values && link.source.values.includes(srcVal);
    }

    _sourceMatchesSandbox(link, sandbox) {
        const key = `${link.source.questionnaire}:${link.source.question}`;
        const srcVal = sandbox[key];
        if (srcVal == null) return false;
        if (link.source.match_method) {
            const fn = MATCH_METHODS[link.source.match_method];
            if (!fn) return false;
            return fn(srcVal, link.source.match_args || {});
        }
        return link.source.values && link.source.values.includes(srcVal);
    }

    _targetCompatible(link, value) {
        if (link.target.match_method) {
            const fn = MATCH_METHODS[link.target.match_method];
            if (!fn) return false;
            return fn(value, link.target.match_args || {});
        }
        return link.target.compatible && link.target.compatible.includes(value);
    }

    // ── Dirty-set cascade ───────────────────────────────────

    _cascade(changedQId, changedQnId) {
        this.contradictions = [];
        const dirty = new Set([`${changedQId}:${changedQnId}`]);
        const processed = new Set();

        while (dirty.size > 0) {
            const key = dirty.values().next().value;
            dirty.delete(key);
            if (processed.has(key)) continue;
            processed.add(key);

            const [srcQId, srcQnId] = key.split(':');
            const srcVal = (this.answers[srcQId] || {})[srcQnId];

            if (srcVal != null) {
                for (const link of this.allLinks) {
                    if (link.source.questionnaire !== srcQId || link.source.question !== srcQnId) continue;
                    if (!this._sourceMatches(link, this.answers)) continue;

                    const tgtQId = link.target.questionnaire;
                    const tgtQnId = link.target.question;
                    const tgtKey = `${tgtQId}:${tgtQnId}`;
                    const tgtVal = (this.answers[tgtQId] || {})[tgtQnId];
                    const tgtSrc = (this.sources[tgtQId] || {})[tgtQnId];

                    // Must have compatible (option-ID list) or match_method on target
                    if (!link.target.compatible && !link.target.match_method) continue;

                    const isCompat = (v) => this._targetCompatible(link, v);

                    if (tgtVal == null) {
                        if (link.target.compatible && link.target.compatible.length === 1) {
                            if (!this.answers[tgtQId]) this.answers[tgtQId] = {};
                            if (!this.sources[tgtQId]) this.sources[tgtQId] = {};
                            this.answers[tgtQId][tgtQnId] = link.target.compatible[0];
                            this.sources[tgtQId][tgtQnId] = 'link';
                            dirty.add(tgtKey);
                        }
                    } else if (tgtSrc === 'manual') {
                        if (!isCompat(tgtVal)) {
                            this.contradictions.push({
                                link,
                                srcQuestionText: this.questionText(srcQId, srcQnId),
                                srcAnswerLabel: this._labelForValue(srcQId, srcQnId, srcVal),
                                tgtQuestionText: this.questionText(tgtQId, tgtQnId),
                                tgtAnswerLabel: this._labelForValue(tgtQId, tgtQnId, tgtVal),
                                tgtQuestionId: tgtQnId,
                            });
                        }
                    } else {
                        if (isCompat(tgtVal)) {
                            // no-op
                        } else if (link.target.compatible && link.target.compatible.length === 1) {
                            this.answers[tgtQId][tgtQnId] = link.target.compatible[0];
                            this.sources[tgtQId][tgtQnId] = 'link';
                            dirty.add(tgtKey);
                        } else {
                            delete this.answers[tgtQId][tgtQnId];
                            delete this.sources[tgtQId][tgtQnId];
                            dirty.add(tgtKey);
                        }
                    }
                }
            }

            // Stale cleanup
            for (const link of this.allLinks) {
                if (link.source.questionnaire !== srcQId || link.source.question !== srcQnId) continue;
                if (this._sourceMatches(link, this.answers)) continue;
                if (!link.target.compatible && !link.target.match_method) continue;
                const tgtQId = link.target.questionnaire, tgtQnId = link.target.question;
                const tgtSrc = (this.sources[tgtQId] || {})[tgtQnId];
                if (tgtSrc === 'link') {
                    const tgtVal = (this.answers[tgtQId] || {})[tgtQnId];
                    const still = this.allLinks.some(o => {
                        if (o === link) return false;
                        if (o.target.questionnaire !== tgtQId || o.target.question !== tgtQnId) return false;
                        if (!o.target.compatible && !o.target.match_method) return false;
                        return this._sourceMatches(o, this.answers) && this._targetCompatible(o, tgtVal);
                    });
                    if (!still) {
                        delete this.answers[tgtQId][tgtQnId]; delete this.sources[tgtQId][tgtQnId];
                        dirty.add(`${tgtQId}:${tgtQnId}`);
                    }
                }
            }
        }
    }

    _labelForValue(qId, qnId, val) {
        const q = this._findQ(qId, qnId);
        if (!q) return String(val);
        if (q.type === 'slider') return `${val}%`;
        return this.optionLabel(qId, qnId, val);
    }

    _validateGraph() {
        const issues = [];
        const sourceNodes = new Map();
        for (const link of this.allLinks) {
            if (!link.source.values) continue; // skip match_method links for validation
            const key = `${link.source.questionnaire}:${link.source.question}`;
            if (!sourceNodes.has(key)) sourceNodes.set(key, new Set());
            for (const v of link.source.values) sourceNodes.get(key).add(v);
        }
        for (const [nodeKey, optionIds] of sourceNodes) {
            for (const optId of optionIds) {
                const sandbox = {};
                const dirty = new Set([nodeKey]);
                const processed = new Set();
                sandbox[nodeKey] = optId;
                while (dirty.size > 0) {
                    const key = dirty.values().next().value;
                    dirty.delete(key);
                    if (processed.has(key)) continue;
                    processed.add(key);
                    const [srcQId, srcQnId] = key.split(':');
                    const srcVal = sandbox[key];
                    if (srcVal == null) continue;
                    for (const link of this.allLinks) {
                        if (link.source.questionnaire !== srcQId || link.source.question !== srcQnId) continue;
                        if (!this._sourceMatchesSandbox(link, sandbox)) continue;
                        if (!link.target.compatible || link.target.compatible.length !== 1) continue;
                        const tgtKey = `${link.target.questionnaire}:${link.target.question}`;
                        const fillId = link.target.compatible[0];
                        if (sandbox[tgtKey] != null && sandbox[tgtKey] !== fillId) {
                            issues.push(`Conflict: ${nodeKey}=${optId} → ${tgtKey}=${fillId} vs ${sandbox[tgtKey]}`);
                        } else if (sandbox[tgtKey] == null) { sandbox[tgtKey] = fillId; dirty.add(tgtKey); }
                    }
                }
            }
        }
        if (issues.length) console.error('Graph issues:', issues);
        return issues;
    }

    _shouldShow(question, answers) {
        const c = question.show_if;
        if (!c) return true;
        if (c.any_of) return c.any_of.some(x => answers[x.question] === x.equals);
        return answers[c.question] === c.equals;
    }
    _findQ(qId, questionId) { const d = this.qDefs[qId]; return d ? d.questions.find(q => q.id === questionId) || null : null; }
    _dedup(links) {
        const seen = new Set();
        return links.filter(l => {
            const key = JSON.stringify({ s: l.source, t: l.target });
            if (seen.has(key)) return false;
            seen.add(key); return true;
        });
    }
}

// ─── Slider helpers ─────────────────────────────────────────

function computeSliderConfig(gapHours) {
    const segments = gapHours <= 18 ? 2 : Math.max(2, Math.round(gapHours / 12));
    const step = 100 / segments;
    const points = [];
    for (let i = 0; i <= segments; i++) points.push(Math.round(i * step));
    return { segments, step, points };
}

function sliderLabel(pct, gapHours) {
    if (pct === 0) return 'None';
    if (pct === 100) return 'All of the time';
    if (gapHours <= 24) {
        const h = Math.round(pct / 100 * gapHours);
        return `About ${h} hour${h !== 1 ? 's' : ''}`;
    }
    const days = pct / 100 * gapHours / 24;
    const totalDays = gapHours / 24;
    if (days < 1) return `About ${Math.round(days * 24)} hours out of ${totalDays.toFixed(1)} days`;
    return `About ${days.toFixed(1)} days out of ${totalDays.toFixed(1)} days`;
}

function snapToPoint(val, points) {
    let closest = points[0], minDist = Math.abs(val - points[0]);
    for (const p of points) { const d = Math.abs(val - p); if (d < minDist) { minDist = d; closest = p; } }
    return closest;
}

// ─── View ───────────────────────────────────────────────────

const APP = document.getElementById('app');
let session = null, questionIndex = 0, sidebarOpen = false, autosaveTimer = null;
let questionnaires = [], flows = [], stagingList = [];

function esc(s) { if (s == null) return ''; const d = document.createElement('div'); d.textContent = String(s); return d.innerHTML; }
function fmtDate(iso) { if (!iso) return ''; const d = new Date(iso); return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`; }
function fmtTime(iso) { if (!iso) return ''; const d = new Date(iso); return `${fmtDate(iso)} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; }
function today() { return new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }); }
function trunc(s, n) { return !s ? '' : s.length > n ? s.slice(0, n) + '\u2026' : s; }
function optLbl(q, id) {
    if (q.type === 'slider') return `${id}%`;
    if (q.type === 'text') return id;
    if (q.type === 'multi_choice' && Array.isArray(id)) return id.map(i => { const o = (q.options || []).find(x => x.id === i); return o ? o.label : i; }).join(', ');
    const o = (q.options || []).find(x => x.id === id); return o ? o.label : String(id);
}
function fmtGap(h) {
    if (h < 1) return `${Math.round(h * 60)} minutes`;
    if (h < 24) return `${Math.round(h)} hour${Math.round(h) !== 1 ? 's' : ''}`;
    const d = h / 24;
    if (d < 2) return `1 day ${Math.round(h - 24)} hours`;
    return `${d.toFixed(1)} days`;
}

// Autosave
function scheduleAutosave() { clearTimeout(autosaveTimer); autosaveTimer = setTimeout(doAutosave, 600); }
async function doAutosave() {
    if (!session) return; showSave('Saving\u2026');
    try { const p = session.toStagingPayload(); p.current_index = questionIndex; await api('/api/staging', { method: 'POST', body: JSON.stringify(p) }); showSave('Saved'); }
    catch (e) { showSave('Save failed'); }
}
function showSave(t) { let el = document.getElementById('autosave'); if (!el) { el = document.createElement('div'); el.id = 'autosave'; el.className = 'autosave-indicator'; document.body.appendChild(el); } el.textContent = t; el.classList.toggle('saved', t === 'Saved'); el.classList.add('visible'); clearTimeout(el._h); el._h = setTimeout(() => el.classList.remove('visible'), 1500); }

// Router
function nav(h) { window.location.hash = h; }
function handleRoute() { const p = (window.location.hash || '#/').slice(1).split('/').filter(Boolean); if (p[0] === 'flow' && p[1]) startFlow(p[1]); else if (p[0] === 'q' && p[1]) startSingleQ(p[1]); else if (p[0] === 'history') renderHistory(); else if (p[0] === 'entry' && p[1]) renderEntryDetail(p[1]); else renderHome(); }
window.addEventListener('hashchange', handleRoute);

// ─── Home ───────────────────────────────────────────────────
async function renderHome() {
    session = null;
    try { [questionnaires, stagingList, flows] = await Promise.all([api('/api/questionnaires'), api('/api/staging'), api('/api/flows')]); }
    catch (e) { APP.innerHTML = '<div class="empty-state"><p>Failed to load.</p></div>'; return; }
    const fsm = {}; for (const s of stagingList.filter(s => s.flow_id)) if (!fsm[s.flow_id]) fsm[s.flow_id] = s;
    let h = `<div class="header"><h1>Mental Health Tracker</h1><span class="header-date">${esc(today())}</span></div><div class="nav-tabs"><div class="nav-tab active">Questionnaires</div><div class="nav-tab" onclick="nav('#/history')">History</div></div>`;
    for (const f of flows) { const r = fsm[f.id]; if (r) h += `<div class="resume-banner"><div class="resume-info"><div class="resume-title">${esc(f.title)}</div><div class="resume-detail">In progress</div></div><div class="resume-actions"><button class="btn btn-primary" onclick="nav('#/flow/${f.id}')">Resume</button><button class="btn btn-danger" onclick="discardFlow('${f.id}')">Discard</button></div></div>`; else h += `<button class="btn btn-primary btn-block flow-btn" onclick="nav('#/flow/${f.id}')">${esc(f.title)}<span class="flow-btn-meta">${f.questionnaire_count} questionnaires \xb7 ${f.total_questions} questions</span></button>`; }
    h += `<div class="section-label">Individual Questionnaires</div>`;
    for (const q of questionnaires) h += `<div class="card" onclick="nav('#/q/${q.id}')"><div class="card-title">${esc(q.title)}${q.micro ? ' <span class="card-badge badge-micro">Micro</span>' : ''}</div><div class="card-desc">${esc(q.description)}</div><div class="card-meta"><span>${q.question_count} questions</span></div></div>`;
    h += `<div class="section-label">Tools</div>`;
    h += `<div class="card" onclick="showGenerateModal()"><div class="card-title">Generate Full Questionnaires</div><div class="card-desc">Compute standard scores from your micro check-in data</div></div>`;
    APP.innerHTML = h;
}
async function discardFlow(fid) { showConfirm('Discard?', 'Delete all in-progress answers.', async () => { for (const s of stagingList.filter(s => s.flow_id === fid)) await api(`/api/staging/${s.entry_id}`, { method: 'DELETE' }); renderHome(); }); }
function showConfirm(t, m, ok) { const ov = document.createElement('div'); ov.className = 'confirm-overlay'; ov.innerHTML = `<div class="confirm-dialog"><div class="confirm-title">${esc(t)}</div><div class="confirm-message">${esc(m)}</div><div class="confirm-buttons"><button class="btn btn-secondary" id="cc">Cancel</button><button class="btn btn-danger" id="co">Discard</button></div></div>`; document.body.appendChild(ov); ov.querySelector('#cc').onclick = () => ov.remove(); ov.querySelector('#co').onclick = async () => { ov.remove(); await ok(); }; ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); }); }

// ─── Generate Modal ─────────────────────────────────────────

function showGenerateModal() {
    // Find standard questionnaires that have micro counterparts
    const targets = [];
    const microQs = questionnaires.filter(q => q.micro);
    const fullQs = questionnaires.filter(q => !q.micro);

    // We need the full micro defs to check reconstructs — use cached data
    // For now, use known mapping from the questionnaire list
    const defaultDays = { 'PHQ-9': 14, 'GAD-7': 14, 'C-SSRS': 14, 'ASRS': 183, 'MDQ': 9999 };

    for (const fq of fullQs) {
        // Check if any micro questionnaire reconstructs this one
        const hasMicro = microQs.some(mq => mq.title.toLowerCase().includes(fq.title.split(' ')[0].toLowerCase()));
        if (hasMicro) {
            const key = Object.keys(defaultDays).find(k => fq.title.includes(k)) || '';
            targets.push({ id: fq.id, title: fq.title, days: defaultDays[key] || 14, enabled: true, useFull: false });
        }
    }

    if (!targets.length) {
        alert('No micro questionnaires found to generate from.');
        return;
    }

    const ov = document.createElement('div');
    ov.className = 'confirm-overlay';

    function renderModal() {
        let h = `<div class="gen-dialog">
            <div class="confirm-title">Generate Full Questionnaires</div>
            <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:16px">Compute standard scores from your micro check-in data.</p>`;

        for (let i = 0; i < targets.length; i++) {
            const t = targets[i];
            h += `<div class="gen-row">
                <label class="hf-check" onclick="window._genTargets[${i}].enabled=!window._genTargets[${i}].enabled;window._genRender();">
                    <span class="h-check ${t.enabled ? 'checked' : ''}">${t.enabled ? '\u2713' : ''}</span>
                    ${esc(t.title)}
                </label>
                <div class="gen-opts">
                    <label class="gen-days">Days: <input type="number" min="1" max="9999" value="${t.days}" onchange="window._genTargets[${i}].days=+this.value"></label>
                    <label class="hf-check" onclick="window._genTargets[${i}].useFull=!window._genTargets[${i}].useFull;window._genRender();">
                        <span class="h-check ${t.useFull ? 'checked' : ''}">${t.useFull ? '\u2713' : ''}</span>
                        Include full entries
                    </label>
                </div>
            </div>`;
        }

        h += `<div class="confirm-buttons" style="margin-top:16px">
            <button class="btn btn-secondary" onclick="window._genReset()">Reset defaults</button>
            <button class="btn btn-secondary" onclick="this.closest('.confirm-overlay').remove()">Cancel</button>
            <button class="btn btn-primary" onclick="window._genSubmit(this.closest('.confirm-overlay'))">Generate</button>
        </div></div>`;

        ov.innerHTML = h;
    }

    window._genTargets = targets;
    window._genRender = renderModal;
    window._genReset = () => {
        for (const t of targets) {
            const key = Object.keys(defaultDays).find(k => t.title.includes(k)) || '';
            t.days = defaultDays[key] || 14;
            t.useFull = false;
            t.enabled = true;
        }
        renderModal();
    };
    window._genSubmit = async (overlay) => {
        const enabled = targets.filter(t => t.enabled);
        if (!enabled.length) return;
        overlay.remove();
        try {
            const res = await api('/api/generate', {
                method: 'POST',
                body: JSON.stringify({
                    targets: enabled.map(t => ({
                        questionnaire_id: t.id,
                        days: t.days,
                        use_full: t.useFull,
                    })),
                }),
            });
            alert(`Generated ${res.generated} questionnaire${res.generated !== 1 ? 's' : ''}. View them in History.`);
        } catch (e) {
            alert('Generation failed: ' + e.message);
        }
    };

    renderModal();
    document.body.appendChild(ov);
    ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); });
}

// ─── Flow setup ─────────────────────────────────────────────
async function startFlow(fid) {
    let fd; try { const a = await api('/api/flows'); fd = a.find(f => f.id === fid); } catch (e) { APP.innerHTML = '<div class="empty-state"><p>Not found.</p></div>'; return; }
    if (!fd) { APP.innerHTML = '<div class="empty-state"><p>Not found.</p></div>'; return; }
    if (!questionnaires.length) questionnaires = await api('/api/questionnaires');
    try { stagingList = await api('/api/staging'); } catch (e) { stagingList = []; }
    const flowStaging = stagingList.filter(s => s.flow_id === fid).sort((a, b) => (a.flow_step || 0) - (b.flow_step || 0));
    if (flowStaging.length > 0) {
        const re = flowStaging[0];
        const eff = fd.selected ? fd.questionnaire_order.filter(q => fd.selected.includes(q)) : [...fd.questionnaire_order];
        const qd = {}; await Promise.all(eff.map(async q => { try { qd[q] = await api(`/api/questionnaire/${q}`); } catch (e) { } }));
        session = new FlowSession({ flowId: fid, sessionId: re.flow_session_id || crypto.randomUUID(), order: eff, qDefs: qd, gapHours: re.gap_hours || 24 });
        for (const s of flowStaging) {
            if (s.responses && session.answers[s.questionnaire_id]) {
                Object.assign(session.answers[s.questionnaire_id], s.responses);
                for (const k of Object.keys(s.responses)) {
                    if (!session.sources[s.questionnaire_id]) session.sources[s.questionnaire_id] = {};
                    session.sources[s.questionnaire_id][k] = (s.implied_questions || []).includes(k) ? 'link' : 'manual';
                }
            }
            session.entryIds[s.questionnaire_id] = s.entry_id;
            if (s.started_at) session.startedAt[s.questionnaire_id] = s.started_at;
        }
        session.step = re.flow_step || 0;
        questionIndex = re.current_index || 0;
        for (const qid of session.order) for (const [qnId, src] of Object.entries(session.sources[qid] || {})) { if (src === 'manual') session._cascade(qid, qnId); }
        renderQuestion(); return;
    }
    renderFlowOrder(fd);
}
async function startSingleQ(qid) {
    if (!questionnaires.length) try { questionnaires = await api('/api/questionnaires'); } catch (e) { }
    const qd = {}; try { qd[qid] = await api(`/api/questionnaire/${qid}`); } catch (e) { APP.innerHTML = '<div class="empty-state"><p>Not found.</p></div>'; return; }
    session = new FlowSession({ flowId: null, sessionId: crypto.randomUUID(), order: [qid], qDefs: qd });
    questionIndex = 0; renderQuestion();
}
function renderFlowOrder(fd) {
    const qm = {}; for (const q of questionnaires) qm[q.id] = q;
    const cons = fd.ordering_constraints || []; let order = [...fd.questionnaire_order], sel = new Set(fd.selected || fd.questionnaire_order);
    let tfMode = 'auto', customGapHours = 24, autoGapHours = 24, lastGapLabel = '';

    // Compute auto gap from last entry
    (async () => {
        try { const entries = await api('/api/entries'); if (entries.length > 0) { const last = new Date(entries[0].completed_at); autoGapHours = Math.max(1, (Date.now() - last.getTime()) / 3600000); customGapHours = Math.round(autoGapHours); lastGapLabel = fmtGap(autoGapHours); render(); } } catch (e) { }
    })();

    window.setTfMode = (mode) => { tfMode = mode; render(); };

    function viol(a, s) { for (const c of cons) { if (!s.has(c.before) || !s.has(c.after)) continue; const bi = a.indexOf(c.before), ai = a.indexOf(c.after); if (bi >= 0 && ai >= 0 && bi >= ai) return c.reason; } return null; }
    function render() {
        const v = viol(order, sel);
        // Compute default gap
        let h = `<div class="header"><button class="header-back" onclick="nav('#/')">← Back</button><span class="header-date">${esc(fd.title)}</span></div><h2 style="margin-bottom:4px">Configure Check-in</h2><p style="color:var(--text-muted);margin-bottom:16px;font-size:0.85rem">Select questionnaires, reorder, and set the reporting period.</p>`;
        // Timeframe picker
        h += `<div class="config-section"><label class="config-label">Reporting period</label><div class="timeframe-picker"><button class="tf-btn ${tfMode==='auto'?'active':''}" onclick="setTfMode('auto')">Since last time${lastGapLabel?' ('+lastGapLabel+')':''}</button><button class="tf-btn ${tfMode==='custom'?'active':''}" onclick="setTfMode('custom')">Custom</button></div>`;
        if (tfMode === 'custom') h += `<div class="tf-custom"><label>Hours: <input type="number" id="tf-hours" min="1" max="8760" value="${Math.round(customGapHours)}" onchange="customGapHours=+this.value"></label></div>`;
        h += `</div>`;
        if (v) h += `<div class="constraint-error">\u26A0 ${esc(v)}</div>`; if (!sel.size) h += `<div class="constraint-error">\u26A0 Select at least one</div>`;
        h += `<div class="reorder-list" id="reorder-list">`; let n = 0;
        for (let i = 0; i < order.length; i++) { const qid = order[i], q = qm[qid], s = sel.has(qid); if (s) n++; h += `<div class="reorder-item ${s ? '' : 'reorder-deselected'}" draggable="${s}" data-index="${i}"><label class="reorder-check" onclick="event.stopPropagation()"><input type="checkbox" ${s ? 'checked' : ''} onchange="flowToggle('${qid}',this.checked)"></label><div class="reorder-handle">${s ? '\u2261' : ''}</div><div class="reorder-content">${s ? `<div class="reorder-number">${n}</div>` : ''}<div><div class="reorder-title">${esc(q ? q.title : qid)}</div><div class="reorder-desc">${esc(q ? q.description : '')}</div></div></div>${s ? `<div class="reorder-arrows"><button class="reorder-arrow" onclick="flowMove(${i},-1)" ${i === 0 ? 'disabled' : ''}>\u25B2</button><button class="reorder-arrow" onclick="flowMove(${i},1)" ${i === order.length - 1 ? 'disabled' : ''}>\u25BC</button></div>` : ''}</div>`; }
        h += `</div><button class="btn btn-primary btn-block" style="margin-top:20px" onclick="beginFlow()" ${sel.size > 0 && !v ? '' : 'disabled'}>${sel.size <= 1 ? 'Start \u2192' : `Start (${sel.size}) \u2192`}</button>`;
        APP.innerHTML = h; setupDrag(order, render);
    }
    window.flowToggle = (qid, on) => { on ? sel.add(qid) : sel.delete(qid); render(); };
    window.flowMove = (i, d) => { const ni = i + d; if (ni < 0 || ni >= order.length) return; [order[i], order[ni]] = [order[ni], order[i]]; render(); };
    window.beginFlow = async () => {
        if (viol(order, sel) || !sel.size) return;
        try { await api(`/api/flows/${fd.id}/order`, { method: 'POST', body: JSON.stringify({ order, selected: [...sel] }) }); } catch (e) { }
        const eff = order.filter(qid => sel.has(qid)), qd = {};
        await Promise.all(eff.map(async q => { try { qd[q] = await api(`/api/questionnaire/${q}`); } catch (e) { } }));
        const gapHours = tfMode === 'custom' ? (+(document.getElementById('tf-hours')?.value) || customGapHours) : autoGapHours;
        session = new FlowSession({ flowId: fd.id, sessionId: crypto.randomUUID(), order: eff, qDefs: qd, gapHours });
        questionIndex = 0; renderQuestion();
    }; render();
}
function setupDrag(order, rr) { const list = document.getElementById('reorder-list'); if (!list) return; let di = null; list.querySelectorAll('.reorder-item').forEach(item => { item.addEventListener('dragstart', e => { di = +item.dataset.index; item.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; }); item.addEventListener('dragend', () => { item.classList.remove('dragging'); di = null; list.querySelectorAll('.reorder-item').forEach(el => el.classList.remove('drag-over')); }); item.addEventListener('dragover', e => { e.preventDefault(); list.querySelectorAll('.reorder-item').forEach(el => el.classList.remove('drag-over')); item.classList.add('drag-over'); }); item.addEventListener('dragleave', () => item.classList.remove('drag-over')); item.addEventListener('drop', e => { e.preventDefault(); const ti = +item.dataset.index; if (di != null && di !== ti) { const [m] = order.splice(di, 1); order.splice(ti, 0, m); rr(); } }); let tc = null; item.addEventListener('touchstart', () => { di = +item.dataset.index; item.classList.add('dragging'); }, { passive: true }); item.addEventListener('touchmove', e => { const t = e.touches[0], els = document.elementsFromPoint(t.clientX, t.clientY), tgt = els.find(el => el.classList.contains('reorder-item') && el !== item); list.querySelectorAll('.reorder-item').forEach(el => el.classList.remove('drag-over')); if (tgt) { tgt.classList.add('drag-over'); tc = tgt; } else tc = null; }, { passive: true }); item.addEventListener('touchend', () => { item.classList.remove('dragging'); if (tc && di != null) { const ti = +tc.dataset.index; if (di !== ti) { const [m] = order.splice(di, 1); order.splice(ti, 0, m); rr(); } } list.querySelectorAll('.reorder-item').forEach(el => el.classList.remove('drag-over')); di = null; tc = null; }); }); }

// ─── Question view ──────────────────────────────────────────
function renderQuestion() {
    if (!session) return; const qid = session.currentQId(), qDef = session.currentQDef(), vis = session.visibleQuestions(qid);
    if (questionIndex >= vis.length) { renderSummary(); return; }
    const q = vis[questionIndex], total = vis.length;
    const val = session.getAnswer(qid, q.id), imp = session.isImplied(qid, q.id), inFlow = session.order.length > 1;
    let skip = 0; if (imp) for (let i = questionIndex; i < vis.length; i++) { if (session.isImplied(qid, vis[i].id)) skip++; else break; }
    let pos = `${questionIndex + 1}/${total}`; if (inFlow) pos = `Q${questionIndex + 1}/${total} \xb7 Step ${session.step + 1}/${session.order.length}`;

    let h = `<div class="compact-header"><button class="header-back" onclick="goBack()">\u2190</button><button class="sidebar-toggle" onclick="toggleSidebar()">\u2630</button><span class="compact-title">${esc(qDef.title)}</span><button class="exit-link" onclick="exitFlow()">Save & Exit</button><span class="compact-pos">${pos}</span></div>`;

    // Timeframe banner for micro questionnaires
    if (qDef.micro && questionIndex === 0) {
        h += `<div class="timeframe-banner">Reporting on: last ${fmtGap(session.gapHours)}</div>`;
    }

    if (q.section) h += `<div class="question-section">${esc(q.section)}</div>`;
    h += `<div class="question-text">${esc(q.text)}</div>`; h += q.description ? `<div class="question-desc">${esc(q.description)}</div>` : '<div style="height:12px"></div>';
    if (imp) h += `<div class="implied-label">Pre-filled based on previous answer</div>`;
    if (!session.linksEnabled) h += `<div class="links-off-label">Auto-fill disabled for this session</div>`;

    if (session.contradictions.length) {
        h += `<div class="contradiction-banner"><strong>\u26A0 Contradiction${session.contradictions.length > 1 ? 's' : ''}:</strong>`;
        for (const c of session.contradictions) h += `<div class="contra-detail">"${esc(c.srcAnswerLabel)}" on "${esc(trunc(c.srcQuestionText, 50))}" conflicts with "${esc(c.tgtAnswerLabel)}" on "${esc(trunc(c.tgtQuestionText, 50))}"</div>`;
        h += `<div class="contradiction-actions"><button class="btn btn-primary btn-sm" onclick="resolveContra('${q.id}')">Resolve (clear conflicts) \u2192</button><button class="btn btn-secondary btn-sm" onclick="dismissAll()">Disable auto-fill</button></div></div>`;
    }

    // ── Render by question type ──
    if (q.type === 'slider') {
        const cfg = computeSliderConfig(session.gapHours);
        const selLabel = val != null ? `${val}% \u2014 ${sliderLabel(val, session.gapHours)}` : 'Select a value';
        h += `<div class="slider-value-label">${esc(selLabel)}</div>`;
        h += `<div class="radio-slider"><div class="radio-slider-track"></div><div class="radio-slider-dots">`;
        for (let i = 0; i < cfg.points.length; i++) {
            const p = cfg.points[i];
            const sel = val === p;
            const pct = p; // position percentage
            h += `<div class="radio-dot-wrap" style="left:${pct}%" onclick="answerSlider('${q.id}',${p})">
                <div class="radio-dot ${sel ? 'selected' : ''} ${sel && imp ? 'implied' : ''}"></div>
            </div>`;
        }
        h += `</div><div class="radio-slider-labels">`;
        h += `<span>None</span>`;
        if (cfg.points.length > 2) h += `<span>${sliderLabel(cfg.points[Math.floor(cfg.points.length / 2)], session.gapHours)}</span>`;
        h += `<span>All</span>`;
        h += `</div></div>`;
    } else if (q.type === 'yes_no' || q.type === 'single_choice') {
        const incompat = session.getIncompatibleOptions(qid, q.id);
        h += q.type === 'yes_no' ? '<div class="yesno-options">' : '<div class="options">';
        for (const o of q.options) { const s = val === o.id, im = s && imp, dim = incompat.has(o.id) && !s;
            if (q.type === 'yes_no') h += `<button class="yesno-btn ${s ? 'selected' : ''} ${im ? 'implied' : ''} ${dim ? 'dimmed' : ''}" onclick="answerQ('${q.id}','${o.id}')">${esc(o.label)}</button>`;
            else h += `<div class="option ${s ? 'selected' : ''} ${im ? 'implied' : ''} ${dim ? 'dimmed' : ''}" onclick="answerQ('${q.id}','${o.id}')"><div class="option-radio"></div><span>${esc(o.label)}</span></div>`;
        } h += '</div>';
    } else if (q.type === 'multi_choice') { const ar = Array.isArray(val) ? val : []; h += '<div class="options">'; for (const o of q.options) h += `<div class="option ${ar.includes(o.id) ? 'selected' : ''}" onclick="toggleMulti('${q.id}','${o.id}')"><div class="option-check"></div><span>${esc(o.label)}</span></div>`; h += '</div>'; }
    else if (q.type === 'text') h += `<textarea class="text-input" placeholder="Type here\u2026" oninput="answerText('${q.id}',this.value)">${esc(val || '')}</textarea>`;

    if (imp && skip > 1) h += `<button class="btn btn-secondary btn-block skip-implied-btn" onclick="skipImplied(${skip})">Skip ${skip} pre-filled \u2192</button>`;

    // Nav buttons
    h += '<div class="nav-buttons">'; h += `<button class="btn btn-secondary" onclick="goBack()">← Back</button>`;
    const last = questionIndex === total - 1;
    if (q.type === 'multi_choice' || q.type === 'text') {
        h += `<button class="btn btn-primary" onclick="goNext()">${last ? 'Review →' : 'Next →'}</button>`;
    } else if (val == null) {
        h += `<button class="btn btn-secondary" onclick="goNext()">Skip →</button>`;
    } else {
        h += `<button class="btn btn-primary" onclick="goNext()">${last ? 'Review →' : 'Next →'}</button>`;
    }
    h += '</div>'; APP.innerHTML = wrapSidebar(h);
}

// ── Answer handlers ──
function answerSlider(qnId, val) { session.setAnswer(session.currentQId(), qnId, val); scheduleAutosave(); renderQuestion(); if (!session.contradictions.length) setTimeout(() => goNext(), 300); }
function answerQ(qnId, optId) { session.setAnswer(session.currentQId(), qnId, optId); scheduleAutosave(); renderQuestion(); if (!session.contradictions.length) setTimeout(() => goNext(), 300); }
function answerText(qnId, t) { session.setAnswer(session.currentQId(), qnId, t); scheduleAutosave(); }
function toggleMulti(qnId, optId) { const qid = session.currentQId(); let a = session.getAnswer(qid, qnId); if (!Array.isArray(a)) a = []; const i = a.indexOf(optId); if (i === -1) a.push(optId); else a.splice(i, 1); session.setAnswer(qid, qnId, a); scheduleAutosave(); renderQuestion(); }
function dismissAll() { session.dismissContradictions(); goNext(); }
function resolveContra(currentQnId) { session.resolveContradictions(session.currentQId(), currentQnId); scheduleAutosave(); renderQuestion(); if (!session.contradictions.length) setTimeout(() => goNext(), 300); }

// Navigation
function goNext() { questionIndex++; const vis = session.visibleQuestions(session.currentQId()); if (questionIndex >= vis.length) renderSummary(); else renderQuestion(); }
function goBack() { if (questionIndex > 0) { questionIndex--; renderQuestion(); } else if (session && session.step > 0) { doAutosave(); session.goToStep(session.step - 1); const vis = session.visibleQuestions(session.currentQId()); questionIndex = Math.max(0, vis.length - 1); renderQuestion(); } else exitFlow(); }
function skipImplied(n) { questionIndex += n; const vis = session.visibleQuestions(session.currentQId()); if (questionIndex >= vis.length) renderSummary(); else renderQuestion(); }
function exitFlow() { doAutosave(); nav('#/'); }

// ─── Summary ────────────────────────────────────────────────
function renderSummary() {
    if (!session) return; const qid = session.currentQId(), qDef = session.currentQDef(), vis = session.visibleQuestions(qid);
    const inFlow = session.order.length > 1, isLast = session.step >= session.order.length - 1;
    const sl = inFlow ? (isLast ? 'Submit All' : 'Next \u2192') : 'Submit';
    const submitFn = inFlow ? (isLast ? 'submitAll()' : 'advanceToNext()') : 'submitCurrent()';
    let h = `<div class="compact-header"><button class="header-back" onclick="questionIndex=${vis.length - 1};renderQuestion();">\u2190</button><button class="sidebar-toggle" onclick="toggleSidebar()">\u2630</button><span class="compact-title">${esc(qDef.title)} \u2014 Review</span><button class="exit-link" onclick="exitFlow()">Save & Exit</button><span class="compact-pos"></span></div>`;
    let ls = ''; for (let i = 0; i < vis.length; i++) { const q = vis[i], v = session.getAnswer(qid, q.id), im = session.isImplied(qid, q.id); if (q.section && q.section !== ls) { ls = q.section; h += `<div class="summary-section" style="margin-top:12px">${esc(q.section)}</div>`; }
        h += `<div class="summary-card review-clickable" onclick="questionIndex=${i};renderQuestion();"><div class="summary-question">${esc(q.text)}</div>`;
        if (v != null && v !== '' && !(Array.isArray(v) && !v.length)) h += `<div class="summary-answer">${esc(optLbl(q, v))}${im ? ' <span class="implied-badge">auto</span>' : ''}</div>`; else h += `<div class="summary-unanswered">Not answered</div>`;
        h += `<div class="review-edit-hint">\u270E tap to edit</div></div>`; }
    h += `<div class="review-actions" style="padding-bottom:${inFlow ? '72px' : '0'}"><button class="btn btn-secondary" style="flex:1" onclick="questionIndex=0;renderQuestion();">Edit All</button><button class="btn btn-success" style="flex:1" onclick="${submitFn}">${sl}</button></div>`;
    if (inFlow) h += `<div class="sticky-submit-bar"><button class="btn btn-success btn-block" onclick="${submitFn}">${sl}</button></div>`;
    APP.innerHTML = wrapSidebar(h);
}
async function advanceToNext() { await doAutosave(); session.advanceStep(); questionIndex = 0; renderQuestion(); }
async function submitCurrent() { await doAutosave(); try { const res = await fetch(`/api/submit/${session.currentEntryId()}`, { method: 'POST', headers: {'Content-Type':'application/json'} }); if (!res.ok && res.status !== 409) { const e = await res.json().catch(()=>({error:res.statusText})); throw new Error(e.error||'fail'); } const e = await res.json(); await cleanupStaging(); renderDone(e); } catch (e) { alert('Submit failed: ' + e.message); } }
async function submitAll() {
    if (!session) return;
    // Save staging for all questionnaires (cascade may have modified earlier Qs)
    try {
        for (let i = 0; i < session.order.length; i++) {
            const qid = session.order[i];
            const p = session.toStagingPayloadForQ(qid, i);
            await api('/api/staging', { method: 'POST', body: JSON.stringify(p) });
        }
    } catch (e) { alert('Save failed: ' + e.message); return; }
    // Submit each entry
    const errors = [];
    for (const qid of session.order) {
        const eid = session.entryIds[qid];
        try {
            const res = await fetch(`/api/submit/${eid}`, { method: 'POST', headers: {'Content-Type':'application/json'} });
            if (!res.ok && res.status !== 409) { const e = await res.json().catch(()=>({error:res.statusText})); errors.push(`${session.qDefs[qid]?.title||qid}: ${e.error||'fail'}`); }
        } catch (e) { errors.push(`${session.qDefs[qid]?.title||qid}: ${e.message}`); }
    }
    if (errors.length) { alert('Some submissions failed:\n' + errors.join('\n')); }
    await cleanupStaging();
    renderFlowDone();
}
async function cleanupStaging() { if (!session) return; try { const all = await api('/api/staging'); const mine = all.filter(s => s.flow_session_id === session.sessionId || (session.flowId && s.flow_id === session.flowId)); for (const s of mine) try { await api(`/api/staging/${s.entry_id}`, { method: 'DELETE' }); } catch (e) { } } catch (e) { } }
function renderFlowDone() { const n = session ? session.order.length : 0; APP.innerHTML = `<div style="text-align:center;padding:40px 0"><div style="font-size:3rem;margin-bottom:16px">\u2713</div><h2>Check-in Complete</h2><p style="color:var(--text-muted);margin-bottom:24px">All ${n} questionnaires submitted.</p><div style="display:flex;gap:12px;margin-top:24px"><button class="btn btn-secondary" style="flex:1" onclick="nav('#/history')">History</button><button class="btn btn-primary" style="flex:1" onclick="nav('#/')">Home</button></div></div>`; session = null; }
function renderDone(e) { const s = e.scores || {}; let sc = ''; if (s.total != null && s.severity) sc = `<div class="score-card"><div class="score-value">${s.total}</div><div class="score-label">${esc(s.severity)}</div></div>`; else if (s.screener_result) sc = `<div class="score-card"><div class="score-label">${esc(s.screener_result)}</div></div>`; else if (s.screen_result) sc = `<div class="score-card"><div class="score-label">${esc(s.screen_result)}</div></div>`; else if (s.ideation_label) sc = `<div class="score-card"><div class="score-label">${esc(s.ideation_label)}</div></div>`; APP.innerHTML = `<div style="text-align:center;padding:40px 0"><div style="font-size:3rem;margin-bottom:16px">\u2713</div><h2>Submitted</h2><p style="color:var(--text-muted);margin-bottom:24px">${esc(e.questionnaire_title)}</p>${sc}<div style="display:flex;gap:12px;margin-top:24px"><button class="btn btn-secondary" style="flex:1" onclick="nav('#/entry/${e.entry_id}')">Details</button><button class="btn btn-primary" style="flex:1" onclick="nav('#/')">Home</button></div></div>`; session = null; }

// ─── Sidebar ────────────────────────────────────────────────
function sIcon(s) { const ic = { answered: '\u2713', prefilled: '\u25C9', submitted: '\u2713', skipped: '\u2013', current: '\u25B6', future: '\u25CB' }, cl = { answered: 'sb-answered', prefilled: 'sb-prefilled', submitted: 'sb-submitted', skipped: 'sb-skipped', current: 'sb-current', future: 'sb-future' }; return `<span class="sb-icon ${cl[s] || 'sb-future'}">${ic[s] || '\u25CB'}</span>`; }
function buildSB() { if (!session) return ''; let h = ''; for (let si = 0; si < session.order.length; si++) { const sqid = session.order[si], qd = session.qDefs[sqid]; if (!qd) continue; const cur = si === session.step, past = si < session.step; h += `<div class="sb-group ${cur ? 'sb-group-current' : past ? 'sb-group-done' : 'sb-group-future'}"><div class="sb-group-title">${esc(qd.title)}</div>`; const vis = session.visibleQuestions(sqid); for (let qi = 0; qi < vis.length; qi++) { const q = vis[qi]; let st; if (cur && qi === questionIndex) st = 'current'; else { const a = session.getAnswer(sqid, q.id), src = session.getSource(sqid, q.id); if (a != null) st = src === 'link' ? 'prefilled' : (past ? 'submitted' : 'answered'); else st = past ? 'skipped' : 'future'; } const cc = cur || past || st === 'answered' || st === 'prefilled'; const act = cc ? (cur ? `sbJump(${qi})` : `sbStep(${si},'${q.id}')`) : ''; h += `<div class="sb-item ${cc ? 'sb-clickable' : ''} ${st === 'current' ? 'sb-active' : ''}" ${act ? `onclick="${act}"` : ''}>${sIcon(st)}<span class="sb-text">${trunc(q.text, 50)}</span></div>`; } h += '</div>'; } return h; }
function sbJump(i) { questionIndex = i; sidebarOpen = false; renderQuestion(); }
function sbStep(si, qnId) { if (!session) return; doAutosave(); session.goToStep(si); const vis = session.visibleQuestions(session.currentQId()); const idx = vis.findIndex(q => q.id === qnId); questionIndex = idx >= 0 ? idx : 0; sidebarOpen = false; renderQuestion(); }
function toggleSidebar() { sidebarOpen = !sidebarOpen; const el = document.getElementById('sidebar'), ov = document.getElementById('sidebar-overlay'); if (el) el.classList.toggle('open', sidebarOpen); if (ov) ov.classList.toggle('visible', sidebarOpen); }
function wrapSidebar(main) { return `<div class="layout-with-sidebar"><div id="sidebar-overlay" class="sidebar-overlay ${sidebarOpen ? 'visible' : ''}" onclick="toggleSidebar()"></div><aside id="sidebar" class="sidebar ${sidebarOpen ? 'open' : ''}"><div class="sb-header"><span class="sb-header-title">Questions</span><button class="sb-close" onclick="toggleSidebar()">\u2715</button></div><div class="sb-body">${buildSB()}</div></aside><main class="main-content">${main}</main></div>`; }

// ─── History ────────────────────────────────────────────────

const hFilter = {
    search: '',
    types: new Set(['micro', 'full', 'generated']),  // entry types to show
    questionnaires: new Set(),  // empty = all
    datePreset: 'all',  // 'today','7d','30d','all','custom'
    dateFrom: '',
    dateTo: '',
    sort: 'newest',
    // UI state
    selectMode: false,
    selected: new Set(),
    panelOpen: false,
};

let hEntries = [];

function hReset() {
    hFilter.search = ''; hFilter.types = new Set(['micro', 'full', 'generated']);
    hFilter.questionnaires = new Set(); hFilter.datePreset = 'all';
    hFilter.dateFrom = ''; hFilter.dateTo = '';
    hFilter.sort = 'newest'; hFilter.selectMode = false;
    hFilter.selected = new Set(); hFilter.panelOpen = false;
}

async function renderHistory() {
    session = null; hReset();
    try { hEntries = await api('/api/entries'); if (!questionnaires.length) questionnaires = await api('/api/questionnaires'); }
    catch (e) { APP.innerHTML = '<div class="empty-state"><p>Failed.</p></div>'; return; }
    renderHV();
}

function hToggleType(t) { hFilter.types.has(t) ? hFilter.types.delete(t) : hFilter.types.add(t); hFilter.selected.clear(); renderHV(); }
function hToggleQ(qid) { hFilter.questionnaires.has(qid) ? hFilter.questionnaires.delete(qid) : hFilter.questionnaires.add(qid); hFilter.selected.clear(); renderHV(); }
function hSetPreset(p) { hFilter.datePreset = p; hFilter.selected.clear(); renderHV(); }
function hTogglePanel() { hFilter.panelOpen = !hFilter.panelOpen; renderHV(); }
function hToggleSelect() { hFilter.selectMode = !hFilter.selectMode; hFilter.selected.clear(); renderHV(); }
function hToggleSel(eid, ev) { if (ev) ev.stopPropagation(); hFilter.selected.has(eid) ? hFilter.selected.delete(eid) : hFilter.selected.add(eid); renderHV(); }
function hSelectAll() { const f = getFilteredH(); if (hFilter.selected.size === f.length) hFilter.selected.clear(); else hFilter.selected = new Set(f.map(e => e.entry_id)); renderHV(); }
async function hDeleteSelected() {
    if (!hFilter.selected.size) return;
    showConfirm('Delete?', `Delete ${hFilter.selected.size} entries? Cannot be undone.`, async () => {
        try { await api('/api/entries/delete', { method: 'POST', body: JSON.stringify({ entry_ids: [...hFilter.selected] }) }); }
        catch (e) { alert('Failed: ' + e.message); return; }
        hFilter.selected.clear(); hFilter.selectMode = false; await renderHistory();
    });
}

function entryType(e) {
    if (e.generated) return 'generated';
    if (e.micro) return 'micro';
    return 'full';
}

function getFilteredH() {
    let f = [...hEntries];
    // Type filter
    f = f.filter(e => hFilter.types.has(entryType(e)));
    // Questionnaire filter
    if (hFilter.questionnaires.size > 0) f = f.filter(e => hFilter.questionnaires.has(e.questionnaire_id));
    // Search
    if (hFilter.search) {
        const q = hFilter.search.toLowerCase();
        f = f.filter(e => [e.questionnaire_title, e.date, JSON.stringify(e.scores || {})].join(' ').toLowerCase().includes(q));
    }
    // Date range
    const now = new Date();
    let from = '', to = '';
    if (hFilter.datePreset === 'today') { from = fmtDateISO(now); to = fmtDateISO(now); }
    else if (hFilter.datePreset === '7d') { const d = new Date(now); d.setDate(d.getDate() - 7); from = fmtDateISO(d); }
    else if (hFilter.datePreset === '30d') { const d = new Date(now); d.setDate(d.getDate() - 30); from = fmtDateISO(d); }
    else if (hFilter.datePreset === 'custom') { from = hFilter.dateFrom; to = hFilter.dateTo; }
    if (from) f = f.filter(e => e.date >= from);
    if (to) f = f.filter(e => e.date <= to);
    // Sort
    if (hFilter.sort === 'oldest') f.sort((a, b) => a.completed_at.localeCompare(b.completed_at));
    else f.sort((a, b) => b.completed_at.localeCompare(a.completed_at));
    return f;
}

function fmtDateISO(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }

function renderHV() {
    const f = getFilteredH();
    const qids = [...new Set(hEntries.map(e => e.questionnaire_id))];
    const qm = {}; for (const q of questionnaires) qm[q.id] = q.title;
    const allSel = f.length > 0 && hFilter.selected.size === f.length;

    let h = `<div class="header"><button class="header-back" onclick="nav('#/')">\u2190 Home</button><span class="header-date">History</span></div>`;
    h += `<div class="nav-tabs"><div class="nav-tab" onclick="nav('#/')">Questionnaires</div><div class="nav-tab active">History</div></div>`;

    // Toolbar
    h += `<div class="h-toolbar">
        <input class="search-input h-search" type="text" placeholder="Search\u2026" value="${esc(hFilter.search)}" oninput="hFilter.search=this.value;renderHV();">
        <button class="h-icon-btn ${hFilter.panelOpen ? 'active' : ''}" onclick="hTogglePanel()" title="Filter">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M1.5 1.5h13L9 7.5v5l-2 1.5V7.5z"/></svg>
        </button>
        <button class="h-icon-btn" onclick="hFilter.sort=hFilter.sort==='newest'?'oldest':'newest';renderHV();" title="Sort ${hFilter.sort === 'newest' ? 'oldest' : 'newest'} first">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">${hFilter.sort === 'newest' ? '<path d="M4 2v10l-2-2H1l3 4 3-4H6l-2 2V2zm4 0v2h6V2zm0 4v2h4V6zm0 4v2h2V10z"/>' : '<path d="M4 2v10l-2-2H1l3 4 3-4H6l-2 2V2zm4 0v2h2V2zm0 4v2h4V6zm0 4v2h6V10z"/>'}</svg>
        </button>
        <button class="h-icon-btn ${hFilter.selectMode ? 'active' : ''}" onclick="hToggleSelect()" title="Select">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2h12v12H2zm2 2v8h8V4zm1 2h2v2H5zm4 0h2v2H9z"/></svg>
        </button>
    </div>`;

    // Filter panel
    if (hFilter.panelOpen) {
        h += `<div class="h-filter-panel">`;
        // Type checkboxes
        h += `<div class="hf-section"><span class="hf-label">Type</span><div class="hf-checks">`;
        for (const [t, label] of [['full', 'Full'], ['micro', 'Micro'], ['generated', 'Generated']]) {
            const on = hFilter.types.has(t);
            h += `<label class="hf-check" onclick="hToggleType('${t}')"><span class="h-check ${on ? 'checked' : ''}">${on ? '\u2713' : ''}</span>${label}</label>`;
        }
        h += `</div></div>`;
        // Questionnaire checkboxes
        h += `<div class="hf-section"><span class="hf-label">Questionnaire</span><div class="hf-checks">`;
        const allQ = hFilter.questionnaires.size === 0;
        h += `<label class="hf-check" onclick="hFilter.questionnaires.clear();renderHV();"><span class="h-check ${allQ ? 'checked' : ''}">${allQ ? '\u2713' : ''}</span>All</label>`;
        for (const qid of qids) {
            const on = hFilter.questionnaires.has(qid);
            h += `<label class="hf-check" onclick="hToggleQ('${qid}')"><span class="h-check ${on ? 'checked' : ''}">${on ? '\u2713' : ''}</span>${esc(trunc(qm[qid] || qid, 25))}</label>`;
        }
        h += `</div></div>`;
        // Date range
        h += `<div class="hf-section"><span class="hf-label">Date</span><div class="hf-date-presets">`;
        for (const [p, label] of [['all', 'All'], ['today', 'Today'], ['7d', '7 days'], ['30d', '30 days'], ['custom', 'Custom']]) {
            h += `<button class="hf-preset ${hFilter.datePreset === p ? 'active' : ''}" onclick="hSetPreset('${p}')">${label}</button>`;
        }
        h += `</div>`;
        if (hFilter.datePreset === 'custom') {
            h += `<div class="hf-custom-date">
                <input type="date" value="${hFilter.dateFrom}" onchange="hFilter.dateFrom=this.value;renderHV();">
                <span>to</span>
                <input type="date" value="${hFilter.dateTo}" onchange="hFilter.dateTo=this.value;renderHV();">
            </div>`;
        }
        h += `</div></div>`;
    }

    // Selection bar
    if (hFilter.selectMode && f.length) {
        h += `<div class="h-select-bar">
            <label class="h-select-all" onclick="hSelectAll()">
                <span class="h-check ${allSel ? 'checked' : ''}">${allSel ? '\u2713' : ''}</span>
                Select all (${hFilter.selected.size}/${f.length})
            </label>
            <div class="h-select-actions">`;
        if (hFilter.selected.size) {
            h += `<button class="btn btn-danger btn-sm" onclick="hDeleteSelected()">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:-2px;margin-right:4px"><path d="M5.5 0v1H2v2h12V1h-3.5V0zm.5 5v8h1V5zm3 0v8h1V5zM3 3v11a2 2 0 002 2h6a2 2 0 002-2V3z"/></svg>Delete ${hFilter.selected.size}
            </button>
            <button class="btn btn-secondary btn-sm" onclick="hExportSelected()">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:-2px;margin-right:4px"><path d="M8 0l4 5H9v6H7V5H4zm-6 14v2h12v-2z"/></svg>Export
            </button>`;
        }
        h += `</div></div>`;
    }

    // Entries list
    if (!f.length) {
        h += hEntries.length ? '<div class="empty-state"><p>No matches.</p></div>' : '<div class="empty-state"><p>No entries yet.</p></div>';
    } else {
        let ld = '';
        for (const e of f) {
            const dateKey = fmtDate(e.completed_at);
            if (dateKey !== ld) { ld = dateKey; h += `<div class="history-group-title">${esc(dateKey)}</div>`; }
            const s = e.scores || {};
            let sc = '';
            if (s.total != null && s.severity) sc = `<div class="history-score-value">${s.total}</div><div class="history-score-label">${esc(s.severity)}</div>`;
            else if (s.screener_result) sc = `<div class="history-score-label">${esc(s.screener_result)}</div>`;
            else if (s.screen_result) sc = `<div class="history-score-label">${esc(s.screen_result)}</div>`;
            else if (s.ideation_label) sc = `<div class="history-score-label">${esc(s.ideation_label)}</div>`;
            const sel = hFilter.selected.has(e.entry_id);
            const et = entryType(e);
            const badge = et === 'micro' ? '<span class="card-badge badge-micro">Micro</span> '
                : et === 'generated' ? '<span class="card-badge badge-generated">Gen</span> '
                : (e.flow_id ? '<span class="card-badge badge-flow">Flow</span> ' : '');
            const click = hFilter.selectMode ? `hToggleSel('${e.entry_id}')` : `nav('#/entry/${e.entry_id}')`;
            h += `<div class="history-card ${sel ? 'h-selected' : ''}" onclick="${click}">`;
            if (hFilter.selectMode) h += `<span class="h-check ${sel ? 'checked' : ''}" onclick="hToggleSel('${e.entry_id}',event)">${sel ? '\u2713' : ''}</span>`;
            h += `<div class="h-card-body"><div class="history-title">${badge}${esc(e.questionnaire_title)}</div><div class="history-time">${esc(fmtTime(e.completed_at))}</div></div><div class="history-score">${sc}</div></div>`;
        }
        h += `<div class="history-count">${f.length} entr${f.length === 1 ? 'y' : 'ies'}${hFilter.questionnaires.size || hFilter.search || hFilter.datePreset !== 'all' ? ' (filtered)' : ''}</div>`;
    }
    APP.innerHTML = h;
}

// Export modal
function hExportSelected() {
    if (!hFilter.selected.size) return;
    const ov = document.createElement('div'); ov.className = 'confirm-overlay';
    ov.innerHTML = `<div class="confirm-dialog" style="max-width:400px">
        <div class="confirm-title">Export ${hFilter.selected.size} entries</div>
        <div class="confirm-message">Choose format:</div>
        <div class="export-formats">
            <label class="hf-check"><input type="checkbox" value="md" checked> Markdown (.md)</label>
            <label class="hf-check"><input type="checkbox" value="csv"> CSV (.csv)</label>
            <label class="hf-check"><input type="checkbox" value="xlsx"> Excel (.xlsx)</label>
        </div>
        <div class="confirm-buttons" style="margin-top:16px">
            <button class="btn btn-secondary" onclick="this.closest('.confirm-overlay').remove()">Cancel</button>
            <button class="btn btn-primary" onclick="doExport(this.closest('.confirm-overlay'))">Export</button>
        </div>
    </div>`;
    document.body.appendChild(ov);
    ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); });
}

async function doExport(overlay) {
    const checks = overlay.querySelectorAll('.export-formats input:checked');
    const formats = [...checks].map(c => c.value);
    if (!formats.length) return;
    overlay.remove();
    try {
        const res = await fetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entry_ids: [...hFilter.selected], formats }),
        });
        if (!res.ok) { alert('Export failed'); return; }
        const blob = await res.blob();
        const ct = res.headers.get('Content-Type') || '';
        const ext = ct.includes('zip') ? 'zip' : formats[0];
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `mht_export_${fmtDateISO(new Date())}.${ext}`;
        a.click();
        URL.revokeObjectURL(a.href);
    } catch (e) { alert('Export failed: ' + e.message); }
}
async function renderEntryDetail(eid) { let e; try { e = await api(`/api/entry/${eid}`); } catch (er) { APP.innerHTML = '<div class="empty-state"><p>Not found.</p></div>'; return; } const s = e.scores || {}; let h = `<div class="header"><button class="header-back" onclick="nav('#/history')">\u2190 History</button><span class="header-date">${esc(fmtDate(e.completed_at))}</span></div><h2 style="margin-bottom:4px">${esc(e.questionnaire_title)}${e.micro ? ' <span class="card-badge badge-micro">Micro</span>' : ''}</h2><p style="color:var(--text-muted);margin-bottom:20px;font-size:0.85rem">Completed ${esc(fmtTime(e.completed_at))}${e.gap_hours ? ' \xb7 Period: ' + fmtGap(e.gap_hours) : ''}</p>`; if (s.total != null && s.severity) h += `<div class="score-card"><div class="score-value">${s.total}</div><div class="score-label">${esc(s.severity)}</div></div>`; else if (s.screener_result) h += `<div class="score-card"><div class="score-label">${esc(s.screener_result)}</div></div>`; else if (s.screen_result) h += `<div class="score-card"><div class="score-label">${esc(s.screen_result)}</div></div>`; else if (s.ideation_label) h += `<div class="score-card"><div class="score-label">${esc(s.ideation_label)}</div>${s.behavior ? '<div class="score-sublabel" style="color:var(--danger)">Suicidal behavior reported</div>' : ''}${s.frequency ? '<div class="score-sublabel">Frequency: ' + esc(s.frequency) + '</div>' : ''}</div>`; let ls = ''; for (const r of e.responses) { if (r.section && r.section !== ls) { ls = r.section; h += `<div class="summary-section" style="margin-top:16px">${esc(r.section)}</div>`; } h += `<div class="summary-card" style="cursor:default"><div class="summary-question">${esc(r.question_text)}</div><div class="summary-answer">${esc(Array.isArray(r.value_label) ? r.value_label.join(', ') : String(r.value_label))}${r.auto_implied ? ' <span class="implied-badge">auto</span>' : ''}</div></div>`; } h += `<button class="btn btn-secondary btn-block" style="margin-top:20px" onclick="nav('#/history')">Back</button>`; APP.innerHTML = h; }

document.addEventListener('DOMContentLoaded', () => handleRoute());
