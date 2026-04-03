  // Training center queue rendering and loop runtime coordination.

  function tcLoopTimeAgo(isoText) {
    const raw = safe(isoText).trim();
    if (!raw) return '-';
    const ts = Date.parse(raw);
    if (!Number.isFinite(ts)) return raw;
    const diffMs = Math.max(0, Date.now() - ts);
    const min = Math.floor(diffMs / 60000);
    if (min < 1) return '刚刚';
    if (min < 60) return String(min) + ' 分钟前';
    const hours = Math.floor(min / 60);
    if (hours < 24) return String(hours) + ' 小时前';
    const days = Math.floor(hours / 24);
    return String(days) + ' 天前';
  }

  function tcLoopQueueStatusChip(status) {
    const key = safe(status).toLowerCase();
    if (key === 'running') return "<span class='tc-loop-chip blue'>进行中</span>";
    if (key === 'queued') return "<span class='tc-loop-chip'>待评测</span>";
    if (key === 'done') return "<span class='tc-loop-chip green'>已通过</span>";
    if (key === 'removed') return "<span class='tc-loop-chip red'>已移除</span>";
    return "<span class='tc-loop-chip'>" + safe(status || '-') + '</span>';
  }

  function trainingLoopQueueFilterLabel(filterKey) {
    const key = normalizeTrainingLoopQueueFilter(filterKey);
    if (key === 'running') return '进行中';
    if (key === 'queued') return '待评测';
    if (key === 'done') return '已通过';
    if (key === 'removed') return '已移除';
    return '全部';
  }

  function trainingLoopQueueCounts(rows) {
    const counts = { all: 0, running: 0, queued: 0, done: 0, removed: 0 };
    (Array.isArray(rows) ? rows : []).forEach((row) => {
      counts.all += 1;
      const key = normalizeTrainingLoopQueueFilter(row && row.status);
      if (Object.prototype.hasOwnProperty.call(counts, key)) {
        counts[key] += 1;
      }
    });
    return counts;
  }

  function trainingLoopQueueTitle(row) {
    return safe(row && (row.capability_goal || row.agent_name || row.target_agent_id || row.queue_task_id)).trim() || '-';
  }

  function updateTrainingLoopQueueSummary(rows, filtered, filterKey, keyword) {
    const counts = trainingLoopQueueCounts(rows);
    const summaryNode = $('tcLoopQueueSummary');
    if (summaryNode) {
      const parts = ['共 ' + safe(counts.all) + ' 个优化会话'];
      if (filterKey !== 'all') {
        parts.push(trainingLoopQueueFilterLabel(filterKey) + ' ' + safe(filtered.length) + ' 个');
      } else if (keyword) {
        parts.push('匹配 ' + safe(filtered.length) + ' 个');
      } else {
        parts.push('支持重命名、回看和二次确认移除');
      }
      summaryNode.textContent = parts.join(' · ');
    }
    const filterRow = $('tcLoopQueueFilterRow');
    if (!filterRow) return;
    filterRow.querySelectorAll('button[data-filter]').forEach((btn) => {
      const btnKey = normalizeTrainingLoopQueueFilter(btn.getAttribute('data-filter'));
      btn.classList.toggle('active', btnKey === filterKey);
      const label = trainingLoopQueueFilterLabel(btnKey);
      const count = Object.prototype.hasOwnProperty.call(counts, btnKey) ? counts[btnKey] : 0;
      btn.innerHTML =
        "<span class='tc-loop-filter-text'>" +
        safe(label) +
        "</span><span class='tc-loop-filter-count'>" +
        safe(count) +
        '</span>';
      btn.setAttribute('aria-label', label + ' ' + safe(count) + ' 个');
    });
  }

  function renderTrainingCenterQueue() {
    const box = $('tcQueueList');
    if (!box) return;
    box.innerHTML = '';
    const keyword = safe($('tcLoopTaskSearchInput') ? $('tcLoopTaskSearchInput').value : '').trim().toLowerCase();
    const rows = Array.isArray(state.tcQueue) ? state.tcQueue : [];

    const filterKey = normalizeTrainingLoopQueueFilter(state.tcLoopQueueFilter);
    state.tcLoopQueueFilter = filterKey;
    const filterRow = $('tcLoopQueueFilterRow');
    if (filterRow) {
      filterRow.querySelectorAll('button[data-filter]').forEach((btn) => {
        const btnKey = normalizeTrainingLoopQueueFilter(btn.getAttribute('data-filter'));
        btn.classList.toggle('active', btnKey === filterKey);
      });
    }

    let filtered = rows;
    if (filterKey !== 'all') {
      filtered = filtered.filter((row) => safe(row && row.status).toLowerCase() === filterKey);
    }
    if (keyword) {
      filtered = filtered.filter((row) => {
        const parts = [
          safe(row && row.agent_name),
          safe(row && row.target_agent_id),
          safe(row && row.queue_task_id),
          safe(row && row.capability_goal),
          safe(row && row.priority),
          safe(row && row.status),
        ]
          .join(' ')
          .toLowerCase();
        return parts.includes(keyword);
      });
    }

    updateTrainingLoopQueueSummary(rows, filtered, filterKey, keyword);

    const createItem = document.createElement('div');
    createItem.className =
      'tc-queue-item tc-loop-create-item' +
      (normalizeTrainingLoopMode(state.tcLoopMode) === 'create' ? ' active' : '');
    createItem.innerHTML =
      "<div class='tc-loop-task-top'>" +
      "<div class='tc-loop-task-head'>" +
      "<div class='tc-loop-task-target'>训练优化对话入口</div>" +
      "<div class='tc-loop-task-name'>发起新优化会话</div>" +
      "<div class='tc-loop-task-id'>保持单聊天壳，在中部直接收敛目标、能力和验收标准</div>" +
      '</div>' +
      "<div class='tc-loop-task-ops'><span class='tc-loop-chip green'>对话式</span></div>" +
      '</div>' +
      "<div class='tc-loop-task-caption'>默认进入训练优化对话工作台；目标收敛、能力对象草案和启动动作都在同一界面完成。</div>";
    createItem.onclick = () => {
      enterTrainingLoopCreateMode();
    };
    box.appendChild(createItem);

    if (!filtered.length) {
      const empty = document.createElement('div');
      empty.className = 'tc-empty';
      empty.textContent = keyword ? '没有匹配的优化会话' : '优化会话列表为空';
      box.appendChild(empty);
      return;
    }
    for (const row of filtered) {
      const queueTaskId = safe(row && row.queue_task_id).trim();
      if (!queueTaskId) continue;
      const rowTitle = trainingLoopQueueTitle(row);
      const targetText = safe(row.agent_name || row.target_agent_id || '-').trim() || '-';
      const acceptanceText = safe(row.acceptance_criteria).trim();
      const taskCount = Array.isArray(row.training_tasks) ? row.training_tasks.length : 0;
      const latestRunLabel = safe(row.latest_run_status).trim()
        ? statusText(row.latest_run_status)
        : statusText(row.status || '-');
      const latestUpdateText = tcLoopTimeAgo(row.latest_run_updated_at || row.enqueued_at || '');
      const captionText =
        acceptanceText ||
        (taskCount ? '首轮工作集共 ' + safe(taskCount) + ' 项' : '') ||
        '当前未填写验收标准或工作集摘要';
      const node = document.createElement('div');
      node.className =
        'tc-queue-item' +
        (normalizeTrainingLoopMode(state.tcLoopMode) === 'status' &&
        safe(state.tcLoopSelectedQueueTaskId).trim() === queueTaskId
          ? ' active'
          : '');
      const rowStatus = safe(row.status).toLowerCase();
      node.onclick = () => {
        selectTrainingLoopQueueTask(queueTaskId);
      };

      const top = document.createElement('div');
      top.className = 'tc-loop-task-top';
      const head = document.createElement('div');
      head.className = 'tc-loop-task-head';
      const target = document.createElement('div');
      target.className = 'tc-loop-task-target';
      target.textContent = '目标角色：' + targetText;
      const name = document.createElement('div');
      name.className = 'tc-loop-task-name';
      name.textContent = rowTitle;
      name.title = rowTitle;
      const queueId = document.createElement('div');
      queueId.className = 'tc-loop-task-id';
      queueId.textContent = queueTaskId;
      head.appendChild(target);
      head.appendChild(name);
      head.appendChild(queueId);
      top.appendChild(head);

      const ops = document.createElement('div');
      ops.className = 'tc-loop-task-ops';
      const renameBtn = document.createElement('button');
      renameBtn.className = 'alt';
      renameBtn.type = 'button';
      renameBtn.textContent = '重命名';
      renameBtn.disabled = rowStatus === 'removed';
      renameBtn.onclick = (event) => {
        if (event) event.stopPropagation();
        const currentTitle = trainingLoopQueueTitle(row);
        const nextTitle = window.prompt('请输入新的任务名称', currentTitle);
        if (nextTitle === null) return;
        renameTrainingCenterQueueTask(queueTaskId, nextTitle).catch((err) => {
          setTrainingCenterError(err.message || String(err));
        });
      };
      ops.appendChild(renameBtn);

      const removeBtn = document.createElement('button');
      removeBtn.className = 'bad';
      removeBtn.type = 'button';
      removeBtn.textContent = '移除';
      removeBtn.disabled = rowStatus === 'removed';
      removeBtn.onclick = (event) => {
        if (event) event.stopPropagation();
        const confirmed = window.confirm(
          ['确认移除该优化会话？', '会话：' + rowTitle, '目标角色：' + targetText, '移除后如需恢复，请重新创建或重新入队。'].join(
            '\n'
          )
        );
        if (!confirmed) return;
        removeTrainingCenterQueueTask(queueTaskId).catch((err) => {
          setTrainingCenterError(err.message || String(err));
        });
      };
      ops.appendChild(removeBtn);

      const executeBtn = document.createElement('button');
      executeBtn.type = 'button';
      executeBtn.textContent = '执行';
      executeBtn.disabled = !row.can_execute || rowStatus !== 'queued';
      executeBtn.onclick = (event) => {
        if (event) event.stopPropagation();
        executeTrainingCenterQueueTask(queueTaskId).catch((err) => {
          setTrainingCenterError(err.message || String(err));
        });
      };
      ops.appendChild(executeBtn);

      top.appendChild(ops);
      node.appendChild(top);

      const caption = document.createElement('div');
      caption.className = 'tc-loop-task-caption';
      caption.textContent = captionText;
      node.appendChild(caption);

      const chipRow = document.createElement('div');
      chipRow.className = 'tc-loop-chip-row';
      const roundIndex =
        state.tcLoopRoundIndexByQueueTaskId && typeof state.tcLoopRoundIndexByQueueTaskId === 'object'
          ? Number(state.tcLoopRoundIndexByQueueTaskId[queueTaskId] || 0)
          : 0;
      chipRow.innerHTML =
        tcLoopQueueStatusChip(row.status) +
        (Number.isFinite(roundIndex) && roundIndex > 0
          ? "<span class='tc-loop-chip orange'>第 " + safe(roundIndex) + ' 轮</span>'
          : "<span class='tc-loop-chip'>第 ? 轮</span>") +
        (safe(row.priority).trim() ? "<span class='tc-loop-chip'>" + safe(row.priority) + '</span>' : '') +
        (row.similar_flag ? "<span class='tc-loop-chip orange'>相似任务</span>" : '') +
        (row.is_test_data ? "<span class='tc-loop-chip'>测试数据</span>" : '');
      node.appendChild(chipRow);

      const stats = document.createElement('div');
      stats.className = 'tc-loop-task-stats';
      stats.innerHTML =
        "<div class='tc-loop-task-stat'><span>工作集</span><strong>" +
        safe(taskCount) +
        " 项</strong></div>" +
        "<div class='tc-loop-task-stat'><span>最近回执</span><strong>" +
        safe(latestRunLabel) +
        '</strong></div>' +
        "<div class='tc-loop-task-stat'><span>最近更新</span><strong>" +
        safe(latestUpdateText) +
        '</strong></div>';
      node.appendChild(stats);

      const meta = document.createElement('div');
      meta.className = 'tc-loop-task-meta';
      meta.textContent = '当前任务 ID：' + queueTaskId;
      node.appendChild(meta);
      box.appendChild(node);
    }
  }

  async function refreshTrainingCenterQueue(includeRemoved) {
    const includeRemovedFlag = includeRemoved === true;
    const queueUrl = withTestDataQuery('/api/training/queue?include_removed=' + (includeRemovedFlag ? '1' : '0'));
    const data = await getJSON(queueUrl);
    const items = Array.isArray(data.items) ? data.items : [];
    state.tcQueue = items.filter((row) => !!state.showTestData || !row || !row.is_test_data);
    renderTrainingCenterQueue();
    renderTrainingLoop();
  }
