  function renderSessionList() {
    const box = $('sessionList');
    box.innerHTML = '';
    for (const sessionId of state.sessionOrder) {
      const session = state.sessionsById[sessionId];
      if (!session) continue;
      const node = document.createElement('div');
      node.className = 'session-item' + (state.selectedSessionId === sessionId ? ' active' : '');
      const running = state.runningTasks[sessionId];
      const sub =
        (running ? '运行中' : statusText(session.status || 'active')) +
        (session.last_message ? ' · ' + short(session.last_message, 42) : '');
      node.innerHTML =
        "<div class='title'>" +
        short(sessionId, 34) +
        ' · ' +
        safe(session.agent_name || '未命名') +
        "</div><div class='sub'>" +
        sub +
        '</div>';
      node.onclick = () => {
        selectSession(sessionId).catch((err) => setChatError(err.message || String(err)));
      };
      box.appendChild(node);
    }
    if (!state.sessionOrder.length) {
      const empty = document.createElement('div');
      empty.className = 'hint';
      empty.textContent = '暂无会话';
      box.appendChild(empty);
    }
  }

  function createTraceDetails(title, text, options) {
    const details = document.createElement('details');
    const opts = options && typeof options === 'object' ? options : {};
    const taskId = safe(opts.task_id || '').trim();
    const detailKeyRaw = safe(opts.detail_key || title).trim();
    const detailKey = taskId && detailKeyRaw ? taskId + '::' + detailKeyRaw : '';
    if (detailKey) {
      details.open = !!state.taskTraceDetailsOpen[detailKey];
      details.addEventListener('toggle', () => {
        if (details.open) {
          state.taskTraceDetailsOpen[detailKey] = true;
        } else {
          delete state.taskTraceDetailsOpen[detailKey];
        }
      });
    }
    const summary = document.createElement('summary');
    summary.textContent = title;
    details.appendChild(summary);
    const pre = document.createElement('pre');
    pre.className = 'trace-pre';
    pre.textContent = text;
    details.appendChild(pre);
    return details;
  }

  function findTaskRun(sessionId, taskId) {
    const runs = state.sessionTaskRuns[sessionId] || [];
    return runs.find((row) => safe(row.task_id) === safe(taskId)) || null;
  }

  function renderTaskTracePanel(container, sessionId, taskId) {
    container.innerHTML = '';
    const run = findTaskRun(sessionId, taskId);
    const traceState = state.taskTraceCache[taskId] || {};

    const meta = document.createElement('div');
    meta.className = 'trace-meta';
    const duration = run && Number(run.duration_ms || 0) > 0 ? ' · ' + safe(run.duration_ms) + 'ms' : '';
    meta.textContent =
      'task=' +
      safe(taskId) +
      ' · 状态=' +
      statusText(run ? run.status : safe((traceState.data && traceState.data.task && traceState.data.task.status) || 'unknown')) +
      duration;
    container.appendChild(meta);

    if (traceState.loading) {
      const loading = document.createElement('div');
      loading.className = 'hint';
      loading.textContent = '调用链路加载中...';
      container.appendChild(loading);
      return;
    }
    if (traceState.error) {
      const err = document.createElement('div');
      err.className = 'error';
      err.textContent = safe(traceState.error);
      container.appendChild(err);
      return;
    }
    const data = traceState.data || {};
    const trace = data.trace || {};
    const task = data.task || {};
    const events = Array.isArray(data.events) ? data.events : [];

    const command = Array.isArray(task.command)
      ? task.command.map((v) => safe(v))
      : run && Array.isArray(run.command)
        ? run.command.map((v) => safe(v))
        : [];
    const commandText = command.length ? command.join(' ') : '(无命令信息)';
    container.appendChild(
      createTraceDetails('调用命令链路', commandText, {
        task_id: taskId,
        detail_key: 'command',
      }),
    );

    const promptText = safe(trace.prompt);
    container.appendChild(
      createTraceDetails('执行提示词（prompt）', promptText || '(未生成 prompt 快照，可能是旧任务)', {
        task_id: taskId,
        detail_key: 'prompt',
      }),
    );

    const eventLines = events.length
      ? events
          .map((event) => {
            const ts = safe(event.timestamp);
            const tp = safe(event.event_type);
            const payload = formatJsonLines(event.payload || {});
            return ts + ' | ' + tp + '\n' + payload;
          })
          .join('\n\n')
      : '(暂无任务事件)';
    container.appendChild(
      createTraceDetails('任务事件链路', eventLines, {
        task_id: taskId,
        detail_key: 'events',
      }),
    );
  }

  async function ensureTaskTrace(taskId, force) {
    const key = safe(taskId);
    if (!key) return;
    const existing = state.taskTraceCache[key];
    if (!force && existing && (existing.loading || existing.data)) return;
    state.taskTraceCache[key] = { loading: true, data: null, error: '' };
    renderFeed();
    try {
      const data = await getJSON('/api/tasks/' + encodeURIComponent(key) + '/trace');
      state.taskTraceCache[key] = { loading: false, data: data, error: '' };
    } catch (err) {
      state.taskTraceCache[key] = {
        loading: false,
        data: null,
        error: '调用链路加载失败: ' + safe(err.message || String(err)),
      };
    }
    renderFeed();
  }

  function renderFeed() {
    const feed = $('feed');
    const previousScrollTop = Number(feed.scrollTop || 0);
    const previousScrollHeight = Number(feed.scrollHeight || 0);
    const previousClientHeight = Number(feed.clientHeight || 0);
    const wasNearBottom =
      previousScrollHeight <= previousClientHeight + 1 ||
      previousScrollHeight - (previousScrollTop + previousClientHeight) <= 24;
    feed.innerHTML = '';
    const session = currentSession();
    if (!session) {
      state.feedRenderedSessionId = '';
      $('chatTitle').textContent = '未选择会话';
      const d = document.createElement('div');
      d.className = 'bubble system';
      d.textContent = '请选择会话，或先创建一个会话';
      feed.appendChild(d);
      applyGateState();
      return;
    }
    const currentSessionId = safe(session.session_id);
    const sessionChanged = currentSessionId !== safe(state.feedRenderedSessionId);
    state.feedRenderedSessionId = currentSessionId;
    $('chatTitle').textContent =
      short(session.session_id, 32) + ' · ' + safe(session.agent_name || '') + ' · 根路径=' + safe(session.agent_search_root || '');
    for (const msg of session.messages || []) {
      const d = document.createElement('div');
      const role = safe(msg.role);
      d.className =
        'bubble ' +
        (role === 'user' ? 'user' : role === 'assistant' ? 'assistant' : 'system');
      const createdAtText = safe(msg.created_at).trim();
      const messageMeta = createdAtText
        ? (() => {
            const node = document.createElement('div');
            node.className = 'bubble-meta';
            node.textContent = formatDateTime(createdAtText);
            return node;
          })()
        : null;
      if (role === 'assistant' && safe(msg.run_state)) {
        const stateWrap = document.createElement('div');
        const runtimeInfo = runtimePhaseInfo(msg.run_state);
        stateWrap.className = 'assistant-runtime-state';
        const badge = document.createElement('span');
        badge.className = 'state-chip ' + safe(runtimeInfo.tone || 'running');
        appendIconLabel(badge, runtimeInfo.label, runtimeInfo.icon, {
          spinning: !!runtimeInfo.spinning,
          labelClassName: 'state-chip-label',
        });
        stateWrap.appendChild(badge);
        if (safe(msg.run_state) === 'sent' || safe(msg.run_state) === 'generating') {
          const thinking = document.createElement('span');
          thinking.className = 'thinking-text';
          thinking.appendChild(createStatusIcon('running', { spinning: true, compact: true }));
          const thinkingLabel = document.createElement('span');
          thinkingLabel.textContent = '思考中';
          thinking.appendChild(thinkingLabel);
          const dots = document.createElement('span');
          dots.className = 'thinking-dots';
          dots.setAttribute('aria-hidden', 'true');
          for (let i = 0; i < 3; i += 1) {
            const dot = document.createElement('span');
            dot.textContent = '.';
            dots.appendChild(dot);
          }
          thinking.appendChild(dots);
          stateWrap.appendChild(thinking);
        }
        d.appendChild(stateWrap);
      }
      const content = document.createElement('div');
      content.textContent = safe(msg.content);
      d.appendChild(content);
      if (role === 'assistant' && safe(msg.run_hint)) {
        const hint = document.createElement('div');
        hint.className = 'assistant-runtime-hint';
        hint.textContent = safe(msg.run_hint);
        d.appendChild(hint);
      }
      if (role === 'assistant' && codexFailureHasValue(msg.codex_failure)) {
        const failureHost = document.createElement('div');
        renderCodexFailureCard(failureHost, msg.codex_failure, {
          title: '本轮失败原因',
          compact: true,
          context: {
            sessionId: safe(session.session_id),
          },
        });
        d.appendChild(failureHost);
      }
      if (role === 'assistant' && safe(msg.task_id)) {
        const taskId = safe(msg.task_id);
        const actions = document.createElement('div');
        actions.className = 'trace-actions';
        const btn = document.createElement('button');
        btn.className = 'alt trace-toggle';
        btn.type = 'button';
        btn.setAttribute('data-task-id', taskId);
        const expanded = !!state.taskTraceExpanded[taskId];
        btn.textContent = expanded ? '隐藏调用链路' : '查看调用链路';
        actions.appendChild(btn);
        d.appendChild(actions);
        if (expanded) {
          const panel = document.createElement('div');
          panel.className = 'trace-panel';
          renderTaskTracePanel(panel, safe(session.session_id), taskId);
          d.appendChild(panel);
        }
      }
      if (messageMeta) {
        d.appendChild(messageMeta);
      }
      feed.appendChild(d);
    }
    const runtime = state.runningTasks[safe(session.session_id)];
    if (runtime) {
      const run = findTaskRun(safe(session.session_id), safe(runtime.task_id));
      const startedAt = safe((run && run.start_at) || runtime.started_at);
      const startedMs = startedAt ? new Date(startedAt).getTime() : NaN;
      const elapsedMs = Number.isFinite(startedMs) ? Math.max(0, Date.now() - startedMs) : 0;
      const status = safe((run && run.status) || runtime.status || 'running');
      const tip = document.createElement('div');
      tip.className = 'bubble system';
      tip.textContent =
        '正在运行中 · task=' +
        safe(runtime.task_id) +
        ' · 状态=' +
        statusText(status) +
        ' · started_at=' +
        formatDateTime(startedAt) +
        ' · elapsed=' +
        formatElapsedMs(elapsedMs) +
        '。可点击“中断当前会话”。';
      feed.appendChild(tip);
    }
    if (sessionChanged || wasNearBottom) {
      feed.scrollTop = feed.scrollHeight;
    } else {
      const maxTop = Math.max(0, feed.scrollHeight - feed.clientHeight);
      feed.scrollTop = Math.max(0, Math.min(maxTop, previousScrollTop));
    }
    applyGateState();
  }

  function appendSessionMessage(sessionId, role, content, extra) {
    const session = ensureSessionEntry({ session_id: sessionId });
    if (!session) return -1;
    if (!Array.isArray(session.messages)) session.messages = [];
    const row = {
      role: role,
      content: safe(content),
      created_at: new Date().toISOString(),
      task_id: '',
    };
    if (extra && typeof extra === 'object') {
      Object.assign(row, extra);
    }
    session.messages.push(row);
    moveSessionToTop(sessionId);
    renderSessionList();
    if (state.selectedSessionId === sessionId) {
      scheduleFeedRender();
    }
    return session.messages.length - 1;
  }

  function patchSessionMessage(sessionId, index, patch) {
    const sid = safe(sessionId);
    const session = state.sessionsById[sid];
    if (!session || !Array.isArray(session.messages)) return;
    if (index < 0 || index >= session.messages.length) return;
    const row = session.messages[index];
    if (!row || safe(row.role) !== 'assistant') return;
    Object.assign(row, patch || {});
    if (state.selectedSessionId === sid) {
      scheduleFeedRender();
    }
  }

  function appendPendingChunk(sessionId, pendingIndex, chunk) {
    const session = state.sessionsById[sessionId];
    if (!session || !Array.isArray(session.messages)) return;
    if (pendingIndex < 0 || pendingIndex >= session.messages.length) return;
    const row = session.messages[pendingIndex];
    if (safe(row.role) !== 'assistant') return;
    if (row.pending_placeholder) {
      row.content = '';
    }
    row.pending_placeholder = false;
    row.run_state = 'generating';
    row.run_hint = '';
    row.content = safe(row.content) + safe(chunk);
    if (state.selectedSessionId === sessionId) {
      scheduleFeedRender();
    }
  }

  function scheduleFeedRender() {
    if (state.feedRenderRaf) return;
    state.feedRenderRaf = window.requestAnimationFrame(() => {
      state.feedRenderRaf = 0;
      renderFeed();
    });
  }

  function taskRunIsActiveStatus(status) {
    const text = safe(status).trim().toLowerCase();
    return text === 'pending' || text === 'queued' || text === 'running';
  }

  function latestSessionTaskRun(sessionId) {
    const sid = safe(sessionId).trim();
    const runs = Array.isArray(state.sessionTaskRuns[sid]) ? state.sessionTaskRuns[sid] : [];
    if (!runs.length) return null;
    return runs[runs.length - 1] || null;
  }

  function sessionMessageIndexByTaskId(sessionId, taskId) {
    const sid = safe(sessionId).trim();
    const taskKey = safe(taskId).trim();
    const session = state.sessionsById[sid];
    if (!session || !Array.isArray(session.messages) || !taskKey) return -1;
    return session.messages.findIndex((row) => safe(row && row.task_id).trim() === taskKey);
  }

  function nonPlaceholderAssistantContent(row) {
    const item = row && typeof row === 'object' ? row : null;
    if (!item) return '';
    if (item.pending_placeholder) return '';
    return safe(item.content).trim();
  }

  function recoveredTaskPlaceholderText(status) {
    return taskRunIsActiveStatus(status) && safe(status).trim().toLowerCase() === 'running'
      ? '正在恢复本轮执行输出...'
      : '任务已恢复，等待继续执行...';
  }

  function ensureRecoveredTaskMessage(sessionId, taskRun) {
    const sid = safe(sessionId).trim();
    const item = taskRun && typeof taskRun === 'object' ? taskRun : {};
    const taskId = safe(item.task_id).trim();
    if (!sid || !taskId) return null;
    const phase = normalizeRuntimePhase(item.status);
    const active = taskRunIsActiveStatus(item.status);
    const summary = safe(item.summary).trim();
    const codexFailure = normalizeCodexFailure(item.codex_failure);
    const fallbackContent = active
      ? recoveredTaskPlaceholderText(item.status)
      : phase === 'done'
        ? '（已完成，但未返回文本内容）'
        : '执行结束：' + statusText(item.status) + (summary ? ' ' + summary : '');
    const fallbackHint = active
      ? '检测到页面重连，正在恢复本轮执行...'
      : phase === 'done'
        ? ''
        : codexFailure
          ? ''
          : '执行未完成，可点击“重试上一轮”再次尝试。';
    let pendingIndex = sessionMessageIndexByTaskId(sid, taskId);
    if (pendingIndex < 0) {
      pendingIndex = appendSessionMessage(sid, 'assistant', fallbackContent, {
        task_id: taskId,
        run_state: phase,
        pending_placeholder: !!active,
        run_hint: fallbackHint,
        codex_failure: codexFailure,
      });
    } else {
      const session = state.sessionsById[sid];
      const current =
        session &&
        Array.isArray(session.messages) &&
        pendingIndex >= 0 &&
        pendingIndex < session.messages.length
          ? session.messages[pendingIndex]
          : null;
      patchSessionMessage(sid, pendingIndex, {
        task_id: taskId,
        run_state: phase,
        pending_placeholder: !!active,
        run_hint: fallbackHint,
        codex_failure: codexFailure,
        content: nonPlaceholderAssistantContent(current) || fallbackContent,
      });
    }
    return {
      pending_index: pendingIndex,
      active: !!active,
      task_id: taskId,
      started_at: safe(item.start_at || item.created_at),
      status: safe(item.status || 'pending'),
      agent_name: safe(item.agent_name),
    };
  }

  function recoverSessionTaskRuntime(sessionId) {
    const sid = safe(sessionId).trim();
    if (!sid) return null;
    const latestRun = latestSessionTaskRun(sid);
    if (!latestRun || !safe(latestRun.task_id).trim()) {
      delete state.runningTasks[sid];
      return null;
    }
    const recovered = ensureRecoveredTaskMessage(sid, latestRun);
    if (!recovered) {
      delete state.runningTasks[sid];
      return null;
    }
    if (!recovered.active) {
      delete state.runningTasks[sid];
      return recovered;
    }
    state.runningTasks[sid] = {
      task_id: recovered.task_id,
      since_id: 0,
      pending_index: recovered.pending_index,
      started_at: recovered.started_at,
      status: recovered.status,
      agent_name: recovered.agent_name,
    };
    return recovered;
  }

  function renderAgentSelectOptions(manual) {
    const sel = $('agentSelect');
    const currentSelection = manual ? selectedAgent() : '';
    const visible = visibleAgents();
    sel.innerHTML = '';

    if (!visible.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = state.agents.length
        ? '(当前已隐藏测试/系统 agent，可勾选“显示测试/系统 agent”)'
        : '(无可用 agent)';
      sel.appendChild(opt);
      sel.value = '';
      localStorage.removeItem(agentCacheKey);
      setAgentDropdownOpen(false);
      const reason = state.agents.length
        ? '当前列表仅剩测试/系统 agent，默认已隐藏'
        : '无可用 agent，禁止创建会话';
      setSessionPolicyGateState('idle_unselected', reason, '');
      renderAgentStatusList([]);
      updateClearPolicyCacheButton();
      return;
    }

    const first = document.createElement('option');
    first.value = '';
    first.textContent = '请选择agent';
    sel.appendChild(first);

    for (const item of visible) {
      const opt = document.createElement('option');
      const name = safe(item.agent_name);
      const status = agentStatusInfo(item);
      opt.value = name;
      opt.textContent = name + ' · ' + safe(status.text);
      sel.appendChild(opt);
    }

    const names = visible.map((it) => safe(it.agent_name));
    if (manual && currentSelection && names.includes(currentSelection)) {
      sel.value = currentSelection;
    } else {
      sel.value = '';
      localStorage.removeItem(agentCacheKey);
      setAgentDropdownOpen(false);
    }
    renderAgentStatusList(visible);
    updateClearPolicyCacheButton();
  }

  async function refreshAgents(manual, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const autoAnalyze = opts.autoAnalyze !== false;
    const forceRefresh = !!opts.forceRefresh;
    let agentsPath = safe(opts.agentsPath).trim() || '/api/agents';
    if (forceRefresh) {
      agentsPath += (agentsPath.includes('?') ? '&' : '?') + 'force_refresh=1';
    }
    const data = await getJSON(agentsPath);
    const rootReadyRaw =
      data.agent_search_root_ready !== undefined
        ? !!data.agent_search_root_ready
        : data.workspace_root_valid !== false;
    state.agentSearchRootReady = !!rootReadyRaw;
    state.agentSearchRootError = safe(data.workspace_root_error || data.agent_search_root_error || '');
    state.agents = state.agentSearchRootReady && Array.isArray(data.agents) ? data.agents : [];
    if (applyShowTestDataPolicyPayload(data)) {
      const currentErr = safe($('settingsErr') ? $('settingsErr').textContent : '').trim();
      if (currentErr.includes('测试数据环境策略读取失败')) {
        setSettingsError('');
      }
    } else {
      setSettingsError('测试数据环境策略读取失败，请点击“刷新状态”重试。');
    }
    state.allowManualPolicyInput = !!data.allow_manual_policy_input;
    state.policyClosureStats = data.policy_closure && typeof data.policy_closure === 'object' ? data.policy_closure : {};
    state.artifactRootPath = safe(data.task_artifact_root || data.artifact_root).trim();
    state.artifactWorkspaceRoot = safe(
      data.task_records_root || data.tasks_root || data.artifact_workspace_root || data.workspace_root,
    ).trim();
    state.artifactTasksRoot = safe(
      data.tasks_root || data.task_records_root || data.artifact_workspace_root || data.workspace_root,
    ).trim();
    state.artifactStructurePath = safe(
      data.tasks_structure_path || data.artifact_root_structure_path,
    ).trim();
    state.artifactRootDefaultPath = safe(data.default_task_artifact_root || data.artifact_root_default).trim();
    state.artifactRootValidationStatus = safe(data.artifact_root_validation_status).trim();
    updateArtifactRootMeta();
    applyDeveloperWorkspaceSettingsPayload(data);
    applyAssignmentExecutionSettingsPayload(data.assignment_execution_settings || {});
    const hasRootField = Object.prototype.hasOwnProperty.call(data || {}, 'agent_search_root');
    const nextRoot = hasRootField
      ? safe(data.agent_search_root).trim()
      : safe($('agentSearchRoot').value).trim();
    const rootChanged =
      !!state.currentAgentSearchRoot &&
      !!nextRoot &&
      safe(state.currentAgentSearchRoot).trim() !== nextRoot;
    const needResetAnalysisCache = !state.agentPolicyAnalysisInitialized || rootChanged;
    if (needResetAnalysisCache) {
      state.agentPolicyProgressByName = {};
    }
    for (const item of state.agents || []) {
      const name = safe(item && item.agent_name).trim();
      if (!name) continue;
      const chain =
        item && item.analysis_chain && typeof item.analysis_chain === 'object'
          ? item.analysis_chain
          : {};
      const snapshot =
        chain.ui_progress && typeof chain.ui_progress === 'object' ? chain.ui_progress : null;
      if (snapshot) {
        setAgentPolicyProgressSnapshot(name, snapshot);
      }
    }
    syncAgentPolicyAnalysisCache({ resetAll: needResetAnalysisCache });
    state.agentPolicyAnalysisInitialized = true;
    state.currentAgentSearchRoot = nextRoot;
    if (!state.agentSearchRootReady) {
      const reason = safe(data.workspace_root_error || data.agent_search_root_error || 'agent_search_root_not_set');
      setSettingsError(
        '当前功能已锁定，请先设置有效的 agent路径（需包含 workflow/ 子目录）' +
          (reason ? ' · ' + reason : ''),
      );
      clearFrontendSessions();
      clearWorkflowPanel();
    } else if (data.workspace_root_valid === false) {
      setSettingsError(
        '当前根路径不符合“工作区根路径”语义（需包含 workflow/ 子目录）：' +
          safe(data.agent_search_root || '') +
          (safe(data.workspace_root_error) ? ' · ' + safe(data.workspace_root_error) : ''),
      );
    } else if (!safe($('settingsErr').textContent).trim()) {
      setSettingsError('');
    }
    const manualCheck = $('allowManualPolicyInputCheck');
    if (manualCheck) manualCheck.checked = state.allowManualPolicyInput;
    updateManualPolicyInputMeta();
    if (hasRootField) {
      $('agentSearchRoot').value = safe(data.agent_search_root);
    }
    renderAgentSelectOptions(manual);
    if (typeof renderAssignmentCenter === 'function') {
      renderAssignmentCenter();
    }
    refreshAnalystOptions(selectedAnalyst());
    if (!state.agentSearchRootReady) {
      setSessionPolicyGateState('idle_unselected', 'agent路径未设置，请先在设置页配置。', '');
      updateAgentMeta();
      applyGateState();
    } else if (visibleAgents().length > 0) {
      if (autoAnalyze) {
        startPolicyAnalysisForSelection();
      } else {
        updateAgentMeta();
        applyGateState();
      }
    } else {
      updateAgentMeta();
      applyGateState();
    }
    updateBatchActionState();
  }

  async function refreshDashboard() {
    try {
      const d = await getJSON('/api/dashboard');
      applyShowTestDataPolicyPayload(d);
      state.dashboardMetrics = d && typeof d === 'object' ? d : {};
      state.dashboardError = '';
      renderGlobalRuntimeMetricLine();
    } catch (err) {
      state.dashboardError = safe(err && err.message ? err.message : err);
      renderGlobalRuntimeMetricLine();
    }
  }

  async function refreshSessions(options) {
    const opts = options && typeof options === 'object' ? options : {};
    const preferredSessionId = safe(opts.preferredSessionId).trim();
    const skipInitialMessages = !!opts.skipInitialMessages;
    const data = await getJSON('/api/chat/sessions');
    const rows = Array.isArray(data.sessions) ? data.sessions : [];
    const oldSelected = state.selectedSessionId;
    const nextById = {};
    const visibleSet = new Set();
    for (const row of rows) {
      const sid = safe(row && row.session_id).trim();
      if (!sid) continue;
      visibleSet.add(sid);
      const current = state.sessionsById[sid] || { session_id: sid, messages: [] };
      nextById[sid] = Object.assign({}, current, row || {});
      if (!Array.isArray(nextById[sid].messages)) {
        nextById[sid].messages = [];
      }
    }
    state.sessionsById = nextById;
    state.sessionOrder = rows
      .map((row) => safe(row.session_id).trim())
      .filter((sid) => !!sid && visibleSet.has(sid));
    for (const sid of Object.keys(state.runningTasks)) {
      if (!visibleSet.has(sid)) {
        delete state.runningTasks[sid];
      }
    }
    for (const sid of Object.keys(state.sessionTaskRuns)) {
      if (!visibleSet.has(sid)) {
        delete state.sessionTaskRuns[sid];
      }
    }
    if (preferredSessionId && visibleSet.has(preferredSessionId) && state.sessionsById[preferredSessionId]) {
      state.selectedSessionId = preferredSessionId;
    } else if (oldSelected && visibleSet.has(oldSelected) && state.sessionsById[oldSelected]) {
      state.selectedSessionId = oldSelected;
    } else if (state.sessionOrder.length) {
      state.selectedSessionId = state.sessionOrder[0];
    } else {
      state.selectedSessionId = '';
      localStorage.removeItem(sessionCacheKey);
    }
    if (state.selectedSessionId) {
      const selectedSession = state.sessionsById[state.selectedSessionId] || null;
      trySelectAgentFromSessionIfMissing(selectedSession);
    }
    renderSessionList();
    if (state.selectedSessionId && !skipInitialMessages) {
      await loadSessionMessages(state.selectedSessionId);
    } else {
      renderFeed();
    }
  }

  async function loadSessionMessages(sessionId) {
    const encoded = encodeURIComponent(sessionId);
    const [data, taskData] = await Promise.all([
      getJSON('/api/chat/sessions/' + encoded + '/messages'),
      getJSON('/api/chat/sessions/' + encoded + '/task-runs?limit=300'),
    ]);
    const session = ensureSessionEntry({ session_id: sessionId });
    if (!session) return;
    session.messages = Array.isArray(data.messages)
      ? data.messages.map((it) => ({
          role: safe(it.role),
          content: safe(it.content),
          created_at: safe(it.created_at),
          analysis_state: safe(it.analysis_state || ''),
          analysis_reason: safe(it.analysis_reason || ''),
          analysis_run_id: safe(it.analysis_run_id || ''),
          analysis_updated_at: safe(it.analysis_updated_at || ''),
          task_id: '',
        }))
      : [];
    state.sessionTaskRuns[sessionId] = Array.isArray(taskData.items)
      ? taskData.items.map((row) => normalizeTaskRunRow(row))
      : [];
    linkSessionMessagesToTasks(sessionId);
    const recoveredTask = recoverSessionTaskRuntime(sessionId);
    renderSessionList();
    renderFeed();
    if (recoveredTask && recoveredTask.active) {
      startTaskPolling();
    } else {
      stopTaskPollingIfIdle();
    }
  }

  async function selectSession(sessionId) {
    const session = state.sessionsById[sessionId];
    if (!session) return;
    state.selectedSessionId = sessionId;
    localStorage.setItem(sessionCacheKey, sessionId);
    trySelectAgentFromSessionIfMissing(session);
    renderSessionList();
    await loadSessionMessages(sessionId);
  }

  async function createSession() {
    if (!state.agentSearchRootReady) {
      throw new Error('agent路径未设置或无效，请先在设置页配置。');
    }
    const agent = selectedAgent();
    if (!agent) throw new Error('请先选择 agent');
    const gate = safe(state.sessionPolicyGateState);
    if (!['policy_ready', 'policy_confirmed'].includes(gate)) {
      throw new Error(safe(state.sessionPolicyGateReason) || '当前门禁不允许创建会话');
    }
    const requestPayload = {
      agent_name: agent,
      focus: 'Workflow baseline: web workbench + real-agent gate execution',
      agent_search_root: safe($('agentSearchRoot').value).trim(),
      is_test_data: false,
    };
    let data;
    try {
      data = await postJSON('/api/sessions', requestPayload);
    } catch (err) {
      const code = safe(err && err.code).toLowerCase();
      const payload = (err && err.data) || {};
      if (code === 'agent_policy_confirmation_required') {
        openPolicyConfirmModal(payload.policy_confirmation || payload, requestPayload);
        setStatus('角色与职责待确认，请完成弹窗操作');
        return null;
      }
      if (code === 'agent_policy_extract_failed' || code === 'target_agents_path_out_of_scope') {
        const info = payload.policy_confirmation || payload;
        if (info) {
          openPolicyConfirmModal(info, requestPayload);
          if (code === 'target_agents_path_out_of_scope') {
            setStatus('目标 AGENTS.md 超出当前 root 作用域，请修复根路径后重试');
          } else {
            setStatus('角色与职责提取失败，可手动兜底后创建会话');
          }
          return null;
        }
      }
      if (code === 'agent_policy_clarity_blocked') {
        const info = payload.policy_confirmation || payload;
        if (info && info.manual_fallback_allowed) {
          openPolicyConfirmModal(info, requestPayload);
          setStatus('角色与职责清晰度不足，可手动兜底后创建会话');
          return null;
        }
        const detail = safe((payload.policy_confirmation || {}).clarity_score) || safe(payload.clarity_score) || '-';
        throw new Error('角色与职责清晰度不足（' + detail + '/100），已阻断。请补齐 AGENTS.md 后重试。');
      }
      if (code === 'manual_policy_input_disabled') {
        throw new Error('手动角色与职责兜底已关闭，请联系管理员开启后重试。');
      }
      throw err;
    }
    const session = ensureSessionEntry(data);
    if (!session) throw new Error('创建会话失败');
    state.selectedSessionId = safe(session.session_id);
    moveSessionToTop(state.selectedSessionId);
    localStorage.setItem(sessionCacheKey, state.selectedSessionId);
    localStorage.setItem(agentCacheKey, safe(session.agent_name));
    appendSessionMessage(
      state.selectedSessionId,
      'system',
      '[会话初始化] agent=' +
        safe(session.agent_name) +
        ' hash=' +
        short(session.agents_hash, 12),
    );
    await loadSessionMessages(state.selectedSessionId);
    renderSessionList();
    setSessionPolicyGateState('policy_ready', '角色与职责分析完成，可创建会话。', state.sessionPolicyCacheLine);
    updateAgentMeta();
    applyGateState();
    return session;
  }

  async function reopenClosedSession(sessionId) {
    const sid = safe(sessionId).trim();
    if (!sid) throw new Error('会话无效');
    const data = await postJSON(
      '/api/chat/sessions/' + encodeURIComponent(sid) + '/reopen',
      {},
    );
    ensureSessionEntry(data);
    state.selectedSessionId = sid;
    localStorage.setItem(sessionCacheKey, sid);
    await loadSessionMessages(sid);
    renderSessionList();
    setStatus('已恢复会话: ' + sid);
    return state.sessionsById[sid] || data;
  }

  async function ensureSessionReady() {
    if (state.selectedSessionId && state.sessionsById[state.selectedSessionId]) {
      return state.sessionsById[state.selectedSessionId];
    }
    return createSession();
  }

  function startTaskPolling() {
    if (state.poller) return;
    state.poller = window.setInterval(() => {
      pollRunningTasks().catch((err) => setChatError(err.message || String(err)));
    }, 450);
  }

  function stopTaskPollingIfIdle() {
    if (Object.keys(state.runningTasks).length) return;
    if (state.poller) {
      clearInterval(state.poller);
      state.poller = 0;
    }
    applyGateState();
  }

  async function pollRunningTasks() {
    const entries = Object.entries(state.runningTasks);
    for (const [sessionId, meta] of entries) {
      const taskId = safe(meta.task_id);
      if (!taskId) continue;
      let finished = false;
      const ev = await getJSON(
        '/api/tasks/' + encodeURIComponent(taskId) + '/events?since_id=' + String(meta.since_id || 0),
      );
      const events = Array.isArray(ev.events) ? ev.events : [];
      for (const event of events) {
        meta.since_id = Number(event.event_id || meta.since_id || 0);
        const type = safe(event.event_type);
        const payload = event.payload || {};
        if (type === 'stdout_chunk' || type === 'stderr_chunk') {
          appendPendingChunk(sessionId, meta.pending_index, safe(payload.chunk));
        } else if (type === 'error') {
          patchSessionMessage(sessionId, meta.pending_index, {
            run_state: 'failed',
            pending_placeholder: false,
            run_hint: '',
            content: safe(payload.error || '执行异常'),
          });
        } else if (type === 'done') {
          finished = true;
          const st = safe(payload.status || 'failed');
          const phase = normalizeRuntimePhase(st);
          const failure = normalizeCodexFailure(payload.codex_failure);
          const current = state.sessionsById[sessionId];
          const msgRow =
            current &&
            Array.isArray(current.messages) &&
            meta.pending_index >= 0 &&
            meta.pending_index < current.messages.length
              ? current.messages[meta.pending_index]
              : null;
          const existing = nonPlaceholderAssistantContent(msgRow);
          patchSessionMessage(sessionId, meta.pending_index, {
            run_state: phase,
            pending_placeholder: false,
            run_hint: phase === 'done' || failure ? '' : '执行未完成，可点击“重试上一轮”再次尝试。',
            codex_failure: failure,
            content:
              existing ||
              (phase === 'done'
                ? '（已完成，但未返回文本内容）'
                : '执行结束：' + statusText(st) + '。'),
          });
          upsertSessionTaskRun(sessionId, {
            task_id: taskId,
            session_id: sessionId,
            status: st,
            summary: safe(payload.summary || ''),
            duration_ms: Number(payload.duration_ms || 0),
            trace_available: true,
            codex_failure: failure,
          });
        }
      }
      if (!finished) {
        const row = await getJSON('/api/tasks/' + encodeURIComponent(taskId));
        upsertSessionTaskRun(sessionId, row);
        meta.status = safe(row.status || meta.status || 'running');
        const rowStatus = safe(row.status).toLowerCase();
        if (rowStatus === 'running') {
          patchSessionMessage(sessionId, meta.pending_index, { run_state: 'generating' });
        } else if (rowStatus === 'pending' || rowStatus === 'queued') {
          patchSessionMessage(sessionId, meta.pending_index, { run_state: 'sent' });
        }
        if (safe(row.start_at)) {
          meta.started_at = safe(row.start_at);
        } else if (!safe(meta.started_at) && safe(row.created_at)) {
          meta.started_at = safe(row.created_at);
        }
        const status = rowStatus;
        if (status === 'success' || status === 'failed' || status === 'interrupted') {
          finished = true;
          const phase = normalizeRuntimePhase(status);
          const failure = normalizeCodexFailure(row.codex_failure);
          const current = state.sessionsById[sessionId];
          const msgRow =
            current &&
            Array.isArray(current.messages) &&
            meta.pending_index >= 0 &&
            meta.pending_index < current.messages.length
              ? current.messages[meta.pending_index]
              : null;
          const existing = nonPlaceholderAssistantContent(msgRow);
          patchSessionMessage(sessionId, meta.pending_index, {
            run_state: phase,
            pending_placeholder: false,
            run_hint: phase === 'done' || failure ? '' : '执行未完成，可点击“重试上一轮”再次尝试。',
            codex_failure: failure,
            content:
              existing ||
              (phase === 'done'
                ? '（已完成，但未返回文本内容）'
                : '执行结束：' + statusText(status) + ' ' + safe(row.summary || '')),
          });
        }
      }
      if (state.taskTraceExpanded[taskId] && (events.length > 0 || finished)) {
        ensureTaskTrace(taskId, true).catch(() => {});
      }
      if (finished) {
        delete state.runningTasks[sessionId];
        renderSessionList();
        await refreshDashboard();
      }
    }
    applyGateState();
    stopTaskPollingIfIdle();
  }

  async function runTask(retry) {
    setChatError('');
    if (!state.agentSearchRootReady) {
      throw new Error('agent路径未设置或无效，请先在设置页配置。');
    }
    let session = await ensureSessionReady();
    if (!session) return;
    const sessionId = safe(session.session_id);
    if (!sessionId) throw new Error('会话无效');
    if (safe(session.status).toLowerCase() === 'closed') {
      session = await reopenClosedSession(sessionId);
    }
    const sessionPolicyInfo = resolveSessionPolicyGateInfo(session);
    if (!sessionPolicyInfo.analysis_completed) {
      throw new Error(
        safe(sessionPolicyInfo.reason).trim() || '当前会话 agent 角色分析未完成，禁止发送新对话内容。',
      );
    }
    if (state.runningTasks[sessionId]) {
      throw new Error('当前会话已有运行中的任务');
    }
    let message = safe($('msg').value).trim();
    if (!retry && !message) return;
    if (!retry) {
      appendSessionMessage(sessionId, 'user', message);
      $('msg').value = '';
    } else {
      appendSessionMessage(sessionId, 'system', '[重试上一轮请求]');
      message = '';
    }
    const pendingIndex = appendSessionMessage(sessionId, 'assistant', '思考中...', {
      task_id: '',
      run_state: 'sent',
      pending_placeholder: true,
      run_hint: '',
    });
    const payload = {
      agent_name: safe(session.agent_name || selectedAgent()),
      session_id: sessionId,
      focus: 'Workflow baseline: web workbench + real-agent gate execution',
      retry: !!retry,
      message: message,
      agent_search_root: safe($('agentSearchRoot').value).trim(),
      is_test_data: !!session.is_test_data,
    };
    let data;
    try {
      data = await postJSON('/api/tasks/execute', payload);
    } catch (err) {
      const rawFailure = err && err.data && typeof err.data.codex_failure === 'object'
        ? err.data.codex_failure
        : {
          feature_key: 'session_task_execution',
          attempt_id: '',
          attempt_count: 1,
          failure_code: 'execution_exception',
          failure_detail_code: safe(err && err.code).trim().toLowerCase() || 'execution_failed',
          failure_stage: 'retry_dispatch',
          failure_message: '请求失败：' + safe(err.message || String(err)),
          retryable: true,
          retry_action: {
            kind: 'retry_session_round',
            label: '重试上一轮',
            retryable: true,
            blocked_reason: '',
            payload: { session_id: sessionId },
          },
          trace_refs: [],
          failed_at: new Date().toISOString(),
        };
      patchSessionMessage(sessionId, pendingIndex, {
        run_state: 'failed',
        pending_placeholder: false,
        run_hint: '',
        codex_failure: rawFailure,
        content: '请求失败：' + safe(err.message || String(err)),
      });
      throw err;
    }
    const pendingSession = state.sessionsById[sessionId];
    if (
      pendingSession &&
      Array.isArray(pendingSession.messages) &&
      pendingIndex >= 0 &&
      pendingIndex < pendingSession.messages.length
    ) {
      pendingSession.messages[pendingIndex].task_id = safe(data.task_id);
      pendingSession.messages[pendingIndex].run_state = 'sent';
    }
    upsertSessionTaskRun(sessionId, {
      task_id: safe(data.task_id),
      session_id: sessionId,
      status: 'pending',
      summary: '',
      created_at: new Date().toISOString(),
      duration_ms: 0,
      command: Array.isArray(data.command) ? data.command : [],
      trace_available: false,
    });
    state.runningTasks[sessionId] = {
      task_id: safe(data.task_id),
      since_id: 0,
      pending_index: pendingIndex,
      started_at: new Date().toISOString(),
      status: 'pending',
      agent_name: safe(session.agent_name || selectedAgent()),
    };
    moveSessionToTop(sessionId);
    renderSessionList();
    applyGateState();
    setStatus('任务已启动: ' + safe(data.task_id));
    startTaskPolling();
  }

  async function interruptCurrentTask() {
