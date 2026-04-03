(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const appTabCacheKey = 'workflow.p0.tab';
  const sessionCacheKey = 'workflow.p0.session';
  const agentCacheKey = 'workflow.p0.agent';
  const trainingCenterModuleCacheKey = 'workflow.p0.trainingCenter.module';
  const roleCreationSessionCacheKey = 'workflow.p0.trainingCenter.roleCreation.session';
  const assignmentCreateDraftCacheKey = 'workflow.p0.assignment.createDraft';
  const requirementBugModuleCacheKey = 'workflow.p0.requirementBug.module';
  // Legacy-only keys. They are cleaned on bootstrap and never drive runtime truth.
  const showTestDataCacheKey = 'workflow.p0.settings.showTestData';
  const showSystemAgentsLegacyCacheKey = 'workflow.p0.settings.showSystemAgents';
  const layoutKeys = {
    rail: 'workflow.p0.layout.rail.v2',
    chatLeft: 'workflow.p0.layout.chatLeft',
    trainLeft: 'workflow.p0.layout.trainLeft',
    trainRight: 'workflow.p0.layout.trainRight',
  };

  const state = {
    agents: [],
    sessionsById: {},
    sessionOrder: [],
    selectedSessionId: '',
    runningTasks: {}, // session_id -> { task_id, since_id, pending_index, started_at, status, agent_name }
    sessionTaskRuns: {}, // session_id -> task runs[]
    taskTraceCache: {}, // task_id -> { loading, data, error }
    taskTraceExpanded: {}, // task_id -> bool
    taskTraceDetailsOpen: {}, // task_id:section -> bool
    feedRenderRaf: 0,
    poller: 0,
    workflows: [],
    selectedWorkflowId: '',
    workflowPlans: {}, // workflow_id -> plan[]
    workflowEvents: {}, // workflow_id -> events[]
    workflowEventDetailOpen: {}, // workflow_id -> bool
    workflowEventDebugOpen: {}, // workflow_id:event_id -> bool
    workflowPoller: 0,
    workflowPollBusy: false,
    showTestData: false,
    runtimeEnvironment: '',
    showTestDataSource: 'environment_policy',
    queueMode: 'records', // records | training
    selectedWorkflowIds: {},
    batchRun: {
      running: false,
      action: '',
      total: 0,
      done: 0,
      success: 0,
      failed: 0,
      skipped: 0,
      results: [],
      started_at: '',
      finished_at: '',
    },
    lastBatchReport: null,
    lastFailedWorkflowIds: [],
    pendingPolicyConfirmation: null,
    agentMetaPanelOpen: false,
    agentMetaDetailsOpen: false,
    agentMetaClarityOpen: false,
    allowManualPolicyInput: true,
    policyClosureStats: {},
    dashboardMetrics: {},
    dashboardError: '',
    sessionPolicyGateState: 'idle_unselected',
    sessionPolicyGateReason: '请先选择角色',
    sessionPolicyCacheLine: '',
    sessionPolicyGateSeq: 0,
    policyAnalyzeProgress: null, // { agent_name, gate_seq, active, failed, started_at_ms, finished_at_ms, total_ms, stages[] }
    agentPolicyProgressByName: {}, // agent_name -> ui_progress snapshot
    policyAnalyzeTicker: 0,
    agentPolicyAnalysisByName: {},
    agentPolicyAnalysisInitialized: false,
    currentAgentSearchRoot: '',
    agentSearchRootReady: false,
    agentSearchRootError: '',
    pmWorkspacePath: '',
    pmWorkspaceExists: false,
    codeRootPath: '',
    codeRootReady: false,
    codeRootError: '',
    codeRootIsGitRepo: false,
    developmentWorkspaceRoot: '',
    agentRuntimeRoot: '',
    workspaceBoundaryReady: false,
    workspaceBoundaryError: '',
    developerWorkspaceRegistryPath: '',
    developerWorkspaceCount: 0,
    developerWorkspaces: [],
    agentDropdownOpen: false,
    agentDropdownPanelWidth: 0,
    policyConfirmGateOpen: false,
    policyConfirmEvidenceOpen: false,
    policyConfirmAnalysisOpen: false,
    policyConfirmRiskOpen: true,
    policyRecommendTraceOpen: false,
    feedRenderedSessionId: '',
    tcModule: 'agents', // agents | create-role | ops
    tcAgents: [],
    tcStats: {
      agent_total: 0,
      git_available_count: 0,
      latest_release_at: '',
      training_queue_pending: 0,
    },
    tcSelectedAgentId: '',
    tcSelectedAgentName: '',
    tcSelectedAgentDetail: null,
    tcSelectedAgentContextLoading: false,
    tcSelectedAgentContextRequestSeq: 0,
    tcReleasesByAgent: {}, // agent_id -> releases[]
    tcNormalCommitsByAgent: {}, // agent_id -> normal_commits[]
    tcReleaseReviewByAgent: {}, // agent_id -> review payload
    tcReleaseReviewProgressByAgent: {}, // agent_id -> local running progress
    tcReleaseReviewErrorByAgent: {}, // agent_id -> local failed message snapshot
    tcReleaseReviewProgressTicker: 0,
    tcVersionDropdownOpen: false,
    tcQueue: [],
    tcLoopMode: 'create', // create | status
    tcLoopSelectedQueueTaskId: '',
    tcLoopSelectedNodeId: '',
    tcLoopCreateTab: 'basic', // basic | workset | launch
    tcLoopStatusTab: 'overview', // overview | workset | eval | history
    tcLoopRightTab: 'tasks', // tasks | baseline
    tcLoopQueueFilter: 'all',
    tcLoopRoundIndexByQueueTaskId: {},
    tcLoopQueryApplied: false,
    tcLoopServerQueueTaskId: '',
    tcLoopServerData: null,
    tcLoopServerLoading: false,
    tcLoopServerError: '',
    tcLoopServerRequestSeq: 0,
    tcRoleCreationSessions: [],
    tcRoleCreationTotal: 0,
    tcRoleCreationSelectedSessionId: '',
    tcRoleCreationDetail: null,
    tcRoleCreationLoading: false,
    tcRoleCreationError: '',
    tcRoleCreationOptimisticMessages: {},
    tcRoleCreationMessagesRenderedSessionId: '',
    tcRoleCreationPoller: 0,
    tcRoleCreationPollBusy: false,
    tcRoleCreationDetailTab: 'evolution',
    tcRoleCreationDraftAttachments: [],
    tcRoleCreationDraftCollapsed: false,
    tcRoleCreationQuery: '',
    tcRoleCreationStatusFilter: 'all',
    tcRoleCreationTaskPreview: {
      kind: '',
      stage_key: '',
      node_id: '',
      pinned: false,
      anchor_rect: null,
    },
    requirementBugModule: 'defect',
    defectList: [],
    defectSelectedReportId: '',
    defectDetail: null,
    defectLoading: false,
    defectDetailLoading: false,
    defectError: '',
    defectSubmitError: '',
    defectQueueSummary: null,
    defectQueueSaving: false,
    defectStatusFilter: 'all',
    defectKeyword: '',
    defectComposerCollapsed: false,
    defectComposerTouched: false,
    defectListTotal: 0,
    defectListLimit: 20,
    defectListNextOffset: 0,
    defectListHasMore: false,
    defectDraftImages: [],
    defectSupplementDraftImages: [],
    defectTaskDraftAction: '',
    defectTaskDraftReportId: '',
    defectTaskDraftBaseName: '',
    defectTaskDraftDefaultBaseName: '',
    defectTaskDraftError: '',
    assignmentGraphs: [],
    assignmentSelectedTicketId: '',
    assignmentGraphData: null,
    assignmentSelectedNodeId: '',
    assignmentScheduler: null,
    artifactRootPath: '',
    artifactWorkspaceRoot: '',
    artifactTasksRoot: '',
    artifactStructurePath: '',
    artifactRootDefaultPath: '',
    artifactRootValidationStatus: '',
    assignmentExecutionSettings: {
      execution_provider: 'codex',
      codex_command_path: '',
      command_template: '',
      global_concurrency_limit: 5,
      updated_at: '',
      poll_mode: 'event_stream',
      poll_interval_ms: 450,
    },
    assignmentExecutionEventSource: null,
    assignmentExecutionEventSourceTicketId: '',
    assignmentExecutionEventSourceConnected: false,
    assignmentExecutionEventSourceSeq: 0,
    assignmentExecutionRealtimeRefreshTimer: 0,
    assignmentExecutionRealtimeRefreshBusy: false,
    assignmentExecutionRealtimeRefreshPending: false,
    assignmentExecutionRealtimeRefreshGraph: false,
    assignmentExecutionRealtimeRefreshDetail: false,
    assignmentExecutionPoller: 0,
    assignmentExecutionPollBusy: false,
    assignmentExecutionPollIntervalMs: 450,
    assignmentActiveLoaded: 0,
    assignmentHistoryLoaded: 0,
    assignmentCreateOpen: false,
    assignmentCreateDraftLoaded: false,
    assignmentCreateForm: {
      node_name: '',
      assigned_agent_id: '',
      priority: 'P1',
      node_goal: '',
      expected_artifact: '',
      delivery_mode: 'none',
      delivery_receiver_agent_id: '',
    },
    assignmentCreateUpstreamSearch: '',
    assignmentCreateSelectedUpstreamIds: [],
    assignmentDetail: null,
    assignmentDetailSectionOpen: {}, // node_id:section -> bool
    assignmentExecutionPanelOpen: {}, // node_id:run_id:panel -> bool
    assignmentExecutionScrollState: {}, // node_id:run_id:panel -> { top, stickBottom }
    assignmentLoading: false,
    assignmentError: '',
    assignmentDetailError: '',
    assignmentDrawerError: '',
    assignmentGraphRequestSeq: 0,
    assignmentDetailRequestSeq: 0,
    schedulePlans: [],
    scheduleSelectedId: '',
    scheduleDetail: null,
    scheduleLoading: false,
    scheduleError: '',
    scheduleView: 'list',
    scheduleCalendar: null,
    scheduleCalendarMonth: '',
    scheduleCalendarSelectedDate: '',
    scheduleCalendarLoading: false,
    scheduleEditorOpen: false,
    scheduleEditorMode: 'create',
    scheduleEditorError: '',
  };

  function safe(value) {
    if (value === null || value === undefined) return '';
    return String(value);
  }

  function normalizeAppTab(value) {
    const key = safe(value).trim().toLowerCase();
    if (
      key === 'chat' ||
      key === 'training' ||
      key === 'training-center' ||
      key === 'task-center' ||
      key === 'schedule-center' ||
      key === 'requirement-bug' ||
      key === 'settings'
    ) {
      return key;
    }
    return 'chat';
  }

  function readSavedAppTab() {
    try {
      return normalizeAppTab(localStorage.getItem(appTabCacheKey));
    } catch (_) {
      return 'chat';
    }
  }

  function writeSavedAppTab(value) {
    try {
      localStorage.setItem(appTabCacheKey, normalizeAppTab(value));
    } catch (_) {
      // ignore localStorage errors
    }
  }

  function normalizeTrainingCenterModule(value) {
    const key = safe(value).trim().toLowerCase();
    if (key === 'ops' || key === 'create-role') {
      return key;
    }
    return 'agents';
  }

  function readSavedTrainingCenterModule() {
    try {
      return normalizeTrainingCenterModule(localStorage.getItem(trainingCenterModuleCacheKey));
    } catch (_) {
      return 'agents';
    }
  }

  function writeSavedTrainingCenterModule(value) {
    try {
      localStorage.setItem(trainingCenterModuleCacheKey, normalizeTrainingCenterModule(value));
    } catch (_) {
      // ignore localStorage errors
    }
  }

  function readSavedRoleCreationSessionId() {
    try {
      return safe(localStorage.getItem(roleCreationSessionCacheKey)).trim();
    } catch (_) {
      return '';
    }
  }

  function normalizeRequirementBugModule(value) {
    return safe(value).trim().toLowerCase() === 'requirement' ? 'requirement' : 'defect';
  }

  function readSavedRequirementBugModule() {
    try {
      return normalizeRequirementBugModule(localStorage.getItem(requirementBugModuleCacheKey));
    } catch (_) {
      return 'defect';
    }
  }

  function writeSavedRequirementBugModule(value) {
    try {
      localStorage.setItem(requirementBugModuleCacheKey, normalizeRequirementBugModule(value));
    } catch (_) {
      // ignore localStorage errors
    }
  }

  function writeSavedRoleCreationSessionId(value) {
    const text = safe(value).trim();
    try {
      if (!text) {
        localStorage.removeItem(roleCreationSessionCacheKey);
        return;
      }
      localStorage.setItem(roleCreationSessionCacheKey, text);
    } catch (_) {
      // ignore localStorage errors
    }
  }

  function short(value, maxLen) {
    const text = safe(value);
    if (text.length <= maxLen) return text;
    return text.slice(0, maxLen) + '...';
  }

  function nowText() {
    return new Date().toLocaleTimeString();
  }

  function queryParam(name) {
    try {
      const url = new URL(window.location.href);
      return safe(url.searchParams.get(name)).trim();
    } catch (_) {
      return '';
    }
  }

  function isLayoutProbeEnabled() {
    return queryParam('layout_probe') === '1';
  }

  function isPolicyProbeEnabled() {
    return queryParam('policy_probe') === '1';
  }

  function isTrainingCenterProbeEnabled() {
    return queryParam('tc_probe') === '1';
  }

  function isAssignmentProbeEnabled() {
    return queryParam('assignment_probe') === '1';
  }

  function isDefectProbeEnabled() {
    return queryParam('defect_probe') === '1';
  }

  function isTestDataToggleProbeEnabled() {
    return queryParam('td_probe') === '1';
  }

  function assignmentProbeCase() {
    return safe(queryParam('assignment_probe_case')).trim().toLowerCase() || 'visible';
  }

  function defectProbeCase() {
    return safe(queryParam('defect_probe_case')).trim().toLowerCase() || 'main';
  }

  function testDataToggleProbeCase() {
    return safe(queryParam('td_probe_case')).trim().toLowerCase() || 'ac_td_01';
  }

  function trainingCenterProbeCase() {
    return safe(queryParam('tc_probe_case')).trim().toLowerCase() || 'ac_uo_01';
  }

  function policyProbeStage() {
    const value = queryParam('policy_probe_stage').toLowerCase();
    if (['initial', 'analyzing', 'ready', 'manual'].includes(value)) return value;
    return 'initial';
  }

  const startupOverlayStages = ['shell', 'connect', 'agents', 'sessions', 'workspace', 'ready'];
  const startupOverlayRevealDelayMs = 1400;
  let startupOverlayState = {
    active: false,
    startedAt: 0,
    stage: 'shell',
    title: '正在准备工作台',
    detail: '正在初始化布局、连接运行时并恢复最近的工作状态。',
    hint: '首次启动通常会更慢，因为需要做环境检查、运行态恢复和数据预热。',
    percent: 0,
    error: '',
    ready: false,
    failed: false,
    hideTimer: 0,
    tickTimer: 0,
    revealTimer: 0,
  };

  function ensureStartupOverlayRefs() {
    const node = $('startupOverlay');
    if (!node) return null;
    if (node._startupOverlayRefs) return node._startupOverlayRefs;
    node._startupOverlayRefs = {
      root: node,
      title: $('startupOverlayTitle'),
      detail: $('startupOverlayDetail'),
      percent: $('startupOverlayPercent'),
      elapsed: $('startupOverlayElapsed'),
      hint: $('startupOverlayHint'),
      error: $('startupOverlayError'),
      stages: Array.from(node.querySelectorAll('[data-stage]')),
    };
    return node._startupOverlayRefs;
  }

  function formatStartupOverlayElapsed(ms) {
    const value = Math.max(0, Number(ms || 0));
    if (value < 1000) return '刚开始';
    const seconds = Math.floor(value / 1000);
    if (seconds < 60) return '已等待 ' + String(seconds) + 's';
    const minutes = Math.floor(seconds / 60);
    const remain = seconds % 60;
    return '已等待 ' + String(minutes) + 'm ' + String(remain) + 's';
  }

  function clearStartupOverlayTimers() {
    if (startupOverlayState.hideTimer) {
      clearTimeout(startupOverlayState.hideTimer);
      startupOverlayState.hideTimer = 0;
    }
    if (startupOverlayState.tickTimer) {
      clearInterval(startupOverlayState.tickTimer);
      startupOverlayState.tickTimer = 0;
    }
    if (startupOverlayState.revealTimer) {
      clearTimeout(startupOverlayState.revealTimer);
      startupOverlayState.revealTimer = 0;
    }
  }

  function clearStartupOverlayRevealTimer() {
    if (!startupOverlayState.revealTimer) return;
    clearTimeout(startupOverlayState.revealTimer);
    startupOverlayState.revealTimer = 0;
  }

  function ensureStartupOverlayTicker() {
    if (startupOverlayState.tickTimer) return;
    startupOverlayState.tickTimer = window.setInterval(() => {
      if (!startupOverlayState.active) {
        clearStartupOverlayTimers();
        return;
      }
      renderStartupOverlay();
    }, 500);
  }

  function scheduleStartupOverlayReveal() {
    if (startupOverlayState.active || startupOverlayState.ready || startupOverlayState.failed) return;
    if (startupOverlayState.revealTimer) return;
    const startedAt = Number(startupOverlayState.startedAt || 0) || Date.now();
    const remainingMs = Math.max(0, startupOverlayRevealDelayMs - (Date.now() - startedAt));
    const reveal = () => {
      startupOverlayState.revealTimer = 0;
      if (startupOverlayState.active || startupOverlayState.ready || startupOverlayState.failed) return;
      startupOverlayState.active = true;
      ensureStartupOverlayTicker();
      renderStartupOverlay();
    };
    if (remainingMs <= 0) {
      reveal();
      return;
    }
    startupOverlayState.revealTimer = window.setTimeout(reveal, remainingMs);
  }

  function renderStartupOverlay() {
    const refs = ensureStartupOverlayRefs();
    if (!refs) return;
    const stateNode = startupOverlayState;
    const elapsedMs = stateNode.startedAt ? Date.now() - stateNode.startedAt : 0;
    const slow = !stateNode.ready && !stateNode.failed && elapsedMs >= 12000;
    const safePercent = Math.max(0, Math.min(100, Number(stateNode.percent || 0)));
    refs.root.classList.toggle('is-hidden', !stateNode.active);
    refs.root.classList.toggle('is-ready', !!stateNode.ready);
    refs.root.classList.toggle('is-error', !!stateNode.failed);
    if (refs.title) refs.title.textContent = safe(stateNode.title);
    if (refs.detail) refs.detail.textContent = safe(stateNode.detail);
    if (refs.percent) refs.percent.textContent = String(Math.round(safePercent)) + '%';
    if (refs.elapsed) refs.elapsed.textContent = formatStartupOverlayElapsed(elapsedMs);
    if (refs.hint) {
      refs.hint.textContent = slow
        ? '当前启动时间偏长，通常是首次部署、数据库回填或会话数据恢复较慢；如果长时间不动，可刷新页面并查看启动窗口。'
        : safe(stateNode.hint);
      refs.hint.classList.toggle('is-slow', slow);
    }
    if (refs.error) {
      refs.error.textContent = safe(stateNode.error);
    }
    const currentIndex = startupOverlayStages.indexOf(safe(stateNode.stage).trim().toLowerCase());
    refs.stages.forEach((node) => {
      const key = safe(node.getAttribute('data-stage')).trim().toLowerCase();
      const index = startupOverlayStages.indexOf(key);
      node.classList.toggle('is-done', index >= 0 && index < currentIndex);
      node.classList.toggle('is-active', index === currentIndex && !stateNode.failed);
      node.classList.toggle('is-error', index === currentIndex && !!stateNode.failed);
    });
  }

  function setStartupProgress(payload) {
    const next = payload && typeof payload === 'object' ? payload : {};
    const stage = safe(next.stage).trim().toLowerCase();
    if (startupOverlayState.hideTimer) {
      clearTimeout(startupOverlayState.hideTimer);
      startupOverlayState.hideTimer = 0;
    }
    startupOverlayState = Object.assign({}, startupOverlayState, next, {
      active: !!startupOverlayState.active,
      startedAt: startupOverlayState.startedAt || Date.now(),
      stage: startupOverlayStages.includes(stage) ? stage : startupOverlayState.stage,
      ready: !!next.ready,
      failed: !!next.failed,
      error: safe(next.error || ''),
    });
    if (startupOverlayState.failed) {
      clearStartupOverlayRevealTimer();
      startupOverlayState.active = true;
      ensureStartupOverlayTicker();
      renderStartupOverlay();
      return;
    }
    if (startupOverlayState.ready) {
      clearStartupOverlayRevealTimer();
      renderStartupOverlay();
      return;
    }
    if (startupOverlayState.active) {
      ensureStartupOverlayTicker();
      renderStartupOverlay();
      return;
    }
    startupOverlayState.active = false;
    renderStartupOverlay();
    scheduleStartupOverlayReveal();
  }

  function finishStartupProgress(detail) {
    const wasVisible = !!startupOverlayState.active;
    setStartupProgress({
      stage: 'ready',
      title: '工作台已准备完成',
      detail: safe(detail).trim() || '基础界面与最近工作状态已恢复完成。',
      percent: 100,
      ready: true,
      failed: false,
      error: '',
      hint: '页面已就绪，后续角色分析和局部模块刷新会在后台继续进行。',
    });
    if (!wasVisible) {
      startupOverlayState.active = false;
      renderStartupOverlay();
      clearStartupOverlayTimers();
      return;
    }
    startupOverlayState.hideTimer = window.setTimeout(() => {
      startupOverlayState.active = false;
      renderStartupOverlay();
      clearStartupOverlayTimers();
    }, 520);
  }

  function failStartupProgress(error) {
    const message = safe(error).trim() || '启动失败，请刷新页面后重试。';
    setStartupProgress({
      failed: true,
      ready: false,
      error: message,
      percent: Math.max(12, Number(startupOverlayState.percent || 0)),
      detail: '页面启动过程中发生错误，工作台暂未准备完成。',
      hint: '可以先刷新页面；如果仍失败，请回看启动窗口里的报错原文。',
    });
  }

  function layoutProbeTab() {
    const value = queryParam('layout_probe_tab').toLowerCase();
    if (
      value === 'training' ||
      value === 'training-center' ||
      value === 'settings' ||
      value === 'chat'
    ) {
      return value;
    }
    return 'chat';
  }

  function setStatus(text) {
    const node = $('statusLine');
    if (!node) return;
    const content = '[' + nowText() + '] ' + text;
    node.textContent = content;
    node.title = content;
    node.setAttribute('aria-label', content);
  }

  function setChatError(text) {
    $('chatErr').textContent = safe(text);
  }

  function setSettingsError(text) {
    $('settingsErr').textContent = safe(text);
  }

  function setWorkflowResult(obj) {
    if (typeof obj === 'string') {
      $('workflowResult').textContent = obj;
      return;
    }
    $('workflowResult').textContent = JSON.stringify(obj || {}, null, 2);
  }

  function statusText(value) {
    const key = safe(value).toLowerCase();
    const map = {
      active: '进行中',
      running: '运行中',
      pending: '排队中',
      queued: '排队中',
      success: '成功',
      failed: '失败',
      interrupted: '已中断',
      closed: '已关闭',
      done: '已完成',
      none: '无',
      skipped: '已跳过',
      training: '训练中',
      assigned: '已指派',
      analyzing: '分析中',
      analyzed: '已分析',
      planned: '已生成任务',
      selected: '已选择执行项',
      train: '入训',
      skip: '跳过',
      need_info: '待补充',
    };
    return map[key] || safe(value);
  }

  function reasonText(value) {
    const key = safe(value).toLowerCase();
    const map = {
      no_training_value: '无训练价值',
      missing_previous_context: '上文缺失',
      missing_next_context: '下文缺失',
      all_messages_analyzed: '会话全部消息已分析',
      no_work_records: '会话无可分析消息',
      conversation_locked_by_training_plan: '会话已生成训练计划，禁止删除聊天记录',
      session_busy: '当前会话有运行中的任务',
    };
    return map[key] || safe(value);
  }

  function createSvgElement(tag, attrs) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    const source = attrs || {};
    for (const key of Object.keys(source)) {
      node.setAttribute(key, safe(source[key]));
    }
    return node;
  }

  function createStatusIcon(kind, options) {
    const icon = safe(kind).toLowerCase();
    const opts = options || {};
    const classNames = ['status-icon'];
    if (opts.spinning) classNames.push('icon-spin');
    if (opts.compact) classNames.push('compact');
    const svg = createSvgElement('svg', {
      viewBox: '0 0 20 20',
      class: classNames.join(' '),
      'aria-hidden': 'true',
      focusable: 'false',
    });
    if (opts.spinning) {
      const cycleMs = Math.max(500, Number(opts.spinCycleMs || 1000) || 1000);
      const clockNow =
        typeof window !== 'undefined' &&
        window.performance &&
        typeof window.performance.now === 'function'
          ? window.performance.now()
          : Date.now();
      const offset = Math.floor(Math.max(0, Number(clockNow) || 0) % cycleMs);
      svg.style.setProperty('--icon-spin-duration', String(cycleMs) + 'ms');
      // Keep spin phase continuous across rerenders to avoid visible "jump back to 0deg".
      svg.style.animationDelay = '-' + String(offset) + 'ms';
    }
    const append = (tag, attrs) => {
      svg.appendChild(createSvgElement(tag, attrs));
    };
    if (icon === 'refresh') {
      append('path', { d: 'M15.4 8.2A5.9 5.9 0 1 0 16 10' });
      append('path', { d: 'M12.8 4.6H16V7.8' });
      return svg;
    }
    if (icon === 'cache') {
      append('ellipse', { cx: '10', cy: '5.5', rx: '5.8', ry: '2.2' });
      append('path', { d: 'M4.2 5.5V14.5C4.2 15.9 6.8 17 10 17C13.2 17 15.8 15.9 15.8 14.5V5.5' });
      append('path', { d: 'M4.2 10C4.2 11.4 6.8 12.5 10 12.5C13.2 12.5 15.8 11.4 15.8 10' });
      return svg;
    }
    if (icon === 'clear_one') {
      append('rect', { x: '5.4', y: '6.5', width: '9.2', height: '8.8', rx: '1.6' });
      append('path', { d: 'M4.2 6.5H15.8' });
      append('path', { d: 'M8 8.5V13.5' });
      append('path', { d: 'M12 10.9H15.9' });
      return svg;
    }
    if (icon === 'clear_all') {
      append('rect', { x: '5.4', y: '6.5', width: '9.2', height: '8.8', rx: '1.6' });
      append('path', { d: 'M4.2 6.5H15.8' });
      append('path', { d: 'M8 8.5V13.5' });
      append('path', { d: 'M12 8.5V13.5' });
      return svg;
    }
    if (icon === 'sent') {
      append('rect', { x: '3', y: '5', width: '14', height: '10', rx: '2' });
      append('path', { d: 'M3.8 6.4L10 11.2L16.2 6.4' });
      return svg;
    }
    if (icon === 'spinner') {
      append('circle', { class: 'icon-ring', cx: '10', cy: '10', r: '7.5' });
      append('path', { d: 'M10 2.5A7.5 7.5 0 0 1 17.5 10' });
      return svg;
    }
    if (icon === 'report') {
      append('rect', { x: '4.5', y: '3.2', width: '11', height: '13.6', rx: '1.6' });
      append('path', { d: 'M7 7.2H13' });
      append('path', { d: 'M7 10H13' });
      append('path', { d: 'M7 12.8H11.2' });
      return svg;
    }
    if (icon === 'flag') {
      append('path', { d: 'M6 3.4V16.6' });
      append('path', { d: 'M6.2 4.2H14.8L12.6 7.3L14.8 10.4H6.2' });
      return svg;
    }
    if (icon === 'pending') {
      append('circle', { cx: '10', cy: '10', r: '7.5' });
      append('circle', { cx: '10', cy: '10', r: '1.5', fill: 'currentColor', stroke: 'none' });
      return svg;
    }
    if (icon === 'success') {
      append('circle', { cx: '10', cy: '10', r: '7.5' });
      append('path', { d: 'M6.3 10.4L8.8 12.9L13.7 8' });
      return svg;
    }
    if (icon === 'failed') {
      append('circle', { cx: '10', cy: '10', r: '7.5' });
      append('path', { d: 'M7 7L13 13' });
      append('path', { d: 'M13 7L7 13' });
      return svg;
    }
    if (icon === 'interrupted') {
      append('circle', { cx: '10', cy: '10', r: '7.5' });
      append('path', { d: 'M6.7 10H13.3' });
      return svg;
    }
    if (icon === 'skipped') {
      append('path', { d: 'M6 6.8L10.4 10L6 13.2V6.8Z' });
      append('path', { d: 'M10.2 6.8L14.6 10L10.2 13.2V6.8Z' });
      return svg;
    }
    append('circle', { class: 'icon-ring', cx: '10', cy: '10', r: '7.5' });
    append('path', { d: 'M10 2.5A7.5 7.5 0 0 1 17.5 10' });
    return svg;
  }

  function appendIconLabel(node, label, iconKind, options) {
    const opts = options || {};
    const icon = createStatusIcon(iconKind, {
      spinning: !!opts.spinning,
      compact: !!opts.compact,
    });
    const text = document.createElement('span');
    text.className = safe(opts.labelClassName || 'chip-label');
    text.textContent = safe(label);
    node.appendChild(icon);
    node.appendChild(text);
  }

  function analysisBadgeHtml(info) {
    const item = info || {};
    return (
      "<span class='" +
      safe(item.className) +
      "' data-icon='" +
      safe(item.icon || 'pending') +
      "'" +
      (item.spinning ? " data-spin='1'" : '') +
      '>' +
      safe(item.text) +
      '</span>'
    );
  }

  function hydrateAnalysisBadges(rootNode) {
    const root = rootNode || document;
    const badges = root.querySelectorAll('.analysis-badge[data-icon]');
    for (const badge of badges) {
      if (safe(badge.getAttribute('data-icon-ready')) === '1') continue;
      const label = safe(badge.textContent);
      const icon = safe(badge.getAttribute('data-icon') || 'pending');
      const spinning = safe(badge.getAttribute('data-spin')) === '1';
      badge.textContent = '';
      appendIconLabel(badge, label, icon, {
        spinning: spinning,
        labelClassName: 'analysis-chip-label',
      });
      badge.setAttribute('data-icon-ready', '1');
    }
  }

  function createAnalysisBadgeNode(info) {
    const badge = document.createElement('span');
    const item = info || {};
    badge.className = safe(item.className || 'analysis-badge pending');
    appendIconLabel(badge, safe(item.text || ''), safe(item.icon || 'pending'), {
      spinning: !!item.spinning,
      labelClassName: 'analysis-chip-label',
    });
    return badge;
  }

  function setIconOnlyButton(buttonId, iconKind) {
    const btn = $(buttonId);
    if (!btn) return;
    const title = safe(btn.getAttribute('title')).trim();
    btn.textContent = '';
    btn.appendChild(createStatusIcon(iconKind, { compact: false }));
    if (title) {
      btn.setAttribute('aria-label', title);
    }
  }

  function setupSessionEntryToolbarIcons() {
    setIconOnlyButton('loadAgentsBtn', 'refresh');
    setIconOnlyButton('clearPolicyCacheBtn', 'clear_one');
    setIconOnlyButton('clearAllPolicyCacheBtn', 'clear_all');
    setIconOnlyButton('regeneratePolicyCacheBtn', 'cache');
  }
