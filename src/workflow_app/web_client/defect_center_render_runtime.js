  function defectFormatMetaLine(label, value) {
    return (
      "<div class='defect-meta-item'>" +
        "<div class='defect-meta-key'>" + escapeHtml(label) + '</div>' +
        "<div class='defect-meta-value'>" + escapeHtml(safe(value).trim() || '-') + '</div>' +
      '</div>'
    );
  }

  function defectFormatTime(value) {
    const text = safe(value).trim();
    if (!text) return '-';
    if (typeof assignmentFormatBeijingTime === 'function') {
      return assignmentFormatBeijingTime(text);
    }
    return text.replace('T', ' ').replace(/\+\d\d:\d\d$/, '');
  }

  function defectResolvedVersionDisplay(report) {
    const value = safe(report && report.resolved_version).trim();
    if (value) return value;
    return report && report.is_formal ? '待发布' : '-';
  }

  function defectPriorityTone(value) {
    const key = safe(value).trim().toUpperCase();
    if (key === 'P0') return 'p0';
    if (key === 'P1') return 'p1';
    if (key === 'P2') return 'p2';
    return 'p3';
  }

  function defectPriorityChipHtml(value) {
    const text = safe(value).trim().toUpperCase() || 'P1';
    return "<span class='defect-priority-chip " + escapeHtml(defectPriorityTone(text)) + "'>" + escapeHtml(text) + '</span>';
  }

  function defectQueueModeBadgeHtml(report) {
    const label = safe(report && report.queue_mode_text).trim();
    if (!label || safe(report && report.queue_mode).trim() === 'out_of_queue') return '';
    return "<span class='defect-queue-flag'>" + escapeHtml(label) + '</span>';
  }

  function defectQueueRefText(displayId, priority, summary) {
    const parts = [];
    if (safe(displayId).trim()) parts.push(safe(displayId).trim());
    if (safe(priority).trim()) parts.push(safe(priority).trim());
    if (safe(summary).trim()) parts.push(safe(summary).trim());
    return parts.length ? parts.join(' · ') : '-';
  }

  function defectCurrentActionText(report, detail, taskRefs) {
    const status = safe(report && report.status).trim().toLowerCase();
    const refs = Array.isArray(taskRefs) ? taskRefs : [];
    if (status === 'resolved') return detail && detail.can_close ? '等待用户关闭' : '已写回解决版本';
    if (status === 'closed') return '无需操作';
    if (status === 'dispute') {
      if (refs.length) return '补充证据后等待复核';
      return safe(report && report.queue_mode).trim() === 'manual' ? '手动复核建单' : '等待顺序建单';
    }
    if (status === 'not_formal') return '未进入正式流程';
    if (status === 'unresolved') {
      if (refs.length) return '处理中';
      return safe(report && report.queue_mode).trim() === 'manual' ? '手动处理建单' : '等待顺序建单';
    }
    return '-';
  }

  function defectQueueRuleText(queue) {
    const row = queue && typeof queue === 'object' ? queue : {};
    if (row.enabled) {
      if (Number(row.candidate_total || 0) <= 0) {
        return '总开关已开启：当前队列为空；后续若出现新的未解决或有分歧缺陷，系统会继续按优先级和上报时间自动串行建单。';
      }
      return '总开关已开启：当前缺陷进入已解决或已关闭后，系统会立即继续推进下一条；全过程始终只允许 1 条缺陷占用主动处理位，并统一挂到任务中心全局主图。';
    }
    return '总开关已关闭：系统不会自动创建新的处理或复核任务；仍允许手动点击处理缺陷或提交复核。';
  }

  function defectQueueSummaryCardHtml() {
    const queue = defectQueueSummary();
    const stateText = queue.enabled ? '连续推进中' : '自动建单关闭';
    const stateClass = queue.enabled ? ' on' : '';
    return (
      "<div id='defectQueueSummaryCard' class='defect-detail-card defect-queue-summary-card'>" +
        "<div class='defect-queue-summary-head'>" +
          "<div>" +
            "<div class='card-title'>顺序建单摘要</div>" +
            "<div class='defect-section-sub'>默认排序：任务优先级高到低；同优先级按上报时间早到晚。</div>" +
          '</div>' +
          "<span class='defect-queue-summary-state" + stateClass + "'>" + escapeHtml(stateText) + '</span>' +
        '</div>' +
        "<div class='defect-queue-summary-grid'>" +
          "<div class='defect-queue-summary-item'>" +
            "<div class='defect-queue-summary-label'>当前主动处理缺陷</div>" +
            "<div id='defectQueueSummaryActiveValue' class='defect-queue-summary-value'>" +
              escapeHtml(defectQueueRefText(queue.active_display_id, queue.active_task_priority, queue.active_summary)) +
            '</div>' +
          '</div>' +
          "<div class='defect-queue-summary-item'>" +
            "<div class='defect-queue-summary-label'>下一条待建单缺陷</div>" +
            "<div id='defectQueueSummaryNextValue' class='defect-queue-summary-value'>" +
              escapeHtml(defectQueueRefText(queue.next_display_id, queue.next_task_priority, queue.next_summary)) +
            '</div>' +
          '</div>' +
        '</div>' +
        "<div id='defectQueueSummaryRule' class='defect-queue-summary-rule'>" + escapeHtml(defectQueueRuleText(queue)) + '</div>' +
      '</div>'
    );
  }

  function renderDefectQueueHeader() {
    const queue = defectQueueSummary();
    const toggleBtn = $('defectQueueToggleBtn');
    if (!toggleBtn) return;
    toggleBtn.classList.toggle('on', !!queue.enabled);
    toggleBtn.classList.toggle('off', !queue.enabled);
    toggleBtn.disabled = !!state.defectQueueSaving;
    toggleBtn.textContent = state.defectQueueSaving
      ? '切换中...'
      : ('按顺序创建任务：' + (queue.enabled ? '开启' : '关闭'));
  }

  function defectEvidenceShotsHtml(images) {
    const rows = Array.isArray(images) ? images : [];
    if (!rows.length) {
      return "<div class='defect-empty-note'>未附带图片证据</div>";
    }
    return rows.map((item) => (
      "<div class='defect-evidence-shot'>" +
        "<img class='defect-evidence-shot-image' src='" + escapeHtml(safe(item && item.url)) + "' alt='证据图片' />" +
        "<div class='defect-evidence-shot-name'>" + escapeHtml(safe(item && item.name) || '图片证据') + '</div>' +
      '</div>'
    )).join('');
  }

  function defectTopActionsHtml(report, detail) {
    const actions = [];
    const reportId = safe(report && report.report_id).trim();
    if (!reportId) return '';
    if (detail && detail.can_process) {
      actions.push("<button id='defectCreateProcessTaskBtn' type='button'>处理缺陷</button>");
    }
    if (detail && detail.can_close) {
      actions.push("<button id='defectCloseBtn' type='button'>确认关闭</button>");
    }
    if (safe(report && report.status).trim().toLowerCase() === 'closed') {
      actions.push("<button id='defectReopenBtn' class='alt' type='button'>重新打开</button>");
    }
    return actions.length
      ? "<div class='defect-issue-actions'>" + actions.join('') + '</div>'
      : '';
  }

  function defectTaskDraftMeta(actionKind) {
    const action = safe(actionKind).trim().toLowerCase();
    if (action === 'review') {
      return {
        card_title: '确认复核任务名称',
        input_label: '复核任务名称基名',
        submit_label: '确认并提交复核',
        helper_text: '会创建 1 个复核节点，名称会自动派生成“<任务名称基名> - 复核”。',
        stages: ['复核'],
      };
    }
    return {
      card_title: '确认处理任务名称',
      input_label: '处理任务名称基名',
      submit_label: '确认并创建处理任务',
      helper_text: '会在任务中心全局主图中追加 3 个节点，分别对应分析、修复和推送到目标版本。',
      stages: ['分析', '修复', '推送到目标版本'],
    };
  }

  function defectTaskDraftPreviewHtml(actionKind) {
    const meta = defectTaskDraftMeta(actionKind);
    const baseName = defectTaskDraftPreviewBaseName();
    return meta.stages.map((stage) => (
      "<div class='defect-task-card-note'>" + escapeHtml(baseName + ' - ' + stage) + '</div>'
    )).join('');
  }

  function defectTaskDraftCardHtml(report, actionKind) {
    const reportId = safe(report && report.report_id).trim();
    if (!defectTaskDraftVisible(actionKind, reportId)) return '';
    const meta = defectTaskDraftMeta(actionKind);
    return (
      "<div class='defect-detail-card defect-section-card'>" +
        "<div class='card-title'>" + escapeHtml(meta.card_title) + '</div>' +
        "<div class='defect-section-sub'>" + escapeHtml(meta.helper_text) + '</div>' +
        "<div class='defect-action-grid'>" +
          "<label class='defect-field defect-span-2'>" +
            "<span class='hint'>" + escapeHtml(meta.input_label) + '</span>' +
            "<input id='defectTaskNameBaseInput' type='text' value='" + escapeHtml(defectTaskDraftPreviewBaseName()) + "' placeholder='" + escapeHtml(defectTaskDraftDefaultBaseName(report)) + "' />" +
          '</label>' +
        '</div>' +
        "<div class='hint'>将创建以下任务节点：</div>" +
        "<div class='defect-task-list'>" + defectTaskDraftPreviewHtml(actionKind) + '</div>' +
        "<div id='defectTaskDraftError' class='error'>" + escapeHtml(safe(state.defectTaskDraftError)) + '</div>' +
        "<div class='defect-detail-actions'>" +
          "<button id='defectConfirmTaskNameBtn' type='button' data-action-kind='" + escapeHtml(actionKind) + "'>" + escapeHtml(meta.submit_label) + '</button>' +
          "<button id='defectCancelTaskNameBtn' class='alt' type='button'>取消</button>" +
        '</div>' +
      '</div>'
    );
  }

  function defectHistoryBodyHtml(detail) {
    const row = detail && typeof detail === 'object' ? detail : {};
    const text = safe(row.text).trim();
    const summary = safe(row.summary).trim();
    const statusText = safe(row.status_text).trim();
    const reason = safe(row.reason).trim();
    const resolvedVersion = safe(row.resolved_version).trim();
    const ticketId = safe(row.ticket_id).trim();
    const lines = [];
    if (text) lines.push(text);
    if (summary) lines.push(summary);
    if (statusText) lines.push('状态：' + statusText);
    if (reason) lines.push('原因：' + reason);
    if (resolvedVersion) lines.push('解决版本：' + resolvedVersion);
    if (ticketId) lines.push('任务中心：' + ticketId);
    return lines.length ? lines.join(' / ') : '';
  }

  function defectHistoryHtml(items) {
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) {
      return "<div class='hint'>暂无状态与补充历史</div>";
    }
    return rows.map((item) => {
      const detail = item && item.detail && typeof item.detail === 'object' ? item.detail : {};
      const bodyText = defectHistoryBodyHtml(detail);
      let body = bodyText ? "<div class='defect-history-text'>" + escapeHtml(bodyText) + '</div>' : '';
      if (Array.isArray(detail.images) && detail.images.length) {
        body += "<div class='defect-history-images'>" +
          detail.images.map((image) => "<img class='defect-history-thumb' src='" + escapeHtml(safe(image && image.url)) + "' alt='补充图片' />").join('') +
          '</div>';
      }
      if (!body && Object.keys(detail).length) {
        body = "<pre class='pre defect-history-pre'>" + escapeHtml(JSON.stringify(detail, null, 2)) + '</pre>';
      }
      return (
        "<div class='defect-timeline-item'>" +
          "<div class='defect-timeline-head'>" +
            "<div class='defect-timeline-title'>" + escapeHtml(safe(item.title) || safe(item.entry_type) || '历史记录') + '</div>' +
            "<div class='defect-timeline-time'>" + escapeHtml(defectFormatTime(item.created_at)) + '</div>' +
          '</div>' +
          "<div class='defect-history-sub'>" + escapeHtml(safe(item.actor) || '-') + '</div>' +
          body +
        '</div>'
      );
    }).join('');
  }

  function defectTaskActionText(action) {
    const key = safe(action).trim().toLowerCase();
    if (key === 'mark-success') return '标记成功';
    if (key === 'mark-failed') return '标记失败';
    if (key === 'rerun') return '重跑任务';
    if (key === 'override-status') return '修改状态';
    if (key === 'deliver-artifact') return '提交产物';
    if (key === 'view-artifact') return '查看产物';
    if (key === 'delete') return '删除任务';
    return safe(action).trim();
  }

  function defectTaskCardMetaHtml(label, value) {
    return (
      "<div class='defect-task-card-meta'>" +
        "<div class='defect-task-card-meta-key'>" + escapeHtml(label) + '</div>' +
        "<div class='defect-task-card-meta-value'>" + escapeHtml(safe(value).trim() || '-') + '</div>' +
      '</div>'
    );
  }

  function defectTaskCardNoteHtml(text, tone) {
    const content = safe(text).trim();
    if (!content) return '';
    const toneClass = safe(tone).trim() ? (' ' + safe(tone).trim()) : '';
    return "<div class='defect-task-card-note" + toneClass + "'>" + escapeHtml(content) + '</div>';
  }

  function defectTaskRefsHtml(taskRefs) {
    const rows = Array.isArray(taskRefs) ? taskRefs : [];
    if (!rows.length) {
      return "<div class='defect-empty-note'>尚未创建任务中心任务引用</div>";
    }
    return rows.map((item) => {
      const node = item && item.selected_node && typeof item.selected_node === 'object' ? item.selected_node : {};
      const ticketMeta = safe(item.graph_name).trim() || safe(item.ticket_id).trim() || '-';
      const nodeMeta = safe(node.node_name || item.node_name || item.title || item.focus_node_id).trim() || '-';
      const nodeIdText = safe(node.node_id || item.focus_node_id).trim() || '-';
      const assignedAgent = safe(node.assigned_agent_name || node.assigned_agent_id).trim() || '-';
      const priorityText = safe(node.priority_label || node.priority).trim() || '-';
      const artifactStatusText = safe(node.artifact_delivery_status_text).trim() || '-';
      const completedAt = safe(node.completed_at).trim()
        ? defectFormatTime(node.completed_at)
        : defectFormatTime(item.created_at);
      const receiptParts = [];
      if (safe(node.result_ref).trim()) receiptParts.push('结果引用：' + safe(node.result_ref).trim());
      if (safe(node.success_reason).trim()) receiptParts.push('成功理由：' + safe(node.success_reason).trim());
      if (safe(node.failure_reason).trim()) receiptParts.push('失败原因：' + safe(node.failure_reason).trim());
      const blockingText = Array.isArray(item.blocking_reasons) && item.blocking_reasons.length
        ? ('阻塞来源：' + item.blocking_reasons.map((reason) => {
          const entry = reason && typeof reason === 'object' ? reason : {};
          return safe(entry.node_name || entry.node_id).trim() || '-';
        }).join(' / '))
        : '';
      const footerParts = [];
      const actions = Array.isArray(item.available_actions)
        ? item.available_actions.map((action) => defectTaskActionText(action)).filter((text) => !!safe(text).trim())
        : [];
      if (actions.length) footerParts.push('可操作：' + actions.join(' / '));
      if (Array.isArray(item.audit_refs) && item.audit_refs.length) footerParts.push('人工处置 ' + String(item.audit_refs.length) + ' 条');
      if (Array.isArray(node.artifact_paths) && node.artifact_paths.length) footerParts.push('已交付 ' + String(node.artifact_paths.length) + ' 份产物');
      return (
        "<div class='defect-task-card'>" +
          "<div class='defect-task-card-head'>" +
            "<div class='defect-task-card-title'>" + escapeHtml(safe(item.title) || nodeMeta) + '</div>' +
            "<span class='defect-status-chip " + escapeHtml(defectStatusTone(node.status || item.node_status || item.scheduler_state)) + "'>" +
              escapeHtml(safe(node.status_text || item.node_status_text || item.scheduler_state_text) || '待查看') +
            '</span>' +
          '</div>' +
          "<div class='defect-task-card-sub'>" + escapeHtml(ticketMeta) + '</div>' +
          "<div class='defect-task-card-sub'>任务 ID：" + escapeHtml(nodeIdText) + '</div>' +
          "<div class='defect-task-card-grid'>" +
            defectTaskCardMetaHtml('执行角色', assignedAgent) +
            defectTaskCardMetaHtml('优先级', priorityText) +
            defectTaskCardMetaHtml('产物状态', artifactStatusText) +
            defectTaskCardMetaHtml('完成时间', completedAt) +
          '</div>' +
          defectTaskCardNoteHtml(safe(node.expected_artifact).trim() ? ('预期产物：' + safe(node.expected_artifact).trim()) : '', '') +
          defectTaskCardNoteHtml(receiptParts.join(' / '), '') +
          defectTaskCardNoteHtml(blockingText, 'warn') +
          defectTaskCardNoteHtml(footerParts.join(' · '), '') +
          "<div class='defect-task-card-actions'>" + defectTaskRefOpenButton(item) + '</div>' +
        '</div>'
      );
    }).join('');
  }

  function defectLoadedCount() {
    return Array.isArray(state.defectList) ? state.defectList.length : 0;
  }

  function defectDraftHasContent() {
    const summaryValue = $('defectSummaryInput') ? safe($('defectSummaryInput').value).trim() : '';
    const reportValue = $('defectReportTextInput') ? safe($('defectReportTextInput').value).trim() : '';
    return !!summaryValue || !!reportValue || ((state.defectDraftImages || []).length > 0);
  }

  function syncDefectComposerCollapsedState() {
    if (state.defectComposerTouched) return;
    state.defectComposerCollapsed = defectLoadedCount() > 0 && !defectDraftHasContent();
  }

  function defectListMetaText() {
    const loaded = defectLoadedCount();
    const total = Math.max(0, Number(state.defectListTotal || 0));
    if (total > loaded) {
      return '已加载 ' + String(loaded) + ' / ' + String(total) + ' 条记录';
    }
    return '共 ' + String(Math.max(total, loaded)) + ' 条记录';
  }

  function mergeDefectListItems(existingRows, nextRows) {
    const merged = [];
    const seen = new Set();
    [existingRows, nextRows].forEach((rows) => {
      (Array.isArray(rows) ? rows : []).forEach((raw) => {
        const item = normalizeDefectListItem(raw);
        const reportId = safe(item.report_id).trim();
        if (!reportId || seen.has(reportId)) return;
        seen.add(reportId);
        merged.push(item);
      });
    });
    return merged;
  }

  function renderDefectList() {
    const node = $('defectList');
    if (!node) return;
    const rows = Array.isArray(state.defectList) ? state.defectList : [];
    if (state.defectLoading && !rows.length) {
      node.innerHTML = "<div class='defect-empty-card'><div class='hint'>缺陷列表加载中...</div></div>";
      return;
    }
    if (!rows.length) {
      const env = safe(state.runtimeEnvironment).trim().toUpperCase() || '当前环境';
      node.innerHTML =
        "<div class='defect-empty-card'>" +
          "<div class='defect-empty-title'>暂无缺陷记录</div>" +
          "<div class='hint'>" +
            escapeHtml(env + " 暂无缺陷记录。缺陷按环境独立存储；如果你要看之前在其他环境提交的记录，请切回对应环境。") +
          '</div>' +
        '</div>';
      return;
    }
    const currentId = defectSelectedReportId();
    node.innerHTML = rows.map((raw) => {
      const item = normalizeDefectListItem(raw);
      const active = item.report_id === currentId;
      return (
        "<button class='defect-list-item" + (active ? ' active' : '') + "' type='button' data-report-id='" + escapeHtml(item.report_id) + "'>" +
          "<div class='defect-list-item-head'>" +
            "<div class='defect-list-item-title'>" + escapeHtml(item.defect_summary || item.display_id) + '</div>' +
            "<span class='defect-status-chip " + escapeHtml(defectStatusTone(item.status)) + "'>" + escapeHtml(item.status_text) + '</span>' +
          '</div>' +
          "<div class='defect-list-item-sub'>" + escapeHtml(item.display_id || '-') + '</div>' +
          "<div class='defect-list-item-tags'>" +
            defectPriorityChipHtml(item.task_priority) +
            defectQueueModeBadgeHtml(item) +
          '</div>' +
          "<div class='defect-list-item-meta'>" + escapeHtml(item.reported_at ? defectFormatTime(item.reported_at) : '-') + '</div>' +
          "<div class='defect-list-item-meta'>" + escapeHtml(item.decision_title || item.decision_summary || '等待判定') + '</div>' +
        '</button>'
      );
    }).join('');
  }

  function renderDefectDetail() {
    const body = $('defectDetailBody');
    const meta = $('defectDetailMeta');
    if (!body) return;
    const detail = defectCurrentDetail();
    const report = defectCurrentReport();
    if (!safe(report.report_id).trim()) {
      if (meta) meta.textContent = '请选择左侧缺陷记录';
      body.innerHTML =
        defectQueueSummaryCardHtml() +
        "<div class='defect-empty-card'><div class='defect-empty-title'>暂无记录详情</div><div class='hint'>筛选或选择左侧记录后，可在这里查看 DTS、结论、任务引用和状态历史。</div></div>";
      return;
    }
    if (meta) meta.textContent = safe(report.display_id || report.dts_id || report.report_id);
    const images = Array.isArray(report.evidence_images) ? report.evidence_images : [];
    const history = Array.isArray(detail.history) ? detail.history : [];
    const taskRefs = Array.isArray(detail.task_refs) ? detail.task_refs : [];
    const decision = report.current_decision && typeof report.current_decision === 'object' ? report.current_decision : {};
    const statusKey = safe(report.status).trim().toLowerCase();
    const queueModeText = safe(report.queue_mode_text).trim() || '手动建单模式';
    const reviewButtonText = report.status === 'resolved'
      ? '提交复评'
      : (report.status === 'dispute' ? '继续补充并提交复核' : '标记有分歧并提交复核');
    const reviewSectionTitle = statusKey === 'resolved'
      ? '仍未解决？补充证据并提交复评'
      : (statusKey === 'dispute' ? '补充证据与描述' : '不同意当前结论？补充证据并提交复核');
    const emptyFormalNote = statusKey === 'not_formal'
      ? "<div class='defect-empty-note'>当前上报没有进入正式缺陷流程，因此没有 DTS，也没有任务中心处理链。</div>"
      : '';
    body.innerHTML =
      defectQueueSummaryCardHtml() +
      "<div class='defect-detail-card defect-issue-card'>" +
        "<div class='defect-issue-head'>" +
          "<div>" +
            "<div class='defect-detail-sub'>" + escapeHtml(report.display_id || report.report_id) + '</div>' +
            "<div class='defect-issue-title'>" + escapeHtml(report.defect_summary || report.display_id) + '</div>' +
          '</div>' +
          "<div class='defect-detail-badges'>" +
            defectPriorityChipHtml(report.task_priority) +
            defectQueueModeBadgeHtml(report) +
            "<span class='defect-status-chip " + escapeHtml(defectStatusTone(report.status)) + "'>" + escapeHtml(report.status_text || defectStatusText(report.status)) + '</span>' +
          '</div>' +
        '</div>' +
        "<div class='defect-facts-grid'>" +
          defectFormatMetaLine('任务优先级', report.task_priority) +
          defectFormatMetaLine('上报时间', defectFormatTime(report.reported_at)) +
          defectFormatMetaLine('建单模式', queueModeText) +
          defectFormatMetaLine('发现迭代', report.discovered_iteration) +
          defectFormatMetaLine('解决版本', defectResolvedVersionDisplay(report)) +
          defectFormatMetaLine('当前动作', defectCurrentActionText(report, detail, taskRefs)) +
        '</div>' +
        defectTopActionsHtml(report, detail) +
      '</div>' +
      defectTaskDraftCardHtml(report, 'process') +
      emptyFormalNote +
      "<div class='defect-detail-card defect-section-card'>" +
        "<div class='card-title'>原始上报</div>" +
        "<div class='defect-section-sub'>上报来源： " + escapeHtml(report.report_source || '-') + " · 提交时间： " + escapeHtml(defectFormatTime(report.created_at)) + '</div>' +
        "<div class='defect-evidence-layout'>" +
          "<div class='defect-evidence-stack'>" + defectEvidenceShotsHtml(images) + '</div>' +
          "<div class='defect-text-block'>" + escapeHtml(report.report_text || '-') + '</div>' +
        '</div>' +
      '</div>' +
      "<div class='defect-detail-card defect-section-card'>" +
        "<div class='card-title'>当前判定 / 复评结论</div>" +
        "<div class='defect-section-sub'>结论来源： " + escapeHtml(report.decision_source || safe(decision.decision_source) || '-') + '</div>' +
        "<div class='defect-decision-title'>" + escapeHtml(safe(decision.title) || report.decision_title || '等待结论') + '</div>' +
        "<div class='defect-text-block'>" + escapeHtml(safe(decision.summary) || report.decision_summary || '-') + '</div>' +
      '</div>' +
      (detail.show_re_review_input
        ? "<div class='defect-detail-card defect-section-card'>" +
            "<div class='card-title'>" + escapeHtml(reviewSectionTitle) + "</div>" +
            "<div class='defect-section-sub'>首轮不成立后的补充与已解决后的复评共用同一输入区；可直接在说明框中粘贴截图。</div>" +
            "<div class='defect-evidence-layout defect-evidence-layout-editable'>" +
              "<div id='defectSharedImageList' class='defect-image-list defect-evidence-stack'></div>" +
              "<div class='defect-supplement-box'>" +
                "<label class='defect-field defect-span-2'>" +
                  "<span class='hint'>补充说明</span>" +
                  "<textarea id='defectSharedTextInput' rows='5' placeholder='补充说明当前证据、复现结果或分歧点；可直接在此粘贴截图'></textarea>" +
                '</label>' +
                "<div class='hint defect-paste-tip'>在说明框中直接 Ctrl+V 粘贴图片，系统会自动收进左侧图片证据。</div>" +
                "<div class='defect-detail-actions'>" +
                  "<button id='defectSubmitReviewBtn' type='button'" + (detail.can_review ? '' : ' disabled') + ">" + escapeHtml(reviewButtonText) + '</button>' +
                '</div>' +
                defectTaskDraftCardHtml(report, 'review') +
              '</div>' +
            '</div>' +
          '</div>'
        : '') +
      "<div class='defect-detail-card defect-section-card'>" +
        "<div class='card-title'>任务引用</div>" +
        "<div class='defect-task-list'>" + defectTaskRefsHtml(taskRefs) + '</div>' +
      '</div>' +
      ((report.is_formal || report.status === 'resolved')
        ? "<div class='defect-detail-card defect-section-card'>" +
            "<div class='card-title'>解决版本与确认</div>" +
            "<div class='defect-section-sub'>正式缺陷在修复发布后写回版本；已解决记录可由用户最终确认关闭。</div>" +
            "<div class='defect-action-grid'>" +
              "<label class='defect-field defect-span-2'>" +
                "<span class='hint'>解决版本</span>" +
                "<input id='defectResolvedVersionInput' type='text' value='" + escapeHtml(report.resolved_version) + "' placeholder='留空则使用当前 workflow 版本' />" +
              '</label>' +
            '</div>' +
            "<div class='defect-detail-actions'>" +
              ((report.status === 'unresolved' || report.status === 'dispute') && report.is_formal
                ? "<button id='defectResolvedVersionBtn' class='alt' type='button'>写回解决版本</button>"
                : '') +
            '</div>' +
          '</div>'
        : '') +
      "<div class='defect-detail-card defect-section-card'>" +
        "<div class='card-title'>状态变更历史</div>" +
        "<div class='defect-timeline'>" + defectHistoryHtml(history) + '</div>' +
      '</div>';
    renderDefectDraftImages('defectSharedImageList', state.defectSupplementDraftImages, 'removeDefectSupplementDraftImage');
  }

  function renderDefectCenter() {
    syncDefectComposerCollapsedState();
    setRequirementBugModule(state.requirementBugModule, { persist: false });
    const keywordInput = $('defectKeywordInput');
    const statusSelect = $('defectStatusFilterSelect');
    if (keywordInput && document.activeElement !== keywordInput) {
      keywordInput.value = safe(state.defectKeyword);
    }
    if (statusSelect && document.activeElement !== statusSelect) {
      statusSelect.value = safe(state.defectStatusFilter).trim() || 'all';
    }
    renderDefectDraftImages('defectDraftImageList', state.defectDraftImages, 'removeDefectDraftImage');
    const composerCard = $('defectComposerCard');
    if (composerCard) {
      composerCard.classList.toggle('is-collapsed', !!state.defectComposerCollapsed);
    }
    const composerToggleBtn = $('defectComposerToggleBtn');
    if (composerToggleBtn) {
      composerToggleBtn.textContent = state.defectComposerCollapsed ? '展开提缺陷' : '收起';
    }
    renderDefectQueueHeader();
    renderDefectList();
    renderDefectDetail();
    setDefectError(state.defectError);
    setDefectSubmitError(state.defectSubmitError);
    const totalNode = $('defectListMeta');
    if (totalNode) {
      totalNode.textContent = defectListMetaText();
    }
    const loadMoreBtn = $('defectLoadMoreBtn');
    if (loadMoreBtn) {
      const showMore = !!state.defectListHasMore && defectLoadedCount() > 0;
      loadMoreBtn.hidden = !showMore;
      loadMoreBtn.disabled = !!state.defectLoading;
      loadMoreBtn.textContent = state.defectLoading && defectLoadedCount() > 0 ? '加载中...' : '加载更多';
    }
    const loadMoreMeta = $('defectListMoreMeta');
    if (loadMoreMeta) {
      loadMoreMeta.textContent = state.defectListHasMore
        ? '继续加载更早的缺陷记录'
        : (defectLoadedCount() > 0 ? '当前筛选结果已全部显示' : '');
    }
  }

  async function refreshDefectDetail(reportId, options) {
    const key = safe(reportId).trim();
    const opts = options && typeof options === 'object' ? options : {};
    if (!key) {
      state.defectSelectedReportId = '';
      state.defectDetail = null;
      defectTaskDraftReset();
      renderDefectCenter();
      return null;
    }
    state.defectDetailLoading = true;
    try {
      const data = await getJSON(defectApiUrl('/api/defects/' + encodeURIComponent(key)));
      state.defectSelectedReportId = key;
      state.defectDetail = data;
      state.defectQueueSummary = normalizeDefectQueueSummary(data.queue);
      if (defectTaskDraftReportId() && defectTaskDraftReportId() !== key) {
        defectTaskDraftReset();
      }
      setDefectError('');
      if (!opts.skipRender) {
        renderDefectCenter();
      }
      return data;
    } finally {
      state.defectDetailLoading = false;
    }
  }

  async function refreshDefectList(options) {
    const opts = options && typeof options === 'object' ? options : {};
    const append = !!opts.append;
    const requestOffset = append ? Math.max(0, Number(state.defectListNextOffset || 0)) : 0;
    const requestLimit = Math.max(20, Number(state.defectListLimit || 100));
    state.defectLoading = true;
    try {
      const data = await getJSON(defectApiUrl('/api/defects', {
        status: safe(state.defectStatusFilter).trim() || 'all',
        keyword: safe(state.defectKeyword).trim(),
        limit: requestLimit,
        offset: requestOffset,
      }));
      const nextRows = Array.isArray(data.items) ? data.items.map(normalizeDefectListItem) : [];
      state.defectList = append ? mergeDefectListItems(state.defectList, nextRows) : nextRows;
      state.defectQueueSummary = normalizeDefectQueueSummary(data.queue);
      state.defectListTotal = Math.max(defectLoadedCount(), Number(data.total || 0));
      state.defectListLimit = Math.max(20, Number(data.limit || requestLimit));
      state.defectListNextOffset = Math.max(defectLoadedCount(), Number(data.next_offset || (requestOffset + nextRows.length)));
      state.defectListHasMore = !!data.has_more && state.defectListNextOffset < state.defectListTotal;
      const preferred = safe(opts.preferredReportId).trim();
      const available = new Set(state.defectList.map((item) => safe(item.report_id).trim()).filter((item) => !!item));
      let nextReportId = preferred || defectSelectedReportId();
      if (!available.has(nextReportId)) {
        nextReportId = state.defectList.length ? safe(state.defectList[0].report_id).trim() : '';
      }
      state.defectSelectedReportId = nextReportId;
      if (!opts.skipRender) {
        renderDefectCenter();
      }
      if (!opts.skipDetail && nextReportId && (!append || preferred || !safe(defectCurrentReport().report_id).trim())) {
        return await refreshDefectDetail(nextReportId, { skipRender: true });
      }
      if (!nextReportId) {
        state.defectDetail = null;
        defectTaskDraftReset();
      }
      renderDefectCenter();
      return data;
    } finally {
      state.defectLoading = false;
      renderDefectCenter();
    }
  }

  function clearDefectDraftForm() {
    state.defectDraftImages = [];
    state.defectComposerTouched = false;
    if ($('defectSummaryInput')) $('defectSummaryInput').value = '';
    if ($('defectReportTextInput')) $('defectReportTextInput').value = '';
    renderDefectDraftImages('defectDraftImageList', state.defectDraftImages, 'removeDefectDraftImage');
  }

  function clearDefectSharedDraft() {
    state.defectSupplementDraftImages = [];
    if ($('defectSharedTextInput')) $('defectSharedTextInput').value = '';
    renderDefectDraftImages('defectSharedImageList', state.defectSupplementDraftImages, 'removeDefectSupplementDraftImage');
  }

  async function submitDefectReport() {
    const payload = await postJSON('/api/defects', {
      defect_summary: safe($('defectSummaryInput') ? $('defectSummaryInput').value : '').trim(),
      report_text: safe($('defectReportTextInput') ? $('defectReportTextInput').value : '').trim(),
      evidence_images: state.defectDraftImages,
      operator: 'web-user',
    });
    clearDefectDraftForm();
    setDefectSubmitError('');
    setRequirementBugModule('defect');
    await refreshDefectList({ preferredReportId: safe(payload && payload.report && payload.report.report_id).trim() });
    setStatus('缺陷记录已提交');
    return payload;
  }

  async function toggleDefectQueueModeAction() {
    const current = defectQueueSummary();
    state.defectQueueSaving = true;
    renderDefectCenter();
    try {
      const result = await postJSON('/api/defects/queue-mode', {
        enabled: !current.enabled,
      });
      state.defectQueueSummary = normalizeDefectQueueSummary(result.queue);
      await refreshDefectList({ preferredReportId: defectSelectedReportId() });
      setStatus('顺序建单已' + (state.defectQueueSummary.enabled ? '开启' : '关闭'));
      return result;
    } finally {
      state.defectQueueSaving = false;
      renderDefectCenter();
    }
  }

  function focusDefectTaskDraftInput() {
    const input = $('defectTaskNameBaseInput');
    if (!input) return;
    input.focus();
    if (typeof input.setSelectionRange === 'function') {
      const length = safe(input.value).length;
      input.setSelectionRange(length, length);
    }
  }

  async function requestDefectReviewTaskAction() {
    const report = defectCurrentReport();
    const reportId = safe(report.report_id).trim();
    if (!reportId) return null;
    const text = safe($('defectSharedTextInput') ? $('defectSharedTextInput').value : '').trim();
    const images = Array.isArray(state.defectSupplementDraftImages) ? state.defectSupplementDraftImages : [];
    if (!text && !images.length) {
      throw new Error('请先补充说明或图片证据');
    }
    defectTaskDraftOpen('review', report);
    renderDefectCenter();
    focusDefectTaskDraftInput();
    return null;
  }

  async function submitDefectReviewFlow() {
    const report = defectCurrentReport();
    const reportId = safe(report.report_id).trim();
    if (!reportId) return null;
    const taskNameBase = defectTaskDraftPreviewBaseName();
    if (!taskNameBase) {
      setDefectTaskDraftError('任务名称基名不能为空');
      throw new Error('任务名称基名不能为空');
    }
    const text = safe($('defectSharedTextInput') ? $('defectSharedTextInput').value : '').trim();
    const images = Array.isArray(state.defectSupplementDraftImages) ? state.defectSupplementDraftImages : [];
    if (!text && !images.length) {
      throw new Error('请先补充说明或图片证据');
    }
    if (text) {
      await postJSON('/api/defects/' + encodeURIComponent(reportId) + '/supplements/text', {
        text: text,
        operator: 'web-user',
      });
    }
    if (images.length) {
      await postJSON('/api/defects/' + encodeURIComponent(reportId) + '/supplements/images', {
        evidence_images: images,
        operator: 'web-user',
      });
    }
    if (report.status === 'not_formal' || report.status === 'resolved') {
      await postJSON('/api/defects/' + encodeURIComponent(reportId) + '/dispute', {
        reason: text,
        operator: 'web-user',
      });
    }
    const result = await postJSON('/api/defects/' + encodeURIComponent(reportId) + '/review-task', {
      operator: 'web-user',
      task_name_base: taskNameBase,
    });
    defectTaskDraftReset();
    clearDefectSharedDraft();
    await refreshDefectList({ preferredReportId: reportId });
    setStatus('复核任务已创建');
    return result;
  }

  async function requestDefectProcessTaskAction() {
    const report = defectCurrentReport();
    const reportId = safe(report.report_id).trim();
    if (!reportId) return null;
    defectTaskDraftOpen('process', report);
    renderDefectCenter();
    focusDefectTaskDraftInput();
    return null;
  }

  async function createDefectProcessTaskAction() {
    const report = defectCurrentReport();
    const reportId = safe(report.report_id).trim();
    if (!reportId) return null;
    const taskNameBase = defectTaskDraftPreviewBaseName();
    if (!taskNameBase) {
      setDefectTaskDraftError('任务名称基名不能为空');
      throw new Error('任务名称基名不能为空');
    }
    const result = await postJSON('/api/defects/' + encodeURIComponent(reportId) + '/process-task', {
      operator: 'web-user',
      task_name_base: taskNameBase,
    });
    defectTaskDraftReset();
    await refreshDefectList({ preferredReportId: reportId });
    setStatus('处理任务已创建');
    return result;
  }

  async function submitDefectTaskDraftAction(actionKind) {
    const action = safe(actionKind || defectTaskDraftAction()).trim().toLowerCase();
    syncDefectTaskDraftInput();
    if (!defectTaskDraftPreviewBaseName()) {
      setDefectTaskDraftError('任务名称基名不能为空');
      throw new Error('任务名称基名不能为空');
    }
    setDefectTaskDraftError('');
    if (action === 'review') {
      return submitDefectReviewFlow();
    }
    return createDefectProcessTaskAction();
  }

  async function writeDefectResolvedVersionAction() {
    const report = defectCurrentReport();
    const reportId = safe(report.report_id).trim();
    if (!reportId) return null;
    const result = await postJSON('/api/defects/' + encodeURIComponent(reportId) + '/resolved-version', {
      resolved_version: safe($('defectResolvedVersionInput') ? $('defectResolvedVersionInput').value : '').trim(),
      operator: 'web-user',
    });
    await refreshDefectList({ preferredReportId: reportId });
    setStatus('解决版本已写回');
    return result;
  }

  async function closeDefectAction() {
    const report = defectCurrentReport();
    const reportId = safe(report.report_id).trim();
    if (!reportId) return null;
    const result = await postJSON('/api/defects/' + encodeURIComponent(reportId) + '/status', {
      status: 'closed',
      operator: 'web-user',
    });
    await refreshDefectList({ preferredReportId: reportId });
    setStatus('缺陷已关闭');
    return result;
  }

  async function reopenDefectAction() {
    const report = defectCurrentReport();
    const reportId = safe(report.report_id).trim();
    if (!reportId) return null;
    const result = await postJSON('/api/defects/' + encodeURIComponent(reportId) + '/status', {
      status: 'unresolved',
      operator: 'web-user',
    });
    await refreshDefectList({ preferredReportId: reportId });
    setStatus('缺陷已重新打开');
    return result;
  }
