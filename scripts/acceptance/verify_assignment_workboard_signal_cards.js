#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function main() {
  const repoRoot = path.resolve(__dirname, '..', '..');
  const source = fs.readFileSync(
    path.join(repoRoot, 'src', 'workflow_app', 'web_client', 'assignment_center_render_runtime.js'),
    'utf8',
  );

  const fixedNow = new Date('2026-04-09T15:20:00+08:00').getTime();
  Date.now = () => fixedNow;

  global.safe = (value) => (value == null ? '' : String(value));
  global.state = {
    assignmentGraphLastRefreshAtMs: fixedNow - 4000,
    dashboardLastRefreshAtMs: fixedNow - 9000,
    dashboardLastFetchedAt: '2026-04-09T07:19:40Z',
    assignmentExecutionEventSource: null,
    assignmentExecutionEventSourceConnected: false,
    assignmentExecutionPollIntervalMs: 600,
  };
  global.assignmentExecutionMode = () => 'event_stream';
  global.assignmentExecutionRefreshModeText = () => '实时流';
  global.assignmentExecutionSettingsPayload = () => ({ poll_interval_ms: 450 });
  global.assignmentFormatBeijingTime = (value) => global.safe(value).replace('T', ' ').slice(0, 16);
  global.formatElapsedMs = (value) => `${Math.round(Number(value || 0) / 1000)}s`;
  global.assignmentStatusTone = (status) => {
    const text = global.safe(status).trim().toLowerCase();
    if (text === 'running') return 'running';
    if (text === 'failed') return 'fail';
    if (text === 'succeeded') return 'done';
    return 'future';
  };
  global.escapeHtml = (value) => global.safe(value);

  vm.runInThisContext(source, { filename: 'assignment_center_render_runtime.js' });

  const freshness = global.assignmentWorkboardFreshnessSnapshot();
  assert(freshness.label === '数据新鲜', `unexpected freshness label: ${freshness.label}`);
  assert(freshness.detail.includes('来源 任务图'), `unexpected freshness detail: ${freshness.detail}`);

  const connection = global.assignmentWorkboardConnectionSnapshot();
  assert(connection.label === '已回退短轮询', `unexpected connection label: ${connection.label}`);
  assert(connection.detail.includes('600ms'), `unexpected connection detail: ${connection.detail}`);

  const timing = global.assignmentWorkboardNodeTimingText({
    updated_at: '2026-04-09T15:19:00+08:00',
  });
  assert(timing.includes('最近更新 2026-04-09 15:19'), `unexpected timing text: ${timing}`);
  assert(timing.includes('60s 前'), `unexpected timing age: ${timing}`);

  const stage = global.assignmentWorkboardNodeStageSnapshot({
    latest_run_stage_label: '正在对齐版本计划',
    latest_run_stage_detail: '最近命令：读取 PM 版本推进计划',
    latest_run_stage_at: '2026-04-09T15:18:00+08:00',
  });
  assert(stage && stage.label === '正在对齐版本计划', `unexpected stage label: ${stage && stage.label}`);
  assert(stage && stage.detail.includes('读取 PM 版本推进计划'), `unexpected stage detail: ${stage && stage.detail}`);
  assert(stage && stage.timeText.includes('阶段时间 2026-04-09 15:18'), `unexpected stage time: ${stage && stage.timeText}`);

  const focusHtml = global.assignmentWorkboardFocusCardHtml(
    {
      node_id: 'node-mainline',
      node_name: '[持续迭代] workflow / 2026-04-09 16:51:00',
      status: 'running',
      status_text: '进行中',
      priority_label: 'P2',
      updated_at: '2026-04-09T15:19:00+08:00',
      latest_run_stage_label: '正在对齐版本计划',
      latest_run_stage_detail: '最近命令：读取 PM 版本推进计划',
      latest_run_stage_at: '2026-04-09T15:18:00+08:00',
    },
    {
      eyebrow: '当前主线',
      tone: 'running',
      note: '当前真正会消耗 token 的连续迭代节点。',
    },
  );
  assert(focusHtml.includes('assignment-workboard-focus-stage'), 'focus card missing stage block');
  assert(focusHtml.includes('正在对齐版本计划'), `focus card missing stage label: ${focusHtml}`);
  assert(focusHtml.includes('最近命令：读取 PM 版本推进计划'), `focus card missing stage detail: ${focusHtml}`);

  const guidance = global.assignmentWorkboardGuidanceSnapshot(
    { status: 'running' },
    { status: 'ready' },
    null,
    [],
    {},
  );
  assert(guidance.label === '继续等待当前主线', `unexpected guidance label: ${guidance.label}`);

  process.stdout.write(
    JSON.stringify(
      {
        ok: true,
        freshness_label: freshness.label,
        connection_label: connection.label,
        timing_text: timing,
        stage_label: stage.label,
        guidance_label: guidance.label,
      },
      null,
      2,
    ) + '\n'
  );
}

main();
