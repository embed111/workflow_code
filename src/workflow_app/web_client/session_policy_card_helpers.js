    if (!state.selectedSessionId) return null;
    return state.sessionsById[state.selectedSessionId] || null;
  }

  function ensureSessionEntry(raw) {
    const sid = safe(raw && raw.session_id).trim();
    if (!sid) return null;
    if (!state.sessionsById[sid]) {
      state.sessionsById[sid] = {
        session_id: sid,
        messages: [],
      };
    }
    Object.assign(state.sessionsById[sid], raw || {});
    if (!Array.isArray(state.sessionsById[sid].messages)) {
      state.sessionsById[sid].messages = [];
    }
    if (!state.sessionOrder.includes(sid)) {
      state.sessionOrder.unshift(sid);
    }
    return state.sessionsById[sid];
  }

  function moveSessionToTop(sessionId) {
    state.sessionOrder = state.sessionOrder.filter((sid) => sid !== sessionId);
    state.sessionOrder.unshift(sessionId);
  }

  function activeTaskCount() {
    return Object.keys(state.runningTasks).length;
  }

  function dashboardMetricNumber(key, fallback) {
    const metrics = state.dashboardMetrics && typeof state.dashboardMetrics === 'object'
      ? state.dashboardMetrics
      : {};
    const value = Number(metrics[key]);
    if (Number.isFinite(value) && value >= 0) return value;
    return Number(fallback || 0);
  }

  function assignmentRuntimeMetricSnapshot() {
    const runningTaskCount = dashboardMetricNumber('assignment_running_task_count', 0);
    const runningAgentCount = dashboardMetricNumber('assignment_running_agent_count', 0);
    const executionValue = dashboardMetricNumber('assignment_active_execution_count', 0);
    const agentCallCount = dashboardMetricNumber('agent_call_count', runningTaskCount);
    return {
      running_task_count: runningTaskCount,
      running_agent_count: runningAgentCount,
      active_execution_count: executionValue,
      agent_call_count: Math.max(0, agentCallCount - activeTaskCount()),
    };
  }

  function globalRunningTaskCount() {
    return Math.max(0, dashboardMetricNumber('running_task_count', activeTaskCount()));
  }

  function globalAgentCallCount() {
    return Math.max(0, dashboardMetricNumber('agent_call_count', globalRunningTaskCount()));
  }

  function appendGlobalRuntimeMetricNote(container, text, tone) {
    const note = document.createElement('div');
    note.className = 'brand-metric-note' + (safe(tone).trim() ? ' ' + safe(tone).trim() : '');
    note.textContent = text;
    container.appendChild(note);
  }

  function renderGlobalRuntimeMetricLine() {
    const node = $('metricLine');
    if (!node) return;
    const dashboardError = safe(state.dashboardError).trim();
    const locked = !!(state.dashboardMetrics && state.dashboardMetrics.features_locked);
    const metricRows = [
      {
        label: 'Agent调用中',
        value: globalAgentCallCount(),
        tone: globalAgentCallCount() > 0 ? 'is-live' : '',
      },
      {
        label: '运行中任务',
        value: globalRunningTaskCount(),
        tone: globalRunningTaskCount() > 0 ? 'is-live' : '',
      },
      {
        label: '可用Agent',
        value: dashboardMetricNumber('available_agents', 0),
        tone: dashboardMetricNumber('available_agents', 0) > 0 ? 'is-ok' : 'is-bad',
      },
    ];
    const fragment = document.createDocumentFragment();
    const summary = document.createElement('div');
    summary.className = 'brand-metric-summary';
    metricRows.forEach((item) => {
      const part = document.createElement('div');
      part.className = 'brand-metric-summary-row' + (safe(item.tone).trim() ? ' ' + safe(item.tone).trim() : '');

      const labelNode = document.createElement('span');
      labelNode.className = 'brand-metric-label';
      labelNode.textContent = item.label;

      const valueNode = document.createElement('strong');
      valueNode.className = 'brand-metric-value';
      valueNode.textContent = String(item.value);

      part.appendChild(labelNode);
      part.appendChild(valueNode);
      summary.appendChild(part);
    });
    fragment.appendChild(summary);
    if (locked || dashboardError) {
      const notes = document.createElement('div');
      notes.className = 'brand-metric-notes';
      if (locked) {
        appendGlobalRuntimeMetricNote(notes, '功能锁定中', 'is-warn');
      }
      if (dashboardError) {
        appendGlobalRuntimeMetricNote(notes, '仪表盘异常：' + dashboardError, 'is-bad');
      }
      fragment.appendChild(notes);
    }
    node.replaceChildren(fragment);
    node.setAttribute(
      'aria-label',
      metricRows.map((item) => item.label + '=' + String(item.value)).join('，')
    );
    node.title =
      'Agent调用中与运行中任务仅统计当前仍在执行的会话任务和任务中心活跃执行批次。';
  }

  function formatDateTime(text) {
    const raw = safe(text).trim();
    if (!raw) return '-';
    const dt = new Date(raw);
    if (Number.isNaN(dt.getTime())) return raw;
    return dt.toLocaleString();
  }

  function formatElapsedMs(value) {
    const ms = Number(value || 0);
    if (!Number.isFinite(ms) || ms < 0) return '-';
    if (ms < 1000) return Math.floor(ms) + 'ms';
    const sec = Math.floor(ms / 1000);
    const min = Math.floor(sec / 60);
    const rem = sec % 60;
    if (!min) return sec + 's';
    return min + 'm ' + rem + 's';
  }

  function renderRunningTaskPanel() {
    const box = $('runningTaskList');
    if (!box) return;
    box.innerHTML = '';
    const entries = Object.entries(state.runningTasks);
    if (!entries.length) {
      const empty = document.createElement('div');
      empty.className = 'hint';
      empty.textContent = '当前无运行中任务';
      box.appendChild(empty);
      return;
    }
    for (const [sessionId, meta] of entries) {
      const taskId = safe(meta.task_id);
      const run = findTaskRun(sessionId, taskId);
      const startedAt = safe((run && run.start_at) || meta.started_at);
      const startedMs = startedAt ? new Date(startedAt).getTime() : NaN;
      const isDone = !!run && Number(run.duration_ms || 0) > 0;
      const elapsedMs = isDone
        ? Number(run.duration_ms || 0)
        : Number.isFinite(startedMs)
          ? Math.max(0, Date.now() - startedMs)
          : 0;
      const status = safe((run && run.status) || meta.status || 'running');
      const agentName = safe((run && run.agent_name) || meta.agent_name || (state.sessionsById[sessionId] || {}).agent_name);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'alt running-task-item';
      btn.onclick = () => {
        selectSession(sessionId).catch((err) => setChatError(err.message || String(err)));
      };
      const line1 = document.createElement('div');
      line1.className = 'title';
      line1.textContent = short(sessionId, 34) + ' · ' + (agentName || '-');
      const line2 = document.createElement('div');
      line2.className = 'sub';
      line2.textContent =
        'task=' +
        short(taskId, 24) +
        ' · 状态=' +
        statusText(status) +
        ' · started_at=' +
        formatDateTime(startedAt) +
        ' · elapsed=' +
        formatElapsedMs(elapsedMs);
      btn.appendChild(line1);
      btn.appendChild(line2);
      box.appendChild(btn);
    }
  }

  function normalizeAgentTextItems(raw, fallbackText) {
    const out = [];
    const seen = new Set();
    const push = (value) => {
      let text = safe(value).trim();
      if (!text) return;
      text = text.replace(/^\s*(?:[-*+]|[0-9]+[.)]|[（(]?[0-9]+[）)])\s*/, '').trim();
      text = text.replace(/\s+/g, ' ').trim();
      if (!text) return;
      const key = text.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push(text);
    };
    if (Array.isArray(raw)) {
      for (const item of raw) push(item);
    } else {
      for (const part of safe(raw).split(/\r?\n|[；;]/)) push(part);
    }
    if (!out.length && safe(fallbackText).trim()) {
      for (const part of safe(fallbackText).split(/\r?\n|[；;]/)) push(part);
    }
    return out;
  }

  function normalizeWarnList(raw) {
    const source = Array.isArray(raw) ? raw : [];
    const out = [];
    const seen = new Set();
    for (const item of source) {
      const key = safe(item).trim();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(parseWarningLabel(key));
    }
    return out;
  }

  function previewTextFromRole(roleProfile, fallbackAgent) {
    const text = safe(roleProfile).replace(/\s+/g, ' ').trim();
    if (!text) return safe(fallbackAgent) || '未提取';
    if (text.length <= 120) return text;
    return text.slice(0, 120).trimEnd() + '...';
  }

  function createPolicyCard(title, items, previewLimit, emptyText) {
    const card = document.createElement('section');
    card.className = 'agent-policy-card';

    const head = document.createElement('div');
    head.className = 'agent-policy-card-head';
    head.textContent = title;
    card.appendChild(head);

    const body = document.createElement('div');
    body.className = 'agent-policy-card-body';
    if (!items.length) {
      body.textContent = emptyText;
    } else {
      const list = document.createElement('ul');
      list.className = 'agent-policy-list';
      const display = items.slice(0, Math.max(1, previewLimit));
      for (const text of display) {
        const li = document.createElement('li');
        li.textContent = text;
        list.appendChild(li);
      }
      body.appendChild(list);
      if (items.length > display.length) {
        const hint = document.createElement('div');
        hint.className = 'agent-policy-more';
        hint.textContent = '还有 ' + safe(items.length - display.length) + ' 条，展开后查看';
        body.appendChild(hint);
      }
    }
    card.appendChild(body);
    return card;
  }

  function normalizeConstraintEntries(raw) {
    const source = Array.isArray(raw) ? raw : [];
    const out = [];
    const seen = new Set();
    for (const item of source) {
      if (!item || typeof item !== 'object') continue;
      const text = safe(item.text).trim();
      if (!text) continue;
      const key = text.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({
        text: text,
        evidence: safe(item.evidence).trim(),
        source_title: safe(item.source_title).trim(),
      });
    }
    return out;
  }

  function constraintEntryTextList(raw) {
    const source = Array.isArray(raw) ? raw : [];
    const out = [];
    const seen = new Set();
    for (const item of source) {
      const text =
        typeof item === 'string'
          ? safe(item).trim()
          : safe(item && item.text).trim();
      if (!text) continue;
      const key = text.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(text);
    }
    return out;
  }

  function buildDutyEditorTextFromConstraints(constraints, fallbackItems) {
    const node = constraints && typeof constraints === 'object' ? constraints : {};
    const sections = [
      ['must（必须项）', constraintEntryTextList(node.must)],
      ['must_not（禁止项）', constraintEntryTextList(node.must_not)],
      ['preconditions（前置条件）', constraintEntryTextList(node.preconditions)],
    ];
    const hasStructured =
      sections.some((pair) => pair[1].length > 0) ||
      Array.isArray(node.must) ||
      Array.isArray(node.must_not) ||
      Array.isArray(node.preconditions);
    const lines = [];
    if (hasStructured) {
      for (const pair of sections) {
        const title = pair[0];
        const items = pair[1];
        if (lines.length) lines.push('');
        lines.push(title);
        if (!items.length) {
          lines.push('(无)');
          continue;
        }
        for (const item of items) {
          lines.push('- ' + item);
        }
      }
      return lines.join('\n');
    }
    const fallback = Array.isArray(fallbackItems) ? fallbackItems : [];
    return fallback
      .map((item) => safe(item).trim())
      .filter((item) => !!item)
      .join('\n');
  }

  function normalizeDutyEditorItems(raw) {
    const out = [];
    const seen = new Set();
    const placeholderSet = new Set(['(无)', '无', 'none', 'n/a', 'na', '-', '--']);
    const isHeading = (text) => {
      const compact = safe(text).trim().toLowerCase();
      if (!compact) return false;
      if (compact.startsWith('must_not')) return true;
      if (compact.startsWith('must')) return true;
      if (compact.startsWith('preconditions')) return true;
      if (compact.startsWith('precondition')) return true;
      return false;
    };
    const push = (value) => {
      let text = safe(value).trim();
      if (!text) return;
      text = text.replace(/^\s*(?:[-*+]|[0-9]+[.)]|[（(]?[0-9]+[）)])\s*/, '').trim();
      if (!text) return;
      if (isHeading(text)) return;
      if (placeholderSet.has(text.toLowerCase())) return;
      const key = text.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push(text);
    };
    const source = safe(raw);
    const lines = source.split(/\r?\n|[；;]/);
    for (const line of lines) push(line);
    return out;
  }

  function normalizeScoreWeights(raw) {
    const source = raw && typeof raw === 'object' ? raw : {};
    const defaults = {
      completeness: 0.2,
      executability: 0.2,
      consistency: 0.2,
      traceability: 0.15,
      risk_coverage: 0.15,
      operability: 0.1,
    };
    const out = {};
    for (const key of Object.keys(defaults)) {
      const value = Number(source[key]);
      out[key] = Number.isFinite(value) && value >= 0 ? value : defaults[key];
    }
    return out;
  }

  function normalizeScoreDimensions(raw, weights) {
    const source = raw && typeof raw === 'object' ? raw : {};
    const order = [
      ['completeness', '完整性'],
      ['executability', '可执行边界'],
      ['consistency', '一致性'],
      ['traceability', '可追溯性'],
      ['risk_coverage', '风险覆盖度'],
      ['operability', '可操作性'],
    ];
    const out = {};
    for (const pair of order) {
      const key = pair[0];
      const fallbackLabel = pair[1];
      const node = source[key] && typeof source[key] === 'object' ? source[key] : {};
      const evidenceRaw = Array.isArray(node.evidence_map) ? node.evidence_map : [];
      const evidence = [];
      for (const item of evidenceRaw) {
        if (!item || typeof item !== 'object') continue;
        const ref = safe(item.ref).trim();
        const snippet = safe(item.snippet).trim();
        if (!ref && !snippet) continue;
        evidence.push({
          ref: ref || 'unknown',
          snippet: snippet,
        });
      }
      out[key] = {
        key: key,
        label: safe(node.label).trim() || fallbackLabel,
        score: Math.max(0, Math.min(100, Number(node.score || 0))),
        weight: Number(node.weight || weights[key] || 0),
        status: safe(node.status).trim() || 'manual_review',
        has_evidence: !!node.has_evidence,
        manual_review_required: !!node.manual_review_required,
        deduction_reason: safe(node.deduction_reason).trim(),
        evidence_map: evidence,
        repair_suggestion: safe(node.repair_suggestion).trim(),
      };
    }
    return {
      order: order.map((pair) => pair[0]),
      items: out,
    };
  }

  function createPolicyModule(title, moduleKey, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const collapsible = !!opts.collapsible;
    const expanded = opts.expanded !== false;
    const section = document.createElement(collapsible ? 'details' : 'section');
    section.className = 'policy-confirm-module';
    section.setAttribute('data-policy-module', safe(moduleKey));
    if (collapsible) {
      section.open = !!expanded;
    }
    const head = document.createElement(collapsible ? 'summary' : 'div');
    head.className = 'policy-confirm-module-head';
    head.textContent = safe(title);
    section.appendChild(head);
    const body = document.createElement('div');
    body.className = 'policy-confirm-module-body';
    section.appendChild(body);
    return { section, body };
  }

  function updateAgentMeta() {
    const current = selectedAgent();
    const item = state.agents.find((v) => v.agent_name === current);
    const node = $('agentMeta');
    if (!item) {
      node.textContent = '';
      state.agentMetaPanelOpen = false;
      state.agentMetaDetailsOpen = false;
      state.agentMetaClarityOpen = false;
      return;
    }
    node.textContent = '';
    const wrap = document.createElement('div');
    wrap.className = 'agent-policy-wrap';
    const rec = getAgentPolicyAnalysisRecord(current);
    const isAnalyzing =
      !!(rec && rec.analyzing) || safe(state.sessionPolicyGateState).trim().toLowerCase() === 'analyzing_policy';
    const isAnalyzed = !!(rec && rec.status === 'analyzed');
    const scoreLine = document.createElement('div');
    scoreLine.className = 'policy-gate-line ready';
    if (isAnalyzing) {
      scoreLine.textContent = '角色评分: 分析中...';
    } else if (!isAnalyzed) {
      scoreLine.textContent = '角色评分: 待分析';
    } else {
      scoreLine.textContent =
        '角色评分: ' +
        safe(Number(item.clarity_score || 0)) +
        '/100 · parse=' +
        parseStatusText(item.parse_status || 'pending');
    }
    wrap.appendChild(scoreLine);

    const hintLine = document.createElement('div');
    hintLine.className = 'agent-meta-line';
    hintLine.textContent = '其余详情请在“角色与职责确认/兜底”查看。';
    wrap.appendChild(hintLine);

    node.appendChild(wrap);
    node.scrollLeft = 0;
  }

  function setPolicyConfirmError(text) {
    const node = $('policyConfirmError');
    if (!node) return;
    node.textContent = safe(text);
  }

  function setPolicyRescoreMeta(text) {
    const node = $('policyRescoreMeta');
    if (!node) return;
    node.textContent = safe(text);
  }

  function policyEditFingerprint() {
    const role = safe($('policyEditRole') && $('policyEditRole').value).trim();
    const goal = safe($('policyEditGoal') && $('policyEditGoal').value).trim();
    const duty = safe($('policyEditDuty') && $('policyEditDuty').value).trim();
    return [role, goal, duty].join('\n---\n');
  }

  function policyEditorDraftSnapshot() {
    const role = safe($('policyEditRole') && $('policyEditRole').value).trim();
    const goal = safe($('policyEditGoal') && $('policyEditGoal').value).trim();
    const dutyText = safe($('policyEditDuty') && $('policyEditDuty').value).trim();
    return {
      role_profile: role,
      session_goal: goal,
      duty_constraints_text: dutyText,
      duty_constraints: normalizeDutyEditorItems(dutyText),
    };
  }

  function policyDraftComparableSignature(draft) {
    const node = draft && typeof draft === 'object' ? draft : {};
    const role = safe(node.role_profile).replace(/\s+/g, ' ').trim();
    const goal = safe(node.session_goal).replace(/\s+/g, ' ').trim();
    const dutyItems = Array.isArray(node.duty_constraints)
      ? node.duty_constraints
      : normalizeDutyEditorItems(node.duty_constraints_text || '');
    const duty = dutyItems.map((item) => safe(item).replace(/\s+/g, ' ').trim()).filter((item) => !!item).join('\n');
    return [role, goal, duty].join('\n---\n');
  }

  function validatePolicyRecommendInstruction(text) {
    const raw = safe(text).trim();
    if (!raw) {
      return {
        ok: false,
        message: '请先输入一句话优化需求',
      };
    }
    const compact = raw.replace(/\s+/g, '');
    const semantic = compact.replace(/[，。！？；：、,.;:!?~`'"“”‘’（）()【】\[\]{}<>《》_\/\\|\-]+/g, '');
    if (semantic.length < 6) {
      return {
        ok: false,
        message: '信息过少，请补充具体目标、边界或场景',
      };
    }
    if (!/[A-Za-z\u4e00-\u9fff]/.test(semantic)) {
      return {
        ok: false,
        message: '缺少可识别语义，请补充关键目标或约束',
      };
    }
    const weakTokens = new Set(['优化', '优化一下', '改一下', '调整一下', '随便', '都行', '同上', '一样', '继续', '默认', 'test', 'ok', 'none']);
    if (weakTokens.has(semantic.toLowerCase())) {
      return {
        ok: false,
        message: '内容过于笼统，请补充具体优化方向',
      };
    }
    const normalizedLower = raw.toLowerCase();
    const directionTokens = [
      '参考业界实践',
      '业界实践',
      '最佳实践',
      'best practice',
      'industry practice',
      '目标',
      '边界',
      '约束',
      '风险',
      '必须',
      '禁止',
      '前置',
      '场景',
      '用户',
      '步骤',
      '流程',
      '输出',
      '格式',
      '证据',
      '一致',
      '评分',
      '门禁',
      '缓存',
      '性能',
      '安全',
      '补充',
      '完善',
      '修复',
      '收敛',
      '细化',
      '清晰',
      '清楚',
      '可执行',
      '可追溯',
    ];
    let hasDirection = directionTokens.some((token) => normalizedLower.includes(token));
    if (!hasDirection) {
      hasDirection = /如果.*(没有|无|未发现).*(优化|改进|问题).*(不优化|不改|保持|不变)/.test(raw);
    }
    if (!hasDirection) {
      return {
        ok: false,
        message: '未识别到明确优化方向，请补充要优化的目标、边界或参考标准',
      };
    }
    return {
      ok: true,
      message: '',
    };
  }

