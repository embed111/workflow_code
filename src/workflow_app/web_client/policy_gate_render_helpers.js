  function renderAgentDropdownTrigger(items) {
    const rows = Array.isArray(items) ? items : [];
    const trigger = $('agentSelectTrigger');
    const textNode = $('agentSelectTriggerText');
    const subNode = $('agentSelectTriggerSub');
    const badge = $('agentSelectTriggerState');
    if (!trigger || !textNode || !subNode || !badge) return;

    const selected = selectedAgent();
    const selectedItem =
      rows.find((item) => safe(item && item.agent_name).trim() === selected) || selectedAgentItem();
    const info = selectedItem
      ? agentStatusInfo(selectedItem)
      : selected
        ? agentStatusInfoByRecord(getAgentPolicyAnalysisRecord(selected))
        : {
            text: rows.length ? '未分析' : '无可用 agent',
            icon: rows.length ? 'pending' : 'failed',
            spinning: false,
            chipClass: rows.length ? 'pending' : 'blocked',
          };

    textNode.textContent = selected || '请选择agent';
    subNode.textContent = selected ? '状态：' + safe(info.text) : rows.length ? '' : '无可用 agent';
    badge.className = 'analysis-badge ' + safe(info.chipClass || 'pending');
    badge.textContent = '';
    appendIconLabel(badge, safe(info.text), safe(info.icon), {
      spinning: !!info.spinning,
      labelClassName: 'analysis-chip-label',
    });
  }

  function renderAgentStatusList(items) {
    const host = $('agentSelectOptions') || $('agentSelectPanel');
    if (!host) return;
    host.innerHTML = '';
    const rows = Array.isArray(items) ? items : [];
    const analyzing = safe(state.sessionPolicyGateState) === 'analyzing_policy';
    const rawQuery = safe($('agentSelectSearch') && $('agentSelectSearch').value).trim().toLowerCase();
    const filteredRows = rawQuery
      ? rows.filter((item) => {
          const name = safe(item && item.agent_name).trim().toLowerCase();
          const info = agentStatusInfo(item);
          const statusText = safe(info && info.text).trim().toLowerCase();
          return name.includes(rawQuery) || statusText.includes(rawQuery);
        })
      : rows;
    renderAgentDropdownTrigger(rows);
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'agent-dropdown-empty';
      empty.textContent = '暂无可选 agent';
      host.appendChild(empty);
      setAgentDropdownOpen(false);
      return;
    }
    if (!filteredRows.length) {
      const empty = document.createElement('div');
      empty.className = 'agent-dropdown-empty';
      empty.textContent = '未匹配到 agent';
      host.appendChild(empty);
      return;
    }
    const selected = selectedAgent();
    for (const item of filteredRows) {
      const name = safe(item && item.agent_name).trim();
      if (!name) continue;
      const info = agentStatusInfo(item);
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'agent-dropdown-option' + (selected === name ? ' active' : '');
      row.disabled = analyzing;
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', selected === name ? 'true' : 'false');

      const left = document.createElement('span');
      left.className = 'agent-dropdown-option-main';
      const title = document.createElement('span');
      title.className = 'agent-dropdown-option-name';
      title.textContent = name;
      left.appendChild(title);
      row.appendChild(left);

      const right = document.createElement('span');
      right.className = 'analysis-badge agent-dropdown-option-status ' + safe(info.chipClass || 'pending');
      appendIconLabel(right, safe(info.text), safe(info.icon), {
        spinning: !!info.spinning,
        labelClassName: 'analysis-chip-label',
      });
      row.appendChild(right);

      row.onclick = () => {
        if (safe(state.sessionPolicyGateState) === 'analyzing_policy') return;
        setAgentDropdownOpen(false);
        $('agentSelect').value = name;
        localStorage.setItem(agentCacheKey, name);
        renderAgentSelectOptions(true);
        startPolicyAnalysisForSelection();
      };
      host.appendChild(row);
    }
    if (analyzing) {
      setAgentDropdownOpen(false);
      return;
    }
    if (state.agentDropdownOpen) {
      positionAgentDropdownPanel();
    }
  }

  function cacheReasonText(raw) {
    const map = {
      cache_hit: '命中缓存（hash+mtime 一致）',
      cache_miss: '缓存缺失，已重算',
      cache_not_found: '缓存缺失，已重算',
      cache_disabled: '缓存未启用',
      agents_hash_mismatch: 'hash 不一致',
      cached_before_agents_mtime: '缓存时间早于 AGENTS.md 修改时间',
      cached_at_missing: '缓存时间缺失',
      agents_mtime_missing: 'AGENTS.md 时间戳缺失',
      cache_payload_invalid_json: '缓存内容损坏',
      cache_payload_incomplete: '缓存字段不完整',
      cache_parse_status_missing: '缓存缺少 parse_status',
      cache_clarity_score_invalid: '缓存缺少 clarity_score',
      cache_prompt_version_mismatch: '提示词版本不匹配',
      cache_extract_source_mismatch: '提取链路来源不匹配',
      manual_clear: '已手动清理缓存',
      cache_write_failed: '缓存写入失败（已使用实时重算结果）',
    };
    const text = safe(raw).trim();
    if (!text) return '';
    return text
      .split(',')
      .map((part) => safe(part).trim())
      .filter((part) => !!part)
      .map((part) => map[part] || part)
      .join('；');
  }

  function cacheStepText(value) {
    const key = safe(value).trim().toLowerCase();
    const map = {
      lookup: '读取缓存',
      validate: '校验缓存',
      reuse: '复用缓存',
      recompute: '重算策略',
      write: '写回缓存',
    };
    return map[key] || key || '步骤';
  }

  function cacheStepStatusText(value) {
    const key = safe(value).trim().toLowerCase();
    const map = {
      disabled: '未启用',
      miss: '未命中',
      found: '已找到',
      valid: '通过',
      invalid: '失效',
      hit: '命中',
      start: '开始',
      done: '完成',
      success: '成功',
      failed: '失败',
      skipped: '跳过',
    };
    return map[key] || key || '-';
  }

  function normalizeCacheTrace(raw) {
    if (!Array.isArray(raw)) return [];
    return raw
      .map((item) => {
        const node = item && typeof item === 'object' ? item : {};
        return {
          step: safe(node.step).trim().toLowerCase(),
          status: safe(node.status).trim().toLowerCase(),
          detail: safe(node.detail).trim(),
        };
      })
      .filter((item) => !!item.step);
  }

  function cacheFlowPreview(traceItems) {
    const items = Array.isArray(traceItems) ? traceItems : [];
    if (!items.length) return '';
    return items
      .map((step) => cacheStepText(step.step) + '（' + cacheStepStatusText(step.status) + '）')
      .join(' -> ');
  }

  function gateTextByState(value) {
    const key = safe(value).trim();
    const map = {
      idle_unselected: '未选择 agent',
      analyzing_policy: '正在分析角色与职责',
      policy_cache_missing: '角色缓存待手动生成',
      policy_ready: '角色与职责就绪',
      policy_needs_confirm: '角色与职责待确认',
      policy_failed: '角色与职责阻断',
      policy_confirmed: '角色与职责已确认',
    };
    return map[key] || key;
  }

  function formatDurationMs(ms) {
    if (ms === null || ms === undefined || ms === '') return '-';
    const value = Number(ms);
    if (!Number.isFinite(value) || value < 0) return '-';
    if (value < 1000) return Math.floor(value) + 'ms';
    return (value / 1000).toFixed(2) + 's';
  }

  function parseDurationMsMaybe(rawValue) {
    if (rawValue === null || rawValue === undefined || rawValue === '') return null;
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value < 0) return null;
    return Math.floor(value);
  }

  function formatClockMs(ms) {
    const value = Number(ms);
    if (!Number.isFinite(value) || value <= 0) return '-';
    try {
      return new Date(value).toLocaleTimeString();
    } catch (_) {
      return '-';
    }
  }

  function createFlowArrowIcon() {
    const svg = createSvgElement('svg', {
      viewBox: '0 0 20 20',
      class: 'status-icon compact',
      'aria-hidden': 'true',
      focusable: 'false',
    });
    svg.appendChild(createSvgElement('path', { d: 'M3 10H15' }));
    svg.appendChild(createSvgElement('path', { d: 'M11.5 6.5L15 10L11.5 13.5' }));
    return svg;
  }

  const POLICY_STAGE_ORDER = ['ready', 'running', 'analyzed', 'done'];

  function policyStageDefinition(stageKey) {
    const key = safe(stageKey).trim().toLowerCase();
    const map = {
      ready: {
        label: 'codex与agent信息就绪',
        short: '就绪',
        detail: '已完成工作区校验、agent定位、AGENTS指纹与执行参数准备',
      },
      running: {
        label: 'codex分析中',
        short: '分析',
        detail: '已发起 codex exec，等待结构化结果与证据文件输出',
      },
      analyzed: {
        label: 'codex分析完成',
        short: '完成',
        detail: '已收到 codex 输出，完成 JSON 契约解析与字段校验',
      },
      done: {
        label: '角色分析结束',
        short: '结束',
        detail: '已完成门禁判定并刷新会话入口可执行状态',
      },
    };
    return map[key] || {
      label: key || '未知阶段',
      short: key || '未知',
      detail: '无阶段说明',
    };
  }

  function policyStageIconKind(stageKey) {
    const key = safe(stageKey).trim().toLowerCase();
    if (key === 'ready') return 'cache';
    if (key === 'running') return 'spinner';
    if (key === 'analyzed') return 'report';
    if (key === 'done') return 'flag';
    return 'pending';
  }

  function policyStageShortLabel(stageKey) {
    const label = policyStageDefinition(stageKey).short;
    return label.length > 4 ? label.slice(0, 4) : label;
  }

  function policyAnalyzeStageLabel(stageKey) {
    const key = safe(stageKey).trim().toLowerCase();
    return policyStageDefinition(key).label || key || '未知阶段';
  }

  function policyStageDetailText(stageKey) {
    return policyStageDefinition(stageKey).detail;
  }

  function policyStageStatusText(status) {
    const key = safe(status).trim().toLowerCase();
    const map = {
      pending: '待开始',
      running: '进行中',
      done: '已完成',
      failed: '失败',
    };
    return map[key] || key || '-';
  }

  function buildPolicyStageTimeline(progress) {
    const src = progress && typeof progress === 'object' ? progress : {};
    const rawStages = Array.isArray(src.stages) ? src.stages : [];
    const nowMs = Date.now();
    const byKey = {};
    const orderedKeys = [];
    const normalizeDurationMaybe = (rawValue) => {
      if (rawValue === null || rawValue === undefined || rawValue === '') return null;
      const value = Number(rawValue);
      if (!Number.isFinite(value) || value < 0) return null;
      return Math.floor(value);
    };
    for (const item of rawStages) {
      const node = item && typeof item === 'object' ? item : {};
      const key = safe(node.key).trim().toLowerCase();
      if (!key) continue;
      const startedAtMs = Number(node.started_at_ms || 0);
      const durationRaw = normalizeDurationMaybe(node.duration_ms);
      byKey[key] = {
        key: key,
        label: safe(node.label).trim() || policyAnalyzeStageLabel(key),
        started_at_ms: Number.isFinite(startedAtMs) ? startedAtMs : 0,
        duration_ms: durationRaw,
      };
      orderedKeys.push(key);
    }
    const currentKey = orderedKeys.length ? orderedKeys[orderedKeys.length - 1] : '';
    const currentIdx = POLICY_STAGE_ORDER.indexOf(currentKey);
    const stages = [];
    for (let i = 0; i < POLICY_STAGE_ORDER.length; i += 1) {
      const key = POLICY_STAGE_ORDER[i];
      const existing = byKey[key];
      const reached = !!existing;
      const startedAtMs = reached ? Number(existing.started_at_ms || 0) : 0;
      let durationMs = reached ? normalizeDurationMaybe(existing.duration_ms) : null;
      if (durationMs === null) {
        if (src.active && key === currentKey && startedAtMs > 0) {
          durationMs = Math.max(0, nowMs - startedAtMs);
        } else if (reached && startedAtMs > 0) {
          let nextStartedAtMs = 0;
          for (let j = i + 1; j < POLICY_STAGE_ORDER.length; j += 1) {
            const nextKey = POLICY_STAGE_ORDER[j];
            const nextStage = byKey[nextKey];
            if (!nextStage) continue;
            const candidate = Number(nextStage.started_at_ms || 0);
            if (candidate > 0) {
              nextStartedAtMs = candidate;
              break;
            }
          }
          if (nextStartedAtMs > startedAtMs) {
            durationMs = Math.max(0, nextStartedAtMs - startedAtMs);
          } else {
            const finishedAtMs = Number(src.finished_at_ms || 0);
            if (!src.active && finishedAtMs > startedAtMs) {
              durationMs = Math.max(0, finishedAtMs - startedAtMs);
            } else {
              durationMs = null;
            }
          }
        }
      }
      let status = 'pending';
      if (reached) status = 'done';
      if (src.active && key === currentKey) status = 'running';
      if (src.failed && key === currentKey) status = 'failed';
      if (!reached && currentIdx >= 0 && i < currentIdx) status = 'done';
      stages.push({
        index: i + 1,
        key: key,
        label: policyAnalyzeStageLabel(key),
        short_label: policyStageShortLabel(key),
        detail: policyStageDetailText(key),
        status: status,
        reached: reached,
        started_at_ms: startedAtMs,
        duration_ms: durationMs,
      });
    }
    const totalMs = src.active
      ? Math.max(0, nowMs - Number(src.started_at_ms || nowMs))
      : Math.max(0, Number(src.total_ms || 0));
    return {
      stages: stages,
      active: !!src.active,
      failed: !!src.failed,
      total_ms: Math.max(0, Math.floor(totalMs)),
      started_at_ms: Number(src.started_at_ms || 0),
      finished_at_ms: Number(src.finished_at_ms || 0),
      current_key: currentKey,
    };
  }

  function resetPolicyAnalyzeProgress() {
    stopPolicyAnalyzeTicker();
    state.policyAnalyzeProgress = null;
  }

  function stopPolicyAnalyzeTicker() {
    if (state.policyAnalyzeTicker) {
      clearInterval(state.policyAnalyzeTicker);
      state.policyAnalyzeTicker = 0;
    }
  }

  function ensurePolicyAnalyzeTicker() {
    // Avoid high-frequency rerendering:
    // it resets spinner animation and causes hover tooltip flicker.
    // Stage timeline is refreshed on stage transitions and completion.
    stopPolicyAnalyzeTicker();
  }

  function beginPolicyAnalyzeProgress(agentName, gateSeq) {
    stopPolicyAnalyzeTicker();
    state.policyAnalyzeProgress = {
      agent_name: safe(agentName).trim(),
      gate_seq: Number(gateSeq || 0),
      active: true,
      failed: false,
      started_at_ms: Date.now(),
      finished_at_ms: 0,
      total_ms: 0,
      stages: [],
    };
  }

  function markPolicyAnalyzeStage(gateSeq, stageKey, stageLabel) {
    const progress = state.policyAnalyzeProgress;
    if (!progress) return;
    if (Number(progress.gate_seq || 0) !== Number(gateSeq || 0)) return;
    const nowMs = Date.now();
    if (!Array.isArray(progress.stages)) {
      progress.stages = [];
    }
    const stages = progress.stages;
    const current = stages.length ? stages[stages.length - 1] : null;
    const key = safe(stageKey).trim().toLowerCase();
    const label = safe(stageLabel).trim() || policyAnalyzeStageLabel(key);
    if (current && safe(current.key).trim().toLowerCase() === key) {
      return;
    }
    if (current && parseDurationMsMaybe(current.duration_ms) === null) {
      current.duration_ms = Math.max(0, nowMs - Number(current.started_at_ms || nowMs));
    }
    stages.push({
      key: key,
      label: label,
      started_at_ms: nowMs,
      duration_ms: null,
    });
  }

  function finishPolicyAnalyzeProgress(gateSeq, options) {
    const progress = state.policyAnalyzeProgress;
    if (!progress) return;
    if (Number(progress.gate_seq || 0) !== Number(gateSeq || 0)) return;
    const opts = options && typeof options === 'object' ? options : {};
    if (opts.stage_key || opts.stage_label) {
      markPolicyAnalyzeStage(gateSeq, safe(opts.stage_key || 'done'), safe(opts.stage_label));
    }
    const nowMs = Date.now();
    const stages = Array.isArray(progress.stages) ? progress.stages : [];
    const current = stages.length ? stages[stages.length - 1] : null;
    if (current && parseDurationMsMaybe(current.duration_ms) === null) {
      current.duration_ms = Math.max(0, nowMs - Number(current.started_at_ms || nowMs));
    }
    progress.active = false;
    progress.failed = !!opts.failed;
    progress.finished_at_ms = nowMs;
    progress.total_ms = Math.max(0, nowMs - Number(progress.started_at_ms || nowMs));
  }

  function currentPolicyAnalyzeProgress(agentName) {
    const progress = state.policyAnalyzeProgress;
    const target = safe(agentName).trim();
    if (!progress || safe(progress.agent_name).trim() !== target) return null;
    const progressSeq = Number(progress.gate_seq || 0);
    const currentSeq = Number(state.sessionPolicyGateSeq || 0);
    if (progressSeq <= 0 || currentSeq <= 0 || progressSeq !== currentSeq) return null;
    return progress;
  }

  function policyAnalyzeProgressLine(agentName) {
    const progress = currentPolicyAnalyzeProgress(agentName);
    if (!progress) return '';
    const stages = Array.isArray(progress.stages) ? progress.stages : [];
    if (!stages.length) return '';
    const nowMs = Date.now();
    const stageParts = stages.map((stage, index) => {
      const label = safe(stage.label).trim() || policyAnalyzeStageLabel(stage.key);
      let costMs = parseDurationMsMaybe(stage.duration_ms);
      if (costMs === null) {
        costMs = Math.max(0, nowMs - Number(stage.started_at_ms || nowMs));
      }
      return String(index + 1) + '. ' + label + ' ' + formatDurationMs(costMs);
    });
    const totalMs = progress.active
      ? Math.max(0, nowMs - Number(progress.started_at_ms || nowMs))
      : Math.max(0, Number(progress.total_ms || 0));
    const prefix = progress.active ? '分析阶段' : progress.failed ? '最近分析（失败）' : '最近分析';
    return (
      prefix +
      ': ' +
      stageParts.join(' | ') +
      ' | 总计: ' +
      formatDurationMs(totalMs)
    );
  }

  function policyAnalyzeProgressSnapshot(agentName) {
    const progress = currentPolicyAnalyzeProgress(agentName);
    if (!progress) return null;
    const stages = Array.isArray(progress.stages) ? progress.stages : [];
    if (!stages.length) return null;
    const nowMs = Date.now();
    const outStages = stages.map((stage, index) => {
      const startedAtMs = Number(stage && stage.started_at_ms);
      let durationMs = parseDurationMsMaybe(stage && stage.duration_ms);
      if (durationMs === null) {
        durationMs = Number.isFinite(startedAtMs) ? Math.max(0, nowMs - startedAtMs) : 0;
      }
      return {
        index: index + 1,
        key: safe(stage && stage.key).trim(),
        label: safe(stage && stage.label).trim() || policyAnalyzeStageLabel(stage && stage.key),
        started_at_ms: Number.isFinite(startedAtMs) ? startedAtMs : 0,
        duration_ms: Math.max(0, Math.floor(durationMs)),
      };
    });
    const startedAt = Number(progress.started_at_ms || 0);
    const finishedAt = Number(progress.finished_at_ms || 0);
    const totalMs = progress.active
      ? Math.max(0, nowMs - Number(startedAt || nowMs))
      : Math.max(0, Number(progress.total_ms || 0));
    return {
      source: 'web-ui',
      active: !!progress.active,
      failed: !!progress.failed,
      started_at_ms: Number.isFinite(startedAt) ? startedAt : 0,
      finished_at_ms: Number.isFinite(finishedAt) ? finishedAt : 0,
      total_ms: Math.max(0, Math.floor(totalMs)),
      stages: outStages,
    };
  }

  function normalizePolicyAnalyzeProgress(raw) {
    const node = raw && typeof raw === 'object' ? raw : {};
    const stagesRaw = Array.isArray(node.stages) ? node.stages : [];
    const stages = stagesRaw
      .map((stage, index) => {
        const row = stage && typeof stage === 'object' ? stage : {};
        const label = safe(row.label).trim() || policyAnalyzeStageLabel(row.key);
        const key = safe(row.key).trim().toLowerCase();
        const startedAtMs = Number(row.started_at_ms || 0);
        let durationMs = null;
        if (row.duration_ms !== null && row.duration_ms !== undefined && row.duration_ms !== '') {
          const parsedDuration = Number(row.duration_ms);
          if (Number.isFinite(parsedDuration) && parsedDuration >= 0) {
            durationMs = Math.floor(parsedDuration);
          }
        }
        return {
          index: Number(row.index || index + 1),
          key: key,
          label: label,
          started_at_ms: Number.isFinite(startedAtMs) ? startedAtMs : 0,
          duration_ms: durationMs,
        };
      })
      .filter((stage) => !!safe(stage.label).trim());
    return {
      source: safe(node.source || '').trim(),
      active: !!node.active,
      failed: !!node.failed,
      started_at_ms: Number.isFinite(Number(node.started_at_ms)) ? Number(node.started_at_ms) : 0,
      finished_at_ms: Number.isFinite(Number(node.finished_at_ms)) ? Number(node.finished_at_ms) : 0,
      total_ms: Number.isFinite(Number(node.total_ms)) && Number(node.total_ms) >= 0 ? Math.floor(Number(node.total_ms)) : 0,
      stages: stages,
    };
  }

  function policyGateMetaText() {
    const agent = selectedAgent();
    const progressLine = policyAnalyzeProgressLine(agent);
    if (!agent) return '请选择 agent';
    if (state.sessionPolicyGateState === 'analyzing_policy') {
      return progressLine || '角色与职责分析中...';
    }
    if (state.sessionPolicyGateState === 'policy_cache_missing') {
      return '当前角色缓存已清理，请点击“生成缓存”图标后再继续。';
    }
    return progressLine;
  }

  function buildPolicyFallbackProgressByGate(gateState) {
    const gate = safe(gateState).trim().toLowerCase();
    const doneStages = POLICY_STAGE_ORDER.map((key) => ({
      key: key,
      label: policyAnalyzeStageLabel(key),
      started_at_ms: 0,
      duration_ms: null,
    }));
    if (gate === 'policy_ready' || gate === 'policy_needs_confirm' || gate === 'policy_confirmed') {
      return {
        active: false,
        failed: false,
        started_at_ms: 0,
        finished_at_ms: 0,
        total_ms: 0,
        stages: doneStages,
      };
    }
    if (gate === 'policy_failed') {
      return {
        active: false,
        failed: true,
        started_at_ms: 0,
        finished_at_ms: 0,
        total_ms: 0,
        stages: doneStages,
      };
    }
    if (gate === 'analyzing_policy') {
      return {
        active: true,
        failed: false,
        started_at_ms: Date.now(),
        finished_at_ms: 0,
        total_ms: 0,
        stages: [
          {
            key: 'ready',
            label: policyAnalyzeStageLabel('ready'),
            started_at_ms: Date.now(),
            duration_ms: 0,
          },
          {
            key: 'running',
            label: policyAnalyzeStageLabel('running'),
            started_at_ms: Date.now(),
            duration_ms: null,
          },
        ],
      };
    }
    return {
      active: false,
      failed: false,
      started_at_ms: 0,
      finished_at_ms: 0,
      total_ms: 0,
      stages: [],
    };
  }

  function buildPolicyFallbackProgressFromInfo(info) {
    const node = info && typeof info === 'object' ? info : {};
    const parseStatus = safe(node.parse_status).trim().toLowerCase();
    const clarityGate = safe(node.clarity_gate).trim().toLowerCase();
    if (clarityGate === 'block' || parseStatus === 'failed') {
      return buildPolicyFallbackProgressByGate('policy_failed');
    }
    if (clarityGate === 'confirm') {
      return buildPolicyFallbackProgressByGate('policy_needs_confirm');
    }
    if (clarityGate === 'auto' || parseStatus === 'ok' || parseStatus === 'incomplete') {
      return buildPolicyFallbackProgressByGate('policy_ready');
    }
    return buildPolicyFallbackProgressByGate('idle_unselected');
  }

  function renderPolicyGateMetaPipeline(node, progress) {
    const host = node;
    const timeline = buildPolicyStageTimeline(progress);
    const stages = Array.isArray(timeline.stages) ? timeline.stages : [];
    if (!stages.length) return false;
    host.innerHTML = '';
    host.className = 'hint policy-gate-pipeline-wrap';
    const line = document.createElement('div');
    line.className = 'policy-gate-stage-line';
    const lastIndex = stages.length - 1;
    for (let i = 0; i < stages.length; i += 1) {
      const stage = stages[i] && typeof stages[i] === 'object' ? stages[i] : {};
      const fullLabel = safe(stage.label).trim() || policyAnalyzeStageLabel(stage.key);
      const shortLabel = safe(stage.short_label).trim() || policyStageShortLabel(stage.key);
      const stageStatus = safe(stage.status).trim().toLowerCase() || 'pending';
      const stageStatusText = policyStageStatusText(stageStatus);
      const isFailed = stageStatus === 'failed';
      const isRunning = stageStatus === 'running';
      const isPending = stageStatus === 'pending';
      const iconKind = isFailed ? 'failed' : isPending ? 'pending' : policyStageIconKind(stage.key);
      const stageNode = document.createElement('span');
      stageNode.className = 'policy-gate-stage-node';
      if (i === 0) stageNode.classList.add('first');
      if (i === lastIndex) stageNode.classList.add('last');
      if (isFailed) {
        stageNode.classList.add('failed');
      } else if (isRunning) {
        stageNode.classList.add('running');
      } else if (isPending) {
        stageNode.classList.add('pending');
      } else {
        stageNode.classList.add('done');
      }
      stageNode.setAttribute('tabindex', '0');
      const anchor = document.createElement('span');
      anchor.className = 'policy-gate-stage-anchor';
      stageNode.appendChild(anchor);
      const icon = createStatusIcon(iconKind, {
        compact: true,
        spinning: isRunning,
      });
      const iconBox = document.createElement('span');
      iconBox.className = 'policy-gate-stage-icon';
      iconBox.appendChild(icon);
      anchor.appendChild(iconBox);
      const text = document.createElement('span');
      text.className = 'policy-gate-stage-label';
      text.textContent = shortLabel;
      anchor.appendChild(text);
      const pendingHint =
        isPending
          ? i > 0
            ? '等待上一阶段完成：' + (safe(stages[i - 1] && stages[i - 1].label).trim() || '前序阶段')
            : '等待启动分析'
          : '';
      const startedText = isPending ? '未开始' : formatClockMs(stage.started_at_ms);
      const durationText = isPending ? '-' : formatDurationMs(stage.duration_ms);
      const stageTip =
        '#' + String(i + 1) + ' · ' + fullLabel + '\n' +
        '图标: ' + iconKind + '\n' +
        '状态: ' + stageStatusText + '\n' +
        '阶段说明: ' + safe(stage.detail).trim() + '\n' +
        (pendingHint ? '进度提示: ' + pendingHint + '\n' : '') +
        '开始: ' + startedText + '\n' +
        '耗时: ' + durationText;
      stageNode.setAttribute('aria-label', stageTip.replace(/\n/g, ' ; '));
      const tooltip = document.createElement('div');
      tooltip.className = 'policy-gate-stage-tooltip';
      const title = document.createElement('div');
      title.className = 'policy-gate-stage-tooltip-title';
      title.textContent = fullLabel;
      tooltip.appendChild(title);
      const lines = [
        '阶段 #' + String(i + 1),
        '图标: ' + iconKind,
        '状态: ' + stageStatusText,
        '说明: ' + safe(stage.detail).trim(),
        pendingHint ? '进度提示: ' + pendingHint : '',
        '开始: ' + startedText,
        '耗时: ' + durationText,
      ];
      for (const part of lines) {
        if (!safe(part).trim()) continue;
        const row = document.createElement('div');
        row.className = 'policy-gate-stage-tooltip-line';
        row.textContent = part;
        tooltip.appendChild(row);
      }
      anchor.appendChild(tooltip);
      line.appendChild(stageNode);
      if (i < lastIndex) {
        const arrowWrap = document.createElement('span');
        arrowWrap.className = 'policy-gate-stage-arrow';
        arrowWrap.appendChild(createFlowArrowIcon());
        line.appendChild(arrowWrap);
      }
    }
    host.appendChild(line);
    return true;
  }
