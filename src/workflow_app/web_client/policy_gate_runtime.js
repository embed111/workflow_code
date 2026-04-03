  function renderPolicyGateMeta() {
    const node = $('policyGateMeta');
    if (!node) return;
    const agent = selectedAgent();
    if (!agent) {
      node.className = 'hint';
      node.textContent = '请选择 agent';
      return;
    }
    const gate = safe(state.sessionPolicyGateState || '').trim().toLowerCase();
    const forceFallback = gate === 'policy_cache_missing';
    let progress = null;
    if (!forceFallback) {
      progress = policyAnalyzeProgressSnapshot(agent);
      if (!progress) {
        progress = getAgentPolicyProgressSnapshot(agent);
      }
      if (!progress) {
        const selected = selectedAgentItem();
        const chain =
          selected && selected.analysis_chain && typeof selected.analysis_chain === 'object'
            ? selected.analysis_chain
            : {};
        const stored = normalizePolicyAnalyzeProgress(
          chain.ui_progress && typeof chain.ui_progress === 'object' ? chain.ui_progress : {}
        );
        if (Array.isArray(stored.stages) && stored.stages.length) {
          setAgentPolicyProgressSnapshot(agent, stored);
          progress = stored;
        }
      }
    }
    if (!progress) {
      progress = buildPolicyFallbackProgressByGate(state.sessionPolicyGateState);
    }
    if (renderPolicyGateMetaPipeline(node, progress)) {
      if (state.sessionPolicyGateState === 'policy_cache_missing') {
        const note = document.createElement('div');
        note.className = 'hint warn';
        note.textContent = '当前角色缓存已清理，请点击“生成缓存”图标后再继续。';
        node.appendChild(note);
      }
      return;
    }
    node.className = 'hint';
    node.textContent = policyGateMetaText();
  }

  function setSessionPolicyGateState(nextState, reason, cacheLine) {
    state.sessionPolicyGateState = safe(nextState || 'idle_unselected') || 'idle_unselected';
    state.sessionPolicyGateReason = safe(reason);
    state.sessionPolicyCacheLine = safe(cacheLine);
    const agent = selectedAgent();
    if (agent) {
      const gate = safe(state.sessionPolicyGateState);
      if (gate === 'analyzing_policy') {
        setAgentPolicyAnalysisRecord(agent, {
          status: 'unanalyzed',
          analyzing: true,
          requires_manual: false,
        });
      } else if (gate === 'policy_cache_missing') {
        setAgentPolicyAnalysisRecord(agent, {
          status: 'unanalyzed',
          analyzing: false,
          requires_manual: true,
        });
      } else if (
        gate === 'policy_ready' ||
        gate === 'policy_needs_confirm' ||
        gate === 'policy_failed' ||
        gate === 'policy_confirmed'
      ) {
        setAgentPolicyAnalysisRecord(agent, {
          status: 'analyzed',
          analyzing: false,
          requires_manual: false,
          gate: gate,
          reason: safe(reason),
          cacheLine: safe(cacheLine),
        });
      }
    }
    renderPolicyGateMeta();
    renderAgentStatusList(visibleAgents());
  }

  function derivePolicyGateFromAgent(item) {
    if (!item) {
      return {
        gate: 'idle_unselected',
        reason: '请先选择 agent',
      };
    }
    const cacheStatus = safe(item.policy_cache_status || '').toLowerCase();
    const cacheReason = safe(item.policy_cache_reason || '').toLowerCase();
    if (cacheStatus === 'cleared' || cacheReason === 'manual_clear') {
      return {
        gate: 'policy_cache_missing',
        reason: '当前角色缓存已清理，请点击“生成缓存”图标后继续。',
      };
    }
    const parseStatus = safe(item.parse_status || 'failed').toLowerCase();
    const clarityGate = safe(item.clarity_gate || '').toLowerCase();
    const clarityScore = Number(item.clarity_score || 0);
    const parseKnown = parseStatus === 'ok' || parseStatus === 'incomplete' || parseStatus === 'failed';
    const gateKnown = clarityGate === 'auto' || clarityGate === 'confirm' || clarityGate === 'block';
    if (!parseKnown && !gateKnown) {
      return {
        gate: 'policy_failed',
        reason: '角色与职责尚未生成有效分析结果，请先点击“生成缓存”图标。',
      };
    }
    if (parseStatus === 'failed' || clarityGate === 'block') {
      return {
        gate: 'policy_failed',
        reason:
          '角色与职责提取失败或清晰度不足（' +
          safe(clarityScore) +
          '/100），创建会话已阻断' +
          (state.allowManualPolicyInput ? '，可使用“角色与职责确认/兜底”手动编辑。' : '。'),
      };
    }
    if (clarityGate === 'confirm') {
      return {
        gate: 'policy_needs_confirm',
        reason: '角色与职责需人工确认（清晰度=' + safe(clarityScore) + '/100），请先确认再创建会话。',
      };
    }
    return {
      gate: 'policy_ready',
      reason: '角色与职责分析完成，可创建会话。',
    };
  }

  function updateClearPolicyCacheButton() {
    const btn = $('clearPolicyCacheBtn');
    const clearAllBtn = $('clearAllPolicyCacheBtn');
    const regenBtn = $('regeneratePolicyCacheBtn');
    const agent = selectedAgent();
    if (btn) {
      const clearTitle = agent ? '清理当前角色缓存' : '请先选择 agent 后清理当前角色缓存';
      btn.title = clearTitle;
      btn.setAttribute('aria-label', clearTitle);
    }
    if (regenBtn) {
      const regenTitle = agent ? '生成当前角色缓存' : '请先选择 agent 后生成缓存';
      regenBtn.title = regenTitle;
      regenBtn.setAttribute('aria-label', regenTitle);
    }
    if (clearAllBtn) {
      clearAllBtn.title = '清理所有角色缓存';
      clearAllBtn.setAttribute('aria-label', '清理所有角色缓存');
    }
  }

  function startPolicyAnalysisForSelection() {
    const agent = selectedAgent();
    updateClearPolicyCacheButton();
    let gateSeq = Number(state.sessionPolicyGateSeq || 0);
    if (!agent) {
      resetPolicyAnalyzeProgress();
      setSessionPolicyGateState('idle_unselected', '请先选择 agent', '');
      renderAgentSelectOptions(true);
      updateAgentMeta();
      applyGateState();
      return;
    }
    const currentRecord = getAgentPolicyAnalysisRecord(agent);
    if (currentRecord.requires_manual) {
      setSessionPolicyGateState('policy_cache_missing', '当前角色缓存已清理，请点击“生成缓存”图标后继续。', '');
      renderAgentSelectOptions(true);
      updateAgentMeta();
      applyGateState();
      return;
    }
    if (currentRecord.status === 'analyzed') {
      setSessionPolicyGateState(
        safe(currentRecord.gate || 'policy_ready'),
        safe(currentRecord.reason || '角色与职责分析完成，可创建会话。'),
        safe(currentRecord.cacheLine || ''),
      );
      renderAgentSelectOptions(true);
      updateAgentMeta();
      applyGateState();
      return;
    }
    if (currentRecord.analyzing) {
      setSessionPolicyGateState('analyzing_policy', '正在分析角色/职责/目标，请稍候...', '');
      renderAgentSelectOptions(true);
      updateAgentMeta();
      applyGateState();
      return;
    }
    setAgentPolicyAnalysisRecord(agent, {
      status: 'unanalyzed',
      analyzing: true,
      requires_manual: false,
    });
    state.sessionPolicyGateSeq = Number(state.sessionPolicyGateSeq || 0) + 1;
    gateSeq = state.sessionPolicyGateSeq;
    beginPolicyAnalyzeProgress(agent, gateSeq);
    markPolicyAnalyzeStage(gateSeq, 'ready', 'codex与agent信息就绪');
    setSessionPolicyGateState('analyzing_policy', '正在分析角色/职责/目标，请稍候...', '');
    renderAgentSelectOptions(true);
    updateAgentMeta();
    applyGateState();
    let analysisDelayMs = 30;
    if (isPolicyProbeEnabled()) {
      const rawDelay = Number(queryParam('policy_probe_delay_ms') || '');
      if (Number.isFinite(rawDelay) && rawDelay >= 0) {
        analysisDelayMs = Math.floor(rawDelay);
      } else if (policyProbeStage() === 'analyzing') {
        analysisDelayMs = 2500;
      }
    }
    window.setTimeout(async () => {
      if (gateSeq !== state.sessionPolicyGateSeq) return;
      try {
        markPolicyAnalyzeStage(gateSeq, 'running', 'codex分析中');
        setSessionPolicyGateState('analyzing_policy', '正在分析角色/职责/目标，请稍候...', '');
        const data = await postJSON('/api/policy/analyze', {
          agent_name: agent,
          agent_search_root: safe($('agentSearchRoot').value).trim(),
        });
        if (gateSeq !== state.sessionPolicyGateSeq) return;
        markPolicyAnalyzeStage(gateSeq, 'analyzed', 'codex分析完成');
        const item = data && data.agent_policy && typeof data.agent_policy === 'object'
          ? data.agent_policy
          : null;
        if (!item) {
          throw new Error('角色策略分析返回为空');
        }
        mergeAgentItemByName(agent, item);
        const selected = selectedAgentItem();
        if (!selected) {
          setSessionPolicyGateState('idle_unselected', '请先选择 agent', '');
          renderAgentSelectOptions(true);
          updateAgentMeta();
          applyGateState();
          return;
        }
        const derived = derivePolicyGateFromAgent(selected);
        const cacheLine = buildPolicyCacheLineFromItem(selected);
        setAgentPolicyAnalysisRecord(agent, {
          status: 'analyzed',
          analyzing: false,
          gate: safe(derived.gate),
          reason: safe(derived.reason),
          cacheLine: safe(cacheLine),
          requires_manual: false,
        });
        finishPolicyAnalyzeProgress(gateSeq, {
          stage_key: 'done',
          stage_label: '角色分析结束',
          failed: false,
        });
        persistPolicyProgressToAgent(agent);
        setSessionPolicyGateState(derived.gate, derived.reason, cacheLine);
        renderAgentSelectOptions(true);
        updateAgentMeta();
        applyGateState();
      } catch (err) {
        if (gateSeq !== state.sessionPolicyGateSeq) return;
        const text = safe(err && err.message).trim() || '角色与职责分析失败';
        setAgentPolicyAnalysisRecord(agent, {
          status: 'analyzed',
          analyzing: false,
          gate: 'policy_failed',
          reason: text,
          cacheLine: '',
          requires_manual: false,
        });
        finishPolicyAnalyzeProgress(gateSeq, {
          stage_key: 'done',
          stage_label: '角色分析结束（失败）',
          failed: true,
        });
        persistPolicyProgressToAgent(agent);
        setSessionPolicyGateState('policy_failed', text, '');
        renderAgentSelectOptions(true);
        updateAgentMeta();
        applyGateState();
      }
    }, analysisDelayMs);
  }

  function analystCandidates() {
    const out = [];
    const seen = new Set();
    for (const item of state.agents || []) {
      const name = safe(item.agent_name).trim();
      if (!/^Analyst/i.test(name)) continue;
      const key = name.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(name);
    }
    return out;
  }

  function selectedAnalyst() {
    return safe($('analystInput').value || $('batchAnalystInput').value).trim();
  }

  function refreshAnalystOptions(preferredValue) {
    const names = analystCandidates();
    const single = $('analystInput');
    const batch = $('batchAnalystInput');
    const currentSingle = safe(single.value).trim();
    const currentBatch = safe(batch.value).trim();
    let selected = safe(preferredValue).trim();
    if (!selected || !names.includes(selected)) {
      if (names.includes(currentSingle)) {
        selected = currentSingle;
      } else if (names.includes(currentBatch)) {
        selected = currentBatch;
      } else {
        selected = '';
      }
    }

    function fillSelect(node) {
      node.innerHTML = '';
      const first = document.createElement('option');
      first.value = '';
      first.textContent = names.length ? '(请选择分析师)' : '(无可用 Analyst*)';
      node.appendChild(first);
      for (const name of names) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        node.appendChild(opt);
      }
      node.value = selected && names.includes(selected) ? selected : '';
      node.disabled = names.length === 0;
    }

    fillSelect(single);
    fillSelect(batch);
    if (!batch.value && single.value) batch.value = single.value;
    if (!single.value && batch.value) single.value = batch.value;
  }

  function currentSession() {
