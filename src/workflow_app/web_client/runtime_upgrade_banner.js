  state.runtimeUpgrade = {
    environment: '',
    current_version: '',
    candidate_version: '',
    request_candidate_version: '',
    request_requested_at: '',
    banner_visible: false,
    can_upgrade: false,
    request_pending: false,
    blocking_reason: '',
    last_action: {},
    upgrade_highlights: [],
    reconnecting: false,
    offline_seen: false,
    status_error: '',
    refresh_busy: false,
    poller: 0,
    poll_active: false,
    success_hold_until: 0,
    success_hold_key: '',
    success_hold_timer: 0,
    progress_tick: 0,
    progress_stage_key: '',
    progress_stage_started_at: 0,
    progress_session_key: '',
    progress_floor_percent: 0,
  };

  const RUNTIME_UPGRADE_POLL_IDLE_MS = 5000;
  const RUNTIME_UPGRADE_POLL_ACTIVE_MS = 1200;
  const RUNTIME_UPGRADE_SUCCESS_HOLD_MS = 3000;
  const RUNTIME_UPGRADE_PROGRESS_CACHE_KEY = 'workflow.runtime_upgrade.progress.v1';
  const RUNTIME_UPGRADE_ACK_CACHE_KEY = 'workflow.runtime_upgrade.ack.v1';

  function updateRuntimeVersionBadge() {
    const node = $('runtimeVersionBadge');
    if (!node) return;
    const info = state.runtimeUpgrade || {};
    const currentVersion = safe(info.current_version).trim();
    const versionText = currentVersion ? ('版本 ' + currentVersion) : '版本读取中';
    node.textContent = versionText;
    node.setAttribute('title', currentVersion ? ('当前版本: ' + currentVersion) : '当前版本读取中');
    node.setAttribute('aria-label', currentVersion ? ('当前版本 ' + currentVersion) : '当前版本读取中');
  }

  function ensureRuntimeUpgradeBanner() {
    let node = $('runtimeUpgradeBanner');
    if (node) return node;
    node = document.createElement('section');
    node.id = 'runtimeUpgradeBanner';
    node.className = 'runtime-upgrade-banner hidden';
    document.body.appendChild(node);
    return node;
  }

  function ensureRuntimeUpgradeBannerRefs() {
    const node = ensureRuntimeUpgradeBanner();
    if (node._runtimeUpgradeRefs) return node._runtimeUpgradeRefs;

    const wrap = document.createElement('div');
    wrap.className = 'runtime-upgrade-shell';

    const head = document.createElement('div');
    head.className = 'runtime-upgrade-head';
    const headMain = document.createElement('div');
    headMain.className = 'runtime-upgrade-head-main';
    const eyebrow = document.createElement('div');
    eyebrow.className = 'runtime-upgrade-eyebrow';
    eyebrow.textContent = '正式环境';
    const title = document.createElement('div');
    title.className = 'runtime-upgrade-title';
    title.textContent = '工作区升级';
    const meta = document.createElement('div');
    meta.className = 'runtime-upgrade-meta';
    headMain.appendChild(eyebrow);
    headMain.appendChild(title);
    headMain.appendChild(meta);
    const statusChip = document.createElement('div');
    statusChip.className = 'runtime-upgrade-status-chip is-idle';
    head.appendChild(headMain);
    head.appendChild(statusChip);

    const versions = document.createElement('div');
    versions.className = 'runtime-upgrade-version-grid';
    const currentCard = document.createElement('div');
    currentCard.className = 'runtime-upgrade-version-card';
    const currentLabel = document.createElement('div');
    currentLabel.className = 'runtime-upgrade-version-label';
    currentLabel.textContent = '当前版本';
    const currentValue = document.createElement('div');
    currentValue.className = 'runtime-upgrade-version-value';
    currentCard.appendChild(currentLabel);
    currentCard.appendChild(currentValue);
    const candidateCard = document.createElement('div');
    candidateCard.className = 'runtime-upgrade-version-card is-candidate';
    const candidateLabel = document.createElement('div');
    candidateLabel.className = 'runtime-upgrade-version-label';
    candidateLabel.textContent = '候选版本';
    const candidateValue = document.createElement('div');
    candidateValue.className = 'runtime-upgrade-version-value';
    candidateCard.appendChild(candidateLabel);
    candidateCard.appendChild(candidateValue);
    versions.appendChild(currentCard);
    versions.appendChild(candidateCard);

    const body = document.createElement('div');
    body.className = 'runtime-upgrade-body';
    const progressSummary = document.createElement('div');
    progressSummary.className = 'runtime-upgrade-progress-summary';
    const progressMeta = document.createElement('div');
    progressMeta.className = 'runtime-upgrade-progress-meta';
    const progressPercent = document.createElement('div');
    progressPercent.className = 'runtime-upgrade-progress-percent';
    progressSummary.appendChild(progressMeta);
    progressSummary.appendChild(progressPercent);
    const progress = document.createElement('div');
    progress.className = 'runtime-upgrade-progress';
    const progressTrack = document.createElement('div');
    progressTrack.className = 'runtime-upgrade-progress-track';
    const progressFill = document.createElement('div');
    progressFill.className = 'runtime-upgrade-progress-fill';
    progressTrack.appendChild(progressFill);
    progress.appendChild(progressTrack);
    const message = document.createElement('div');
    message.className = 'runtime-upgrade-message';
    const footer = document.createElement('div');
    footer.className = 'runtime-upgrade-footer';
    const footerMeta = document.createElement('div');
    footerMeta.className = 'runtime-upgrade-footer-meta';
    const note = document.createElement('div');
    note.className = 'runtime-upgrade-note';
    const error = document.createElement('div');
    error.className = 'runtime-upgrade-note is-bad';
    footerMeta.appendChild(note);
    footerMeta.appendChild(error);
    body.appendChild(progressSummary);
    body.appendChild(progress);
    body.appendChild(message);
    const highlights = document.createElement('div');
    highlights.className = 'runtime-upgrade-highlights';
    const highlightsTitle = document.createElement('div');
    highlightsTitle.className = 'runtime-upgrade-highlights-title';
    const highlightsList = document.createElement('ul');
    highlightsList.className = 'runtime-upgrade-highlights-list';
    highlights.appendChild(highlightsTitle);
    highlights.appendChild(highlightsList);
    body.appendChild(highlights);

    const actions = document.createElement('div');
    actions.className = 'runtime-upgrade-actions';
    const button = document.createElement('button');
    button.id = 'runtimeUpgradeApplyBtn';
    button.type = 'button';
    actions.appendChild(button);
    footer.appendChild(footerMeta);
    footer.appendChild(actions);

    wrap.appendChild(head);
    wrap.appendChild(versions);
    wrap.appendChild(body);
    wrap.appendChild(footer);
    node.appendChild(wrap);

    node._runtimeUpgradeRefs = {
      wrap,
      body,
      meta,
      statusChip,
      versions,
      currentLabel,
      currentValue,
      candidateLabel,
      candidateValue,
      progressMeta,
      progressPercent,
      progressFill,
      message,
      highlights,
      highlightsTitle,
      highlightsList,
      note,
      error,
      button,
    };
    return node._runtimeUpgradeRefs;
  }

  function runtimeUpgradeAckStore() {
    try {
      return window.localStorage || null;
    } catch (_) {
      return null;
    }
  }

  function readRuntimeUpgradeAckKey() {
    const store = runtimeUpgradeAckStore();
    if (!store) return '';
    try {
      return safe(store.getItem(RUNTIME_UPGRADE_ACK_CACHE_KEY)).trim();
    } catch (_) {
      return '';
    }
  }

  function writeRuntimeUpgradeAckKey(key) {
    const store = runtimeUpgradeAckStore();
    if (!store) return;
    const nextKey = safe(key).trim();
    try {
      if (!nextKey) {
        store.removeItem(RUNTIME_UPGRADE_ACK_CACHE_KEY);
        return;
      }
      store.setItem(RUNTIME_UPGRADE_ACK_CACHE_KEY, nextKey);
    } catch (_) {
    }
  }

  function runtimeUpgradeSuccessReviewKey() {
    const info = state.runtimeUpgrade || {};
    const last = runtimeUpgradeLastAction();
    if (runtimeUpgradeLastActionStatus() !== 'success') return '';
    const previousVersion = safe(last.previous_version).trim();
    const currentVersion =
      safe(last.current_version).trim() ||
      safe(info.current_version).trim();
    const finishedAt =
      safe(last.finished_at).trim() ||
      safe(last.started_at).trim() ||
      safe(last.requested_at).trim();
    if (!currentVersion || !finishedAt) return '';
    return ['success', previousVersion, currentVersion, finishedAt].join('|');
  }

  function acknowledgeRuntimeUpgradeSuccess() {
    const ackKey = runtimeUpgradeSuccessReviewKey();
    if (!ackKey) return;
    writeRuntimeUpgradeAckKey(ackKey);
  }

  function runtimeUpgradeShouldShow() {
    const info = state.runtimeUpgrade || {};
    return safe(info.environment).trim() === 'prod' && (
      !!info.banner_visible ||
      !!info.request_pending ||
      !!info.reconnecting ||
      runtimeUpgradeRecentSuccessVisible() ||
      runtimeUpgradeRecentFailureVisible()
    );
  }

  function runtimeUpgradeLastAction() {
    const info = state.runtimeUpgrade || {};
    return info.last_action && typeof info.last_action === 'object' ? info.last_action : {};
  }

  function runtimeUpgradeLastActionStatus() {
    return safe(runtimeUpgradeLastAction().status).trim().toLowerCase();
  }

  function runtimeUpgradeLastActionAt() {
    const last = runtimeUpgradeLastAction();
    return safe(last.finished_at || last.started_at || last.requested_at).trim();
  }

  function runtimeUpgradeRecentTerminalVisible(statuses) {
    const status = runtimeUpgradeLastActionStatus();
    const allow = Array.isArray(statuses) && statuses.length
      ? statuses.map((item) => safe(item).trim().toLowerCase()).filter(Boolean)
      : ['success', 'rollback_success', 'failed'];
    if (!allow.includes(status)) return false;
    const stamp = runtimeUpgradeLastActionAt();
    const ts = stamp ? Date.parse(stamp) : Number.NaN;
    if (!Number.isFinite(ts)) return false;
    return (Date.now() - ts) <= 180000;
  }

  function runtimeUpgradeRecentFailureVisible() {
    return runtimeUpgradeRecentTerminalVisible(['rollback_success', 'failed']);
  }

  function runtimeUpgradeRecentSuccessVisible() {
    const ackKey = runtimeUpgradeSuccessReviewKey();
    if (!ackKey) return false;
    return runtimeUpgradeRecentTerminalVisible(['success']) && readRuntimeUpgradeAckKey() !== ackKey;
  }

  function runtimeUpgradePassiveVisible() {
    const info = state.runtimeUpgrade || {};
    return !!info.can_upgrade &&
      !info.request_pending &&
      !info.reconnecting &&
      !runtimeUpgradeRecentSuccessVisible() &&
      !runtimeUpgradeRecentFailureVisible();
  }

  function runtimeUpgradePollDelayMs() {
    const info = state.runtimeUpgrade || {};
    if (info.reconnecting || info.request_pending || runtimeUpgradeLastActionStatus() === 'switching') {
      return RUNTIME_UPGRADE_POLL_ACTIVE_MS;
    }
    return RUNTIME_UPGRADE_POLL_IDLE_MS;
  }

  function clearRuntimeUpgradeSuccessHoldTimer() {
    if (state.runtimeUpgrade.success_hold_timer) {
      window.clearTimeout(state.runtimeUpgrade.success_hold_timer);
      state.runtimeUpgrade.success_hold_timer = 0;
    }
  }

  function scheduleRuntimeUpgradeSuccessHoldTimer() {
    clearRuntimeUpgradeSuccessHoldTimer();
  }

  function syncRuntimeUpgradeSuccessHold() {
    const info = state.runtimeUpgrade || {};
    const status = runtimeUpgradeLastActionStatus();
    if (status !== 'success') {
      info.success_hold_until = 0;
      info.success_hold_key = '';
      clearRuntimeUpgradeSuccessHoldTimer();
      return;
    }
    info.success_hold_key = runtimeUpgradeSuccessReviewKey();
    info.success_hold_until = 0;
    scheduleRuntimeUpgradeSuccessHoldTimer();
  }

  function runtimeUpgradeProgressStore() {
    try {
      return window.sessionStorage || null;
    } catch (_) {
      return null;
    }
  }

  function readRuntimeUpgradeProgressSnapshot() {
    const store = runtimeUpgradeProgressStore();
    if (!store) return {};
    try {
      const raw = safe(store.getItem(RUNTIME_UPGRADE_PROGRESS_CACHE_KEY)).trim();
      if (!raw) return {};
      const data = JSON.parse(raw);
      return data && typeof data === 'object' ? data : {};
    } catch (_) {
      return {};
    }
  }

  function clearRuntimeUpgradeProgressSnapshot() {
    const store = runtimeUpgradeProgressStore();
    if (!store) return;
    try {
      store.removeItem(RUNTIME_UPGRADE_PROGRESS_CACHE_KEY);
    } catch (_) {
    }
  }

  function writeRuntimeUpgradeProgressSnapshot(sessionKey, percent) {
    const store = runtimeUpgradeProgressStore();
    if (!store) return;
    const nextSessionKey = safe(sessionKey).trim();
    const nextPercent = Math.max(0, Math.min(100, Number(percent) || 0));
    try {
      if (!nextSessionKey || !(nextPercent > 0)) {
        store.removeItem(RUNTIME_UPGRADE_PROGRESS_CACHE_KEY);
        return;
      }
      store.setItem(
        RUNTIME_UPGRADE_PROGRESS_CACHE_KEY,
        JSON.stringify({
          session_key: nextSessionKey,
          percent: nextPercent,
          updated_at: new Date().toISOString(),
        })
      );
    } catch (_) {
    }
  }

  function runtimeUpgradeProgressSessionKey() {
    const info = state.runtimeUpgrade || {};
    const last = runtimeUpgradeLastAction();
    const status = runtimeUpgradeLastActionStatus();
    const isActive =
      !!info.reconnecting ||
      !!info.request_pending ||
      status === 'switching' ||
      runtimeUpgradeRecentFailureVisible() ||
      runtimeUpgradeRecentSuccessVisible();
    if (!isActive) return '';
    const candidateVersion =
      safe(info.request_candidate_version).trim() ||
      safe(info.candidate_version).trim() ||
      safe(last.candidate_version).trim();
    const requestStamp =
      safe(info.request_requested_at).trim() ||
      safe(last.requested_at).trim() ||
      safe(last.started_at).trim() ||
      safe(last.finished_at).trim();
    if (!candidateVersion && !requestStamp) return '';
    return [
      safe(info.environment).trim() || 'prod',
      candidateVersion,
      requestStamp,
    ].join('|');
  }

  function syncRuntimeUpgradeProgressPercent(sessionKey, percent) {
    const info = state.runtimeUpgrade || {};
    const nextSessionKey = safe(sessionKey).trim();
    const rawPercent = Math.max(0, Math.min(100, Number(percent) || 0));
    if (!nextSessionKey) {
      info.progress_session_key = '';
      info.progress_floor_percent = 0;
      clearRuntimeUpgradeProgressSnapshot();
      return rawPercent;
    }

    const currentSessionKey = safe(info.progress_session_key).trim();
    if (currentSessionKey !== nextSessionKey) {
      const cached = readRuntimeUpgradeProgressSnapshot();
      const cachedSessionKey = safe(cached.session_key).trim();
      info.progress_session_key = nextSessionKey;
      info.progress_floor_percent =
        cachedSessionKey === nextSessionKey
          ? Math.max(0, Math.min(100, Number(cached.percent) || 0))
          : 0;
    }

    const nextPercent = Math.max(
      rawPercent,
      Math.max(0, Math.min(100, Number(info.progress_floor_percent) || 0))
    );
    info.progress_floor_percent = nextPercent;
    writeRuntimeUpgradeProgressSnapshot(nextSessionKey, nextPercent);
    return nextPercent;
  }

  function runtimeUpgradeProgressModel() {
    const info = state.runtimeUpgrade || {};
    const lastStatus = runtimeUpgradeLastActionStatus();
    const stageStamp = safe(runtimeUpgradeLastActionAt()).trim();
    const versionKey = [safe(info.current_version).trim(), safe(info.candidate_version).trim()].join('|');
    const progressSessionKey = runtimeUpgradeProgressSessionKey();
    let stage = null;
    if (info.reconnecting && info.offline_seen) {
      stage = {
        key: ['reconnecting-offline', stageStamp, versionKey].join('|'),
        label: '正在切换版本',
        tone: 'running',
        minPercent: 58,
        maxPercent: 90,
        durationMs: 12000,
      };
    } else if (info.request_pending) {
      stage = {
        key: ['request_pending', stageStamp, versionKey].join('|'),
        label: '升级请求已受理',
        tone: 'running',
        minPercent: 2,
        maxPercent: 10,
        durationMs: 2200,
      };
    } else if (lastStatus === 'switching') {
      stage = {
        key: ['switching', stageStamp, versionKey].join('|'),
        label: '正在切换候选版本',
        tone: 'running',
        minPercent: 10,
        maxPercent: 28,
        durationMs: 3600,
      };
    } else if (info.reconnecting) {
      stage = {
        key: ['reconnecting', stageStamp, versionKey].join('|'),
        label: '等待正式环境重连',
        tone: 'running',
        minPercent: 28,
        maxPercent: 58,
        durationMs: 5000,
      };
    }
    if (stage) {
      if (safe(info.progress_stage_key).trim() !== stage.key) {
        info.progress_stage_key = stage.key;
        info.progress_stage_started_at = Date.now();
      } else if (!(Number(info.progress_stage_started_at || 0) > 0)) {
        info.progress_stage_started_at = Date.now();
      }
      const elapsed = Math.max(0, Date.now() - Number(info.progress_stage_started_at || Date.now()));
      const progressT = Math.max(0, Math.min(1, elapsed / Math.max(1, Number(stage.durationMs) || 1)));
      const easedT = 1 - Math.pow(1 - progressT, 2.2);
      const percent = syncRuntimeUpgradeProgressPercent(
        progressSessionKey,
        stage.minPercent + ((stage.maxPercent - stage.minPercent) * easedT)
      );
      return {
        percent,
        displayPercent: Math.round(percent),
        label: stage.label,
        tone: stage.tone,
        autoAdvance: true,
      };
    }
    info.progress_stage_key = '';
    info.progress_stage_started_at = 0;
    if (lastStatus === 'success' && runtimeUpgradeRecentSuccessVisible()) {
      const percent = syncRuntimeUpgradeProgressPercent(progressSessionKey, 100);
      return { percent, displayPercent: Math.round(percent), label: '升级完成', tone: 'done', autoAdvance: false };
    }
    if (runtimeUpgradeRecentFailureVisible()) {
      if (lastStatus === 'rollback_success') {
        const percent = syncRuntimeUpgradeProgressPercent(progressSessionKey, 100);
        return { percent, displayPercent: Math.round(percent), label: '已自动回滚', tone: 'bad', autoAdvance: false };
      }
      if (lastStatus === 'failed') {
        const percent = syncRuntimeUpgradeProgressPercent(progressSessionKey, 100);
        return { percent, displayPercent: Math.round(percent), label: '升级失败', tone: 'bad', autoAdvance: false };
      }
    }
    syncRuntimeUpgradeProgressPercent('', 0);
    if (info.can_upgrade) {
      return { percent: 0, displayPercent: 0, label: '可开始升级', tone: 'idle', autoAdvance: false };
    }
    return { percent: 0, displayPercent: 0, label: '当前不可升级', tone: 'idle', autoAdvance: false };
  }

  function runtimeUpgradeStatusText() {
    const info = state.runtimeUpgrade || {};
    const lastStatus = runtimeUpgradeLastActionStatus();
    if (info.reconnecting && info.offline_seen) {
      return '旧实例已下线，正在等待新实例恢复。';
    }
    if (info.request_pending) {
      return safe(info.blocking_reason).trim() || '升级请求已提交，正在准备切换正式环境。';
    }
    if (info.reconnecting) {
      return '正式环境正在切换，页面会短暂刷新并自动重连。';
    }
    if (lastStatus === 'success' && runtimeUpgradeRecentSuccessVisible()) {
      return '正式环境已切到新版本，请确认本次新特性。';
    }
    if (runtimeUpgradeRecentFailureVisible()) {
      if (lastStatus === 'rollback_success') {
        return runtimeUpgradeFailureReasonText() || '新版本健康检查失败，系统已自动回滚到上一版本。';
      }
      if (lastStatus === 'failed') {
        return runtimeUpgradeFailureReasonText() || '正式环境升级失败。';
      }
    }
    if (safe(info.blocking_reason).trim()) {
      return safe(info.blocking_reason).trim();
    }
    return '当前无运行中任务，可升级到已通过 test 门禁的新版本。';
  }

  function runtimeUpgradeFailureReasonText() {
    const last = runtimeUpgradeLastAction();
    const reason = safe(last.reason).trim().toLowerCase();
    const timeoutSeconds = Math.max(0, Number(last.health_timeout_seconds || 0) || 0);
    if (!reason) return '';
    if (reason === 'health_timeout') {
      return timeoutSeconds > 0
        ? ('新版本在 ' + timeoutSeconds + ' 秒内未完成健康启动，系统已自动回滚到上一版本。')
        : '新版本在健康检查窗口内未启动成功，系统已自动回滚到上一版本。';
    }
    if (reason === 'launcher_exited') {
      return '新版本启动进程异常退出，系统已自动回滚到上一版本。';
    }
    return safe(last.reason).trim();
  }

  function runtimeUpgradeMetaText(progressInfo) {
    const info = state.runtimeUpgrade || {};
    const tone = safe(progressInfo && progressInfo.tone).trim();
    if (info.reconnecting || info.request_pending || tone === 'running') {
      return '切换期间页面会自动重连，请勿重复操作。';
    }
    if (runtimeUpgradeRecentSuccessVisible()) {
      return '升级已完成，请确认本次新特性后关闭提示。';
    }
    if (runtimeUpgradeRecentFailureVisible()) {
      return '保留最近一次切换结果，便于判断是否需要再次升级。';
    }
    if (info.can_upgrade) {
      return '有新版本可以升级，可在空闲时切换。';
    }
    return '仅在有新版本时展示升级提示。';
  }

  function runtimeUpgradeStatusChip(progressInfo) {
    const info = state.runtimeUpgrade || {};
    const lastStatus = runtimeUpgradeLastActionStatus();
    if (info.reconnecting || info.request_pending || (progressInfo && safe(progressInfo.tone).trim() === 'running')) {
      return { tone: 'running', text: '切换中' };
    }
    if (runtimeUpgradeRecentSuccessVisible()) {
      return { tone: 'done', text: '待确认' };
    }
    if (runtimeUpgradeRecentFailureVisible() && lastStatus === 'rollback_success') {
      return { tone: 'bad', text: '已回滚' };
    }
    if (runtimeUpgradeRecentFailureVisible() && lastStatus === 'failed') {
      return { tone: 'bad', text: '失败' };
    }
    if (info.can_upgrade) {
      return { tone: 'ready', text: '可升级' };
    }
    return { tone: 'idle', text: '待命' };
  }

  function runtimeUpgradeLastActionText() {
    const last = runtimeUpgradeLastAction();
    const status = safe(last.status).trim();
    if (!status) return '';
    const map = {
      requested: '升级请求已记录',
      success: '最近一次升级成功',
      switching: '正在切换正式版本',
      rollback_success: '最近一次升级失败，已自动回退',
      failed: '最近一次升级失败',
    };
    const head = map[status] || ('最近状态：' + status);
    const finishedAt = safe(last.finished_at || last.started_at).trim();
    return finishedAt ? head + ' · ' + formatDateTime(finishedAt) : head;
  }

  function runtimeUpgradeSuccessReviewActive() {
    return runtimeUpgradeLastActionStatus() === 'success' && runtimeUpgradeRecentSuccessVisible();
  }

  function runtimeUpgradeDisplayVersions() {
    const info = state.runtimeUpgrade || {};
    const last = runtimeUpgradeLastAction();
    if (runtimeUpgradeSuccessReviewActive()) {
      const previousVersion = safe(last.previous_version).trim() || '切换前版本未记录';
      const currentVersion =
        safe(last.current_version).trim() ||
        safe(info.current_version).trim() ||
        '切换后版本未记录';
      return {
        leftLabel: '上一版本',
        leftValue: previousVersion,
        rightLabel: '当前版本',
        rightValue: currentVersion,
      };
    }
    return {
      leftLabel: '当前版本',
      leftValue: safe(info.current_version).trim() || '未读取',
      rightLabel: '候选版本',
      rightValue:
        safe(info.request_candidate_version).trim() ||
        safe(info.candidate_version).trim() ||
        '暂无候选',
    };
  }

  function renderRuntimeUpgradeHighlights(refs, info) {
    const rows = Array.isArray(info.upgrade_highlights)
      ? info.upgrade_highlights.map((item) => safe(item).trim()).filter(Boolean)
      : [];
    if (!runtimeUpgradeSuccessReviewActive()) {
      refs.highlights.style.display = 'none';
      refs.highlightsTitle.textContent = '';
      refs.highlightsList.innerHTML = '';
      return;
    }
    refs.highlights.style.display = 'grid';
    refs.highlightsTitle.textContent = '本次修复与变化';
    refs.highlightsList.innerHTML = '';
    const items = rows.length ? rows : ['正式环境已完成版本切换，本次包含若干界面与交互修复。'];
    items.slice(0, 4).forEach((item) => {
      const node = document.createElement('li');
      node.textContent = item;
      refs.highlightsList.appendChild(node);
    });
  }

  function clearRuntimeUpgradeProgressTick() {
    if (state.runtimeUpgrade.progress_tick) {
      window.clearTimeout(state.runtimeUpgrade.progress_tick);
      state.runtimeUpgrade.progress_tick = 0;
    }
  }

  function scheduleRuntimeUpgradeProgressTick(progressInfo) {
    clearRuntimeUpgradeProgressTick();
    if (!runtimeUpgradeShouldShow()) return;
    if (!progressInfo || !progressInfo.autoAdvance) return;
    state.runtimeUpgrade.progress_tick = window.setTimeout(() => {
      state.runtimeUpgrade.progress_tick = 0;
      renderRuntimeUpgradeBanner();
    }, 140);
  }

  function renderRuntimeUpgradeBanner() {
    const node = ensureRuntimeUpgradeBanner();
    const refs = ensureRuntimeUpgradeBannerRefs();
    const info = state.runtimeUpgrade || {};
    if (!runtimeUpgradeShouldShow()) {
      node.classList.add('hidden');
      clearRuntimeUpgradeProgressTick();
      return;
    }
    node.classList.remove('hidden');
    const progressInfo = runtimeUpgradeProgressModel();
    const successReviewActive = runtimeUpgradeSuccessReviewActive();
    const passiveMode = runtimeUpgradePassiveVisible();
    const versionInfo = runtimeUpgradeDisplayVersions();
    node.classList.toggle('is-passive', passiveMode);
    refs.wrap.classList.toggle('is-passive', passiveMode);
    refs.currentLabel.textContent = safe(versionInfo.leftLabel).trim() || '当前版本';
    refs.currentValue.textContent = safe(versionInfo.leftValue).trim() || '未读取';
    refs.candidateLabel.textContent = safe(versionInfo.rightLabel).trim() || '候选版本';
    refs.candidateValue.textContent = safe(versionInfo.rightValue).trim() || '暂无候选';
    refs.versions.style.display = 'grid';
    refs.versions.setAttribute('aria-hidden', 'false');
    refs.body.style.display = passiveMode ? 'none' : 'grid';
    refs.body.setAttribute('aria-hidden', passiveMode ? 'true' : 'false');
    refs.meta.textContent = runtimeUpgradeMetaText(progressInfo);
    const chip = runtimeUpgradeStatusChip(progressInfo);
    refs.statusChip.className = 'runtime-upgrade-status-chip is-' + safe(chip.tone).trim();
    refs.statusChip.textContent = chip.text;
    refs.progressMeta.textContent = progressInfo.label;
    refs.progressPercent.textContent =
      String(Math.max(0, Math.min(100, Number(progressInfo.displayPercent) || 0))) + '%';
    refs.progressFill.className = 'runtime-upgrade-progress-fill is-' + safe(progressInfo.tone).trim();
    refs.progressFill.style.width = String(Math.max(0, Math.min(100, Number(progressInfo.percent) || 0))) + '%';
    refs.message.className = 'runtime-upgrade-message is-' + safe(progressInfo.tone).trim();
    refs.message.textContent = runtimeUpgradeStatusText();
    renderRuntimeUpgradeHighlights(refs, info);

    const lastActionText = runtimeUpgradeLastActionText();
    if (lastActionText) {
      refs.note.textContent = lastActionText;
      refs.note.style.display = '';
    } else {
      refs.note.textContent = '';
      refs.note.style.display = 'none';
    }
    if (safe(info.status_error).trim()) {
      refs.error.textContent = '升级状态读取失败：' + safe(info.status_error).trim();
      refs.error.style.display = '';
    } else {
      refs.error.textContent = '';
      refs.error.style.display = 'none';
    }

    const button = refs.button;
    if (successReviewActive) {
      button.textContent = '我知道了';
      button.disabled = false;
      button.classList.remove('is-placeholder');
      button.removeAttribute('aria-hidden');
      button.tabIndex = 0;
      button.onclick = () => {
        acknowledgeRuntimeUpgradeSuccess();
        renderRuntimeUpgradeBanner();
      };
    } else if (info.reconnecting || info.request_pending || info.can_upgrade) {
      button.textContent = info.reconnecting || info.request_pending ? '切换中' : '升级正式环境';
      button.disabled = !!info.reconnecting || !!info.request_pending || !info.can_upgrade;
      button.classList.remove('is-placeholder');
      button.removeAttribute('aria-hidden');
      button.tabIndex = 0;
      button.onclick = () => {
        applyRuntimeUpgrade().catch((err) => {
          state.runtimeUpgrade.status_error = safe(err && err.message ? err.message : err);
          renderRuntimeUpgradeBanner();
        });
      };
    } else {
      button.textContent = '升级正式环境';
      button.disabled = true;
      button.classList.add('is-placeholder');
      button.tabIndex = -1;
      button.setAttribute('aria-hidden', 'true');
      button.onclick = null;
    }
    scheduleRuntimeUpgradeProgressTick(progressInfo);
  }

  function applyRuntimeUpgradeStatus(payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const prev = state.runtimeUpgrade || {};
    const nextLastAction = data.last_action && typeof data.last_action === 'object' ? data.last_action : {};
    const nextLastStatus = safe(nextLastAction.status).trim().toLowerCase();
    const nextRequestPending = !!data.request_pending;
    const nextRequestCandidateVersion = safe(
      data.request_candidate_version || data.candidate_version || prev.request_candidate_version
    ).trim();
    const nextRequestRequestedAt = safe(
      data.request_requested_at || (nextLastAction && nextLastAction.requested_at) || prev.request_requested_at
    ).trim();
    const nextCurrentVersion = safe(data.current_version).trim();
    const isTerminalStatus = nextLastStatus === 'success' || nextLastStatus === 'rollback_success' || nextLastStatus === 'failed';
    const switchingStatus = nextLastStatus === 'requested' || nextLastStatus === 'switching';
    const hasSwitchIdentity = !!nextRequestCandidateVersion || !!nextRequestRequestedAt;
    const switchApplied = !!nextRequestCandidateVersion && !!nextCurrentVersion && nextCurrentVersion === nextRequestCandidateVersion;
    const reconnecting = !isTerminalStatus && !switchApplied && (nextRequestPending || (switchingStatus && hasSwitchIdentity));
    state.runtimeUpgrade = Object.assign({}, prev, {
      environment: safe(data.environment).trim(),
      current_version: nextCurrentVersion,
      candidate_version: safe(data.candidate_version).trim(),
      request_candidate_version: nextRequestCandidateVersion,
      request_requested_at: nextRequestRequestedAt,
      banner_visible: !!data.banner_visible,
      can_upgrade: !!data.can_upgrade,
      request_pending: nextRequestPending,
      blocking_reason: safe(data.blocking_reason).trim(),
      last_action: nextLastAction,
      upgrade_highlights: Array.isArray(data.upgrade_highlights) ? data.upgrade_highlights.slice(0, 8) : [],
      reconnecting: reconnecting,
      offline_seen: reconnecting ? !!prev.offline_seen : false,
      status_error: '',
    });
    syncRuntimeUpgradeSuccessHold();
    updateRuntimeVersionBadge();
    renderRuntimeUpgradeBanner();
    rescheduleRuntimeUpgradePoller();
    return state.runtimeUpgrade;
  }

  async function refreshRuntimeUpgradeStatus(options) {
    const opts = options || {};
    if (state.runtimeUpgrade.refresh_busy) return state.runtimeUpgrade;
    state.runtimeUpgrade.refresh_busy = true;
    try {
      const data = await getJSON('/api/runtime-upgrade/status');
      return applyRuntimeUpgradeStatus(data);
    } catch (err) {
      if (!opts.silent) {
        state.runtimeUpgrade.status_error = safe(err && err.message ? err.message : err);
        updateRuntimeVersionBadge();
        renderRuntimeUpgradeBanner();
      }
      return state.runtimeUpgrade;
    } finally {
      state.runtimeUpgrade.refresh_busy = false;
    }
  }

  function stopRuntimeUpgradePoller() {
    if (state.runtimeUpgrade.poller) {
      window.clearTimeout(state.runtimeUpgrade.poller);
      state.runtimeUpgrade.poller = 0;
    }
    state.runtimeUpgrade.poll_active = false;
  }

  function scheduleRuntimeUpgradePoller(delayMs) {
    if (!state.runtimeUpgrade.poll_active) return;
    if (state.runtimeUpgrade.poller) {
      window.clearTimeout(state.runtimeUpgrade.poller);
      state.runtimeUpgrade.poller = 0;
    }
    const nextDelay = Math.max(300, Number(delayMs) || runtimeUpgradePollDelayMs());
    state.runtimeUpgrade.poller = window.setTimeout(async () => {
      state.runtimeUpgrade.poller = 0;
      try {
        await refreshRuntimeUpgradeStatus({ silent: true });
      } catch (_) {
      }
      scheduleRuntimeUpgradePoller(runtimeUpgradePollDelayMs());
    }, nextDelay);
  }

  function rescheduleRuntimeUpgradePoller() {
    if (!state.runtimeUpgrade.poll_active) return;
    scheduleRuntimeUpgradePoller(runtimeUpgradePollDelayMs());
  }

  function startRuntimeUpgradePoller() {
    stopRuntimeUpgradePoller();
    state.runtimeUpgrade.poll_active = true;
    refreshRuntimeUpgradeStatus({ silent: true })
      .catch(() => {})
      .finally(() => {
        scheduleRuntimeUpgradePoller(runtimeUpgradePollDelayMs());
      });
  }

  async function fetchRuntimeUpgradeStatusSnapshot() {
    try {
      const response = await fetch('/api/runtime-upgrade/status', { cache: 'no-store' });
      if (!response.ok) return null;
      const data = await response.json();
      return data && typeof data === 'object' ? data : null;
    } catch (_) {
      return null;
    }
  }

  function runtimeUpgradeSwitchApplied(statusPayload) {
    const payload = statusPayload && typeof statusPayload === 'object' ? statusPayload : null;
    if (!payload) return false;
    if (!!payload.request_pending) return false;
    const requestedVersion =
      safe(state.runtimeUpgrade.request_candidate_version).trim() ||
      safe(state.runtimeUpgrade.candidate_version).trim();
    const currentVersion = safe(payload.current_version).trim();
    const lastAction = payload.last_action && typeof payload.last_action === 'object'
      ? payload.last_action
      : {};
    const lastStatus = safe(lastAction.status).trim().toLowerCase();
    const lastCurrentVersion =
      safe(lastAction.current_version).trim() ||
      safe(lastAction.candidate_version).trim() ||
      currentVersion;
    if (requestedVersion && currentVersion && currentVersion === requestedVersion) {
      return true;
    }
    return lastStatus === 'success' && (!requestedVersion || lastCurrentVersion === requestedVersion);
  }

  async function waitForRuntimeUpgradeReconnect() {
    const deadline = Date.now() + 60000;
    let seenOffline = false;
    while (Date.now() < deadline) {
      let ok = false;
      try {
        const response = await fetch('/healthz', { cache: 'no-store' });
        ok = !!response.ok;
      } catch (_) {
        ok = false;
      }
      if (!ok) {
        if (!seenOffline) {
          seenOffline = true;
          state.runtimeUpgrade.offline_seen = true;
          renderRuntimeUpgradeBanner();
          rescheduleRuntimeUpgradePoller();
        }
      } else {
        const statusPayload = await fetchRuntimeUpgradeStatusSnapshot();
        if (runtimeUpgradeSwitchApplied(statusPayload)) {
          state.runtimeUpgrade.offline_seen = false;
          window.location.reload();
          return;
        }
        if (seenOffline) {
          state.runtimeUpgrade.offline_seen = false;
          window.location.reload();
          return;
        }
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
    }
    window.location.reload();
  }

  async function applyRuntimeUpgrade() {
    const info = state.runtimeUpgrade || {};
    if (!info.can_upgrade || info.request_pending || info.reconnecting) {
      renderRuntimeUpgradeBanner();
      return;
    }
    state.runtimeUpgrade.status_error = '';
    state.runtimeUpgrade.progress_stage_key = '';
    state.runtimeUpgrade.progress_stage_started_at = 0;
    state.runtimeUpgrade.progress_session_key = '';
    state.runtimeUpgrade.progress_floor_percent = 0;
    clearRuntimeUpgradeProgressSnapshot();
    const button = $('runtimeUpgradeApplyBtn');
    if (button) button.disabled = true;
    const data = await postJSON('/api/runtime-upgrade/apply', { operator: 'web-user' });
    applyRuntimeUpgradeStatus(
      Object.assign({}, info, {
        request_pending: true,
        request_candidate_version: safe(data.candidate_version || info.candidate_version).trim(),
        request_requested_at: safe(data.requested_at).trim(),
        blocking_reason: safe(data.reconnect_hint || data.message).trim(),
        last_action: {
          status: 'requested',
          requested_at: safe(data.requested_at).trim() || new Date().toISOString(),
        },
      })
    );
    state.runtimeUpgrade.offline_seen = false;
    state.runtimeUpgrade.reconnecting = true;
    renderRuntimeUpgradeBanner();
    rescheduleRuntimeUpgradePoller();
    setStatus('正式环境开始升级，页面将自动重连');
    waitForRuntimeUpgradeReconnect().catch(() => {
      window.location.reload();
    });
  }
