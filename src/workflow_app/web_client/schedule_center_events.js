  function scheduleRunWithElementLock(element, task) {
    const node = element instanceof HTMLElement ? element : null;
    const previous = node ? !!node.disabled : false;
    if (node) node.disabled = true;
    return Promise.resolve()
      .then(() => task())
      .finally(() => {
        if (node) node.disabled = previous;
      });
  }

  function scheduleWeekdaySelections() {
    return Array.from(document.querySelectorAll('[data-schedule-weekday]'))
      .filter((node) => node instanceof HTMLInputElement && node.checked)
      .map((node) => Number(node.getAttribute('data-schedule-weekday')))
      .filter((value) => Number.isFinite(value) && value >= 1 && value <= 7);
  }

  function scheduleApplyEditorDeliveryModeState() {
    const deliveryModeSelect = $('scheduleEditorDeliveryModeSelect');
    const receiverSelect = $('scheduleEditorDeliveryReceiverSelect');
    if (!receiverSelect) return;
    const specified = safe(deliveryModeSelect ? deliveryModeSelect.value : 'none').trim().toLowerCase() === 'specified';
    receiverSelect.disabled = !specified;
    if (!specified) {
      receiverSelect.value = '';
    }
  }

  function scheduleEditorRuleSetsFromInputs() {
    return {
      monthly: {
        enabled: !!($('scheduleRuleMonthlyEnabled') && $('scheduleRuleMonthlyEnabled').checked),
        days_text: safe($('scheduleRuleMonthlyDays') ? $('scheduleRuleMonthlyDays').value : '').trim(),
        times_text: safe($('scheduleRuleMonthlyTimes') ? $('scheduleRuleMonthlyTimes').value : '').trim(),
      },
      weekly: {
        enabled: !!($('scheduleRuleWeeklyEnabled') && $('scheduleRuleWeeklyEnabled').checked),
        weekdays: scheduleWeekdaySelections(),
        times_text: safe($('scheduleRuleWeeklyTimes') ? $('scheduleRuleWeeklyTimes').value : '').trim(),
      },
      daily: {
        enabled: !!($('scheduleRuleDailyEnabled') && $('scheduleRuleDailyEnabled').checked),
        times_text: safe($('scheduleRuleDailyTimes') ? $('scheduleRuleDailyTimes').value : '').trim(),
      },
      once: {
        enabled: !!($('scheduleRuleOnceEnabled') && $('scheduleRuleOnceEnabled').checked),
        date_times_text: safe($('scheduleRuleOnceDates') ? $('scheduleRuleOnceDates').value : '').trim(),
      },
    };
  }

  function scheduleEditorPayloadFromInputs() {
    const deliveryMode = safe($('scheduleEditorDeliveryModeSelect') ? $('scheduleEditorDeliveryModeSelect').value : 'none').trim().toLowerCase() === 'specified'
      ? 'specified'
      : 'none';
    return {
      schedule_name: safe($('scheduleEditorNameInput') ? $('scheduleEditorNameInput').value : '').trim(),
      assigned_agent_id: safe($('scheduleEditorAgentSelect') ? $('scheduleEditorAgentSelect').value : '').trim(),
      priority: safe($('scheduleEditorPrioritySelect') ? $('scheduleEditorPrioritySelect').value : 'P1').trim() || 'P1',
      launch_summary: safe($('scheduleEditorLaunchSummaryInput') ? $('scheduleEditorLaunchSummaryInput').value : '').trim(),
      execution_checklist: safe($('scheduleEditorChecklistInput') ? $('scheduleEditorChecklistInput').value : '').trim(),
      done_definition: safe($('scheduleEditorDoneDefinitionInput') ? $('scheduleEditorDoneDefinitionInput').value : '').trim(),
      expected_artifact: safe($('scheduleEditorArtifactInput') ? $('scheduleEditorArtifactInput').value : '').trim(),
      delivery_mode: deliveryMode,
      delivery_receiver_agent_id: deliveryMode === 'specified'
        ? safe($('scheduleEditorDeliveryReceiverSelect') ? $('scheduleEditorDeliveryReceiverSelect').value : '').trim()
        : '',
      enabled: !!($('scheduleEditorEnabledCheck') && $('scheduleEditorEnabledCheck').checked),
      rule_sets: scheduleEditorRuleSetsFromInputs(),
      operator: 'web-user',
    };
  }

  async function ensureScheduleEditorAgentsReady() {
    if (!state.agentSearchRootReady) return;
    if (Array.isArray(state.agents) && state.agents.length) return;
    await refreshAgents(true, { autoAnalyze: false, forceRefresh: false });
  }

  async function refreshScheduleCenterData(options) {
    const opts = options && typeof options === 'object' ? options : {};
    const preserveSelection = opts.preserveSelection !== false;
    const nextScheduleId = safe(opts.scheduleId).trim();
    const targetMonth = safe(opts.month).trim() || state.scheduleCalendarMonth || scheduleCurrentMonthKey();
    if (nextScheduleId) {
      state.scheduleSelectedId = nextScheduleId;
    }
    await refreshSchedulePlans({ preserveSelection: preserveSelection });
    await refreshScheduleCalendar(targetMonth);
  }

  async function openScheduleEditorForMode(mode, scheduleId) {
    const nextMode = safe(mode).trim().toLowerCase() === 'edit' ? 'edit' : 'create';
    await ensureScheduleEditorAgentsReady();
    if (nextMode === 'edit') {
      const targetId = safe(scheduleId || state.scheduleSelectedId || (selectedScheduleDetail() || {}).schedule_id).trim();
      if (!targetId) {
        throw new Error('请先选择定时计划');
      }
      const selectedDetailId = safe((selectedScheduleDetail() || {}).schedule_id).trim();
      if (selectedDetailId !== targetId) {
        await refreshScheduleDetail(targetId);
      }
      openScheduleEditor('edit', targetId);
    } else {
      openScheduleEditor('create');
    }
    scheduleApplyEditorDeliveryModeState();
  }

  async function submitScheduleEditor() {
    const payload = scheduleEditorPayloadFromInputs();
    const editMode = safe(state.scheduleEditorMode).trim().toLowerCase() === 'edit';
    let data = null;
    if (editMode) {
      const scheduleId = safe(state.scheduleSelectedId || (selectedScheduleDetail() || {}).schedule_id).trim();
      if (!scheduleId) {
        throw new Error('待编辑计划不存在');
      }
      data = await postJSON('/api/schedules/' + encodeURIComponent(scheduleId), payload);
      state.scheduleSelectedId = scheduleId;
    } else {
      data = await postJSON('/api/schedules', payload);
      state.scheduleSelectedId = safe(data && data.schedule_id).trim() || safe(state.scheduleSelectedId).trim();
    }
    state.scheduleDetail = data;
    closeScheduleEditor();
    await refreshScheduleCenterData({
      preserveSelection: true,
      scheduleId: safe(state.scheduleSelectedId).trim(),
    });
    setStatus(editMode ? '定时计划已更新' : '定时计划已创建');
  }

  async function setScheduleEnabledAction(scheduleId, enabled) {
    const targetId = safe(scheduleId || state.scheduleSelectedId).trim();
    if (!targetId) {
      throw new Error('请先选择定时计划');
    }
    await postJSON(
      '/api/schedules/' + encodeURIComponent(targetId) + (enabled ? '/enable' : '/disable'),
      { operator: 'web-user' },
    );
    await refreshScheduleCenterData({
      preserveSelection: true,
      scheduleId: targetId,
    });
    setStatus(enabled ? '定时计划已启用' : '定时计划已停用');
  }

  async function deleteScheduleAction(scheduleId) {
    const targetId = safe(scheduleId || state.scheduleSelectedId).trim();
    const schedule = selectedScheduleDetail() || {};
    if (!targetId) {
      throw new Error('请先选择定时计划');
    }
    const scheduleName = safe(schedule.schedule_id).trim() === targetId
      ? safe(schedule.schedule_name).trim() || targetId
      : targetId;
    const ok = window.confirm('将删除计划“' + scheduleName + '”。删除只影响未来触发，不会抹除历史触发与已创建实例。确认继续？');
    if (!ok) return;
    await deleteJSON('/api/schedules/' + encodeURIComponent(targetId), {
      operator: 'web-user',
    });
    if (safe(state.scheduleSelectedId).trim() === targetId) {
      state.scheduleSelectedId = '';
      state.scheduleDetail = null;
    }
    await refreshScheduleCenterData({ preserveSelection: false });
    setStatus('定时计划已删除');
  }

  async function scanSchedulesNow() {
    const targetId = safe(state.scheduleSelectedId).trim();
    const payload = { operator: 'web-user' };
    if (targetId) {
      payload.schedule_id = targetId;
    }
    const prefix = targetId ? '当前计划' : '全部启用计划';
    setStatus('正在扫描' + prefix + '...');
    const result = await postJSON('/api/schedules/scan', payload);
    await refreshScheduleCenterData({
      preserveSelection: true,
      scheduleId: targetId,
    });
    let message = prefix + '扫描完成';
    if (Number(result.hit_count || 0) <= 0) {
      message += '，本分钟无命中';
    } else {
      message += '，命中 ' + String(Number(result.hit_count || 0)) + ' 条';
      if (Number(result.created_node_count || 0) > 0) {
        message += '，建单 ' + String(Number(result.created_node_count || 0)) + ' 条';
      }
      if (Number(result.deduped_count || 0) > 0) {
        message += '，去重 ' + String(Number(result.deduped_count || 0)) + ' 条';
      }
    }
    setStatus(message);
  }

  async function selectSchedulePlan(scheduleId) {
    const targetId = safe(scheduleId).trim();
    if (!targetId) return;
    setScheduleSelectedId(targetId);
    await refreshScheduleDetail(targetId);
  }

  function ensureScheduleCenterProbeOutputNode() {
    let node = $('scheduleCenterProbeOutput');
    if (node) return node;
    node = document.createElement('pre');
    node.id = 'scheduleCenterProbeOutput';
    node.style.display = 'none';
    document.body.appendChild(node);
    return node;
  }

  function scheduleProbeWait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function scheduleProbeCase() {
    return safe(queryParam('schedule_probe_case')).trim().toLowerCase() || 'list_default';
  }

  function scheduleProbeDelayMs() {
    return Math.max(0, Number(queryParam('schedule_probe_delay_ms') || '900'));
  }

  function scheduleProbeScheduleId() {
    return safe(queryParam('schedule_probe_schedule')).trim();
  }

  function scheduleProbeMonth() {
    return safe(queryParam('schedule_probe_month')).trim();
  }

  function scheduleProbeBaseMonth() {
    return safe(queryParam('schedule_probe_base_month')).trim();
  }

  function scheduleProbeDate() {
    return safe(queryParam('schedule_probe_date')).trim();
  }

  function createScheduleCenterProbeOutput() {
    return {
      ts: new Date().toISOString(),
      case: scheduleProbeCase(),
      pass: false,
      error: '',
      active_tab: '',
      schedule_view: safe(state.scheduleView).trim() || 'list',
      plan_count: Array.isArray(state.schedulePlans) ? state.schedulePlans.length : 0,
      list_card_count: 0,
      selected_schedule_id: '',
      selected_schedule_name: '',
      detail_meta: '',
      detail_action_count: 0,
      rule_chip_count: 0,
      future_trigger_count: 0,
      recent_trigger_count: 0,
      related_task_count: 0,
      create_btn_visible: false,
      latest_result_status: '',
      latest_result_text: '',
      latest_assignment_ticket_id: '',
      latest_assignment_node_id: '',
      editor_open: false,
      editor_mode: '',
      editor_title: '',
      editor_name: '',
      editor_agent: '',
      editor_launch_summary: '',
      editor_receiver_disabled: true,
      editor_receiver_value: '',
      calendar_month: '',
      calendar_month_label: '',
      calendar_base_month: '',
      calendar_probe_month: '',
      calendar_selected_date: '',
      calendar_day_count: 0,
      calendar_plan_count: 0,
      calendar_result_count: 0,
      calendar_edit_btn_count: 0,
      list_empty_visible: false,
      list_empty_text: '',
      detail_empty_text: '',
      detail_empty_title: '',
      calendar_empty_visible: false,
      calendar_empty_text: '',
      calendar_detail_empty_text: '',
      calendar_detail_empty_title: '',
      empty_create_btn_count: 0,
    };
  }

  async function prepareScheduleEmptyProbe() {
    switchTab('schedule-center');
    setScheduleView('list');
    state.scheduleSelectedId = '';
    state.scheduleDetail = null;
    await refreshSchedulePlans({ preserveSelection: false });
    await refreshScheduleCalendar(state.scheduleCalendarMonth || scheduleCurrentMonthKey());
    setScheduleView('calendar');
    await scheduleProbeWait(80);
  }

  async function prepareScheduleListProbe() {
    const scheduleId = scheduleProbeScheduleId();
    switchTab('schedule-center');
    setScheduleView('list');
    await refreshScheduleCenterData({
      preserveSelection: true,
      scheduleId: scheduleId,
    });
    if (scheduleId) {
      await refreshScheduleDetail(scheduleId);
    }
  }

  async function prepareScheduleEditorProbe() {
    await prepareScheduleListProbe();
    await openScheduleEditorForMode('edit', scheduleProbeScheduleId());
    await scheduleProbeWait(80);
  }

  async function prepareScheduleCalendarProbe() {
    const scheduleId = scheduleProbeScheduleId();
    const targetMonth = scheduleProbeMonth() || state.scheduleCalendarMonth || scheduleCurrentMonthKey();
    const targetDate = scheduleProbeDate();
    state.scheduleCalendarMonth = targetMonth;
    switchTab('schedule-center');
    setScheduleView('calendar');
    if (scheduleId) {
      state.scheduleSelectedId = scheduleId;
    }
    await scheduleProbeWait(180);
    await refreshScheduleCalendar(targetMonth);
    if (safe(state.scheduleCalendarMonth).trim() !== targetMonth) {
      await refreshScheduleCalendar(targetMonth);
    }
    if (targetDate) {
      setScheduleCalendarSelectedDate(targetDate);
    }
    await scheduleProbeWait(80);
  }

  function collectScheduleCenterProbe(output) {
    const detail = state.scheduleDetail && typeof state.scheduleDetail === 'object' ? state.scheduleDetail : {};
    const schedule = detail.schedule && typeof detail.schedule === 'object' ? detail.schedule : selectedScheduleDetail();
    const recent = Array.isArray(detail.recent_triggers) ? detail.recent_triggers : [];
    const related = Array.isArray(detail.related_task_refs) ? detail.related_task_refs : [];
    const future = Array.isArray(detail.future_triggers) ? detail.future_triggers : [];
    const latest = recent[0] && typeof recent[0] === 'object' ? recent[0] : {};
    const day = scheduleSelectedCalendarDay();
    const activeTab = document.querySelector('.tab.active');
    output.active_tab = safe(activeTab && activeTab.getAttribute('data-tab')).trim();
    output.schedule_view = safe(state.scheduleView).trim() || 'list';
    output.plan_count = Array.isArray(state.schedulePlans) ? state.schedulePlans.length : 0;
    output.list_card_count = document.querySelectorAll('#schedulePlanList .schedule-plan-item').length;
    output.selected_schedule_id = safe(schedule && schedule.schedule_id).trim();
    output.selected_schedule_name = safe(schedule && schedule.schedule_name).trim();
    output.detail_meta = safe($('scheduleDetailMeta') ? $('scheduleDetailMeta').textContent : '').trim();
    output.detail_action_count = document.querySelectorAll('#scheduleDetailBody [data-schedule-action]').length;
    output.rule_chip_count = document.querySelectorAll('#scheduleDetailBody .schedule-rule-chip').length;
    output.future_trigger_count = future.length;
    output.recent_trigger_count = recent.length;
    output.related_task_count = related.length;
    output.create_btn_visible = !!$('scheduleCreateBtn');
    output.latest_result_status = safe(latest && latest.result_status).trim().toLowerCase();
    output.latest_result_text = safe(latest && latest.result_status_text).trim();
    output.latest_assignment_ticket_id = safe(latest && latest.assignment_ticket_id).trim();
    output.latest_assignment_node_id = safe(latest && latest.assignment_node_id).trim();
    output.editor_open = !!state.scheduleEditorOpen;
    output.editor_mode = safe(state.scheduleEditorMode).trim().toLowerCase();
    output.editor_title = safe($('scheduleEditorTitle') ? $('scheduleEditorTitle').textContent : '').trim();
    output.editor_name = safe($('scheduleEditorNameInput') ? $('scheduleEditorNameInput').value : '').trim();
    output.editor_agent = safe($('scheduleEditorAgentSelect') ? $('scheduleEditorAgentSelect').value : '').trim();
    output.editor_launch_summary = safe($('scheduleEditorLaunchSummaryInput') ? $('scheduleEditorLaunchSummaryInput').value : '').trim();
    output.editor_receiver_disabled = !!($('scheduleEditorDeliveryReceiverSelect') && $('scheduleEditorDeliveryReceiverSelect').disabled);
    output.editor_receiver_value = safe($('scheduleEditorDeliveryReceiverSelect') ? $('scheduleEditorDeliveryReceiverSelect').value : '').trim();
    output.calendar_month = safe(state.scheduleCalendarMonth).trim();
    output.calendar_month_label = safe($('scheduleCalendarMonthLabel') ? $('scheduleCalendarMonthLabel').textContent : '').trim();
    output.calendar_base_month = scheduleProbeBaseMonth();
    output.calendar_probe_month = scheduleProbeMonth();
    output.calendar_selected_date = safe(state.scheduleCalendarSelectedDate).trim();
    output.calendar_day_count = document.querySelectorAll('#scheduleCalendarGrid .schedule-day').length;
    output.calendar_plan_count = Array.isArray(day && day.plans) ? day.plans.length : 0;
    output.calendar_result_count = Array.isArray(day && day.results) ? day.results.length : 0;
    output.calendar_edit_btn_count = document.querySelectorAll('#scheduleCalendarDetailBody [data-schedule-action="edit"]').length;
    output.list_empty_visible = !!document.querySelector('#schedulePlanList .schedule-empty');
    output.list_empty_text = safe(document.querySelector('#schedulePlanList .schedule-empty') ? document.querySelector('#schedulePlanList .schedule-empty').textContent : '').trim();
    output.detail_empty_text = safe(document.querySelector('#scheduleDetailBody .schedule-empty') ? document.querySelector('#scheduleDetailBody .schedule-empty').textContent : '').trim();
    output.detail_empty_title = safe(document.querySelector('#scheduleDetailBody .schedule-hero-empty .schedule-plan-title') ? document.querySelector('#scheduleDetailBody .schedule-hero-empty .schedule-plan-title').textContent : '').trim();
    output.calendar_empty_visible = !!document.querySelector('#scheduleCalendarGrid .schedule-calendar-empty');
    output.calendar_empty_text = safe(document.querySelector('#scheduleCalendarGrid .schedule-calendar-empty') ? document.querySelector('#scheduleCalendarGrid .schedule-calendar-empty').textContent : '').trim();
    output.calendar_detail_empty_text = safe(document.querySelector('#scheduleCalendarDetailBody .schedule-empty') ? document.querySelector('#scheduleCalendarDetailBody .schedule-empty').textContent : '').trim();
    output.calendar_detail_empty_title = safe(document.querySelector('#scheduleCalendarDetailBody .schedule-section .schedule-plan-title') ? document.querySelector('#scheduleCalendarDetailBody .schedule-section .schedule-plan-title').textContent : '').trim();
    output.empty_create_btn_count = document.querySelectorAll('[data-schedule-create]').length;
  }

  function scheduleEmptyStateProbePass(output) {
    return output.active_tab === 'schedule-center' &&
      output.plan_count === 0 &&
      output.list_card_count === 0 &&
      output.list_empty_visible &&
      output.list_empty_text.indexOf('暂无定时计划') >= 0 &&
      (
        output.detail_empty_text.indexOf('暂无定时计划') >= 0 ||
        output.detail_empty_title.indexOf('先创建一条定时任务') >= 0
      ) &&
      output.calendar_empty_visible &&
      output.calendar_empty_text.indexOf('本月暂无定时计划') >= 0 &&
      (
        output.calendar_detail_empty_text.indexOf('本月暂无计划') >= 0 ||
        output.calendar_detail_empty_title.indexOf('本月暂无计划') >= 0
      ) &&
      output.empty_create_btn_count >= 1;
  }

  function scheduleListDefaultProbePass(output) {
    return output.active_tab === 'schedule-center' &&
      output.schedule_view === 'list' &&
      output.plan_count >= 1 &&
      output.list_card_count >= 1 &&
      !!output.selected_schedule_id &&
      output.create_btn_visible &&
      output.detail_action_count >= 3 &&
      output.future_trigger_count >= 1;
  }

  function scheduleListDetailProbePass(output) {
    return scheduleListDefaultProbePass(output) &&
      output.rule_chip_count >= 1 &&
      output.detail_meta.indexOf('source_schedule_id: ') === 0;
  }

  function scheduleEditorEditProbePass(output) {
    return output.active_tab === 'schedule-center' &&
      output.editor_open &&
      output.editor_mode === 'edit' &&
      output.editor_title.indexOf('编辑定时任务') >= 0 &&
      !!output.editor_name &&
      !!output.editor_agent &&
      !!output.editor_launch_summary;
  }

  function scheduleCalendarMonthProbePass(output) {
    return output.active_tab === 'schedule-center' &&
      output.schedule_view === 'calendar' &&
      !!output.calendar_month &&
      !!output.calendar_month_label &&
      output.calendar_day_count >= 28 &&
      !!output.calendar_selected_date &&
      (output.calendar_plan_count + output.calendar_result_count) >= 1 &&
      output.calendar_edit_btn_count >= 1;
  }

  function scheduleCalendarShiftedProbePass(output) {
    return scheduleCalendarMonthProbePass(output) &&
      (!output.calendar_probe_month || output.calendar_month === output.calendar_probe_month) &&
      (!output.calendar_base_month || output.calendar_month !== output.calendar_base_month);
  }

  function scheduleResultDetailProbePass(output) {
    return output.active_tab === 'schedule-center' &&
      output.schedule_view === 'list' &&
      output.recent_trigger_count >= 1 &&
      output.related_task_count >= 1 &&
      !!output.latest_assignment_ticket_id &&
      !!output.latest_assignment_node_id &&
      ['queued', 'running', 'succeeded', 'failed'].includes(output.latest_result_status);
  }

  async function runScheduleCenterProbe() {
    const output = createScheduleCenterProbeOutput();
    try {
      const probeCase = output.case;
      if (probeCase === 'empty_state') {
        await prepareScheduleEmptyProbe();
      } else if (probeCase === 'editor_edit') {
        await prepareScheduleEditorProbe();
      } else if (probeCase === 'calendar_month' || probeCase === 'calendar_shifted') {
        await prepareScheduleCalendarProbe();
      } else {
        await prepareScheduleListProbe();
      }
      const delayMs = scheduleProbeDelayMs();
      if (delayMs > 0) {
        await scheduleProbeWait(delayMs);
      }
      collectScheduleCenterProbe(output);
      if (probeCase === 'empty_state') {
        output.pass = scheduleEmptyStateProbePass(output);
      } else if (probeCase === 'list_default') {
        output.pass = scheduleListDefaultProbePass(output);
      } else if (probeCase === 'list_detail') {
        output.pass = scheduleListDetailProbePass(output);
      } else if (probeCase === 'editor_edit') {
        output.pass = scheduleEditorEditProbePass(output);
      } else if (probeCase === 'calendar_shifted') {
        output.pass = scheduleCalendarShiftedProbePass(output);
      } else if (probeCase === 'result_detail') {
        output.pass = scheduleResultDetailProbePass(output);
      } else {
        output.pass = scheduleCalendarMonthProbePass(output);
      }
    } catch (err) {
      output.error = safe(err && err.message ? err.message : err);
    }
    const node = ensureScheduleCenterProbeOutputNode();
    node.textContent = JSON.stringify(output);
    node.setAttribute('data-pass', output.pass ? '1' : '0');
  }

  function bindScheduleCenterEvents() {
    if ($('scheduleViewListBtn')) {
      $('scheduleViewListBtn').onclick = () => {
        setScheduleView('list');
      };
    }
    if ($('scheduleViewCalendarBtn')) {
      $('scheduleViewCalendarBtn').onclick = async () => {
        try {
          setScheduleView('calendar');
          if (!state.scheduleCalendar) {
            await refreshScheduleCalendar(state.scheduleCalendarMonth || '');
          }
        } catch (err) {
          setScheduleError(err.message || String(err));
        }
      };
    }
    if ($('scheduleRefreshBtn')) {
      $('scheduleRefreshBtn').onclick = async () => {
        try {
          await withButtonLock('scheduleRefreshBtn', async () => {
            await refreshScheduleCenterData({
              preserveSelection: true,
              scheduleId: safe(state.scheduleSelectedId).trim(),
            });
            setStatus('定时任务已刷新');
          });
        } catch (err) {
          setScheduleError(err.message || String(err));
        }
      };
    }
    if ($('scheduleScanBtn')) {
      $('scheduleScanBtn').onclick = async () => {
        try {
          await withButtonLock('scheduleScanBtn', scanSchedulesNow);
        } catch (err) {
          setScheduleError(err.message || String(err));
        }
      };
    }
    if ($('scheduleCreateBtn')) {
      $('scheduleCreateBtn').onclick = async () => {
        try {
          await withButtonLock('scheduleCreateBtn', async () => {
            await openScheduleEditorForMode('create');
          });
        } catch (err) {
          setScheduleError(err.message || String(err));
        }
      };
    }
    if ($('schedulePlanList')) {
      $('schedulePlanList').addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const createBtn = target.closest('[data-schedule-create]');
        if (createBtn) {
          openScheduleEditorForMode('create').catch((err) => {
            setScheduleError(err.message || String(err));
          });
          return;
        }
        const button = target.closest('[data-schedule-select]');
        if (!button) return;
        const scheduleId = safe(button.getAttribute('data-schedule-select')).trim();
        if (!scheduleId) return;
        selectSchedulePlan(scheduleId).catch((err) => {
          setScheduleError(err.message || String(err));
        });
      });
    }
    const handleScheduleActionClick = (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const createBtn = target.closest('[data-schedule-create]');
      if (createBtn) {
        openScheduleEditorForMode('create').catch((err) => {
          setScheduleError(err.message || String(err));
        });
        return;
      }
      const openTaskBtn = target.closest('[data-open-task-center]');
      if (openTaskBtn) {
        openScheduleNodeInTaskCenter(
          openTaskBtn.getAttribute('data-ticket-id'),
          openTaskBtn.getAttribute('data-node-id'),
        );
        return;
      }
      const actionBtn = target.closest('[data-schedule-action]');
      if (!actionBtn) return;
      const action = safe(actionBtn.getAttribute('data-schedule-action')).trim().toLowerCase();
      const scheduleId = safe(actionBtn.getAttribute('data-schedule-id')).trim();
      const run = async (work) => {
        try {
          setScheduleError('');
          await scheduleRunWithElementLock(actionBtn, work);
        } catch (err) {
          setScheduleError(err.message || String(err));
        }
      };
      if (action === 'edit') {
        run(() => openScheduleEditorForMode('edit', scheduleId));
        return;
      }
      if (action === 'enable') {
        run(() => setScheduleEnabledAction(scheduleId, true));
        return;
      }
      if (action === 'disable') {
        run(() => setScheduleEnabledAction(scheduleId, false));
        return;
      }
      if (action === 'delete') {
        run(() => deleteScheduleAction(scheduleId));
      }
    };
    if ($('scheduleDetailBody')) {
      $('scheduleDetailBody').addEventListener('click', handleScheduleActionClick);
    }
    if ($('scheduleCalendarDetailBody')) {
      $('scheduleCalendarDetailBody').addEventListener('click', handleScheduleActionClick);
    }
    if ($('scheduleCalendarGrid')) {
      $('scheduleCalendarGrid').addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const dayBtn = target.closest('[data-schedule-day]');
        if (!dayBtn) return;
        const dateText = safe(dayBtn.getAttribute('data-schedule-day')).trim();
        if (!dateText) return;
        setScheduleCalendarSelectedDate(dateText);
      });
    }
    if ($('schedulePrevMonthBtn')) {
      $('schedulePrevMonthBtn').onclick = async () => {
        try {
          await withButtonLock('schedulePrevMonthBtn', async () => {
            await refreshScheduleCalendar(scheduleShiftMonth(state.scheduleCalendarMonth || scheduleCurrentMonthKey(), -1));
          });
        } catch (err) {
          setScheduleError(err.message || String(err));
        }
      };
    }
    if ($('scheduleNextMonthBtn')) {
      $('scheduleNextMonthBtn').onclick = async () => {
        try {
          await withButtonLock('scheduleNextMonthBtn', async () => {
            await refreshScheduleCalendar(scheduleShiftMonth(state.scheduleCalendarMonth || scheduleCurrentMonthKey(), 1));
          });
        } catch (err) {
          setScheduleError(err.message || String(err));
        }
      };
    }
    if ($('scheduleEditorMask')) {
      $('scheduleEditorMask').addEventListener('click', (event) => {
        if (event.target === $('scheduleEditorMask')) {
          closeScheduleEditor();
        }
      });
    }
    ['scheduleEditorCloseBtn', 'scheduleEditorCancelBtn'].forEach((id) => {
      if ($(id)) {
        $(id).onclick = () => {
          closeScheduleEditor();
        };
      }
    });
    if ($('scheduleEditorDeliveryModeSelect')) {
      $('scheduleEditorDeliveryModeSelect').addEventListener('change', () => {
        scheduleApplyEditorDeliveryModeState();
      });
    }
    if ($('scheduleEditorSubmitBtn')) {
      $('scheduleEditorSubmitBtn').onclick = async () => {
        try {
          await withButtonLock('scheduleEditorSubmitBtn', async () => {
            setScheduleEditorError('');
            await submitScheduleEditor();
          });
        } catch (err) {
          setScheduleEditorError(err.message || String(err));
        }
      };
    }
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && state.scheduleEditorOpen) {
        closeScheduleEditor();
      }
    });
  }
