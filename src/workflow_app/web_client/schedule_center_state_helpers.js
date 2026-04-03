  const SCHEDULE_CALENDAR_TIMEZONE = 'Asia/Shanghai';

  function setScheduleError(message) {
    state.scheduleError = safe(message).trim();
    const node = $('scheduleError');
    if (node) node.textContent = state.scheduleError;
  }

  function selectedSchedulePlan() {
    const items = Array.isArray(state.schedulePlans) ? state.schedulePlans : [];
    return items.find((item) => safe(item && item.schedule_id).trim() === safe(state.scheduleSelectedId).trim()) || null;
  }

  function selectedScheduleDetail() {
    const detail = state.scheduleDetail && typeof state.scheduleDetail === 'object' ? state.scheduleDetail : {};
    return detail.schedule && typeof detail.schedule === 'object' ? detail.schedule : selectedSchedulePlan() || {};
  }

  function scheduleResultTone(status) {
    const key = safe(status).trim().toLowerCase();
    if (key === 'running') return 'running';
    if (key === 'succeeded') return 'succeeded';
    if (key === 'failed') return 'failed';
    if (key === 'queued') return 'queued';
    return 'pending';
  }

  function scheduleCurrentMonthKey() {
    const parts = new Intl.DateTimeFormat('zh-CN', {
      timeZone: SCHEDULE_CALENDAR_TIMEZONE,
      year: 'numeric',
      month: '2-digit',
    }).formatToParts(new Date());
    const year = safe((parts.find((item) => item.type === 'year') || {}).value).trim();
    const month = safe((parts.find((item) => item.type === 'month') || {}).value).trim();
    return year && month ? year + '-' + month : '';
  }

  function scheduleShiftMonth(monthKey, offset) {
    const raw = safe(monthKey).trim() || scheduleCurrentMonthKey();
    const parts = raw.split('-');
    let year = Number(parts[0] || 0);
    let month = Number(parts[1] || 0);
    if (!year || !month) return scheduleCurrentMonthKey();
    month += Number(offset || 0);
    while (month <= 0) {
      month += 12;
      year -= 1;
    }
    while (month > 12) {
      month -= 12;
      year += 1;
    }
    return String(year) + '-' + String(month).padStart(2, '0');
  }

  function scheduleFormatBeijingTime(value) {
    return safe(value).trim() ? assignmentFormatBeijingTime(value) : '-';
  }

  function scheduleDayHasEntries(day) {
    const plans = Array.isArray(day && day.plans) ? day.plans : [];
    const results = Array.isArray(day && day.results) ? day.results : [];
    return plans.length > 0 || results.length > 0;
  }

  function scheduleCalendarHasEntries(calendarData) {
    const calendar = calendarData && typeof calendarData === 'object' ? calendarData : {};
    const days = Array.isArray(calendar.days) ? calendar.days : [];
    return days.some((item) => scheduleDayHasEntries(item));
  }

  function scheduleFirstCalendarEntryDate(calendarData) {
    const calendar = calendarData && typeof calendarData === 'object' ? calendarData : {};
    const days = Array.isArray(calendar.days) ? calendar.days : [];
    const matched = days.find((item) => scheduleDayHasEntries(item));
    return safe(matched && matched.date).trim();
  }

  function scheduleSelectedCalendarDay() {
    const calendar = state.scheduleCalendar && typeof state.scheduleCalendar === 'object' ? state.scheduleCalendar : {};
    const days = Array.isArray(calendar.days) ? calendar.days : [];
    const selectedDate = safe(state.scheduleCalendarSelectedDate).trim();
    if (!selectedDate) {
      return null;
    }
    return days.find((item) => safe(item && item.date).trim() === selectedDate) || null;
  }

  function setScheduleView(view) {
    const next = safe(view).trim().toLowerCase() === 'calendar' ? 'calendar' : 'list';
    state.scheduleView = next;
    renderScheduleCenter();
  }

  function setScheduleSelectedId(scheduleId) {
    state.scheduleSelectedId = safe(scheduleId).trim();
    renderScheduleCenter();
  }

  function setScheduleCalendarSelectedDate(dateText) {
    state.scheduleCalendarSelectedDate = safe(dateText).trim();
    renderScheduleCenter();
  }

  async function refreshScheduleDetail(scheduleId) {
    const targetId = safe(scheduleId || state.scheduleSelectedId).trim();
    if (!targetId) {
      state.scheduleDetail = null;
      renderScheduleCenter();
      return null;
    }
    const data = await getJSON('/api/schedules/' + encodeURIComponent(targetId));
    state.scheduleDetail = data;
    state.scheduleSelectedId = safe(data && data.schedule && data.schedule.schedule_id).trim() || targetId;
    setScheduleError('');
    renderScheduleCenter();
    return data;
  }

  async function refreshSchedulePlans(options) {
    if (!state.agentSearchRootReady) {
      state.schedulePlans = [];
      state.scheduleSelectedId = '';
      state.scheduleDetail = null;
      renderScheduleCenter();
      return { items: [] };
    }
    const opts = options || {};
    state.scheduleLoading = true;
    renderScheduleCenter();
    try {
      const data = await getJSON('/api/schedules');
      state.schedulePlans = Array.isArray(data.items) ? data.items : [];
      const previous = safe(state.scheduleSelectedId).trim();
      const exists = state.schedulePlans.some((item) => safe(item && item.schedule_id).trim() === previous);
      if (!previous || !exists || !opts.preserveSelection) {
        state.scheduleSelectedId = state.schedulePlans.length ? safe(state.schedulePlans[0].schedule_id).trim() : '';
      }
      if (!state.scheduleSelectedId) {
        state.scheduleDetail = null;
      }
      setScheduleError('');
      renderScheduleCenter();
      if (state.scheduleSelectedId) {
        await refreshScheduleDetail(state.scheduleSelectedId);
      }
      return data;
    } finally {
      state.scheduleLoading = false;
      renderScheduleCenter();
    }
  }

  async function refreshScheduleCalendar(monthKey) {
    if (!state.agentSearchRootReady) {
      state.scheduleCalendar = null;
      state.scheduleCalendarMonth = '';
      state.scheduleCalendarSelectedDate = '';
      renderScheduleCenter();
      return null;
    }
    const targetMonth = safe(monthKey).trim() || state.scheduleCalendarMonth || scheduleCurrentMonthKey();
    state.scheduleCalendarLoading = true;
    state.scheduleCalendarMonth = targetMonth;
    renderScheduleCenter();
    try {
      const data = await getJSON('/api/schedules/calendar?month=' + encodeURIComponent(targetMonth));
      state.scheduleCalendar = data;
      state.scheduleCalendarMonth = safe(data.month).trim() || targetMonth;
      const selected = safe(state.scheduleCalendarSelectedDate).trim();
      const days = Array.isArray(data.days) ? data.days : [];
      const exists = days.some((item) => safe(item && item.date).trim() === selected);
      const preferredDate = safe(data.selected_date).trim();
      const preferredHasEntries = days.some((item) => safe(item && item.date).trim() === preferredDate && scheduleDayHasEntries(item));
      const firstEntryDate = scheduleFirstCalendarEntryDate(data);
      state.scheduleCalendarSelectedDate = exists
        ? selected
        : (preferredHasEntries ? preferredDate : firstEntryDate);
      setScheduleError('');
      renderScheduleCenter();
      return data;
    } finally {
      state.scheduleCalendarLoading = false;
      renderScheduleCenter();
    }
  }

  function openScheduleEditor(mode, scheduleId) {
    state.scheduleEditorMode = safe(mode).trim().toLowerCase() === 'edit' ? 'edit' : 'create';
    if (state.scheduleEditorMode === 'edit' && scheduleId) {
      state.scheduleSelectedId = safe(scheduleId).trim();
    }
    state.scheduleEditorOpen = true;
    state.scheduleEditorError = '';
    renderScheduleCenter();
  }

  function closeScheduleEditor() {
    state.scheduleEditorOpen = false;
    state.scheduleEditorError = '';
    renderScheduleCenter();
  }

  function setScheduleEditorError(message) {
    state.scheduleEditorError = safe(message).trim();
    const node = $('scheduleEditorError');
    if (node) node.textContent = state.scheduleEditorError;
  }

  function openScheduleNodeInTaskCenter(ticketId, nodeId) {
    const tid = safe(ticketId).trim();
    const nid = safe(nodeId).trim();
    if (!tid || !nid) return;
    state.assignmentSelectedTicketId = tid;
    state.assignmentSelectedNodeId = nid;
    switchTab('task-center');
    refreshAssignmentGraphData({ ticketId: tid })
      .then(() => refreshAssignmentDetail(nid))
      .catch((err) => {
        setAssignmentError(err.message || String(err));
      });
  }
