#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function main() {
  const repoRoot = path.resolve(__dirname, '..', '..');
  const source = fs.readFileSync(
    path.join(repoRoot, 'src', 'workflow_app', 'web_client', 'assignment_center_render_runtime.js'),
    'utf8',
  );
  global.safe = (value) => (value == null ? '' : String(value));
  global.state = {
    assignmentGraphData: {
      nodes: [
        {
          node_id: 'node-patrol-running',
          node_name: 'pm持续唤醒 - workflow 主线巡检 / 2026-04-09 12:22:00',
          assigned_agent_id: 'workflow',
          assigned_agent_name: 'workflow',
          expected_artifact: 'workflow-pm-wake-summary',
          status: 'running',
          updated_at: '2026-04-09T12:30:00+08:00',
          is_workflow_patrol: true,
        },
        {
          node_id: 'node-mainline-ready',
          node_name: '[持续迭代] workflow / 2026-04-09 12:40:00',
          assigned_agent_id: 'workflow',
          assigned_agent_name: 'workflow',
          expected_artifact: 'continuous-improvement-report.md',
          status: 'ready',
          updated_at: '2026-04-09T12:40:00+08:00',
          is_workflow_mainline: true,
        },
        {
          node_id: 'node-garbled-failed',
          node_name: 'qualitymate-prod-quality-report.md',
          assigned_agent_id: 'workflow_qualitymate',
          assigned_agent_name: 'workflow_qualitymate',
          expected_artifact: 'qualitymate-prod-quality-report.md',
          status: 'failed',
          updated_at: '2026-04-09T11:21:00+08:00',
        },
      ],
    },
    dashboardMetrics: {},
  };

  vm.runInThisContext(source, { filename: 'assignment_center_render_runtime.js' });

  const preferredNodeId = global.pickAssignmentDefaultNode(global.state.assignmentGraphData);
  if (preferredNodeId !== 'node-mainline-ready') {
    throw new Error(`expected node-mainline-ready, got ${preferredNodeId}`);
  }

  const groups = global.assignmentWorkboardGroups();
  const workflowGroup = groups.find((item) => global.safe(item && item.agentId).trim() === 'workflow') || {};
  if (!workflowGroup.workflowMainlineHandoffPending) {
    throw new Error('expected workflowMainlineHandoffPending=true');
  }
  if (!global.safe(workflowGroup.workflowMainlineHandoffNote).includes('[持续迭代] workflow')) {
    throw new Error('expected workflowMainlineHandoffNote to mention [持续迭代] workflow');
  }

  process.stdout.write(
    JSON.stringify(
      {
        ok: true,
        preferred_node_id: preferredNodeId,
        workflow_mainline_handoff_pending: !!workflowGroup.workflowMainlineHandoffPending,
        workflow_mainline_handoff_note: workflowGroup.workflowMainlineHandoffNote,
      },
      null,
      2,
    ) + '\n'
  );
}

main();
