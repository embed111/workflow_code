#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function readUtf8(filePath) {
  return fs.readFileSync(filePath, 'utf8');
}

function repoRoot() {
  return path.resolve(__dirname, '..', '..');
}

function buildBundle(rootDir) {
  const manifestPath = path.join(rootDir, 'src', 'workflow_app', 'web_client', 'bundle_manifest.json');
  const manifest = JSON.parse(readUtf8(manifestPath));
  return manifest
    .map((name) => readUtf8(path.join(rootDir, 'src', 'workflow_app', 'web_client', name)))
    .join('\n');
}

function createSessionEntry(state, sessionId) {
  const sid = String(sessionId || '').trim();
  if (!sid) return null;
  if (!state.sessionsById[sid]) {
    state.sessionsById[sid] = { session_id: sid, messages: [] };
  }
  return state.sessionsById[sid];
}

function installGlobals(state) {
  global.state = state;
  global.safe = (value) => (value == null ? '' : String(value));
  global.normalizeRuntimePhase = (value) => {
    const text = global.safe(value).trim().toLowerCase();
    if (text === 'success') return 'done';
    if (text === 'running') return 'generating';
    if (text === 'failed') return 'failed';
    if (text === 'interrupted') return 'interrupted';
    return 'sent';
  };
  global.statusText = (value) => global.safe(value).trim() || 'unknown';
  global.ensureSessionEntry = (row) => createSessionEntry(state, row && row.session_id);
  global.moveSessionToTop = (sessionId) => {
    const sid = global.safe(sessionId).trim();
    state.sessionOrder = state.sessionOrder.filter((item) => item !== sid);
    if (sid) state.sessionOrder.unshift(sid);
  };
  global.renderSessionList = () => {};
  global.renderFeed = () => {};
  global.scheduleFeedRender = () => {};
  global.applyGateState = () => {};
  global.currentSession = () => state.sessionsById[state.selectedSessionId] || null;
  global.$ = () => null;
  global.formatDateTime = (value) => global.safe(value);
  global.formatElapsedMs = (value) => String(value || 0);
  global.localStorage = { setItem() {}, removeItem() {} };
  global.selectedAgent = () => 'probe-agent';
  global.resolveSessionPolicyGateInfo = () => ({ analysis_completed: true, reason: '' });
  global.setChatError = () => {};
  global.setStatus = () => {};
  global.visibleWorkflows = () => [];
  global.isWorkflowAnalysisSelectable = () => false;
  global.reasonText = (value) => global.safe(value);
  global.analysisBadgeInfo = () => ({ label: 'ok', className: 'ok' });
  global.analysisBadgeHtml = () => '';
  global.hydrateAnalysisBadges = () => {};
  global.loadWorkflowPlan = async () => {};
  global.refreshWorkflowEvents = async () => {};
  global.setWorkflowResult = () => {};
  global.window = {
    requestAnimationFrame: (fn) => {
      fn();
      return 1;
    },
  };
}

function installUiStubs() {
  global.renderSessionList = () => {};
  global.renderFeed = () => {};
  global.scheduleFeedRender = () => {};
  global.applyGateState = () => {};
}

function loadRuntimeScripts(rootDir) {
  const files = [
    path.join(rootDir, 'src', 'workflow_app', 'web_client', 'app_runtime_state_helpers.js'),
    path.join(rootDir, 'src', 'workflow_app', 'web_client', 'policy_confirm_and_interactions.js'),
    path.join(rootDir, 'src', 'workflow_app', 'web_client', 'workflow_queue_selection_core.js'),
    path.join(rootDir, 'src', 'workflow_app', 'web_client', 'workflow_queue_batch_runtime.js'),
    path.join(rootDir, 'src', 'workflow_app', 'web_client', 'workflow_runtime_controls.js'),
    path.join(rootDir, 'src', 'workflow_app', 'web_client', 'workflow_queue_and_batch.js'),
  ];
  const source = files.map((filePath) => readUtf8(filePath)).join('\n');
  vm.runInThisContext(source, { filename: 'chat-task-recovery-smoke.js' });
}

function createState() {
  return {
    sessionsById: {},
    sessionTaskRuns: {},
    runningTasks: {},
    sessionOrder: [],
    selectedSessionId: '',
    feedRenderRaf: 0,
    taskTraceCache: {},
    taskTraceDetailsOpen: {},
    taskTraceExpanded: {},
    selectedWorkflowIds: {},
    workflows: [],
    queueMode: 'records',
    agentSearchRootReady: true,
  };
}

async function runRecoveryScenario() {
  const state = createState();
  installGlobals(state);
  loadRuntimeScripts(repoRoot());
  installUiStubs();

  let pollStartCount = 0;
  let pollStopCount = 0;
  global.startTaskPolling = () => {
    pollStartCount += 1;
  };
  global.stopTaskPollingIfIdle = () => {
    pollStopCount += 1;
  };
  global.getJSON = async (url) => {
    if (url.includes('/messages')) {
      return {
        messages: [
          { role: 'user', content: 'hello', created_at: '2026-03-28T19:20:00+08:00' },
        ],
      };
    }
    if (url.includes('/task-runs')) {
      return {
        items: [
          {
            task_id: 'task-recover-1',
            session_id: 'sess-recover-1',
            agent_name: 'probe-agent',
            status: 'running',
            summary: '',
            created_at: '2026-03-28T19:20:01+08:00',
            start_at: '2026-03-28T19:20:02+08:00',
            end_at: '',
            duration_ms: 0,
            command: ['probe'],
            trace_available: false,
          },
        ],
      };
    }
    throw new Error(`unexpected url: ${url}`);
  };

  createSessionEntry(state, 'sess-recover-1');
  state.selectedSessionId = 'sess-recover-1';
  await global.loadSessionMessages('sess-recover-1');

  const recoveredSession = state.sessionsById['sess-recover-1'];
  const recoveredMessages = Array.isArray(recoveredSession.messages) ? recoveredSession.messages : [];
  const recoveredAssistant = recoveredMessages[recoveredMessages.length - 1] || {};
  if (!state.runningTasks['sess-recover-1']) {
    throw new Error('running task was not recovered');
  }
  if (global.safe(state.runningTasks['sess-recover-1'].task_id).trim() !== 'task-recover-1') {
    throw new Error('recovered task id mismatch');
  }
  if (global.safe(recoveredAssistant.task_id).trim() !== 'task-recover-1') {
    throw new Error('assistant placeholder task id mismatch');
  }
  if (global.safe(recoveredAssistant.run_state).trim() !== 'generating') {
    throw new Error('assistant placeholder run_state mismatch');
  }
  if (pollStartCount !== 1) {
    throw new Error('poller should start exactly once after recovery');
  }

  return {
    poll_start_count: pollStartCount,
    poll_stop_count: pollStopCount,
    recovered_task_id: global.safe(state.runningTasks['sess-recover-1'].task_id).trim(),
    recovered_message_count: recoveredMessages.length,
  };
}

async function runFailedScenario() {
  const state = createState();
  installGlobals(state);
  loadRuntimeScripts(repoRoot());
  installUiStubs();

  let pollStartCount = 0;
  let pollStopCount = 0;
  global.startTaskPolling = () => {
    pollStartCount += 1;
  };
  global.stopTaskPollingIfIdle = () => {
    pollStopCount += 1;
  };
  global.getJSON = async (url) => {
    if (url.includes('/messages')) {
      return {
        messages: [
          { role: 'user', content: 'hello failed', created_at: '2026-03-28T19:30:00+08:00' },
        ],
      };
    }
    if (url.includes('/task-runs')) {
      return {
        items: [
          {
            task_id: 'task-failed-1',
            session_id: 'sess-failed-1',
            agent_name: 'probe-agent',
            status: 'failed',
            summary: 'command exit code=1',
            created_at: '2026-03-28T19:30:01+08:00',
            start_at: '2026-03-28T19:30:02+08:00',
            end_at: '2026-03-28T19:30:05+08:00',
            duration_ms: 3000,
            command: ['probe'],
            trace_available: true,
          },
        ],
      };
    }
    throw new Error(`unexpected url: ${url}`);
  };

  createSessionEntry(state, 'sess-failed-1');
  state.selectedSessionId = 'sess-failed-1';
  await global.loadSessionMessages('sess-failed-1');

  const failedSession = state.sessionsById['sess-failed-1'];
  const failedMessages = Array.isArray(failedSession.messages) ? failedSession.messages : [];
  const failedAssistant = failedMessages[failedMessages.length - 1] || {};
  if (state.runningTasks['sess-failed-1']) {
    throw new Error('failed task should not remain in runningTasks');
  }
  if (global.safe(failedAssistant.task_id).trim() !== 'task-failed-1') {
    throw new Error('failed task assistant message missing task id');
  }
  if (global.safe(failedAssistant.run_state).trim() !== 'failed') {
    throw new Error('failed task assistant message run_state mismatch');
  }
  if (!global.safe(failedAssistant.content).includes('command exit code=1')) {
    throw new Error('failed task assistant message should include summary');
  }
  if (pollStartCount !== 0) {
    throw new Error('failed scenario should not restart task polling');
  }

  return {
    poll_start_count: pollStartCount,
    poll_stop_count: pollStopCount,
    failed_task_id: global.safe(failedAssistant.task_id).trim(),
    failed_message_count: failedMessages.length,
  };
}

async function runEmptySuccessRecoveryScenario() {
  const state = createState();
  installGlobals(state);
  loadRuntimeScripts(repoRoot());
  installUiStubs();

  let pollStartCount = 0;
  let pollStopCount = 0;
  global.startTaskPolling = () => {
    pollStartCount += 1;
  };
  global.stopTaskPollingIfIdle = () => {
    pollStopCount += 1;
  };
  global.getJSON = async (url) => {
    if (url.includes('/messages')) {
      return {
        messages: [
          { role: 'user', content: 'hello success', created_at: '2026-03-28T19:40:00+08:00' },
        ],
      };
    }
    if (url.includes('/task-runs')) {
      return {
        items: [
          {
            task_id: 'task-success-empty-1',
            session_id: 'sess-success-empty-1',
            agent_name: 'probe-agent',
            status: 'success',
            summary: 'command completed successfully',
            created_at: '2026-03-28T19:40:01+08:00',
            start_at: '2026-03-28T19:40:02+08:00',
            end_at: '2026-03-28T19:40:05+08:00',
            duration_ms: 3000,
            command: ['probe'],
            trace_available: true,
          },
        ],
      };
    }
    throw new Error(`unexpected url: ${url}`);
  };

  createSessionEntry(state, 'sess-success-empty-1');
  state.selectedSessionId = 'sess-success-empty-1';
  await global.loadSessionMessages('sess-success-empty-1');

  const successSession = state.sessionsById['sess-success-empty-1'];
  const successMessages = Array.isArray(successSession.messages) ? successSession.messages : [];
  const successAssistant = successMessages[successMessages.length - 1] || {};
  if (state.runningTasks['sess-success-empty-1']) {
    throw new Error('empty success should not remain in runningTasks');
  }
  if (global.safe(successAssistant.task_id).trim() !== 'task-success-empty-1') {
    throw new Error('empty success assistant message missing task id');
  }
  if (global.safe(successAssistant.run_state).trim() !== 'done') {
    throw new Error('empty success assistant message run_state mismatch');
  }
  if (!global.safe(successAssistant.content).includes('已完成，但未返回文本内容')) {
    throw new Error('empty success assistant message should use empty-output fallback');
  }
  if (pollStartCount !== 0) {
    throw new Error('empty success should not restart task polling');
  }

  return {
    poll_start_count: pollStartCount,
    poll_stop_count: pollStopCount,
    success_task_id: global.safe(successAssistant.task_id).trim(),
    success_message_count: successMessages.length,
  };
}

async function runPlaceholderFinalizeScenario(status, summary, expectedContent) {
  const state = createState();
  installGlobals(state);
  loadRuntimeScripts(repoRoot());
  installUiStubs();

  global.refreshDashboard = async () => {};
  global.getJSON = async (url) => {
    if (url.includes('/events')) {
      return { events: [] };
    }
    if (url.includes('/api/tasks/')) {
      return {
        task_id: `task-live-${status}`,
        session_id: `sess-live-${status}`,
        agent_name: 'probe-agent',
        status,
        summary,
        created_at: '2026-03-28T19:50:01+08:00',
        start_at: '2026-03-28T19:50:02+08:00',
        end_at: '2026-03-28T19:50:05+08:00',
        duration_ms: 3000,
        command: ['probe'],
        trace_available: true,
      };
    }
    throw new Error(`unexpected url: ${url}`);
  };

  createSessionEntry(state, `sess-live-${status}`);
  state.selectedSessionId = `sess-live-${status}`;
  state.sessionsById[`sess-live-${status}`].messages = [
    {
      role: 'assistant',
      content: '思考中...',
      created_at: '2026-03-28T19:50:00+08:00',
      task_id: `task-live-${status}`,
      run_state: 'sent',
      pending_placeholder: true,
      run_hint: '',
    },
  ];
  state.sessionTaskRuns[`sess-live-${status}`] = [
    {
      task_id: `task-live-${status}`,
      session_id: `sess-live-${status}`,
      agent_name: 'probe-agent',
      status: 'running',
      summary: '',
      created_at: '2026-03-28T19:50:01+08:00',
      start_at: '2026-03-28T19:50:02+08:00',
      end_at: '',
      duration_ms: 0,
      command: ['probe'],
      trace_available: false,
    },
  ];
  state.runningTasks[`sess-live-${status}`] = {
    task_id: `task-live-${status}`,
    since_id: 0,
    pending_index: 0,
    started_at: '2026-03-28T19:50:02+08:00',
    status: 'running',
    agent_name: 'probe-agent',
  };

  await global.pollRunningTasks();

  const finalized = state.sessionsById[`sess-live-${status}`].messages[0] || {};
  if (global.safe(finalized.content).trim() !== expectedContent) {
    throw new Error(`placeholder finalize content mismatch for ${status}`);
  }
  if (global.safe(finalized.run_state).trim() !== (status === 'success' ? 'done' : status)) {
    throw new Error(`placeholder finalize run_state mismatch for ${status}`);
  }
  if (state.runningTasks[`sess-live-${status}`]) {
    throw new Error(`placeholder finalize should clear runningTasks for ${status}`);
  }

  return {
    status,
    content: global.safe(finalized.content).trim(),
    run_state: global.safe(finalized.run_state).trim(),
  };
}

async function main() {
  const rootDir = repoRoot();
  new Function(buildBundle(rootDir));
  const recovery = await runRecoveryScenario();
  const failed = await runFailedScenario();
  const emptySuccess = await runEmptySuccessRecoveryScenario();
  const liveFailedFinalize = await runPlaceholderFinalizeScenario(
    'failed',
    'command exit code=2',
    '执行结束：failed command exit code=2',
  );
  const liveSuccessFinalize = await runPlaceholderFinalizeScenario(
    'success',
    'command completed successfully',
    '（已完成，但未返回文本内容）',
  );
  console.log(
    JSON.stringify(
      {
        ok: true,
        bundle_syntax: 'passed',
        recovery,
        failed,
        emptySuccess,
        liveFailedFinalize,
        liveSuccessFinalize,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
