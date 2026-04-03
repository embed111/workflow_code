  // Training center loop core state, parsing, and shared render helpers.

  const TC_LOOP_STAGES = [
    { key: 'create', index: 1, title: '创建任务' },
    { key: 'workset', index: 2, title: '配置本轮工作集' },
    { key: 'eval', index: 3, title: '执行三轮评测' },
    { key: 'judge', index: 4, title: '生成结果判定' },
    { key: 'next', index: 5, title: '进入下一轮 / 完成' },
  ];
  const TC_LOOP_CREATE_TABS = [
    { key: 'basic', label: '基础信息' },
    { key: 'workset', label: '首轮工作集' },
    { key: 'launch', label: '启动确认' },
  ];
  const TC_LOOP_STATUS_TABS = [
    { key: 'overview', label: '当前概览' },
    { key: 'workset', label: '工作集变化' },
    { key: 'eval', label: '三轮评测' },
    { key: 'history', label: '历史记录' },
  ];

  function normalizeTrainingLoopMode(value) {
    return safe(value).toLowerCase() === 'status' ? 'status' : 'create';
  }

  function normalizeTrainingLoopCreateTab(value) {
    const key = safe(value).toLowerCase();
    return key === 'workset' || key === 'launch' ? key : 'basic';
  }

  function normalizeTrainingLoopStatusTab(value) {
    const key = safe(value).toLowerCase();
    if (key === 'score' || key === 'decision') return 'overview';
    if (key === 'workset' || key === 'eval' || key === 'history') return key;
    return 'overview';
  }

  function normalizeTrainingLoopRightTab(value) {
    return safe(value).toLowerCase() === 'baseline' ? 'baseline' : 'tasks';
  }

  function scrollTrainingLoopCenterToTop() {
    const node = $('tcLoopCenterPane');
    if (node) node.scrollTop = 0;
  }

  function enterTrainingLoopCreateMode(options) {
    const opts = options && typeof options === 'object' ? options : {};
    state.tcLoopMode = 'create';
    if (!opts.preserveTab) state.tcLoopCreateTab = 'basic';
    if (!opts.preserveRightTab) state.tcLoopRightTab = 'tasks';
    renderTrainingLoop();
    renderTrainingCenterQueue();
    scrollTrainingLoopCenterToTop();
  }

  function setTrainingLoopCreateTab(tabKey) {
    state.tcLoopCreateTab = normalizeTrainingLoopCreateTab(tabKey);
    renderTrainingLoop();
    scrollTrainingLoopCenterToTop();
  }

  function setTrainingLoopStatusTab(tabKey) {
    state.tcLoopStatusTab = normalizeTrainingLoopStatusTab(tabKey);
    renderTrainingLoop();
    scrollTrainingLoopCenterToTop();
  }

  function setTrainingLoopRightTab(tabKey) {
    state.tcLoopRightTab = normalizeTrainingLoopRightTab(tabKey);
    renderTrainingLoop();
  }

  function setTrainingLoopSelectedNode(nodeId) {
    state.tcLoopSelectedNodeId = safe(nodeId).trim();
    renderTrainingLoop();
  }

  function normalizeTrainingLoopQueueFilter(value) {
    const key = safe(value).toLowerCase();
    if (key === 'running' || key === 'queued' || key === 'done' || key === 'removed') return key;
    return 'all';
  }

  function setTrainingLoopQueueFilter(filterKey) {
    state.tcLoopQueueFilter = normalizeTrainingLoopQueueFilter(filterKey);
    renderTrainingCenterQueue();
    renderTrainingLoop();
  }

  function selectTrainingLoopQueueTask(queueTaskId, options) {
    const opts = options && typeof options === 'object' ? options : {};
    state.tcLoopSelectedQueueTaskId = safe(queueTaskId).trim();
    state.tcLoopSelectedNodeId = '';
    state.tcLoopMode = 'status';
    if (!opts.preserveTab) state.tcLoopStatusTab = 'overview';
    if (!opts.preserveRightTab) state.tcLoopRightTab = 'tasks';
    renderTrainingLoop();
    renderTrainingCenterQueue();
    scrollTrainingLoopCenterToTop();
  }

  function selectedTrainingLoopQueueRow() {
    const key = safe(state.tcLoopSelectedQueueTaskId).trim();
    const rows = Array.isArray(state.tcQueue) ? state.tcQueue : [];
    if (!key) return null;
    return rows.find((row) => safe(row && row.queue_task_id).trim() === key) || null;
  }

  function ensureTrainingLoopSelection(mode) {
    const key = safe(state.tcLoopSelectedQueueTaskId).trim();
    const rows = Array.isArray(state.tcQueue) ? state.tcQueue : [];
    if (mode !== 'status') return;
    if (!rows.length) return;
    if (key && rows.some((row) => safe(row && row.queue_task_id).trim() === key)) {
      return;
    }
    const preferred =
      rows.find((row) => safe(row && row.status).toLowerCase() !== 'removed') || rows[0] || null;
    state.tcLoopSelectedQueueTaskId = safe(preferred && preferred.queue_task_id).trim();
    state.tcLoopSelectedNodeId = '';
  }

  function trainingLoopStageIndex(mode, queueRow) {
    const view = normalizeTrainingLoopMode(mode);
    if (view === 'create') return 1;
    const status = safe(queueRow && queueRow.status).toLowerCase();
    if (status === 'running') return 3;
    if (status === 'done' || status === 'failed' || status === 'removed') return 4;
    return 2;
  }

  function trainingLoopStageDesc(stageIndex, currentIndex, mode, queueRow) {
    if (stageIndex < currentIndex) return '已完成';
    if (stageIndex === currentIndex) return '当前阶段';
    const view = normalizeTrainingLoopMode(mode);
    if (view === 'create') {
      if (stageIndex === 2) return '本页同步准备';
      if (stageIndex === 3) return '创建后立即启动';
      if (stageIndex === 4) return '首轮结果回写';
      return '按阈值决策';
    }
    const status = safe(queueRow && queueRow.status).toLowerCase();
    if (stageIndex === 3 && status === 'queued') return '待执行';
    if (stageIndex === 5 && (status === 'done' || status === 'failed')) return '待进入';
    return '待进入';
  }

  function renderTrainingLoopSteps(currentIndex, mode, queueRow) {
    const blocks = TC_LOOP_STAGES.map((stage) => {
      const cls = stage.index < currentIndex ? ' done' : stage.index === currentIndex ? ' active' : '';
      const desc = trainingLoopStageDesc(stage.index, currentIndex, mode, queueRow);
      return (
        "<div class='tc-loop-step" +
        cls +
        "'>" +
        "<div class='tc-loop-step-index'>" +
        safe(stage.index) +
        '</div>' +
        "<div class='tc-loop-step-body'>" +
        "<div class='tc-loop-step-title'>" +
        safe(stage.title) +
        '</div>' +
        "<div class='tc-loop-step-desc'>" +
        safe(desc) +
        '</div>' +
        '</div>' +
        '</div>'
      );
    }).join('');
    return "<div class='tc-loop-steps'>" + blocks + '</div>';
  }

  function beginTrainingLoopServerFetch(queueTaskId) {
    const key = safe(queueTaskId).trim();
    if (!key) {
      state.tcLoopServerLoading = false;
      return 0;
    }
    const nextSeq = Number(state.tcLoopServerRequestSeq || 0) + 1;
    state.tcLoopServerRequestSeq = nextSeq;
    state.tcLoopServerQueueTaskId = key;
    state.tcLoopServerLoading = true;
    state.tcLoopServerError = '';
    state.tcLoopServerData = null;
    state.tcLoopStatusDetailData = null;
    return nextSeq;
  }

  function isTrainingLoopServerFetchCurrent(queueTaskId, requestSeq) {
    const key = safe(queueTaskId).trim();
    if (!key || safe(state.tcLoopSelectedQueueTaskId).trim() !== key) {
      return false;
    }
    const seq = Number(requestSeq || 0);
    if (!seq) return true;
    return Number(state.tcLoopServerRequestSeq || 0) === seq;
  }

  async function refreshTrainingLoopServerData(queueTaskId, options) {
    const key = safe(queueTaskId).trim();
    const opts = options && typeof options === 'object' ? options : {};
    if (!key) return;
    if (
      !opts.force &&
      safe(state.tcLoopServerQueueTaskId).trim() === key &&
      (state.tcLoopServerLoading || state.tcLoopServerData || state.tcLoopServerError)
    ) {
      return;
    }
    const seq = beginTrainingLoopServerFetch(key);
    renderTrainingLoop();
    try {
      const responses = await Promise.all([
        getJSON(withTestDataQuery('/api/training/queue/' + encodeURIComponent(key) + '/loop')),
        getJSON(withTestDataQuery('/api/training/queue/' + encodeURIComponent(key) + '/status-detail')),
      ]);
      if (!isTrainingLoopServerFetchCurrent(key, seq)) return;
      const payload = responses[0] && typeof responses[0] === 'object' ? responses[0] : null;
      const detailPayload = responses[1] && typeof responses[1] === 'object' ? responses[1] : null;
      state.tcLoopServerData = payload;
      state.tcLoopStatusDetailData = detailPayload;
      state.tcLoopServerError = '';
      if (payload && Array.isArray(payload.nodes)) {
        if (!state.tcLoopRoundIndexByQueueTaskId || typeof state.tcLoopRoundIndexByQueueTaskId !== 'object') {
          state.tcLoopRoundIndexByQueueTaskId = {};
        }
        for (const node of payload.nodes) {
          if (!node || typeof node !== 'object') continue;
          const qid = safe(node.queue_task_id || node.node_id).trim();
          if (!qid) continue;
          const ridx = Number(node.round_index || 0);
          if (!Number.isFinite(ridx) || ridx <= 0) continue;
          state.tcLoopRoundIndexByQueueTaskId[qid] = ridx;
        }
      }
    } catch (err) {
      if (!isTrainingLoopServerFetchCurrent(key, seq)) return;
      state.tcLoopServerData = null;
      state.tcLoopStatusDetailData = null;
      state.tcLoopServerError = safe(err && err.message ? err.message : err);
    } finally {
      if (isTrainingLoopServerFetchCurrent(key, seq)) {
        state.tcLoopServerLoading = false;
      }
      renderTrainingLoop();
    }
  }

  function trainingLoopNodesById(loopData) {
    const nodes = Array.isArray(loopData && loopData.nodes) ? loopData.nodes : [];
    const out = {};
    for (const node of nodes) {
      if (!node || typeof node !== 'object') continue;
      const nid = safe(node.node_id).trim();
      if (!nid) continue;
      out[nid] = node;
    }
    return out;
  }

  function trainingLoopSelectedNodeContext(loopData) {
    const payload = loopData && typeof loopData === 'object' ? loopData : null;
    const nodes = Array.isArray(payload && payload.nodes) ? payload.nodes : [];
    const nodesById = trainingLoopNodesById(payload);
    const currentNodeId = safe(payload && payload.current_node_id).trim();
    let selectedNodeId = safe(state.tcLoopSelectedNodeId).trim() || currentNodeId;
    if (selectedNodeId && nodes.length && !nodesById[selectedNodeId]) {
      selectedNodeId = currentNodeId;
    }
    if (!selectedNodeId && currentNodeId) {
      selectedNodeId = currentNodeId;
    }
    if (selectedNodeId && selectedNodeId !== safe(state.tcLoopSelectedNodeId).trim()) {
      state.tcLoopSelectedNodeId = selectedNodeId;
    }
    return {
      payload,
      nodes,
      nodesById,
      currentNodeId,
      selectedNodeId,
      selectedNode: (selectedNodeId && nodesById[selectedNodeId]) || null,
      metricsAvailable: !!(payload && payload.metrics_available),
      metricsReason: safe(payload && payload.metrics_unavailable_reason).trim(),
      isTestData: !!(payload && payload.is_test_data),
      loopId: safe(payload && (payload.loop_id || payload.loopId)).trim() || '-',
    };
  }

  function trainingLoopStatusDetailContext(detailData) {
    const payload = detailData && typeof detailData === 'object' ? detailData : null;
    return {
      payload: payload,
      overview:
        payload && payload.current_overview && typeof payload.current_overview === 'object'
          ? payload.current_overview
          : {},
      workset:
        payload && payload.workset_changes && typeof payload.workset_changes === 'object'
          ? payload.workset_changes
          : {},
      evaluations:
        payload && Array.isArray(payload.evaluations)
          ? payload.evaluations
          : [],
      historyRecords:
        payload && Array.isArray(payload.history_records)
          ? payload.history_records
          : [],
      capabilities:
        payload && Array.isArray(payload.capabilities)
          ? payload.capabilities
          : [],
      tasksEvolution:
        payload && payload.tasks_evolution && typeof payload.tasks_evolution === 'object'
          ? payload.tasks_evolution
          : {},
      baseline:
        payload && payload.baseline && typeof payload.baseline === 'object'
          ? payload.baseline
          : {},
    };
  }

  function trainingLoopScoreText(value, emptyText) {
    if (value === null || value === undefined || value === '') return safe(emptyText || '-');
    const num = Number(value);
    if (!Number.isFinite(num)) return safe(value);
    return num.toFixed(2);
  }

  function renderTrainingLoopWorksetItems(workset) {
    const items = Array.isArray(workset && workset.items) ? workset.items : [];
    if (!items.length) return "<div class='tc-loop-empty'>当前没有结构化工作集条目。</div>";
    return (
      "<ul class='tc-loop-bullet-list'>" +
      items
        .map((item) => {
          const stateLabel =
            safe(item && item.state).trim() === 'removed'
              ? '移除'
              : safe(item && item.state).trim() === 'carried'
                ? '沿用'
                : '新增';
          return '<li>[' + safe(stateLabel) + '] ' + safe(item && item.label) + '</li>';
        })
        .join('') +
      '</ul>'
    );
  }

  function renderTrainingLoopEvaluationCards(evaluations, selectedQueueTaskId) {
    const rows = Array.isArray(evaluations) ? evaluations.slice() : [];
    if (!rows.length) return "<div class='tc-loop-empty'>当前还没有后端回写的三轮评测记录。</div>";
    rows.sort((left, right) => Number(left && left.round_index) - Number(right && right.round_index));
    const selectedId = safe(selectedQueueTaskId).trim();
    return (
      "<div class='tc-loop-history-list'>" +
      rows
        .map((round) => {
          const runResults = Array.isArray(round && round.run_results) ? round.run_results : [];
          const currentMark = safe(round && round.queue_task_id).trim() === selectedId ? ' · 当前查看' : '';
          const runLines = runResults.length
            ? "<div class='tc-loop-summary-list'>" +
              runResults
                .map(
                  (run) =>
                    "<div class='tc-loop-summary-item'><div class='tc-loop-summary-k'>" +
                    safe(run && (run.run_label || ('Run' + safe(run.run_index)))) +
                    "</div><div class='tc-loop-summary-v'>" +
                    safe(statusText(run && run.status ? run.status : '-')) +
                    (run && run.score !== null && run.score !== undefined && run.score !== '' ? ' · ' + trainingLoopScoreText(run.score, '-') : '') +
                    (safe(run && run.summary).trim() ? ' · ' + safe(run.summary) : '') +
                    '</div></div>'
                )
                .join('') +
              '</div>'
            : "<div class='tc-loop-empty'>当前轮尚未开始三轮评测。</div>";
          return (
            "<div class='tc-loop-history-item'>" +
            "<div class='tc-loop-history-title'>" +
            safe(round && (round.title || ('R' + safe(round.round_index)))) +
            safe(currentMark) +
            '</div>' +
            "<div class='tc-loop-history-meta'>阈值 " +
            safe(trainingLoopScoreText(round && round.threshold, '-')) +
            ' · Avg ' +
            safe(trainingLoopScoreText(round && round.avg_score, '待三轮完成')) +
            ' · 上一轮 ' +
            safe(trainingLoopScoreText(round && round.previous_avg_score, '无')) +
            '</div>' +
            "<div class='tc-loop-history-text'>判定：" +
            safe(round && round.decision ? round.decision : '待三轮评测完成') +
            '</div>' +
            "<div class='tc-loop-history-text'>下一步：" +
            safe(round && round.next_action ? round.next_action : '等待三轮评测完成') +
            '</div>' +
            runLines +
            '</div>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function renderTrainingLoopBackendHistoryList(records) {
    const rows = Array.isArray(records) ? records.slice() : [];
    if (!rows.length) return "<div class='tc-loop-empty'>当前还没有可追溯的轮次历史。</div>";
    rows.sort((left, right) => Number(left && left.round_index) - Number(right && right.round_index));
    return (
      "<div class='tc-loop-history-list'>" +
      rows
        .map((item) => {
          const auditRefs = Array.isArray(item && item.audit_refs) ? item.audit_refs : [];
          return (
            "<div class='tc-loop-history-item'>" +
            "<div class='tc-loop-history-title'>" +
            safe(item && (item.title || ('R' + safe(item.round_index)))) +
            '</div>' +
            "<div class='tc-loop-history-meta'>Avg " +
            safe(trainingLoopScoreText(item && item.avg_score, '待三轮完成')) +
            ' · 阈值 ' +
            safe(trainingLoopScoreText(item && item.threshold, '-')) +
            (item && item.rollback_applied ? ' · 已回退' : '') +
            '</div>' +
            "<div class='tc-loop-history-text'>判定：" +
            safe(item && item.decision ? item.decision : '-') +
            '</div>' +
            "<div class='tc-loop-history-text'>工作集：" +
            safe(item && item.workset_delta_summary ? item.workset_delta_summary : '-') +
            '</div>' +
            "<div class='tc-loop-history-text'>审计引用：" +
            safe(auditRefs.map((ref) => safe(ref && ref.audit_id).trim()).filter(Boolean).join(', ') || '暂无') +
            '</div>' +
            '</div>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function trainingLoopPlanSnapshot() {
    const targetAgentId = safe(trainingCenterSelectedTargetAgent()).trim();
    const targetDetail =
      targetAgentId && Array.isArray(state.tcAgents)
        ? state.tcAgents.find((item) => safe(item && item.agent_id).trim() === targetAgentId) || null
        : null;
    const targetName =
      safe(targetDetail && (targetDetail.agent_name || targetDetail.agent_id)).trim() ||
      targetAgentId ||
      '-';
    return {
      targetAgentId,
      targetName,
      capabilityGoal: safe($('tcPlanGoalInput') ? $('tcPlanGoalInput').value : '').trim(),
      trainingTasks: parseTrainingTasksInput(),
      acceptanceCriteria: safe($('tcPlanAcceptanceInput') ? $('tcPlanAcceptanceInput').value : '').trim(),
      priority: safe($('tcPlanPrioritySelect') ? $('tcPlanPrioritySelect').value : '').trim(),
      executionEngine: 'workflow_native',
      executionLabel: trainingExecutionEngineLabel('workflow_native'),
      frozen: safe(targetDetail && targetDetail.training_gate_state).toLowerCase() === 'frozen_switched',
      targetDetail: targetDetail || {},
    };
  }

  function trainingLoopValidationItems(snapshot) {
    const data = snapshot && typeof snapshot === 'object' ? snapshot : trainingLoopPlanSnapshot();
    return [
      { label: '目标角色', ok: !!data.targetAgentId, value: data.targetName || '未选择' },
      { label: '能力目标', ok: !!data.capabilityGoal, value: data.capabilityGoal || '未填写' },
      {
        label: '首轮工作集',
        ok: Array.isArray(data.trainingTasks) && data.trainingTasks.length > 0,
        value: Array.isArray(data.trainingTasks) && data.trainingTasks.length ? data.trainingTasks.length + ' 项' : '未填写',
      },
      { label: '验收标准', ok: !!data.acceptanceCriteria, value: data.acceptanceCriteria || '未填写' },
      { label: '优先级', ok: !!data.priority, value: data.priority || '未选择' },
    ];
  }

  function trainingLoopFormCacheNode() {
    const root = $('tcModuleOps');
    return root ? root.querySelector('.tc-loop-form-cache') : null;
  }

  function restoreTrainingLoopFormCache() {
    const cache = trainingLoopFormCacheNode();
    if (!cache) return;
    ['tcPlanTargetAgentSelect', 'tcPlanGoalInput', 'tcPlanTasksInput', 'tcPlanAcceptanceInput', 'tcPlanPrioritySelect'].forEach((id) => {
      const field = $(id);
      if (field && field.parentElement !== cache) {
        cache.appendChild(field);
      }
    });
  }

  function mountTrainingLoopField(fieldId, mountId, options) {
    const field = $(fieldId);
    const mount = $(mountId);
    if (!field || !mount) return;
    const opts = options && typeof options === 'object' ? options : {};
    if (Object.prototype.hasOwnProperty.call(opts, 'placeholder')) {
      field.setAttribute('placeholder', safe(opts.placeholder));
    }
    if (Object.prototype.hasOwnProperty.call(opts, 'rows') && field.tagName === 'TEXTAREA') {
      field.setAttribute('rows', String(opts.rows || 4));
    }
    mount.innerHTML = '';
    mount.appendChild(field);
  }

  function renderTrainingLoopPreviewSvg() {
    return (
      "<svg class='tc-loop-evolution-svg' viewBox='0 0 620 132' preserveAspectRatio='xMinYMid meet' aria-label='训练路径预览'>" +
      "<path class='tc-loop-graph-line base' d='M72 64 H220' />" +
      "<path class='tc-loop-graph-line fail' d='M220 64 C260 64 280 44 320 34 C340 30 350 30 360 34' />" +
      "<path class='tc-loop-graph-line rollback' d='M360 34 H440' />" +
      "<path class='tc-loop-graph-line keep' d='M220 64 C260 64 280 84 320 96 C340 102 350 102 360 96' />" +
      "<path class='tc-loop-graph-line keep' d='M360 96 H520' />" +
      "<path class='tc-loop-graph-line future' d='M520 96 H600' />" +
      "<circle class='tc-loop-graph-node base' cx='72' cy='64' r='7'></circle>" +
      "<circle class='tc-loop-graph-node fail' cx='360' cy='34' r='7'></circle>" +
      "<circle class='tc-loop-graph-node rollback' cx='440' cy='34' r='7'></circle>" +
      "<circle class='tc-loop-graph-node keep' cx='360' cy='96' r='7'></circle>" +
      "<circle class='tc-loop-graph-node keep' cx='520' cy='96' r='8'></circle>" +
      "<circle class='tc-loop-graph-node future' cx='600' cy='96' r='7'></circle>" +
      "<text class='tc-loop-graph-label' x='28' y='86'>基线</text>" +
      "<text class='tc-loop-graph-muted' x='28' y='102'>对照起点</text>" +
      "<text class='tc-loop-graph-label' x='328' y='18'>评分劣化</text>" +
      "<text class='tc-loop-graph-muted' x='312' y='30'>撤销本轮新增</text>" +
      "<text class='tc-loop-graph-label' x='330' y='114'>提升但不足</text>" +
      "<text class='tc-loop-graph-muted' x='312' y='128'>进入下一轮</text>" +
      "<text class='tc-loop-graph-label' x='494' y='114'>继续主线</text>" +
      "<text class='tc-loop-graph-muted' x='468' y='128'>补强工作集再评测</text>" +
      '</svg>'
    );
  }

  function renderTrainingLoopEvolutionSvg(loopData, selectedNodeId) {
    const payload = loopData && typeof loopData === 'object' ? loopData : null;
    const nodes = Array.isArray(payload && payload.nodes) ? payload.nodes : [];
    const edges = Array.isArray(payload && payload.edges) ? payload.edges : [];
    const selected = safe(selectedNodeId).trim();
    if (!nodes.length) {
      return (
        "<svg class='tc-loop-evolution-svg' viewBox='0 0 640 148' preserveAspectRatio='xMinYMid meet' aria-label='训练演进图'>" +
        "<text class='tc-loop-graph-muted' x='24' y='76'>暂无历史</text>" +
        '</svg>'
      );
    }

    const byId = trainingLoopNodesById(payload);
    let maxRound = 0;
    for (const node of nodes) {
      const ridx = Number(node && node.round_index ? node.round_index : 0);
      if (Number.isFinite(ridx)) maxRound = Math.max(maxRound, ridx);
    }
    const w = Math.max(720, 180 + (maxRound + 1) * 128);
    const h = 148;

    const pos = {};
    for (const node of nodes) {
      if (!node || typeof node !== 'object') continue;
      const nid = safe(node.node_id).trim();
      if (!nid) continue;
      const type = safe(node.node_type).toLowerCase();
      const ridx = Number(node.round_index ? node.round_index : 0);
      const col = type === 'baseline' ? 0 : Number.isFinite(ridx) ? Math.max(0, ridx) : 0;
      const x = 76 + col * 128;
      const y = type === 'baseline' ? 72 : type === 'rollback' ? 38 : 108;
      pos[nid] = { x, y };
    }

    const nodeClass = (node) => {
      const type = safe(node && node.node_type).toLowerCase();
      const status = safe(node && node.status).toLowerCase();
      let baseClass = 'keep';
      if (type === 'baseline') baseClass = 'base';
      if (type === 'rollback') baseClass = 'rollback';
      if (status === 'rolled_back') baseClass = 'fail';
      const nid = safe(node && node.node_id).trim();
      return 'tc-loop-graph-node ' + baseClass + (nid && nid === selected ? ' selected' : '');
    };

    const edgeClass = (edge) => {
      const kind = safe(edge && edge.kind).toLowerCase();
      if (kind === 'rollback') return 'rollback';
      const fromId = safe(edge && (edge.from || edge.from_id)).trim();
      const from = byId[fromId];
      if (from && safe(from.node_type).toLowerCase() === 'baseline') return 'base';
      return 'keep';
    };

    const edgePath = (fromId, toId) => {
      const a = pos[fromId];
      const b = pos[toId];
      if (!a || !b) return '';
      if (a.y === b.y) {
        return 'M' + a.x + ' ' + a.y + ' H' + b.x;
      }
      const cx1 = a.x + 44;
      const cx2 = b.x - 44;
      return 'M' + a.x + ' ' + a.y + ' C' + cx1 + ' ' + a.y + ' ' + cx2 + ' ' + b.y + ' ' + b.x + ' ' + b.y;
    };

    const edgeLines = edges
      .map((edge) => {
        if (!edge || typeof edge !== 'object') return '';
        const fromId = safe(edge.from || edge.from_id).trim();
        const toId = safe(edge.to || edge.to_id).trim();
        if (!fromId || !toId) return '';
        const d = edgePath(fromId, toId);
        if (!d) return '';
        return "<path class='tc-loop-graph-line " + edgeClass(edge) + "' d='" + d + "' />";
      })
      .join('');

    const circles = nodes
      .map((node) => {
        if (!node || typeof node !== 'object') return '';
        const nid = safe(node.node_id).trim();
        if (!nid || !pos[nid]) return '';
        const r = safe(payload && payload.current_node_id).trim() === nid ? 8 : 7;
        return (
          "<circle class='" +
          nodeClass(node) +
          "' data-node-id='" +
          nid +
          "' cx='" +
          pos[nid].x +
          "' cy='" +
          pos[nid].y +
          "' r='" +
          r +
          "'></circle>"
        );
      })
      .join('');

    const labels = nodes
      .map((node) => {
        if (!node || typeof node !== 'object') return '';
        const nid = safe(node.node_id).trim();
        if (!nid || !pos[nid]) return '';
        const title = safe(node.title).trim() || nid;
        const type = safe(node.node_type).toLowerCase();
        const x = pos[nid].x - 28;
        const y = type === 'rollback' ? pos[nid].y - 12 : pos[nid].y + 24;
        const mutedY = type === 'rollback' ? pos[nid].y + 6 : pos[nid].y + 40;
        const decision = safe(node.decision).trim();
        return (
          "<text class='tc-loop-graph-label' x='" +
          x +
          "' y='" +
          y +
          "'>" +
          short(title, 10) +
          '</text>' +
          (decision
            ? "<text class='tc-loop-graph-muted' x='" + x + "' y='" + mutedY + "'>" + short(decision, 12) + '</text>'
            : '')
        );
      })
      .join('');

    return (
      "<svg class='tc-loop-evolution-svg' viewBox='0 0 " +
      w +
      ' ' +
      h +
      "' preserveAspectRatio='xMinYMid meet' aria-label='训练演进图'>" +
      edgeLines +
      circles +
      labels +
      '</svg>'
    );
  }

  function renderTrainingLoopSection(title, desc, bodyHtml, extraClass) {
    return (
      "<section class='tc-loop-section-card" +
      (extraClass ? ' ' + safe(extraClass) : '') +
      "'>" +
      "<div class='tc-loop-section-head'>" +
      "<div class='tc-loop-section-title'>" +
      safe(title) +
      '</div>' +
      (desc ? "<div class='tc-loop-section-desc'>" + safe(desc) + '</div>' : '') +
      '</div>' +
      bodyHtml +
      '</section>'
    );
  }

  function renderTrainingLoopSummaryRows(rows) {
    return (
      "<div class='tc-loop-summary-list'>" +
      rows
        .map(
          (pair) =>
            "<div class='tc-loop-summary-item'><div class='tc-loop-summary-k'>" +
            safe(pair[0]) +
            "</div><div class='tc-loop-summary-v'>" +
            safe(pair[1]) +
            '</div></div>'
        )
        .join('') +
      '</div>'
    );
  }

  function renderTrainingLoopBulletList(items) {
    const rows = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!rows.length) return "<div class='tc-loop-empty'>暂无数据</div>";
    return "<ul class='tc-loop-bullet-list'>" + rows.map((item) => '<li>' + safe(item) + '</li>').join('') + '</ul>';
  }

  function renderTrainingLoopHistoryList(loopCtx) {
    const ctx = loopCtx && typeof loopCtx === 'object' ? loopCtx : {};
    const nodes = Array.isArray(ctx.nodes) ? ctx.nodes.slice() : [];
    if (!nodes.length) return "<div class='tc-loop-empty'>暂无历史节点</div>";
    nodes.sort((left, right) => {
      const a = Number(left && left.round_index ? left.round_index : 0);
      const b = Number(right && right.round_index ? right.round_index : 0);
      if (a !== b) return a - b;
      return safe(left && left.node_id).localeCompare(safe(right && right.node_id));
    });
    return (
      "<div class='tc-loop-history-list'>" +
      nodes
        .map((node) => {
          const title = safe(node && node.title).trim() || safe(node && node.node_id).trim() || '-';
          const roundText =
            Object.prototype.hasOwnProperty.call(node || {}, 'round_index')
              ? '第 ' + safe(node.round_index) + ' 轮'
              : '-';
          return (
            "<div class='tc-loop-history-item'>" +
            "<div class='tc-loop-history-title'>" +
            safe(title) +
            '</div>' +
            "<div class='tc-loop-history-meta'>" +
            safe(roundText) +
            ' · ' +
            safe(statusText(node && node.status ? node.status : '-')) +
            '</div>' +
            "<div class='tc-loop-history-text'>判定：" +
            safe(node && node.decision ? node.decision : '-') +
            '</div>' +
            "<div class='tc-loop-history-text'>下一步：" +
            safe(node && node.next_action ? node.next_action : '-') +
            '</div>' +
            '</div>'
          );
        })
        .join('') +
      '</div>'
    );
  }
