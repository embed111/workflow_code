  function assignmentRunTone(value) {
    const key = safe(value).trim().toLowerCase();
    if (key === 'running' || key === 'starting') return 'running';
    if (key === 'failed' || key === 'cancelled') return 'fail';
    if (key === 'succeeded') return 'done';
    return 'future';
  }

  function assignmentRunStatusText(run) {
    const status = safe(run && run.status).trim().toLowerCase();
    const text = safe(run && run.status_text).trim();
    if (text) return text;
    if (status === 'starting') return '启动中';
    if (status === 'running') return '执行中';
    if (status === 'failed') return '失败';
    if (status === 'cancelled') return '已取消';
    if (status === 'succeeded') return '已完成';
    return '-';
  }

  function assignmentSectionMetaTextHtml(text) {
    const value = safe(text).trim();
    if (!value) return '';
    return "<span class='assignment-section-meta-text'>" + escapeHtml(value) + '</span>';
  }

  function assignmentSelectedNodeKey() {
    const selected = selectedAssignmentNode();
    return safe((selected && selected.node_id) || state.assignmentSelectedNodeId).trim();
  }

  function assignmentResolveOpenState(store, key, fallback) {
    const lookup = safe(key).trim();
    if (!lookup) return !!fallback;
    if (Object.prototype.hasOwnProperty.call(store, lookup)) {
      return !!store[lookup];
    }
    return !!fallback;
  }

  function assignmentDetailSectionStateKey(sectionKey) {
    const nodeId = assignmentSelectedNodeKey();
    const key = safe(sectionKey).trim();
    return nodeId && key ? nodeId + '::' + key : '';
  }

  function assignmentExecutionPanelStateKey(panelKey, runIdOverride) {
    const nodeId = assignmentSelectedNodeKey();
    const currentChain = assignmentExecutionChainPayload();
    const currentRun = assignmentExecutionLatestRun(currentChain);
    const runId = safe(runIdOverride || (currentRun && currentRun.run_id)).trim();
    const key = safe(panelKey).trim();
    return nodeId && runId && key ? nodeId + '::' + runId + '::' + key : '';
  }

  function assignmentExecutionScrollStateKey(panelKey, runIdOverride) {
    return assignmentExecutionPanelStateKey(panelKey, runIdOverride);
  }

  function assignmentExecutionScrollAttr(panelKey, runIdOverride) {
    const key = assignmentExecutionScrollStateKey(panelKey, runIdOverride);
    return key ? " data-assignment-scroll-key='" + escapeHtml(key) + "'" : '';
  }

  function captureAssignmentExecutionScrollState(container) {
    const root = container || $('assignmentDetailBody');
    if (!root) return;
    root.querySelectorAll('[data-assignment-scroll-key]').forEach((node) => {
      const key = safe(node.getAttribute('data-assignment-scroll-key')).trim();
      if (!key) return;
      const maxTop = Math.max(0, Number(node.scrollHeight || 0) - Number(node.clientHeight || 0));
      const top = Math.max(0, Math.min(maxTop, Number(node.scrollTop || 0)));
      state.assignmentExecutionScrollState[key] = {
        top: top,
        stickBottom: maxTop > 0 && (maxTop - top) <= 12,
      };
    });
  }

  function restoreAssignmentExecutionScrollState(container) {
    const root = container || $('assignmentDetailBody');
    if (!root) return;
    root.querySelectorAll('[data-assignment-scroll-key]').forEach((node) => {
      const key = safe(node.getAttribute('data-assignment-scroll-key')).trim();
      if (!key) return;
      const saved = state.assignmentExecutionScrollState[key];
      if (!saved || typeof saved !== 'object') return;
      const maxTop = Math.max(0, Number(node.scrollHeight || 0) - Number(node.clientHeight || 0));
      if (saved.stickBottom) {
        node.scrollTop = maxTop;
        return;
      }
      node.scrollTop = Math.max(0, Math.min(maxTop, Number(saved.top || 0)));
    });
  }

  function bindAssignmentDetailToggleState(container) {
    const root = container || $('assignmentDetailBody');
    if (!root) return;
    root.querySelectorAll('details[data-assignment-detail-key]').forEach((node) => {
      node.addEventListener('toggle', () => {
        const key = safe(node.getAttribute('data-assignment-detail-key')).trim();
        if (!key) return;
        state.assignmentDetailSectionOpen[key] = !!node.open;
      });
    });
    root.querySelectorAll('details[data-assignment-run-key]').forEach((node) => {
      node.addEventListener('toggle', () => {
        const key = safe(node.getAttribute('data-assignment-run-key')).trim();
        if (!key) return;
        state.assignmentExecutionPanelOpen[key] = !!node.open;
      });
    });
  }

  function assignmentDetailSectionHtml(title, bodyHtml, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const sectionClass = 'assignment-detail-section' +
      (safe(opts.section_class).trim() ? ' ' + safe(opts.section_class).trim() : '');
    const bodyClass = 'assignment-detail-section-body' +
      (safe(opts.body_class).trim() ? ' ' + safe(opts.body_class).trim() : '');
    const metaHtml = safe(opts.meta_html);
    const description = safe(opts.description).trim();
    const stateKey = assignmentDetailSectionStateKey(opts.state_key);
    const isOpen = assignmentResolveOpenState(state.assignmentDetailSectionOpen, stateKey, opts.open);
    return (
      "<details class='" + sectionClass + "'" + (stateKey ? " data-assignment-detail-key='" + escapeHtml(stateKey) + "'" : '') + (isOpen ? ' open' : '') + '>' +
      '<summary>' +
      "<span class='assignment-detail-section-heading'>" +
      "<span class='assignment-detail-section-title'>" + escapeHtml(title) + '</span>' +
      (description
        ? "<span class='assignment-detail-section-desc'>" + escapeHtml(description) + '</span>'
        : '') +
      '</span>' +
      (metaHtml ? "<span class='assignment-detail-section-side'>" + metaHtml + '</span>' : '') +
      '</summary>' +
      "<div class='" + bodyClass + "'>" + safe(bodyHtml) + '</div>' +
      '</details>'
    );
  }

  function assignmentStatHtml(label, valueHtml) {
    return (
      "<div class='assignment-stat'>" +
      "<div class='assignment-stat-k'>" + escapeHtml(label) + '</div>' +
      "<div class='assignment-stat-v'>" + safe(valueHtml) + '</div>' +
      '</div>'
    );
  }

  function assignmentNodeListHtml(rows, emptyText) {
    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) {
      return "<div class='assignment-empty-inline'>" + escapeHtml(safe(emptyText).trim() || '-') + '</div>';
    }
    return (
      "<div class='assignment-node-list'>" +
      items.map((item) => (
        "<div class='assignment-node-item'>" +
        escapeHtml(safe(item && (item.node_name || item.node_id)).trim() || '-') +
        '</div>'
      )).join('') +
      '</div>'
    );
  }

  function assignmentExecutionPanelHtml(title, bodyHtml, openByDefault, detailClass, panelKey, runIdOverride) {
    const className = 'assignment-run-details' + (safe(detailClass).trim() ? ' ' + safe(detailClass).trim() : '');
    const stateKey = assignmentExecutionPanelStateKey(panelKey, runIdOverride);
    const isOpen = assignmentResolveOpenState(state.assignmentExecutionPanelOpen, stateKey, openByDefault);
    return (
      "<details class='" + className + "'" + (stateKey ? " data-assignment-run-key='" + escapeHtml(stateKey) + "'" : '') + (isOpen ? ' open' : '') + '>' +
      "<summary>" + escapeHtml(title) + '</summary>' +
      safe(bodyHtml) +
      '</details>'
    );
  }

  function assignmentExecutionContentBlockHtml(title, text, ref, openByDefault, detailClass, scrollClass) {
    const content = safe(text);
    const refText = safe(ref).trim();
    const scrollName = 'assignment-run-scrollbox' + (safe(scrollClass).trim() ? ' ' + safe(scrollClass).trim() : '');
    const scrollAttr = assignmentExecutionScrollAttr(title);
    return assignmentExecutionPanelHtml(
      title,
      "<div class='" + scrollName + "'" + scrollAttr + '>' +
      (content
        ? "<pre class='assignment-run-pre'>" + escapeHtml(content) + '</pre>'
        : "<div class='assignment-run-empty'>暂无内容</div>") +
      "<div class='assignment-run-ref'>引用: " + escapeHtml(refText || '-') + '</div>' +
      '</div>' +
      '',
      openByDefault,
      detailClass,
      title
    );
  }

  function assignmentExecutionEventsHtml(events) {
    const rows = Array.isArray(events) ? events : [];
    if (!rows.length) {
      return "<div class='assignment-run-empty'>暂无执行事件。</div>";
    }
    return (
      "<div class='assignment-run-event-list'>" +
      rows.map((item) => {
        const detailText = formatJsonLines(item && item.detail ? item.detail : {});
        const hasDetail = safe(detailText).trim() && safe(detailText).trim() !== '{}';
        return (
          "<div class='assignment-run-event-item'>" +
          "<div class='assignment-run-event-top'>" +
          "<span class='assignment-run-event-type'>" + escapeHtml(safe(item && item.event_type).trim() || 'event') + '</span>' +
          "<span class='assignment-run-event-time'>" + escapeHtml(safe(item && item.created_at).trim() ? assignmentFormatBeijingTime(item.created_at) : '-') + '</span>' +
          '</div>' +
          "<div class='assignment-run-event-msg'>" + escapeHtml(safe(item && item.message).trim() || '-') + '</div>' +
          (hasDetail
            ? (
              "<details class='assignment-run-details assignment-run-details-inline'>" +
              "<summary>事件明细</summary>" +
              "<pre class='assignment-run-pre'>" + escapeHtml(detailText) + '</pre>' +
              '</details>'
            )
            : '') +
          '</div>'
        );
      }).join('') +
      '</div>'
    );
  }

  function assignmentLatestEventHtml(run) {
    const message = escapeHtml(safe(run && run.latest_event).trim() || '-');
    const eventAt = safe(run && run.latest_event_at).trim();
    if (!eventAt) return message;
    return (
      "<div>" + message + '</div>' +
      "<div class='hint'>发生时间: " + escapeHtml(assignmentFormatBeijingTime(eventAt)) + '</div>'
    );
  }

  function assignmentExecutionHistoryHtml(runs) {
    const rows = Array.isArray(runs) ? runs.slice(1) : [];
    if (!rows.length) return '';
    const scrollAttr = assignmentExecutionScrollAttr('history');
    return assignmentExecutionPanelHtml(
      '历史运行批次',
      "<div class='assignment-run-history-list'" + scrollAttr + '>' +
      rows.map((run) => (
        "<div class='assignment-run-history-item'>" +
        "<div class='assignment-run-history-top'>" +
        "<span class='assignment-run-history-id'>" + escapeHtml(safe(run && run.run_id).trim() || '-') + '</span>' +
        "<span class='assignment-chip " + escapeHtml(assignmentRunTone(run && run.status)) + "'>" + escapeHtml(assignmentRunStatusText(run)) + '</span>' +
        '</div>' +
        "<div class='assignment-run-history-msg'>" +
        '最近事件: ' + assignmentLatestEventHtml(run) +
        '<br/>' +
        '开始时间: ' + escapeHtml(safe(run && run.started_at).trim() ? assignmentFormatBeijingTime(run.started_at) : '-') +
        '<br/>' +
        '结果引用: ' + escapeHtml(safe(run && run.result_ref).trim() || '-') +
        '</div>' +
        '</div>'
      )).join('') +
      '</div>' +
      '',
      false,
      'assignment-run-details-scroll assignment-run-details-history',
      'history'
    );
  }

  function assignmentExecutionChainHtml() {
    const chain = assignmentExecutionChainPayload();
    const latestRun = assignmentExecutionLatestRun(chain);
    const recentRuns = Array.isArray(chain.recent_runs) ? chain.recent_runs : [];
    const latestRunId = safe(latestRun.run_id).trim();
    const pollMode = safe(chain.poll_mode).trim() || safe(assignmentExecutionSettingsPayload().poll_mode).trim() || 'event_stream';
    const pollIntervalMs = Math.max(
      250,
      Number(chain.poll_interval_ms || assignmentExecutionSettingsPayload().poll_interval_ms || 450),
    );
    const refreshModeText = assignmentExecutionRefreshModeText(pollMode);
    if (!latestRunId) {
      return assignmentDetailSectionHtml(
        '执行链路',
        "<div class='hint'>当前任务尚未产生真实运行批次。若任务已失败且没有 run_id，请优先查看调度留痕或工作区映射错误。</div>" +
        "<div class='assignment-run-note'>刷新方式: " + escapeHtml(refreshModeText) + ' · 断线兜底 ' + escapeHtml(String(pollIntervalMs)) + "ms</div>" +
        '',
        {
          open: true,
          section_class: 'assignment-execution-section',
          state_key: 'execution-chain',
          meta_html: assignmentSectionMetaTextHtml('未生成运行批次'),
        }
      );
    }
    const latestStatus = safe(latestRun.status).trim().toLowerCase();
    const eventsOpen = latestStatus === 'starting' || latestStatus === 'running';
    const stderrOpen = latestStatus === 'failed' && safe(latestRun.stderr_text).trim().length > 0;
    const resultOpen =
      latestStatus !== 'starting' &&
      latestStatus !== 'running' &&
      safe(latestRun.result_text).trim().length > 0;
    const executionBody =
      "<div class='assignment-detail-grid assignment-detail-grid-tight'>" +
      assignmentStatHtml('执行通道', escapeHtml(safe(latestRun.provider).trim() || '-')) +
      assignmentStatHtml('运行批次', escapeHtml(latestRunId)) +
      assignmentStatHtml('最新事件', assignmentLatestEventHtml(latestRun)) +
      assignmentStatHtml('目标工作区', escapeHtml(safe(latestRun.workspace_path).trim() || '-')) +
      assignmentStatHtml('调用命令', escapeHtml(safe(latestRun.command_summary).trim() || '-')) +
      assignmentStatHtml('开始时间', escapeHtml(safe(latestRun.started_at).trim() ? assignmentFormatBeijingTime(latestRun.started_at) : '-')) +
      assignmentStatHtml('结束时间', escapeHtml(safe(latestRun.finished_at).trim() ? assignmentFormatBeijingTime(latestRun.finished_at) : '-')) +
      assignmentStatHtml('stdout 引用', escapeHtml(safe(latestRun.stdout_ref).trim() || '-')) +
      assignmentStatHtml('stderr 引用', escapeHtml(safe(latestRun.stderr_ref).trim() || '-')) +
      assignmentStatHtml('result 引用', escapeHtml(safe(latestRun.result_ref).trim() || '-')) +
      assignmentStatHtml('事件数', escapeHtml(String(Number(latestRun.event_count || 0)))) +
      '</div>' +
      "<div class='assignment-execution-stack'>" +
      assignmentExecutionContentBlockHtml('完整提示词', latestRun.prompt_text, latestRun.prompt_ref, false, 'assignment-run-details-scroll assignment-run-details-prompt', 'assignment-run-scrollbox-prompt') +
      assignmentExecutionPanelHtml(
        '执行过程',
        "<div class='assignment-run-scrollbox assignment-run-scrollbox-events'" + assignmentExecutionScrollAttr('events', latestRunId) + '>' +
        assignmentExecutionEventsHtml(latestRun.events) +
        '</div>',
        eventsOpen,
        'assignment-run-details-scroll assignment-run-details-events',
        'events',
        latestRunId
      ) +
      assignmentExecutionContentBlockHtml('stdout', latestRun.stdout_text, latestRun.stdout_ref, false, 'assignment-run-details-scroll') +
      assignmentExecutionContentBlockHtml('stderr', latestRun.stderr_text, latestRun.stderr_ref, stderrOpen, 'assignment-run-details-scroll') +
      assignmentExecutionContentBlockHtml('最终结果', latestRun.result_text, latestRun.result_ref, resultOpen, 'assignment-run-details-scroll') +
      assignmentExecutionHistoryHtml(recentRuns) +
      '</div>' +
      '';
    return assignmentDetailSectionHtml(
      '执行链路',
      executionBody,
      {
        open: true,
        section_class: 'assignment-execution-section',
        state_key: 'execution-chain',
        meta_html:
          "<span class='assignment-chip " + escapeHtml(assignmentRunTone(latestRun.status)) + "'>" +
          escapeHtml(assignmentRunStatusText(latestRun)) +
          '</span>' +
          assignmentSectionMetaTextHtml('刷新 ' + refreshModeText + ' · 兜底 ' + String(pollIntervalMs) + 'ms'),
      }
    );
  }

  function assignmentExecutionMode(detailOverride) {
    const detail = detailOverride && typeof detailOverride === 'object' ? detailOverride : assignmentDetailPayload();
    const chain = detail.execution_chain && typeof detail.execution_chain === 'object'
      ? detail.execution_chain
      : {};
    return safe(chain.poll_mode || assignmentExecutionSettingsPayload().poll_mode).trim().toLowerCase() || 'event_stream';
  }

  function assignmentExecutionShouldPoll(detailOverride) {
    const detail = detailOverride && typeof detailOverride === 'object' ? detailOverride : assignmentDetailPayload();
    const chain = detail.execution_chain && typeof detail.execution_chain === 'object'
      ? detail.execution_chain
      : {};
    const latestRun = assignmentExecutionLatestRun(chain);
    const status = safe(latestRun.status).trim().toLowerCase();
    return !!selectedAssignmentTicketId() &&
      !!safe((detail.selected_node || {}).node_id).trim() &&
      (status === 'starting' || status === 'running');
  }

  function assignmentExecutionStatusSignature(detailOverride) {
    const detail = detailOverride && typeof detailOverride === 'object' ? detailOverride : assignmentDetailPayload();
    const selectedNode = detail.selected_node && typeof detail.selected_node === 'object'
      ? detail.selected_node
      : {};
    const chain = detail.execution_chain && typeof detail.execution_chain === 'object'
      ? detail.execution_chain
      : {};
    const latestRun = assignmentExecutionLatestRun(chain);
    return [
      safe(selectedNode.node_id).trim(),
      safe(selectedNode.status).trim().toLowerCase(),
      safe(latestRun.run_id).trim(),
      safe(latestRun.status).trim().toLowerCase(),
    ].join('::');
  }

  function assignmentExecutionPollInterval(detailOverride) {
    const detail = detailOverride && typeof detailOverride === 'object' ? detailOverride : assignmentDetailPayload();
    const chain = detail.execution_chain && typeof detail.execution_chain === 'object'
      ? detail.execution_chain
      : {};
    return Math.max(
      250,
      Math.min(
        1000,
        Number(chain.poll_interval_ms || assignmentExecutionSettingsPayload().poll_interval_ms || 450),
      ),
    );
  }

  function stopAssignmentExecutionPoller() {
    if (state.assignmentExecutionPoller) {
      window.clearInterval(state.assignmentExecutionPoller);
      state.assignmentExecutionPoller = 0;
    }
    state.assignmentExecutionPollBusy = false;
  }

  function stopAssignmentExecutionEventStream() {
    const source = state.assignmentExecutionEventSource;
    state.assignmentExecutionEventSource = null;
    state.assignmentExecutionEventSourceTicketId = '';
    state.assignmentExecutionEventSourceConnected = false;
    state.assignmentExecutionEventSourceSeq = 0;
    if (source && typeof source.close === 'function') {
      try {
        source.close();
      } catch (_) {
        // ignore close errors
      }
    }
  }

  function stopAssignmentExecutionRealtime() {
    stopAssignmentExecutionEventStream();
    stopAssignmentExecutionPoller();
    if (state.assignmentExecutionRealtimeRefreshTimer) {
      window.clearTimeout(state.assignmentExecutionRealtimeRefreshTimer);
      state.assignmentExecutionRealtimeRefreshTimer = 0;
    }
    state.assignmentExecutionRealtimeRefreshBusy = false;
    state.assignmentExecutionRealtimeRefreshPending = false;
    state.assignmentExecutionRealtimeRefreshGraph = false;
    state.assignmentExecutionRealtimeRefreshDetail = false;
  }

  function assignmentExecutionShouldStream(detailOverride) {
    const activeTab = document.querySelector('.tab.active');
    const activeTabName = safe(activeTab && activeTab.getAttribute('data-tab')).trim();
    return activeTabName === 'task-center' &&
      assignmentExecutionMode(detailOverride) === 'event_stream' &&
      !!selectedAssignmentTicketId() &&
      typeof window.EventSource === 'function';
  }

  function assignmentExecutionStreamUrl(ticketId) {
    return withTestDataQuery('/api/assignments/' + encodeURIComponent(ticketId) + '/events');
  }

  function assignmentExecutionParseStreamEvent(rawEvent) {
    try {
      const payload = JSON.parse(safe(rawEvent && rawEvent.data));
      return payload && typeof payload === 'object' ? payload : {};
    } catch (_) {
      return {};
    }
  }

  async function flushAssignmentExecutionRealtimeRefresh() {
    if (state.assignmentExecutionRealtimeRefreshBusy) {
      state.assignmentExecutionRealtimeRefreshPending = true;
      return;
    }
    const ticketId = selectedAssignmentTicketId();
    const selectedNodeId = safe(state.assignmentSelectedNodeId).trim();
    const shouldRefreshGraph = !!state.assignmentExecutionRealtimeRefreshGraph;
    const shouldRefreshDetail = !!state.assignmentExecutionRealtimeRefreshDetail;
    state.assignmentExecutionRealtimeRefreshGraph = false;
    state.assignmentExecutionRealtimeRefreshDetail = false;
    state.assignmentExecutionRealtimeRefreshBusy = true;
    state.assignmentExecutionRealtimeRefreshPending = false;
    try {
      if (!ticketId) return;
      if (shouldRefreshGraph) {
        await refreshAssignmentGraphData({
          ticketId: ticketId,
          silent: true,
          skipDetail: !shouldRefreshDetail,
        });
        return;
      }
      if (shouldRefreshDetail && selectedNodeId) {
        await refreshAssignmentDetail(selectedNodeId, { skipGraphRender: true });
        return;
      }
      if (shouldRefreshDetail) {
        await refreshAssignmentGraphData({ ticketId: ticketId, silent: true });
      }
    } catch (_) {
      // keep realtime refresh best-effort
    } finally {
      state.assignmentExecutionRealtimeRefreshBusy = false;
      if (
        state.assignmentExecutionRealtimeRefreshPending ||
        state.assignmentExecutionRealtimeRefreshGraph ||
        state.assignmentExecutionRealtimeRefreshDetail
      ) {
        state.assignmentExecutionRealtimeRefreshPending = false;
        void flushAssignmentExecutionRealtimeRefresh();
      }
    }
  }

  function scheduleAssignmentExecutionRealtimeRefresh(options) {
    const opts = options && typeof options === 'object' ? options : {};
    state.assignmentExecutionRealtimeRefreshGraph = !!state.assignmentExecutionRealtimeRefreshGraph || !!opts.graph;
    state.assignmentExecutionRealtimeRefreshDetail = !!state.assignmentExecutionRealtimeRefreshDetail || !!opts.detail;
    if (state.assignmentExecutionRealtimeRefreshTimer) {
      return;
    }
    state.assignmentExecutionRealtimeRefreshTimer = window.setTimeout(() => {
      state.assignmentExecutionRealtimeRefreshTimer = 0;
      void flushAssignmentExecutionRealtimeRefresh();
    }, Math.max(40, Number(opts.delayMs || 80)));
  }

  function syncAssignmentExecutionEventStream(detailOverride) {
    const shouldStream = assignmentExecutionShouldStream(detailOverride);
    if (!shouldStream) {
      stopAssignmentExecutionEventStream();
      return false;
    }
    const ticketId = selectedAssignmentTicketId();
    if (
      state.assignmentExecutionEventSource &&
      safe(state.assignmentExecutionEventSourceTicketId).trim() === ticketId
    ) {
      return !!state.assignmentExecutionEventSourceConnected;
    }
    stopAssignmentExecutionEventStream();
    const source = new window.EventSource(assignmentExecutionStreamUrl(ticketId));
    state.assignmentExecutionEventSource = source;
    state.assignmentExecutionEventSourceTicketId = ticketId;
    state.assignmentExecutionEventSourceConnected = false;
    source.onopen = () => {
      if (state.assignmentExecutionEventSource !== source) return;
      state.assignmentExecutionEventSourceConnected = true;
      stopAssignmentExecutionPoller();
    };
    source.onerror = () => {
      if (state.assignmentExecutionEventSource !== source) return;
      state.assignmentExecutionEventSourceConnected = false;
      if (source.readyState === window.EventSource.CLOSED) {
        stopAssignmentExecutionEventStream();
      }
      syncAssignmentExecutionPoller(detailOverride);
    };
    source.addEventListener('ready', (event) => {
      if (state.assignmentExecutionEventSource !== source) return;
      const payload = assignmentExecutionParseStreamEvent(event);
      state.assignmentExecutionEventSourceSeq = Number(payload.current_seq || payload.seq || 0);
      scheduleAssignmentExecutionRealtimeRefresh({ graph: true, detail: true, delayMs: 0 });
    });
    source.addEventListener('reset', (event) => {
      if (state.assignmentExecutionEventSource !== source) return;
      const payload = assignmentExecutionParseStreamEvent(event);
      state.assignmentExecutionEventSourceSeq = Number(payload.current_seq || payload.seq || 0);
      scheduleAssignmentExecutionRealtimeRefresh({ graph: true, detail: true });
    });
    source.addEventListener('snapshot', (event) => {
      if (state.assignmentExecutionEventSource !== source) return;
      const payload = assignmentExecutionParseStreamEvent(event);
      state.assignmentExecutionEventSourceSeq = Number(payload.seq || state.assignmentExecutionEventSourceSeq || 0);
      if (safe(payload.ticket_id).trim() !== selectedAssignmentTicketId()) return;
      scheduleAssignmentExecutionRealtimeRefresh({ graph: true, detail: true });
    });
    source.addEventListener('run', (event) => {
      if (state.assignmentExecutionEventSource !== source) return;
      const payload = assignmentExecutionParseStreamEvent(event);
      state.assignmentExecutionEventSourceSeq = Number(payload.seq || state.assignmentExecutionEventSourceSeq || 0);
      if (safe(payload.ticket_id).trim() !== selectedAssignmentTicketId()) return;
      const payloadNodeId = safe(payload.node_id).trim();
      const selectedNodeId = safe(state.assignmentSelectedNodeId).trim();
      if (payloadNodeId && selectedNodeId && payloadNodeId !== selectedNodeId) {
        return;
      }
      scheduleAssignmentExecutionRealtimeRefresh({ detail: true });
    });
    return true;
  }

  function syncAssignmentExecutionRealtime(detailOverride) {
    const streamActive = syncAssignmentExecutionEventStream(detailOverride);
    if (streamActive) {
      stopAssignmentExecutionPoller();
      return;
    }
    syncAssignmentExecutionPoller(detailOverride);
  }

  function syncAssignmentExecutionPoller(detailOverride) {
    if (
      assignmentExecutionMode(detailOverride) === 'event_stream' &&
      !!state.assignmentExecutionEventSource &&
      !!state.assignmentExecutionEventSourceConnected
    ) {
      stopAssignmentExecutionPoller();
      return;
    }
    const activeTab = document.querySelector('.tab.active');
    const activeTabName = safe(activeTab && activeTab.getAttribute('data-tab')).trim();
    const shouldPoll = activeTabName === 'task-center' && assignmentExecutionShouldPoll(detailOverride);
    if (!shouldPoll) {
      stopAssignmentExecutionPoller();
      return;
    }
    const intervalMs = assignmentExecutionPollInterval(detailOverride);
    if (state.assignmentExecutionPoller && Number(state.assignmentExecutionPollIntervalMs || 0) === intervalMs) {
      return;
    }
    stopAssignmentExecutionPoller();
    state.assignmentExecutionPollIntervalMs = intervalMs;
    state.assignmentExecutionPoller = window.setInterval(() => {
      if (state.assignmentExecutionPollBusy || state.assignmentLoading) return;
      const ticketId = selectedAssignmentTicketId();
      if (!ticketId || !safe(state.assignmentSelectedNodeId).trim()) {
        stopAssignmentExecutionPoller();
        return;
      }
      const previousSignature = assignmentExecutionStatusSignature();
      state.assignmentExecutionPollBusy = true;
      refreshAssignmentDetail(state.assignmentSelectedNodeId, { skipGraphRender: true })
        .then((detail) => {
          if (!detail) return null;
          const nextSignature = assignmentExecutionStatusSignature(detail);
          if (nextSignature && previousSignature !== nextSignature) {
            return refreshAssignmentGraphData({ ticketId: ticketId, silent: true, skipDetail: true });
          }
          if (assignmentExecutionShouldPoll(detail)) return null;
          return refreshAssignmentGraphData({ ticketId: ticketId, silent: true, skipDetail: true });
        })
        .catch(() => {})
        .finally(() => {
          state.assignmentExecutionPollBusy = false;
        });
    }, intervalMs);
  }
