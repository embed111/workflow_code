  // Training center agent detail and selected-agent context helpers.

  function renderTrainingCenterAgentDetail() {
    const titleNode = $('tcAgentDetailTitle');
    const subtitleNode = $('tcAgentDetailSubtitle');
    const metaNode = $('tcAgentDetailMeta');
    const stateNode = $('tcAgentLifecycleMeta');
    const detailBody = $('tcAgentDetailBody');
    const detailNode = document.querySelector('#tcModuleAgents .tc-detail');
    const enterOpsBtn = $('tcEnterOpsBtn');
    const avatarBtn = $('tcSetAvatarBtn');
    const switchSelect = $('tcSwitchVersionSelect');
    const switchTrigger = $('tcSwitchVersionTrigger');
    const switchTriggerText = $('tcSwitchVersionTriggerText');
    const switchTriggerSub = $('tcSwitchVersionTriggerSub');
    const discardBtn = $('tcDiscardPreReleaseBtn');
    const evalDecisionSelect = $('tcEvalDecisionSelect');
    const item = state.tcSelectedAgentDetail || null;
    const contextLoading =
      !!item &&
      !!state.tcSelectedAgentContextLoading &&
      safe(state.tcSelectedAgentId).trim() === safe(item.agent_id).trim();
    if (detailNode instanceof HTMLElement) {
      detailNode.style.minWidth = '0';
      detailNode.style.maxWidth = '100%';
      detailNode.style.overflowX = 'hidden';
      detailNode.style.overflowY = 'auto';
      detailNode.style.overscrollBehavior = 'contain';
    }
    if (metaNode instanceof HTMLElement) {
      metaNode.style.display = 'block';
      metaNode.style.minWidth = '0';
      metaNode.style.maxWidth = '100%';
      metaNode.style.overflow = 'visible';
      metaNode.style.whiteSpace = 'normal';
      metaNode.style.overflowWrap = 'anywhere';
      metaNode.style.wordBreak = 'break-word';
      metaNode.style.lineHeight = '1.45';
    }
    if (stateNode instanceof HTMLElement) {
      stateNode.style.display = 'flex';
      stateNode.style.flexWrap = 'wrap';
      stateNode.style.gap = '6px';
      stateNode.style.minWidth = '0';
      stateNode.style.maxWidth = '100%';
      stateNode.style.overflow = 'visible';
      stateNode.style.whiteSpace = 'normal';
      stateNode.style.overflowWrap = 'anywhere';
      stateNode.style.wordBreak = 'break-word';
    }
    if (!item) {
      setTrainingCenterVersionDropdownOpen(false);
      if (titleNode) titleNode.textContent = '角色详情';
      if (subtitleNode) subtitleNode.textContent = '请选择左侧角色工卡';
      if (metaNode) metaNode.textContent = '路径/版本信息将在这里展示';
      if (stateNode) stateNode.innerHTML = '';
      if (detailBody instanceof HTMLElement) detailBody.style.display = 'none';
      if (enterOpsBtn) enterOpsBtn.disabled = true;
      if (avatarBtn) avatarBtn.disabled = true;
      if (switchSelect) {
        switchSelect.value = '';
        switchSelect.disabled = true;
      }
      if (switchTrigger) switchTrigger.disabled = true;
      if (switchTriggerText) switchTriggerText.textContent = trainingCenterVersionText('');
      if (switchTriggerSub) switchTriggerSub.textContent = '请选择左侧角色工卡';
      if (discardBtn) discardBtn.disabled = true;
      if (evalDecisionSelect) {
        const rejectDiscardOption = Array.from(evalDecisionSelect.options || []).find(
          (option) => safe(option && option.value).trim() === 'reject_discard_pre_release'
        );
        if (rejectDiscardOption) rejectDiscardOption.disabled = true;
        if (safe(evalDecisionSelect.value).trim() === 'reject_discard_pre_release') {
          evalDecisionSelect.value = 'reject_continue_training';
        }
      }
      setTrainingCenterAgentActionResult('等待发布管理操作...');
      renderTrainingCenterPortrait(null);
      renderTrainingCenterReleases('');
      renderTrainingCenterNormalCommits('');
      renderTrainingCenterReleaseReview('');
      updateTrainingCenterOpsGateState();
      return;
    }
    const publishedRelease = currentTrainingCenterPublishedRelease(item);
    const hasPublishedRelease = !!publishedRelease;
    const roleProfile = trainingCenterRoleProfile(item);
    const roleSubtitle = trainingCenterRolePositionText(
      safe(roleProfile.first_person_summary || (publishedRelease && (publishedRelease.capability_summary || publishedRelease.knowledge_scope)) || '').trim(),
      50
    );
    if (titleNode) {
      titleNode.textContent = '角色详情 · ' + safe(item.agent_name || item.agent_id || '');
    }
    if (subtitleNode) {
      subtitleNode.textContent = '角色介绍：' + roleSubtitle + ' · 来源=' + trainingCenterRoleProfileSourceText(roleProfile.profile_source || '');
    }
    if (detailBody instanceof HTMLElement) detailBody.style.display = '';
    if (avatarBtn) avatarBtn.disabled = false;
    if (switchSelect) {
      const releaseRows = Array.isArray(state.tcReleasesByAgent[safe(item.agent_id).trim()]) ? state.tcReleasesByAgent[safe(item.agent_id).trim()] : [];
      switchSelect.disabled = !releaseRows.length;
      if (switchTrigger) switchTrigger.disabled = !releaseRows.length;
    }
    if (evalDecisionSelect) {
      const rejectDiscardOption = Array.from(evalDecisionSelect.options || []).find(
        (option) => safe(option && option.value).trim() === 'reject_discard_pre_release'
      );
      if (rejectDiscardOption) rejectDiscardOption.disabled = !hasPublishedRelease;
      if (!hasPublishedRelease && safe(evalDecisionSelect.value).trim() === 'reject_discard_pre_release') {
        evalDecisionSelect.value = 'reject_continue_training';
      }
    }
    if (metaNode) {
      const tags = visibleTrainingStatusTags(item.status_tags);
      const preState = safe(item.pre_release_state || item.lifecycle_state || '').toLowerCase();
      const preReason = safe(item.pre_release_reason || '').trim();
      const preCheckedAt = safe(item.pre_release_checked_at || '').trim();
      const workspacePath = safe(item.workspace_path).trim();
      const currentVersion = safe(item.current_version).trim();
      const boundReleaseVersion = safe(item.bound_release_version).trim();
      const latestReleaseVersion = safe(item.latest_release_version).trim();
      const lastReleaseAt = safe(item.last_release_at).trim();
      const lines = [
        '工作区路径=' + (workspacePath || '-'),
        '发布状态=' + (publishedRelease ? '已发布' : '未发布'),
        '预发布判定=' + trainingLifecycleText(preState || 'unknown'),
      ];
      if (currentVersion && (boundReleaseVersion || latestReleaseVersion)) {
        lines.push('当前版本=' + currentVersion);
      }
      if (boundReleaseVersion) {
        lines.push('绑定发布版本=' + boundReleaseVersion);
      }
      if (latestReleaseVersion) {
        lines.push('最新发布版本=' + latestReleaseVersion);
      }
      if (lastReleaseAt) {
        lines.push('最近发布时间=' + lastReleaseAt);
      }
      lines.push('角色详情来源=' + trainingCenterRoleProfileSourceText(roleProfile.profile_source || ''));
      if (roleProfile.source_release_version) {
        lines.push('画像来源版本=' + roleProfile.source_release_version);
      }
      if (tags.length) {
        lines.push('状态标签=' + tags.map((tag) => trainingStatusTagText(tag)).join(','));
      }
      if (preReason) {
        lines.push('预发布原因=' + preReason);
      }
      if (preCheckedAt) {
        lines.push('预发布判定时间=' + preCheckedAt);
      }
      if (contextLoading) {
        lines.push('上下文同步=正在刷新发布版本与评审信息');
      }
      metaNode.innerHTML = '';
      for (const lineText of lines) {
        const lineNode = document.createElement('div');
        lineNode.textContent = safe(lineText);
        lineNode.style.whiteSpace = 'normal';
        lineNode.style.overflowWrap = 'anywhere';
        lineNode.style.wordBreak = 'break-word';
        lineNode.style.lineHeight = '1.45';
        metaNode.appendChild(lineNode);
      }
    }
    if (stateNode) {
      const lifecycle = safe(item.lifecycle_state || 'released').toLowerCase();
      const gate = safe(item.training_gate_state || 'trainable').toLowerCase();
      const parent = safe(item.parent_agent_id || '').trim();
      const lifecycleCls = lifecycle === 'released' ? 'ok' : 'warn';
      const gateCls = gate === 'frozen_switched' ? 'warn' : 'ok';
      stateNode.innerHTML = '';
      const badgeRows = [
        { cls: lifecycleCls, text: '生命周期：' + trainingLifecycleText(lifecycle) },
        { cls: gateCls, text: '训练门禁：' + trainingGateText(gate) },
      ];
      if (parent) {
        badgeRows.push({ cls: '', text: '克隆来源：' + parent });
      }
      for (const row of badgeRows) {
        const badge = document.createElement('span');
        badge.className = row.cls ? 'tc-badge ' + row.cls : 'tc-badge';
        badge.textContent = safe(row.text);
        badge.style.maxWidth = '100%';
        badge.style.whiteSpace = 'normal';
        badge.style.overflowWrap = 'anywhere';
        badge.style.wordBreak = 'break-word';
        stateNode.appendChild(badge);
      }
    }
    if (enterOpsBtn) enterOpsBtn.disabled = !state.agentSearchRootReady;
    if (discardBtn) {
      discardBtn.disabled = safe(item.lifecycle_state).toLowerCase() !== 'pre_release' || !hasPublishedRelease;
    }
    renderTrainingCenterPortrait(item);
    renderTrainingCenterReleases(safe(item.agent_id));
    renderTrainingCenterNormalCommits(safe(item.agent_id));
    renderTrainingCenterReleaseReview(safe(item.agent_id));
    updateTrainingCenterOpsGateState();
  }

  function beginTrainingCenterSelectedAgentContext(agentId) {
    const key = safe(agentId).trim();
    if (!key || safe(state.tcSelectedAgentId).trim() !== key) {
      state.tcSelectedAgentContextLoading = false;
      return 0;
    }
    const nextSeq = Number(state.tcSelectedAgentContextRequestSeq || 0) + 1;
    state.tcSelectedAgentContextRequestSeq = nextSeq;
    state.tcSelectedAgentContextLoading = true;
    return nextSeq;
  }

  function isTrainingCenterSelectedAgentContextCurrent(agentId, requestSeq) {
    const key = safe(agentId).trim();
    if (!key || safe(state.tcSelectedAgentId).trim() !== key) {
      return false;
    }
    const seq = Number(requestSeq || 0);
    if (!seq) {
      return true;
    }
    return Number(state.tcSelectedAgentContextRequestSeq || 0) === seq;
  }

  function syncTrainingCenterSelectedAgentFromPayload(agentId, agentPayload) {
    const key = safe(agentId).trim();
    if (!key || safe(state.tcSelectedAgentId).trim() !== key || !agentPayload || typeof agentPayload !== 'object') {
      return;
    }
    state.tcSelectedAgentDetail = Object.assign({}, state.tcSelectedAgentDetail || {}, agentPayload);
    state.tcSelectedAgentId = safe(agentPayload.agent_id || key);
    state.tcSelectedAgentName = safe(agentPayload.agent_name || state.tcSelectedAgentName);
    updateTrainingCenterSelectedMeta();
  }

  async function refreshTrainingCenterReleases(agentId, options) {
    const key = safe(agentId).trim();
    const opts = options && typeof options === 'object' ? options : {};
    if (!key) {
      if (!opts.skipRender) {
        renderTrainingCenterAgentDetail();
      }
      return;
    }
    const data = await getJSON('/api/training/agents/' + encodeURIComponent(key) + '/releases?page=1&page_size=120');
    if (opts.requestSeq && !isTrainingCenterSelectedAgentContextCurrent(key, opts.requestSeq)) {
      return data;
    }
    if (!state.tcNormalCommitsByAgent || typeof state.tcNormalCommitsByAgent !== 'object') {
      state.tcNormalCommitsByAgent = {};
    }
    state.tcReleasesByAgent[key] = Array.isArray(data.releases) ? data.releases : [];
    state.tcNormalCommitsByAgent[key] = Array.isArray(data.normal_commits) ? data.normal_commits : [];
    if (data.agent && typeof data.agent === 'object') {
      syncTrainingCenterSelectedAgentFromPayload(key, data.agent);
    }
    if (!opts.skipRender && safe(state.tcSelectedAgentId).trim() === key) {
      renderTrainingCenterAgentDetail();
    }
    return data;
  }

  async function refreshTrainingCenterReleaseReview(agentId, options) {
    const key = safe(agentId).trim();
    const opts = options && typeof options === 'object' ? options : {};
    if (!key) {
      if (!opts.skipRender) {
        renderTrainingCenterReleaseReview('');
      }
      return;
    }
    const data = await getJSON('/api/training/agents/' + encodeURIComponent(key) + '/release-review');
    if (opts.requestSeq && !isTrainingCenterSelectedAgentContextCurrent(key, opts.requestSeq)) {
      return data;
    }
    if (!state.tcReleaseReviewByAgent || typeof state.tcReleaseReviewByAgent !== 'object') {
      state.tcReleaseReviewByAgent = {};
    }
    state.tcReleaseReviewByAgent[key] = normalizeTrainingCenterReleaseReviewPayload(key, data);
    if (!opts.skipRender && safe(state.tcSelectedAgentId).trim() === key) {
      renderTrainingCenterReleaseReview(key);
    }
    return data;
  }

  async function refreshTrainingCenterSelectedAgentContext(agentId, options) {
    const key = safe(agentId).trim();
    const opts = options && typeof options === 'object' ? options : {};
    if (!key) {
      state.tcSelectedAgentContextLoading = false;
      renderTrainingCenterAgentDetail();
      return;
    }
    const requestSeq = beginTrainingCenterSelectedAgentContext(key);
    if (!opts.skipRender && safe(state.tcSelectedAgentId).trim() === key) {
      renderTrainingCenterAgentDetail();
    }
    const results = await Promise.allSettled([
      refreshTrainingCenterReleases(key, { skipRender: true, requestSeq: requestSeq }),
      refreshTrainingCenterReleaseReview(key, { skipRender: true, requestSeq: requestSeq }),
    ]);
    if (requestSeq && !isTrainingCenterSelectedAgentContextCurrent(key, requestSeq)) {
      return results;
    }
    if (requestSeq) {
      state.tcSelectedAgentContextLoading = false;
    }
    if (!opts.skipRender && safe(state.tcSelectedAgentId).trim() === key) {
      renderTrainingCenterAgentDetail();
    }
    const rejected = results.find((entry) => entry && entry.status === 'rejected');
    if (rejected && rejected.reason) {
      throw rejected.reason;
    }
    return results;
  }

  function refreshTrainingCenterSelectedAgentContextDeferred(agentId, options) {
    const key = safe(agentId).trim();
    if (!key) return Promise.resolve(null);
    return refreshTrainingCenterSelectedAgentContext(key, options).catch((err) => {
      if (safe(state.tcSelectedAgentId).trim() === key) {
        setTrainingCenterDetailError(err.message || String(err));
      }
      return null;
    });
  }

  async function refreshTrainingCenterAgents(options) {
    const opts = options && typeof options === 'object' ? options : {};
    const data = await getJSON(withTestDataQuery('/api/training/agents'));
    state.tcAgents = Array.isArray(data.items) ? data.items : [];
    const knownAgentIds = new Set(
      state.tcAgents
        .map((item) => safe(item && item.agent_id).trim())
        .filter((item) => !!item)
    );
    const nextReleasesByAgent = {};
    const nextNormalCommitsByAgent = {};
    const nextReleaseReviewByAgent = {};
    const releasesByAgent = state.tcReleasesByAgent && typeof state.tcReleasesByAgent === 'object'
      ? state.tcReleasesByAgent
      : {};
    const normalCommitsByAgent = state.tcNormalCommitsByAgent && typeof state.tcNormalCommitsByAgent === 'object'
      ? state.tcNormalCommitsByAgent
      : {};
    const releaseReviewByAgent = state.tcReleaseReviewByAgent && typeof state.tcReleaseReviewByAgent === 'object'
      ? state.tcReleaseReviewByAgent
      : {};
    Object.keys(releasesByAgent).forEach((agentId) => {
      if (!knownAgentIds.has(agentId)) return;
      nextReleasesByAgent[agentId] = Array.isArray(releasesByAgent[agentId]) ? releasesByAgent[agentId] : [];
    });
    Object.keys(normalCommitsByAgent).forEach((agentId) => {
      if (!knownAgentIds.has(agentId)) return;
      nextNormalCommitsByAgent[agentId] = Array.isArray(normalCommitsByAgent[agentId]) ? normalCommitsByAgent[agentId] : [];
    });
    Object.keys(releaseReviewByAgent).forEach((agentId) => {
      if (!knownAgentIds.has(agentId)) return;
      nextReleaseReviewByAgent[agentId] = releaseReviewByAgent[agentId];
    });
    state.tcReleasesByAgent = nextReleasesByAgent;
    state.tcNormalCommitsByAgent = nextNormalCommitsByAgent;
    state.tcReleaseReviewByAgent = nextReleaseReviewByAgent;
    state.tcStats =
      data.stats && typeof data.stats === 'object'
        ? data.stats
        : {
            agent_total: 0,
            git_available_count: 0,
            latest_release_at: '',
            training_queue_pending: 0,
          };
    renderTrainingCenterAgentStats();
    const selected = safe(state.tcSelectedAgentId).trim();
    const matched =
      selected && state.tcAgents.find((item) => safe(item.agent_id).trim() === selected);
    if (!matched) {
      state.tcSelectedAgentId = '';
      state.tcSelectedAgentName = '';
      state.tcSelectedAgentDetail = null;
      state.tcSelectedAgentContextLoading = false;
    } else {
      state.tcSelectedAgentDetail = matched;
      state.tcSelectedAgentName = safe(matched.agent_name || '');
    }
    syncTrainingCenterPlanAgentOptions();
    updateTrainingCenterSelectedMeta();
    renderTrainingCenterAgentList();
    if (state.tcSelectedAgentId) {
      const contextPromise = refreshTrainingCenterSelectedAgentContextDeferred(state.tcSelectedAgentId);
      if (opts.waitForSelectedContext) {
        await contextPromise;
      }
      return data;
    }
    renderTrainingCenterAgentDetail();
    return data;
  }

  function trainingExecutionEngineLabel(value) {
    const raw = safe(value).trim();
    const key = raw.toLowerCase();
    if (!key || key === 'workflow_native' || key === 'workflow' || key === 'native') {
      return 'workflow 内建训练能力';
    }
    return raw;
  }

  function trainingCenterSelectedTargetAgent() {
    const select = $('tcPlanTargetAgentSelect');
    const fromSelect = safe(select ? select.value : '').trim();
    if (fromSelect) return fromSelect;
    return safe(state.tcSelectedAgentId).trim();
  }

  function parseTrainingTasksInput() {
    const text = safe($('tcPlanTasksInput') ? $('tcPlanTasksInput').value : '').trim();
    if (!text) return [];
    return text
      .split(/\r?\n/)
      .map((line) => safe(line).trim())
      .filter((line) => !!line);
  }

  function setTrainingCenterRunResult(value) {
    const node = $('tcRunResult');
    if (!node) return;
    if (typeof value === 'string') {
      node.textContent = value;
      return;
    }
    node.textContent = JSON.stringify(value || {}, null, 2);
  }
