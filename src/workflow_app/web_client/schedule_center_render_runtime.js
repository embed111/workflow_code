  function scheduleStatusChipHtml(status, text, extraClass) {
    const tone = extraClass || scheduleResultTone(status);
    return "<span class='schedule-status-chip " + escapeHtml(tone) + "'>" + escapeHtml(text || '-') + '</span>';
  }

  function scheduleRepairText(value) {
    const raw = safe(value);
    const text = raw.trim();
    if (!text) return '';
    if (text.indexOf('?') >= 0 && text.replace(/\?/g, '').trim() === '') return '';
    if (text.indexOf('\uFFFD') >= 0) return '';
    if (!/[\u0080-\uFFFF]/.test(text)) return text;
    const maybeMojibake = /(?:Ã.|Â.|å.|ä.|ç.|é.|è.|ê.|î.|ï.|ô.|û.)/.test(text);
    if (!maybeMojibake) return text;
    try {
      const bytes = new Uint8Array(Array.from(text, (ch) => ch.charCodeAt(0) & 0xFF));
      const repaired = new TextDecoder('utf-8', { fatal: true }).decode(bytes).trim();
      return repaired || text;
    } catch (_err) {
      return text;
    }
  }

  function scheduleGuidePointHtml(title, text) {
    return (
      "<div class='schedule-empty-point'>" +
        "<div class='schedule-empty-point-title'>" + escapeHtml(title || '-') + '</div>' +
        "<div class='schedule-plan-sub'>" + escapeHtml(text || '-') + '</div>' +
      '</div>'
    );
  }

  function scheduleEmptyGuideHtml(title, text, points, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const kicker = safe(opts.kicker).trim();
    const ctaLabel = safe(opts.ctaLabel).trim();
    const classes = ['schedule-empty', 'schedule-empty-guide'];
    if (opts.compact) classes.push('compact');
    return (
      "<div class='" + classes.join(' ') + "'>" +
        (kicker ? "<div class='schedule-empty-kicker'>" + escapeHtml(kicker) + '</div>' : '') +
        "<div class='schedule-plan-title'>" + escapeHtml(title || '-') + '</div>' +
        "<div class='schedule-plan-sub'>" + escapeHtml(text || '-') + '</div>' +
        "<div class='schedule-empty-points'>" +
          (Array.isArray(points) ? points.map((item) => scheduleGuidePointHtml(item && item.title, item && item.text)).join('') : '') +
        '</div>' +
        (ctaLabel ? "<button class='alt schedule-empty-cta' type='button' data-schedule-create='1'>" + escapeHtml(ctaLabel) + '</button>' : '') +
      '</div>'
    );
  }

  function scheduleEmptyCardHtml(title, text, extraClass) {
    const classes = ['schedule-empty'];
    if (extraClass) classes.push(extraClass);
    return (
      "<div class='" + classes.join(' ') + "'>" +
        "<div class='schedule-plan-title'>" + escapeHtml(title || '-') + '</div>' +
        "<div class='schedule-plan-sub'>" + escapeHtml(text || '-') + '</div>' +
      '</div>'
    );
  }

  function schedulePlaceholderListHtml(items) {
    return (
      "<div class='schedule-list schedule-placeholder-list'>" +
        items.map((item) => (
          "<div class='schedule-list-item schedule-placeholder-item'>" +
            "<div class='schedule-plan-title'>" + escapeHtml(item && item.title) + '</div>' +
            "<div class='schedule-plan-sub'>" + escapeHtml(item && item.text) + '</div>' +
          '</div>'
        )).join('') +
      '</div>'
    );
  }

  function scheduleEmptyDetailBodyHtml() {
    return (
      "<section class='schedule-hero schedule-hero-empty'>" +
        "<div class='schedule-hero-head'>" +
          "<div>" +
            "<div class='schedule-plan-title'>先创建一条定时任务</div>" +
            "<div class='schedule-plan-sub'>空态仍保持和原型图一致的左右双栏结构。保存后，这里会展开计划详情、发起内容、规则、未来触发和执行结果。</div>" +
          '</div>' +
          scheduleStatusChipHtml('pending', '待配置', 'pending') +
        '</div>' +
        "<div class='schedule-actions'>" +
          "<button class='alt' type='button' data-schedule-create='1'>新建定时任务</button>" +
        '</div>' +
        "<div class='schedule-hero-grid'>" +
          scheduleStatHtml('执行 Agent', '保存后选择') +
          scheduleStatHtml('优先级', '默认 P1，可编辑') +
          scheduleStatHtml('下一次触发', '配置规则后自动计算') +
          scheduleStatHtml('最近结果', '首次触发后展示') +
        '</div>' +
      '</section>' +
      "<section class='schedule-section'>" +
        "<div class='schedule-section-head'><div class='card-title'>发起任务内容预览</div></div>" +
        schedulePlaceholderListHtml([
          { title: '本次目标', text: '例如：固定巡检、发布预检、账单复核等可重复工作。' },
          { title: '执行清单', text: '把命中后要做的关键动作写清楚，避免只留下抽象任务名。' },
          { title: '完成标准', text: '明确什么结果才算完成，后续会原样快照到任务中心实例。' },
        ]) +
      '</section>' +
      "<section class='schedule-section'>" +
        "<div class='card-title'>触发规则</div>" +
        "<div class='schedule-plan-rules'>" +
          "<span class='schedule-rule-chip'>每月</span>" +
          "<span class='schedule-rule-chip'>每周</span>" +
          "<span class='schedule-rule-chip'>每日</span>" +
          "<span class='schedule-rule-chip'>定时</span>" +
        '</div>' +
        "<div class='schedule-plan-sub schedule-section-note'>支持混合启用；同一分钟多条规则命中时，仍只会向任务中心创建一条实例。</div>" +
      '</section>' +
      "<section class='schedule-section'><div class='card-title'>未来触发</div>" +
        schedulePlaceholderListHtml([
          { title: '暂无未来触发', text: '保存并启用后，系统会按北京时间计算未来触发时间。' },
        ]) +
      '</section>' +
      "<section class='schedule-section'><div class='card-title'>最近执行结果</div>" +
        schedulePlaceholderListHtml([
          { title: '暂无执行记录', text: '计划首次命中并完成建单后，这里会展示真实等待、运行、成功或失败结果。' },
        ]) +
      '</section>' +
      "<section class='schedule-section'><div class='card-title'>关联任务中心实例</div>" +
        schedulePlaceholderListHtml([
          { title: '暂无关联实例', text: '定时任务只负责计划配置与命中建单，真实执行链路继续以任务中心为准。' },
        ]) +
      '</section>'
    );
  }

  function scheduleEmptyCalendarDetailBodyHtml() {
    return (
      "<section class='schedule-section'>" +
        "<div class='schedule-calendar-day-head'>" +
          "<div>" +
            "<div class='schedule-plan-title'>本月暂无计划排期</div>" +
            "<div class='schedule-plan-sub'>空态下也保留原型图中的右侧详情结构。先创建计划，随后从这里回看当月计划与真实结果。</div>" +
          '</div>' +
        '</div>' +
        "<div class='schedule-actions'>" +
          "<button class='alt' type='button' data-schedule-create='1'>新建定时任务</button>" +
        '</div>' +
      '</section>' +
      "<section class='schedule-section'><div class='card-title'>发起内容预览</div>" +
        schedulePlaceholderListHtml([
          { title: '本次目标', text: '计划命中后要发起什么任务，会在这里提前预览。' },
          { title: '关键动作', text: '把关键检查动作和交付要求写清楚，避免只知道“会触发”但不知道“触发什么”。' },
        ]) +
      '</section>' +
      "<section class='schedule-section'><div class='card-title'>当月计划</div>" +
        schedulePlaceholderListHtml([
          { title: '暂无当月计划', text: '保存后，日历会同时展示未来计划与已经发生的执行结果。' },
        ]) +
      '</section>' +
      "<section class='schedule-section'><div class='card-title'>实际结果</div>" +
        schedulePlaceholderListHtml([
          { title: '暂无实际结果', text: '首次命中建单后，这里会回显任务中心里的真实状态和关联实例。' },
        ]) +
      '</section>'
    );
  }

  function schedulePlanCardHtml(item, isActive) {
    const labels = Array.isArray(item && item.rule_labels) ? item.rule_labels : [];
    const tone = !!(item && item.enabled) ? safe(item && item.last_result_status).trim().toLowerCase() || 'pending' : 'disabled';
    const text = !!(item && item.enabled)
      ? (safe(item && item.last_result_status_text).trim() || '待触发')
      : '已停用';
    const scheduleName = scheduleRepairText(item && item.schedule_name) || '-';
    const launchSummary = scheduleRepairText(item && item.launch_summary) || '-';
    return (
      "<button class='schedule-plan-item" + (isActive ? " active" : '') + "' type='button' data-schedule-select='" + escapeHtml(safe(item && item.schedule_id).trim()) + "'>" +
        "<div class='schedule-plan-title'>" + escapeHtml(scheduleName) + '</div>' +
        "<div class='schedule-plan-desc'>" + escapeHtml(launchSummary) + '</div>' +
        "<div class='schedule-plan-rules'>" +
          labels.map((label) => "<span class='schedule-rule-chip'>" + escapeHtml(label) + "</span>").join('') +
        '</div>' +
        "<div class='schedule-plan-meta'>" +
          "<div><div class='schedule-plan-sub'>下一次触发</div><div class='schedule-plan-sub'>" + escapeHtml(safe(item && item.next_trigger_text).trim() || '-') + '</div></div>' +
          "<div><div class='schedule-plan-sub'>最近结果</div><div>" + scheduleStatusChipHtml(tone, text, tone) + '</div></div>' +
        '</div>' +
      '</button>'
    );
  }

  function scheduleStatHtml(label, value) {
    return (
      "<div class='schedule-stat'>" +
        "<div class='schedule-stat-k'>" + escapeHtml(label) + '</div>' +
        "<div class='schedule-stat-v'>" + escapeHtml(safe(value).trim() || '-') + '</div>' +
      '</div>'
    );
  }

  function scheduleHistoryItemHtml(item) {
    const openBtn = safe(item && item.assignment_ticket_id).trim() && safe(item && item.assignment_node_id).trim()
      ? "<button class='alt schedule-jump-btn' type='button' data-open-task-center='1' data-ticket-id='" + escapeHtml(safe(item.assignment_ticket_id).trim()) + "' data-node-id='" + escapeHtml(safe(item.assignment_node_id).trim()) + "'>去任务中心查看</button>"
      : '';
    return (
      "<div class='schedule-list-item'>" +
        "<div class='schedule-list-item-head'>" +
          "<div>" +
            "<div class='schedule-plan-title'>" + escapeHtml(scheduleFormatBeijingTime(item && item.planned_trigger_at)) + '</div>' +
            "<div class='schedule-plan-sub'>" + escapeHtml(safe(item && item.trigger_rule_summary).trim() || '-') + '</div>' +
          '</div>' +
          scheduleStatusChipHtml(safe(item && item.result_status).trim(), safe(item && item.result_status_text).trim() || '-', '') +
        '</div>' +
        "<div class='schedule-plan-sub'>" + escapeHtml(safe(item && item.trigger_message).trim() || safe(item && item.assignment_status_text).trim() || '-') + '</div>' +
        (openBtn ? "<div class='schedule-actions'>" + openBtn + '</div>' : '') +
      '</div>'
    );
  }

  function renderScheduleDetailBody() {
    const body = $('scheduleDetailBody');
    const meta = $('scheduleDetailMeta');
    if (!body) return;
    const detail = state.scheduleDetail && typeof state.scheduleDetail === 'object' ? state.scheduleDetail : {};
    const selectedId = safe(state.scheduleSelectedId).trim();
    const selectedPlan = selectedSchedulePlan();
    const detailSchedule = detail.schedule && typeof detail.schedule === 'object' ? detail.schedule : null;
    const schedule = selectedId
      ? (safe(detailSchedule && detailSchedule.schedule_id).trim() === selectedId ? detailSchedule : (selectedPlan || detailSchedule))
      : null;
    if (!schedule || !safe(schedule.schedule_id).trim()) {
      if (meta) meta.textContent = '暂无定时计划';
      body.innerHTML = scheduleEmptyDetailBodyHtml();
      return;
    }
    if (meta) meta.textContent = 'source_schedule_id: ' + safe(schedule.schedule_id).trim();
    const future = Array.isArray(detail.future_triggers) ? detail.future_triggers : [];
    const recent = Array.isArray(detail.recent_triggers) ? detail.recent_triggers : [];
    const related = Array.isArray(detail.related_task_refs) ? detail.related_task_refs : [];
    const enabled = !!schedule.enabled;
    const scheduleName = scheduleRepairText(schedule.schedule_name) || '-';
    const launchSummary = scheduleRepairText(schedule.launch_summary) || '-';
    const executionChecklist = scheduleRepairText(schedule.execution_checklist) || '-';
    const doneDefinition = scheduleRepairText(schedule.done_definition) || '-';
    body.innerHTML =
      "<section class='schedule-hero'>" +
        "<div class='schedule-hero-head'>" +
          "<div>" +
            "<div class='schedule-plan-title'>" + escapeHtml(scheduleName) + '</div>' +
            "<div class='schedule-plan-sub'>" + escapeHtml(launchSummary) + '</div>' +
          '</div>' +
          scheduleStatusChipHtml(enabled ? safe(schedule.last_result_status).trim() : 'disabled', enabled ? (safe(schedule.last_result_status_text).trim() || '待触发') : '已停用', enabled ? '' : 'disabled') +
        '</div>' +
        "<div class='schedule-actions'>" +
          "<button class='alt' type='button' data-schedule-action='edit' data-schedule-id='" + escapeHtml(safe(schedule.schedule_id).trim()) + "'>编辑计划</button>" +
          "<button class='alt' type='button' data-schedule-action='" + (enabled ? 'disable' : 'enable') + "' data-schedule-id='" + escapeHtml(safe(schedule.schedule_id).trim()) + "'>" + (enabled ? '停用计划' : '启用计划') + "</button>" +
          "<button class='bad' type='button' data-schedule-action='delete' data-schedule-id='" + escapeHtml(safe(schedule.schedule_id).trim()) + "'>删除计划</button>" +
        '</div>' +
        "<div class='schedule-hero-grid'>" +
          scheduleStatHtml('执行 Agent', safe(schedule.assigned_agent_name).trim() || safe(schedule.assigned_agent_id).trim()) +
          scheduleStatHtml('优先级', safe(schedule.priority).trim()) +
          scheduleStatHtml('下一次触发', safe(schedule.next_trigger_text).trim()) +
          scheduleStatHtml('最近一次触发', safe(schedule.last_trigger_at).trim() ? scheduleFormatBeijingTime(schedule.last_trigger_at) : '-') +
        '</div>' +
      '</section>' +
      "<section class='schedule-section'>" +
        "<div class='schedule-section-head'><div class='card-title'>发起任务内容预览</div></div>" +
        "<div class='schedule-section-grid'>" +
          scheduleStatHtml('本次目标', launchSummary) +
          scheduleStatHtml('预期产物', safe(schedule.expected_artifact).trim() || '-') +
          scheduleStatHtml('执行清单', executionChecklist) +
          scheduleStatHtml('完成标准', doneDefinition) +
        '</div>' +
      '</section>' +
      "<section class='schedule-section'><div class='card-title'>触发规则</div><div class='schedule-plan-rules'>" +
        (Array.isArray(schedule.rule_labels) && schedule.rule_labels.length
          ? schedule.rule_labels.map((label) => "<span class='schedule-rule-chip'>" + escapeHtml(label) + "</span>").join('')
          : "<span class='schedule-plan-sub'>暂无规则</span>") +
      '</div></section>' +
      "<section class='schedule-section'><div class='card-title'>未来触发</div><div class='schedule-list'>" +
        (future.length
          ? future.map((item) => "<div class='schedule-list-item'><div class='schedule-plan-title'>" + escapeHtml(scheduleFormatBeijingTime(item.planned_trigger_at)) + "</div><div class='schedule-plan-sub'>" + escapeHtml(safe(item.trigger_rule_summary).trim() || '-') + "</div></div>").join('')
          : "<div class='schedule-empty'><div class='schedule-plan-sub'>暂无未来触发</div></div>") +
      '</div></section>' +
      "<section class='schedule-section'><div class='card-title'>最近执行结果</div><div class='schedule-list'>" +
        (recent.length ? recent.map(scheduleHistoryItemHtml).join('') : "<div class='schedule-empty'><div class='schedule-plan-sub'>暂无执行记录</div></div>") +
      '</div></section>' +
      "<section class='schedule-section'><div class='card-title'>关联任务中心实例</div><div class='schedule-list'>" +
        (related.length
          ? related.map((item) => "<div class='schedule-list-item'><div class='schedule-list-item-head'><div><div class='schedule-plan-title'>" + escapeHtml(scheduleRepairText(item.assignment_node_name) || safe(item.assignment_node_id).trim()) + "</div><div class='schedule-plan-sub'>" + escapeHtml(scheduleFormatBeijingTime(item.planned_trigger_at)) + "</div></div>" + scheduleStatusChipHtml(safe(item.result_status).trim(), safe(item.result_status_text).trim() || '-', '') + "</div><div class='schedule-actions'><button class='alt schedule-jump-btn' type='button' data-open-task-center='1' data-ticket-id='" + escapeHtml(safe(item.assignment_ticket_id).trim()) + "' data-node-id='" + escapeHtml(safe(item.assignment_node_id).trim()) + "'>去任务中心查看</button></div></div>").join('')
          : "<div class='schedule-empty'><div class='schedule-plan-sub'>暂无关联实例</div></div>") +
      '</div></section>';
  }

  function renderScheduleCalendarGrid() {
    const grid = $('scheduleCalendarGrid');
    const label = $('scheduleCalendarMonthLabel');
    if (!grid) return;
    const calendarData = state.scheduleCalendar && typeof state.scheduleCalendar === 'object' ? state.scheduleCalendar : {};
    if (label) label.textContent = safe(calendarData.month_title).trim() || '-';
    const days = Array.isArray(calendarData.days) ? calendarData.days : [];
    const headerNodes = [
      "<div class='schedule-weekday'>周一</div>",
      "<div class='schedule-weekday'>周二</div>",
      "<div class='schedule-weekday'>周三</div>",
      "<div class='schedule-weekday'>周四</div>",
      "<div class='schedule-weekday'>周五</div>",
      "<div class='schedule-weekday'>周六</div>",
      "<div class='schedule-weekday'>周日</div>",
    ];
    if (!state.agentSearchRootReady) {
      grid.innerHTML = headerNodes.concat(
        "<div class='schedule-calendar-empty'>" +
          scheduleEmptyCardHtml('功能已锁定', '请先在设置页配置有效的 agent 路径，定时任务日历才会解锁。') +
        '</div>',
      ).join('');
      return;
    }
    if (!scheduleCalendarHasEntries(calendarData)) {
      grid.innerHTML = headerNodes.concat(
        "<div class='schedule-calendar-empty'>" +
          scheduleEmptyCardHtml('本月暂无定时计划', '先在列表视角创建计划；保存后，这里会展示未来计划和真实执行结果。') +
        '</div>',
      ).join('');
      return;
    }
    grid.innerHTML = headerNodes.concat(
      days.map((day) => {
        const classes = ['schedule-day'];
        if (!day.is_current_month) classes.push('is-muted');
        if (day.is_today) classes.push('is-today');
        if (safe(day.date).trim() === safe(state.scheduleCalendarSelectedDate).trim()) classes.push('is-selected');
        const planEvents = (Array.isArray(day.plans) ? day.plans : []).slice(0, 2).map((item) => "<div class='schedule-day-event plan'>" + escapeHtml(safe(item.planned_trigger_at).trim().slice(11, 16) + ' ' + safe(item.schedule_name).trim()) + '</div>').join('');
        const resultEvents = (Array.isArray(day.results) ? day.results : []).slice(0, 2).map((item) => "<div class='schedule-day-event " + escapeHtml(scheduleResultTone(item.result_status)) + "'>" + escapeHtml(safe(item.planned_trigger_at).trim().slice(11, 16) + ' ' + safe(item.schedule_name_snapshot || item.assignment_node_name || item.schedule_id).trim()) + '</div>').join('');
        return "<button class='" + classes.join(' ') + "' type='button' data-schedule-day='" + escapeHtml(safe(day.date).trim()) + "'><div class='schedule-day-num'>" + escapeHtml(String(day.day || '')) + "</div><div class='schedule-day-events'>" + planEvents + resultEvents + "</div></button>";
      }).join(''),
    ).join('');
  }

  function renderScheduleCalendarDetail() {
    const body = $('scheduleCalendarDetailBody');
    const meta = $('scheduleCalendarDetailMeta');
    if (!body) return;
    const calendarData = state.scheduleCalendar && typeof state.scheduleCalendar === 'object' ? state.scheduleCalendar : {};
    if (!state.agentSearchRootReady) {
      if (meta) meta.textContent = '功能已锁定';
      body.innerHTML = scheduleEmptyCardHtml('功能已锁定', '请先在设置页配置有效的 agent 路径。');
      return;
    }
    if (!scheduleCalendarHasEntries(calendarData)) {
      if (meta) meta.textContent = '本月暂无计划';
      body.innerHTML = scheduleEmptyCalendarDetailBodyHtml();
      return;
    }
    const day = scheduleSelectedCalendarDay();
    if (!day) {
      if (meta) meta.textContent = '请选择日期';
      body.innerHTML = scheduleEmptyCardHtml('请选择日期', '点击左侧有事件的日期后，在这里查看当日计划和实际结果。');
      return;
    }
    if (meta) meta.textContent = safe(day.date).trim();
    const plans = Array.isArray(day.plans) ? day.plans : [];
    const results = Array.isArray(day.results) ? day.results : [];
    body.innerHTML =
      "<section class='schedule-section'>" +
        "<div class='schedule-calendar-day-head'><div><div class='schedule-plan-title'>" + escapeHtml(safe(day.date).trim()) + "</div><div class='schedule-plan-sub'>选中日可直接查看将要发起的任务摘要和已触发实例结果。</div></div></div>" +
      '</section>' +
      "<section class='schedule-section'><div class='card-title'>当日计划</div><div class='schedule-list'>" +
        (plans.length
          ? plans.map((item) => "<div class='schedule-list-item'><div class='schedule-list-item-head'><div><div class='schedule-plan-title'>" + escapeHtml(scheduleRepairText(item.schedule_name) || '-') + "</div><div class='schedule-plan-sub'>" + escapeHtml(scheduleFormatBeijingTime(item.planned_trigger_at)) + "</div></div><button class='alt schedule-jump-btn' type='button' data-schedule-action='edit' data-schedule-id='" + escapeHtml(safe(item.schedule_id).trim()) + "'>编辑计划</button></div><div class='schedule-plan-sub'>" + escapeHtml(safe(item.trigger_rule_summary).trim()) + "</div></div>").join('')
          : "<div class='schedule-empty'><div class='schedule-plan-sub'>当日暂无未来计划</div></div>") +
      '</div></section>' +
      "<section class='schedule-section'><div class='card-title'>实际结果</div><div class='schedule-list'>" +
        (results.length
          ? results.map((item) => "<div class='schedule-list-item'><div class='schedule-list-item-head'><div><div class='schedule-plan-title'>" + escapeHtml(scheduleRepairText(item.schedule_name_snapshot) || scheduleRepairText(item.assignment_node_name) || '-') + "</div><div class='schedule-plan-sub'>" + escapeHtml(scheduleFormatBeijingTime(item.planned_trigger_at)) + "</div></div>" + scheduleStatusChipHtml(safe(item.result_status).trim(), safe(item.result_status_text).trim() || '-', '') + "</div><div class='schedule-plan-sub'>" + escapeHtml(scheduleRepairText(item.launch_summary_snapshot) || safe(item.trigger_message).trim() || '-') + "</div><div class='schedule-actions'>" + (safe(item.assignment_ticket_id).trim() && safe(item.assignment_node_id).trim() ? "<button class='alt schedule-jump-btn' type='button' data-open-task-center='1' data-ticket-id='" + escapeHtml(safe(item.assignment_ticket_id).trim()) + "' data-node-id='" + escapeHtml(safe(item.assignment_node_id).trim()) + "'>去任务中心查看</button>" : '') + (safe(item.schedule_id).trim() ? "<button class='alt schedule-jump-btn' type='button' data-schedule-action='edit' data-schedule-id='" + escapeHtml(safe(item.schedule_id).trim()) + "'>编辑计划</button>" : '') + "</div></div>").join('')
          : "<div class='schedule-empty'><div class='schedule-plan-sub'>当日暂无执行结果</div></div>") +
      '</div></section>';
  }

  function populateScheduleEditor() {
    const schedule = state.scheduleEditorMode === 'edit' ? selectedScheduleDetail() : {};
    const inputs = schedule.editor_rule_inputs || { monthly: {}, weekly: {}, daily: {}, once: {} };
    $('scheduleEditorTitle').textContent = state.scheduleEditorMode === 'edit' ? '编辑定时任务' : '新建定时任务';
    $('scheduleEditorNameInput').value = scheduleRepairText(schedule.schedule_name);
    $('scheduleEditorPrioritySelect').value = safe(schedule.priority).trim() || 'P1';
    $('scheduleEditorLaunchSummaryInput').value = scheduleRepairText(schedule.launch_summary);
    $('scheduleEditorChecklistInput').value = scheduleRepairText(schedule.execution_checklist);
    $('scheduleEditorDoneDefinitionInput').value = scheduleRepairText(schedule.done_definition);
    $('scheduleEditorArtifactInput').value = safe(schedule.expected_artifact).trim();
    $('scheduleEditorDeliveryModeSelect').value = safe(schedule.delivery_mode).trim() || 'none';
    $('scheduleEditorEnabledCheck').checked = state.scheduleEditorMode === 'edit' ? !!schedule.enabled : true;
    $('scheduleRuleMonthlyEnabled').checked = !!inputs.monthly.enabled;
    $('scheduleRuleMonthlyDays').value = safe(inputs.monthly.days_text).trim();
    $('scheduleRuleMonthlyTimes').value = safe(inputs.monthly.times_text).trim();
    $('scheduleRuleWeeklyEnabled').checked = !!inputs.weekly.enabled;
    $('scheduleRuleWeeklyTimes').value = safe(inputs.weekly.times_text).trim();
    document.querySelectorAll('[data-schedule-weekday]').forEach((node) => {
      node.checked = Array.isArray(inputs.weekly.weekdays) && inputs.weekly.weekdays.includes(Number(node.getAttribute('data-schedule-weekday')));
    });
    $('scheduleRuleDailyEnabled').checked = !!inputs.daily.enabled;
    $('scheduleRuleDailyTimes').value = safe(inputs.daily.times_text).trim();
    $('scheduleRuleOnceEnabled').checked = !!inputs.once.enabled;
    $('scheduleRuleOnceDates').value = safe(inputs.once.date_times_text).trim();
    const agentSelect = $('scheduleEditorAgentSelect');
    const deliverySelect = $('scheduleEditorDeliveryReceiverSelect');
    const options = Array.isArray(state.agents) ? state.agents : [];
    const currentAgent = safe(schedule.assigned_agent_id).trim() || safe(schedule.assigned_agent_name).trim();
    const currentReceiver = safe(schedule.delivery_receiver_agent_id).trim() || safe(schedule.delivery_receiver_agent_name).trim();
    const rendered = ["<option value=''>请选择执行 agent</option>"].concat(options.map((item) => "<option value='" + escapeHtml(safe(item && item.agent_id).trim() || safe(item && item.agent_name).trim()) + "'>" + escapeHtml(safe(item && item.agent_name).trim() || safe(item && item.agent_id).trim()) + "</option>"));
    if (agentSelect) {
      agentSelect.innerHTML = rendered.join('');
      agentSelect.value = currentAgent;
    }
    if (deliverySelect) {
      deliverySelect.innerHTML = ["<option value=''>默认交付给当前 agent</option>"].concat(rendered.slice(1)).join('');
      deliverySelect.value = currentReceiver;
    }
    if (typeof scheduleApplyEditorDeliveryModeState === 'function') {
      scheduleApplyEditorDeliveryModeState();
    }
    setScheduleEditorError(state.scheduleEditorError);
  }

  function renderScheduleCenter() {
    const errorNode = $('scheduleError');
    if (errorNode) errorNode.textContent = state.scheduleError || '';
    const listBtn = $('scheduleViewListBtn');
    const calendarBtn = $('scheduleViewCalendarBtn');
    const listView = $('scheduleListView');
    const calendarView = $('scheduleCalendarView');
    if (listBtn) listBtn.classList.toggle('active', state.scheduleView !== 'calendar');
    if (calendarBtn) calendarBtn.classList.toggle('active', state.scheduleView === 'calendar');
    if (listView) listView.classList.toggle('active', state.scheduleView !== 'calendar');
    if (calendarView) calendarView.classList.toggle('active', state.scheduleView === 'calendar');
    const meta = $('scheduleMeta');
    if (meta) {
      if (!state.agentSearchRootReady) {
        meta.textContent = 'agent路径未设置或无效，定时任务模块已锁定。';
      } else if (state.scheduleLoading) {
        meta.textContent = '计划加载中...';
      } else if (!Array.isArray(state.schedulePlans) || !state.schedulePlans.length) {
        meta.textContent = '暂无计划，可点击 + 新建';
      } else {
        meta.textContent = '共 ' + String(Array.isArray(state.schedulePlans) ? state.schedulePlans.length : 0) + ' 条计划';
      }
    }
    const list = $('schedulePlanList');
    const count = $('schedulePlanCountChip');
    if (count) count.textContent = String(Array.isArray(state.schedulePlans) ? state.schedulePlans.length : 0) + ' 条计划';
    if (list) {
      if (!state.agentSearchRootReady) {
        list.innerHTML = "<div class='schedule-empty'><div class='schedule-plan-title'>功能已锁定</div><div class='schedule-plan-sub'>请先在设置页配置有效的 agent 路径。</div></div>";
      } else if (!Array.isArray(state.schedulePlans) || !state.schedulePlans.length) {
        list.innerHTML = scheduleEmptyGuideHtml(
          '暂无定时计划',
          '当前还没有可执行的定时计划。先创建一条计划，后续会在这里看到下一次触发、最近结果和规则摘要。',
          [
            { title: '计划配置', text: '填写计划名称、执行 agent、发起摘要、执行清单和完成标准。' },
            { title: '规则混合', text: '支持每月 / 每周 / 每日 / 定时混合启用，并自动合并同分钟命中。' },
            { title: '结果回看', text: '命中后会向任务中心建单，这里再同步展示真实执行结果。' },
          ],
          { kicker: '列表视角', ctaLabel: '新建定时任务' },
        );
      } else {
        list.innerHTML = state.schedulePlans.map((item) => schedulePlanCardHtml(item, safe(item && item.schedule_id).trim() === safe(state.scheduleSelectedId).trim())).join('');
      }
    }
    renderScheduleDetailBody();
    renderScheduleCalendarGrid();
    renderScheduleCalendarDetail();
    const mask = $('scheduleEditorMask');
    if (mask) {
      mask.classList.toggle('hidden', !state.scheduleEditorOpen);
    }
    if (state.scheduleEditorOpen) {
      populateScheduleEditor();
    }
  }
