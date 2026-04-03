  function runtimePhaseInfo(value) {
    const key = safe(value).toLowerCase();
    const map = {
      sent: { label: '已发送', icon: 'sent', tone: 'running' },
      pending: { label: '已发送', icon: 'sent', tone: 'running' },
      queued: { label: '已发送', icon: 'sent', tone: 'running' },
      running: { label: '正在生成', icon: 'running', tone: 'running', spinning: true },
      generating: { label: '正在生成', icon: 'running', tone: 'running', spinning: true },
      done: { label: '完成', icon: 'success', tone: 'success' },
      success: { label: '完成', icon: 'success', tone: 'success' },
      failed: { label: '失败', icon: 'failed', tone: 'failed' },
      interrupted: { label: '已中断', icon: 'interrupted', tone: 'failed' },
    };
    return map[key] || { label: safe(value) || '未知', icon: 'running', tone: 'running' };
  }

  function normalizeRuntimePhase(value) {
    const key = safe(value).toLowerCase();
    if (key === 'running' || key === 'generating') return 'generating';
    if (key === 'success' || key === 'done') return 'done';
    if (key === 'failed') return 'failed';
    if (key === 'interrupted') return 'interrupted';
    if (key === 'queued' || key === 'pending' || key === 'sent') return 'sent';
    return 'sent';
  }

  function analysisBadgeInfo(value) {
    const done = safe(value) === '已分析';
    return {
      text: done ? '已分析' : '未分析',
      className: done ? 'analysis-badge done' : 'analysis-badge pending',
      icon: done ? 'success' : 'pending',
    };
  }

  function workflowAnalysisBadgeInfo(row) {
    const unanalyzed = Math.max(0, Number((row && row.unanalyzed_message_count) || 0));
    const analyzed = Math.max(0, Number((row && row.analyzed_message_count) || 0));
    if (unanalyzed > 0) {
      return {
        text: '未分析 ' + unanalyzed,
        className: 'analysis-badge pending',
        icon: 'pending',
      };
    }
    if (analyzed > 0) {
      return {
        text: '已分析',
        className: 'analysis-badge done',
        icon: 'success',
      };
    }
    return {
      text: '未分析',
      className: 'analysis-badge pending',
      icon: 'pending',
    };
  }

  function stageText(stage, payload) {
    const key = safe(stage).toLowerCase();
    const step = safe(payload && payload.step).toLowerCase();
    if (key === 'assignment') return '指派分析师';
    if (key === 'analysis' && step === 'collect_context') return '收集上下文';
    if (key === 'analysis' && step === 'summarize') return '生成分析摘要';
    if (key === 'analysis') return '执行分析';
    if (key === 'plan') return '生成计划';
    if (key === 'select') return '选择执行项';
    if (key === 'train') return '执行训练';
    return safe(stage) || '未知阶段';
  }

  function nextStepHint(stage, status) {
    const stageKey = safe(stage).toLowerCase();
    const statusKey = safe(status).toLowerCase();
    if (statusKey === 'failed' || statusKey === 'interrupted') {
      return '当前阶段失败，建议先展开时间线查看失败原因和调试数据，再决定重试。';
    }
    if (statusKey === 'running' || statusKey === 'pending' || statusKey === 'queued') {
      return '当前正在执行中，可展开时间线查看实时进展。';
    }
    if (stageKey === 'assignment') return '下一步通常是执行分析。';
    if (stageKey === 'analysis') return '下一步通常是生成训练计划。';
    if (stageKey === 'plan') return '下一步通常是选择执行项并执行训练。';
    if (stageKey === 'select') return '下一步通常是执行训练。';
    if (stageKey === 'train') return '训练完成后可回看结果并决定是否继续补充样本。';
    return '可展开时间线详情查看完整过程。';
  }

  function eventTone(status) {
    const key = safe(status).toLowerCase();
    if (key === 'success' || key === 'done') return 'success';
    if (key === 'failed' || key === 'interrupted') return 'failed';
    if (key === 'running' || key === 'pending' || key === 'queued') return 'running';
    if (key === 'skipped') return 'skipped';
    return 'running';
  }

  function eventToneInfo(status) {
    const tone = eventTone(status);
    const map = {
      success: { label: '成功', icon: 'success', className: 'tone-success' },
      running: { label: '进行中', icon: 'running', className: 'tone-running', spinning: true },
      failed: { label: '失败', icon: 'failed', className: 'tone-failed' },
      skipped: { label: '跳过', icon: 'skipped', className: 'tone-skipped' },
    };
    return map[tone] || map.running;
  }

  function workflowEventDebugKey(workflowId, eventId) {
    return safe(workflowId) + ':' + safe(eventId || 0);
  }

  function isWorkflowAnalysisSelectable(row) {
    return !!(row && row.analysis_selectable);
  }

  function normalizeTaskRunRow(row) {
    const item = row || {};
    const command = Array.isArray(item.command)
      ? item.command.map((v) => safe(v))
      : [];
    return {
      task_id: safe(item.task_id),
      session_id: safe(item.session_id),
      agent_name: safe(item.agent_name),
      status: safe(item.status),
      summary: safe(item.summary),
      created_at: safe(item.created_at),
      start_at: safe(item.start_at),
      end_at: safe(item.end_at),
      duration_ms: Number(item.duration_ms || 0),
      command: command,
      trace_available: !!item.trace_available,
      codex_failure: normalizeCodexFailure(item.codex_failure),
    };
  }

  function upsertSessionTaskRun(sessionId, row) {
    const sid = safe(sessionId);
    if (!sid) return;
    const item = normalizeTaskRunRow(row);
    const taskId = safe(item.task_id);
    if (!taskId) return;
    if (!Array.isArray(state.sessionTaskRuns[sid])) {
      state.sessionTaskRuns[sid] = [];
    }
    const list = state.sessionTaskRuns[sid];
    const idx = list.findIndex((it) => safe(it.task_id) === taskId);
    if (idx >= 0) {
      list[idx] = Object.assign({}, list[idx], item);
    } else {
      list.push(item);
    }
    list.sort((a, b) => safe(a.created_at).localeCompare(safe(b.created_at)));
  }

  function linkSessionMessagesToTasks(sessionId) {
    const session = state.sessionsById[sessionId];
    if (!session || !Array.isArray(session.messages)) return;
    const runs = Array.isArray(state.sessionTaskRuns[sessionId]) ? state.sessionTaskRuns[sessionId] : [];
    const successRuns = runs.filter((row) => safe(row.status).toLowerCase() === 'success');
    let runIndex = 0;
    for (const msg of session.messages) {
      if (safe(msg.role) !== 'assistant') continue;
      if (safe(msg.task_id)) continue;
      if (runIndex >= successRuns.length) break;
      msg.task_id = safe(successRuns[runIndex].task_id);
      runIndex += 1;
    }
  }

  function formatJsonLines(value) {
    try {
      return JSON.stringify(value || {}, null, 2);
    } catch (_) {
      return safe(value);
    }
  }

  async function withButtonLock(buttonId, task) {
    const btn = $(buttonId);
    const old = btn ? btn.disabled : false;
    if (btn) btn.disabled = true;
    try {
      return await task();
    } finally {
      if (btn) btn.disabled = old;
    }
  }

  function batchProgressText() {
    const run = state.batchRun || {};
    if (!run.running) {
      return '分析任务空闲';
    }
    return (
      '处理中[' +
      safe(run.action || '-') +
      '] ' +
      safe(run.done || 0) +
      '/' +
      safe(run.total || 0) +
      '，成功=' +
      safe(run.success || 0) +
      '，失败=' +
      safe(run.failed || 0) +
      '，跳过=' +
      safe(run.skipped || 0)
    );
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function isCompactLayout() {
    return window.matchMedia('(max-width:1080px)').matches;
  }

  function readLayoutValue(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      const value = Number(raw);
      if (Number.isFinite(value) && value > 0) {
        return value;
      }
      return fallback;
    } catch (_) {
      return fallback;
    }
  }

  function writeLayoutValue(key, value) {
    try {
      localStorage.setItem(key, String(Math.round(value)));
    } catch (_) {
      // ignore localStorage errors
    }
  }

  function setCssWidth(cssVar, value) {
    document.documentElement.style.setProperty(cssVar, Math.round(value) + 'px');
  }

  function resetCssWidth(cssVar) {
    document.documentElement.style.removeProperty(cssVar);
  }

  function applySavedLayout() {
    if (isCompactLayout()) {
      resetCssWidth('--rail-width');
      resetCssWidth('--chat-left-width');
      resetCssWidth('--train-left-width');
      resetCssWidth('--train-right-width');
      return;
    }
    setCssWidth('--rail-width', clamp(readLayoutValue(layoutKeys.rail, 200), 200, 420));
    setCssWidth('--chat-left-width', clamp(readLayoutValue(layoutKeys.chatLeft, 340), 280, 560));
    setCssWidth('--train-left-width', clamp(readLayoutValue(layoutKeys.trainLeft, 360), 300, 620));
    setCssWidth('--train-right-width', clamp(readLayoutValue(layoutKeys.trainRight, 420), 320, 680));
  }

  function bindSplitter(config) {
    const splitter = $(config.splitterId);
    const container = $(config.containerId);
    if (!splitter || !container) return;

    splitter.ondblclick = () => {
      setCssWidth(config.cssVar, config.defaultValue);
      writeLayoutValue(config.storageKey, config.defaultValue);
    };

    splitter.addEventListener('pointerdown', (event) => {
      if (isCompactLayout()) return;
      event.preventDefault();
      const startX = event.clientX;
      const computed = getComputedStyle(document.documentElement).getPropertyValue(config.cssVar);
      const startValue = Number.parseInt(computed, 10) || config.defaultValue;
      document.body.classList.add('is-resizing');
      splitter.classList.add('is-active');
      splitter.setPointerCapture(event.pointerId);

      function onMove(moveEvent) {
        const dx = moveEvent.clientX - startX;
        const delta = config.direction === 'right' ? -dx : dx;
        const rect = container.getBoundingClientRect();
        let maxAllowed = config.max;
        if (Number.isFinite(config.minOther) && config.minOther > 0) {
          maxAllowed = Math.min(maxAllowed, Math.max(config.min, rect.width - config.minOther - 10));
        }
        const next = clamp(startValue + delta, config.min, maxAllowed);
        setCssWidth(config.cssVar, next);
        writeLayoutValue(config.storageKey, next);
      }

      function onStop() {
        document.body.classList.remove('is-resizing');
        splitter.classList.remove('is-active');
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onStop);
        window.removeEventListener('pointercancel', onStop);
      }

      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onStop);
      window.addEventListener('pointercancel', onStop);
    });
  }

  function initSplitters() {
    applySavedLayout();
    bindSplitter({
      splitterId: 'appSplitter',
      containerId: 'appRoot',
      cssVar: '--rail-width',
      storageKey: layoutKeys.rail,
      defaultValue: 200,
      min: 200,
      max: 420,
      minOther: 760,
      direction: 'left',
    });
    bindSplitter({
      splitterId: 'chatSplitter',
      containerId: 'chatWrap',
      cssVar: '--chat-left-width',
      storageKey: layoutKeys.chatLeft,
      defaultValue: 340,
      min: 280,
      max: 560,
      minOther: 420,
      direction: 'left',
    });
    bindSplitter({
      splitterId: 'trainSplitter',
      containerId: 'trainWrap',
      cssVar: '--train-left-width',
      storageKey: layoutKeys.trainLeft,
      defaultValue: 360,
      min: 300,
      max: 620,
      minOther: 520,
      direction: 'left',
    });
    bindSplitter({
      splitterId: 'trainDetailSplitter',
      containerId: 'trainMain',
      cssVar: '--train-right-width',
      storageKey: layoutKeys.trainRight,
      defaultValue: 420,
      min: 320,
      max: 680,
      minOther: 360,
      direction: 'right',
    });
    window.addEventListener('resize', () => {
      if (!isCompactLayout()) {
        applySavedLayout();
      }
    });
  }

  async function requestJSON(url, options) {
    const resp = await fetch(url, options || {});
    let data = {};
    try {
      data = await resp.json();
    } catch (_) {
      data = {};
    }
    if (!resp.ok || !data.ok) {
      const code = safe(data.code).toLowerCase();
      if (code === 'agent_search_root_not_set') {
        state.agentSearchRootReady = false;
        state.agentSearchRootError = code;
        const input = $('agentSearchRoot');
        if (input && Object.prototype.hasOwnProperty.call(data || {}, 'agent_search_root')) {
          input.value = safe(data.agent_search_root);
        }
        applyGateState();
      }
      const error = new Error(data.error || data.code || ('请求失败: ' + url));
      error.status = resp.status;
      error.code = safe(data.code);
      error.data = data || {};
      throw error;
    }
    return data;
  }

  async function getJSON(url) {
    return requestJSON(url);
  }

  async function postJSON(url, body) {
    return requestJSON(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
  }

  async function deleteJSON(url, body) {
    const options = {
      method: 'DELETE',
    };
    if (body && typeof body === 'object') {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(body);
    }
    return requestJSON(url, options);
  }

  function withTestDataQuery(url) {
    return safe(url);
  }

  function assignmentExecutionRefreshModeText(mode) {
    const key = safe(mode).trim().toLowerCase();
    if (key === 'event_stream') return '事件推送';
    if (key === 'short_poll') return '短轮询';
    return key || '短轮询';
  }

  function cleanupLegacyTestDataCaches() {
    try {
      localStorage.removeItem(showSystemAgentsLegacyCacheKey);
    } catch (_) {
      // ignore storage errors
    }
    try {
      localStorage.removeItem(showTestDataCacheKey);
    } catch (_) {
      // ignore storage errors
    }
  }

  function cleanupLegacyShowSystemAgentsCache() {
    cleanupLegacyTestDataCaches();
  }

  function applyShowTestDataPolicyPayload(payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    if (!Object.prototype.hasOwnProperty.call(data, 'show_test_data')) {
      return false;
    }
    state.showTestData = !!data.show_test_data;
    state.runtimeEnvironment = safe(data.environment).trim().toLowerCase();
    state.showTestDataSource = safe(data.show_test_data_source).trim() || 'environment_policy';
    cleanupLegacyTestDataCaches();
    updateShowTestDataMeta();
    return true;
  }

  function runtimeEnvironmentBadgeInfo() {
    const env = safe(state.runtimeEnvironment).trim().toLowerCase() || 'source';
    const map = {
      prod: { key: 'prod', label: 'PROD' },
      test: { key: 'test', label: 'TEST' },
      dev: { key: 'dev', label: 'DEV' },
      source: { key: 'source', label: 'SOURCE' },
    };
    return map[env] || { key: env, label: env.toUpperCase() };
  }

  function updateRuntimeEnvironmentBadge() {
    const node = $('runtimeEnvBadge');
    if (!node) return;
    const info = runtimeEnvironmentBadgeInfo();
    node.textContent = safe(info.label).trim() || 'SOURCE';
    node.setAttribute('data-env', safe(info.key).trim() || 'source');
    node.setAttribute('title', '当前环境: ' + (safe(info.key).trim() || 'source'));
    node.setAttribute('aria-label', '当前环境 ' + (safe(info.label).trim() || 'SOURCE'));
  }

  function updateShowTestDataMeta() {
    const node = $('showTestDataPolicyMeta');
    updateRuntimeEnvironmentBadge();
    if (!node) return;
    const env = safe(state.runtimeEnvironment).trim() || 'source';
    const visibility = state.showTestData ? '显示测试数据' : '隐藏测试数据';
    const source = safe(state.showTestDataSource).trim() || 'environment_policy';
    node.textContent = '环境=' + env + ' · ' + visibility + ' · 来源=' + source + '（只读）';
  }

  function updateManualPolicyInputMeta() {
    const node = $('allowManualPolicyInputMeta');
    if (!node) return;
    const enabled = !!state.allowManualPolicyInput;
    const stats = state.policyClosureStats && typeof state.policyClosureStats === 'object' ? state.policyClosureStats : {};
    const alertOn = !!stats.manual_fallback_usage_alert;
    const rate = Number(stats.manual_fallback_rate_pct || 0);
    const suffix = alertOn ? '（兜底触发率偏高: ' + String(rate) + '%）' : '';
    node.textContent = (enabled ? '默认开启' : '已关闭') + suffix;
  }

  function updateArtifactRootMeta() {
    const pathInput = $('artifactRootPathInput');
    const pathValue = safe(state.artifactRootPath).trim();
    if (pathInput && document.activeElement !== pathInput) {
      pathInput.value = pathValue;
    }
    const tasksRoot = safe(state.artifactTasksRoot || state.artifactWorkspaceRoot).trim();
    const tasksRootNode = $('artifactWorkspacePath');
    if (tasksRootNode) {
      tasksRootNode.textContent = tasksRoot || '-';
    }
    const structureNode = $('artifactStructurePath');
    if (structureNode) {
      structureNode.textContent = safe(state.artifactStructurePath).trim() || '-';
    }
    const statusNode = $('artifactRootStatusMeta');
    if (statusNode) {
      const status = safe(state.artifactRootValidationStatus).trim().toLowerCase();
      statusNode.textContent = status === 'ok'
        ? '路径校验通过，已按任务聚合到 tasks/'
        : (status || '未校验');
    }
  }

  function applyDeveloperWorkspaceSettingsPayload(payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const boundary = data.workspace_boundary && typeof data.workspace_boundary === 'object'
      ? data.workspace_boundary
      : {};
    state.pmWorkspacePath = safe(data.pm_workspace_path || boundary.pm_root).trim();
    state.pmWorkspaceExists = !!(data.pm_workspace_exists !== undefined ? data.pm_workspace_exists : boundary.pm_root_exists);
    state.codeRootPath = safe(data.code_root_path || boundary.code_root).trim();
    state.codeRootReady = !!(data.code_root_ready !== undefined ? data.code_root_ready : boundary.code_root_ready);
    state.codeRootError = safe(data.code_root_error || boundary.code_root_error).trim();
    state.codeRootIsGitRepo = !!(data.code_root_is_git_repo !== undefined ? data.code_root_is_git_repo : boundary.code_root_is_git_repo);
    state.developmentWorkspaceRoot = safe(data.development_workspace_root || boundary.development_workspace_root).trim();
    state.agentRuntimeRoot = safe(data.agent_runtime_root || boundary.agent_runtime_root).trim();
    state.workspaceBoundaryReady = !!(data.workspace_boundary_ready !== undefined ? data.workspace_boundary_ready : boundary.workspace_boundary_ready);
    state.workspaceBoundaryError = safe(
      data.workspace_boundary_error || boundary.code_root_error || boundary.workspace_root_error,
    ).trim();
    state.developerWorkspaceRegistryPath = safe(data.developer_workspace_registry_path).trim();
    state.developerWorkspaceCount = Math.max(0, Number(data.developer_workspace_count || 0));
    state.developerWorkspaces = Array.isArray(data.developer_workspaces) ? data.developer_workspaces : [];
    updateDeveloperWorkspaceMeta();
    return {
      pm_workspace_path: state.pmWorkspacePath,
      code_root_path: state.codeRootPath,
      development_workspace_root: state.developmentWorkspaceRoot,
      code_root_ready: state.codeRootReady,
      workspace_boundary_ready: state.workspaceBoundaryReady,
    };
  }

  function updateDeveloperWorkspaceMeta() {
    const pmNode = $('pmWorkspacePath');
    if (pmNode) pmNode.textContent = safe(state.pmWorkspacePath).trim() || '-';
    const codeNode = $('codeRootPath');
    if (codeNode) codeNode.textContent = safe(state.codeRootPath).trim() || '-';
    const devNode = $('developmentWorkspaceRootPath');
    if (devNode) devNode.textContent = safe(state.developmentWorkspaceRoot).trim() || '-';
    const statusNode = $('developerWorkspaceStatusMeta');
    if (statusNode) {
      const ready = !!state.codeRootReady && !!state.workspaceBoundaryReady;
      const countText = '已记录开发工作区 ' + String(Math.max(0, Number(state.developerWorkspaceCount || 0))) + ' 个';
      const registry = safe(state.developerWorkspaceRegistryPath).trim();
      const registryText = registry ? ' · 留痕=' + registry : '';
      const errorText = safe(state.codeRootError || state.workspaceBoundaryError).trim();
      statusNode.textContent = ready
        ? ('双仓边界已固定 · ' + countText + registryText)
        : ('代码根仓未就绪：' + (errorText || '未配置') + ' · ' + countText + registryText);
    }
  }

  function applyAssignmentExecutionSettingsPayload(payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    state.assignmentExecutionSettings = {
      execution_provider: safe(data.execution_provider).trim().toLowerCase() || 'codex',
      codex_command_path: safe(data.codex_command_path).trim(),
      command_template: safe(data.command_template),
      global_concurrency_limit: Math.max(1, Number(data.global_concurrency_limit || 5)),
      updated_at: safe(data.updated_at).trim(),
      poll_mode: safe(data.poll_mode).trim() || 'event_stream',
      poll_interval_ms: Math.max(250, Number(data.poll_interval_ms || 450)),
    };
    updateAssignmentExecutionSettingsMeta();
    return state.assignmentExecutionSettings;
  }

  function assignmentExecutionSettingsPayload() {
    return state.assignmentExecutionSettings && typeof state.assignmentExecutionSettings === 'object'
      ? state.assignmentExecutionSettings
      : {};
  }

  function updateAssignmentExecutionSettingsMeta() {
    const settings = assignmentExecutionSettingsPayload();
    const providerSelect = $('assignmentExecutionProviderSelect');
    const codexPathInput = $('assignmentCodexCommandPathInput');
    const commandTemplateInput = $('assignmentCommandTemplateInput');
    const concurrencyInput = $('assignmentExecutionConcurrencyInput');
    const metaNode = $('assignmentExecutionMeta');
    if (providerSelect && document.activeElement !== providerSelect) {
      providerSelect.value = safe(settings.execution_provider).trim() || 'codex';
    }
    if (codexPathInput && document.activeElement !== codexPathInput) {
      codexPathInput.value = safe(settings.codex_command_path);
    }
    if (commandTemplateInput && document.activeElement !== commandTemplateInput) {
      commandTemplateInput.value = safe(settings.command_template);
    }
    if (concurrencyInput && document.activeElement !== concurrencyInput) {
      concurrencyInput.value = String(Math.max(1, Number(settings.global_concurrency_limit || 5)));
    }
    if (metaNode) {
      const updatedAt = safe(settings.updated_at).trim()
        ? assignmentFormatBeijingTime(settings.updated_at)
        : '-';
      metaNode.textContent =
        '最近更新 ' +
        updatedAt +
        ' · 刷新方式 ' +
        assignmentExecutionRefreshModeText(safe(settings.poll_mode).trim() || 'event_stream') +
        ' · 断线兜底 ' +
        String(Math.max(250, Number(settings.poll_interval_ms || 450))) +
        'ms';
    }
  }

  function normalizePathToken(value) {
    return safe(value).toLowerCase().replace(/\\/g, '/');
  }

  function isSystemOrTestAgent(item) {
    const path = normalizePathToken((item && item.agents_md_path) || '');
    if (!path) return false;
    const rootNode = $('agentSearchRoot');
    const currentRoot = normalizePathToken(rootNode ? rootNode.value : '');
    const rootIsTestRuntime =
      currentRoot.includes('/state/test-runtime/') ||
      currentRoot.includes('/.test/');
    if (rootIsTestRuntime && path.startsWith(currentRoot)) {
      return false;
    }
    return (
      path.includes('/workflow/state/') ||
      path.includes('/workflow/.runtime/') ||
      path.includes('/state/test-runtime/') ||
      path.includes('/test-runtime/') ||
      path.includes('/.test/') ||
      path.includes('/.runtime/')
    );
  }

  function visibleAgents() {
    if (state.showTestData) return [...(state.agents || [])];
    return (state.agents || []).filter((item) => !isSystemOrTestAgent(item));
  }

  function parseStatusText(value) {
    const key = safe(value).trim().toLowerCase();
    const map = {
      ok: '完整',
      incomplete: '不完整',
      failed: '失败',
      pending: '未分析',
      '': '未分析',
    };
    return map[key] || key || '-';
  }

  function parseWarningLabel(value) {
    const key = safe(value).trim();
    const map = {
      agents_md_empty: 'AGENTS.md 为空',
      missing_role_section: '未识别到角色章节',
      missing_goal_section: '未识别到目标章节',
      goal_inferred_from_role_profile: '目标由角色内容推断',
      missing_duty_section: '未识别到职责章节',
      empty_duty_constraints: '职责章节缺少清晰条目',
      missing_required_policy_fields: '关键字段不足',
      constraints_missing: '职责边界缺失',
      constraints_evidence_missing: '职责边界存在无证据条目',
      constraints_conflict: '职责边界存在冲突',
      target_agents_path_out_of_scope: '目标 AGENTS.md 超出当前根路径作用域',
      workspace_root_missing_workflow_subdir: '根路径缺少 workflow/ 子目录',
      codex_output_invalid_json: 'Codex 输出不符合 JSON 契约',
      contract_parse_status_invalid: 'parse_status 不在契约允许值',
      contract_clarity_score_invalid: 'clarity_score 不符合契约',
      contract_clarity_gate_invalid: 'clarity_gate 不符合契约',
    };
    return map[key] || key;
  }

  function clarityGateText(value) {
    const key = safe(value).trim().toLowerCase();
    const map = {
      auto: '自动生效',
      confirm: '需确认',
      block: '阻断',
    };
    return map[key] || key || '-';
  }

  function clarityGateReasonText(value) {
    const key = safe(value).trim().toLowerCase();
    const map = {
      role_goal_duty_complete: '角色/目标/职责完整，允许自动生效',
      extraction_incomplete: '提取不完整，需人工确认',
      extraction_failed: '提取失败，已阻断',
      clarity_score_below_auto_threshold: '清晰度低于自动阈值，需人工确认',
      clarity_score_below_confirm_threshold: '清晰度低于确认阈值，已阻断',
      policy_field_validation_failed: '关键字段校验失败，已阻断',
      policy_section_conflict: '章节内容冲突，需人工确认或阻断',
      parse_failed: '策略提取失败，已阻断',
      parse_incomplete: '策略提取不完整，需人工确认',
      score_below_60: '评分低于 60，已阻断',
      score_60_79: '评分在 60~79，需人工确认',
      score_evidence_insufficient: '评分证据不足，需人工确认',
      constraints_missing: '职责边界缺失，需人工确认',
      constraints_evidence_missing: '职责边界存在无证据条目，需人工确认',
      constraints_conflict: '职责边界冲突，需人工确认',
    };
    return map[key] || safe(value);
  }

  function selectedAgent() {
    return safe($('agentSelect').value).trim();
  }

  function selectedAgentItem() {
    const name = selectedAgent();
    if (!name) return null;
    return state.agents.find((item) => safe(item.agent_name) === name) || null;
  }

  function mergeAgentItemByName(agentName, patch) {
    const name = safe(agentName).trim();
    if (!name || !patch || typeof patch !== 'object') return;
    const idx = state.agents.findIndex((item) => safe(item && item.agent_name).trim() === name);
    if (idx < 0) return;
    state.agents[idx] = Object.assign({}, state.agents[idx], patch);
    const chain =
      patch.analysis_chain && typeof patch.analysis_chain === 'object'
        ? patch.analysis_chain
        : {};
    if (chain.ui_progress && typeof chain.ui_progress === 'object') {
      setAgentPolicyProgressSnapshot(name, chain.ui_progress);
    }
  }

  function normalizeAgentNameKey(value) {
    return safe(value).trim();
  }

  function defaultAgentPolicyAnalysisRecord() {
    return {
      status: 'unanalyzed',
      gate: '',
      reason: '',
      cacheLine: '',
      analyzing: false,
      requires_manual: false,
    };
  }

  function buildPolicyCacheLineFromItem(item) {
    const node = item && typeof item === 'object' ? item : {};
    const cacheStatus = safe(node.policy_cache_status).trim().toLowerCase();
    const cacheReason = cacheReasonText(node.policy_cache_reason);
    const cachedAt = safe(node.policy_cache_cached_at).trim();
    let head = '待分析';
    if (cacheStatus === 'hit' || node.policy_cache_hit) {
      head = '命中';
    } else if (cacheStatus === 'recomputed') {
      head = '已重算';
    } else if (cacheStatus === 'stale') {
      head = '缓存失效';
    } else if (cacheStatus === 'disabled') {
      head = '缓存未启用';
    } else if (cacheStatus === 'pending') {
      head = '待检查';
    }
    return (
      '缓存: ' +
      head +
      (cacheReason ? '（' + cacheReason + '）' : '') +
      (cachedAt ? ' · cached_at=' + cachedAt : '')
    );
  }

  function hasPolicyGateFields(item) {
    const node = item && typeof item === 'object' ? item : {};
    const parseStatus = safe(node.parse_status).trim().toLowerCase();
    const clarityGate = safe(node.clarity_gate).trim().toLowerCase();
    return (
      parseStatus === 'ok' ||
      parseStatus === 'incomplete' ||
      parseStatus === 'failed' ||
      clarityGate === 'auto' ||
      clarityGate === 'confirm' ||
      clarityGate === 'block'
    );
  }

  function parsePolicyCacheReasonCodes(raw) {
    const text = safe(raw).trim().toLowerCase();
    if (!text) return [];
    const parts = text.split(/[,;\s]+/);
    const out = [];
    const seen = new Set();
    for (const part of parts) {
      const code = safe(part).trim().toLowerCase();
      if (!code || seen.has(code)) continue;
      seen.add(code);
      out.push(code);
    }
    return out;
  }

  function isAgentPolicyReanalyzeRequired(cacheStatus, reasonCodes) {
    const status = safe(cacheStatus).trim().toLowerCase();
    const codes = Array.isArray(reasonCodes) ? reasonCodes : [];
    if (status === 'cleared' || status === 'stale') return true;
    if (codes.includes('manual_clear')) return true;
    const forceCodes = new Set([
      'agents_hash_mismatch',
      'cached_before_agents_mtime',
      'cached_at_missing',
      'agents_mtime_missing',
      'cache_payload_invalid_json',
      'cache_payload_incomplete',
      'cache_parse_status_missing',
      'cache_clarity_score_invalid',
      'cache_prompt_version_mismatch',
      'cache_extract_source_mismatch',
      'cache_write_failed',
    ]);
    return codes.some((code) => forceCodes.has(code));
  }

  function buildAgentAnalysisRecordFromItem(item) {
    const node = item && typeof item === 'object' ? item : {};
    const cacheStatus = safe(node.policy_cache_status).trim().toLowerCase();
    const reasonCodes = parsePolicyCacheReasonCodes(node.policy_cache_reason);
    if (cacheStatus === 'cleared' || reasonCodes.includes('manual_clear')) {
      return {
        status: 'unanalyzed',
        gate: '',
        reason: '',
        cacheLine: '',
        analyzing: false,
        requires_manual: true,
      };
    }
    if (isAgentPolicyReanalyzeRequired(cacheStatus, reasonCodes)) {
      const staleByAgents =
        reasonCodes.includes('agents_hash_mismatch') ||
        reasonCodes.includes('cached_before_agents_mtime');
      return {
        status: 'unanalyzed',
        gate: '',
        reason: staleByAgents
          ? '检测到 AGENTS.md 已更新，需重新分析后才能对话。'
          : '角色缓存已过期或无效，需重新分析后才能对话。',
        cacheLine: buildPolicyCacheLineFromItem(node),
        analyzing: false,
        requires_manual: false,
      };
    }
    if (!hasPolicyGateFields(node)) {
      return defaultAgentPolicyAnalysisRecord();
    }
    const derived = derivePolicyGateFromAgent(node);
    return {
      status: 'analyzed',
      gate: safe(derived.gate),
      reason: safe(derived.reason),
      cacheLine: buildPolicyCacheLineFromItem(node),
      analyzing: false,
      requires_manual: false,
    };
  }
