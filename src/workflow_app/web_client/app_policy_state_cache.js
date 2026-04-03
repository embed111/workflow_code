  function syncAgentPolicyAnalysisCache(options) {
    const opts = options && typeof options === 'object' ? options : {};
    const resetAll = !!opts.resetAll;
    const next = {};
    for (const item of state.agents || []) {
      const key = normalizeAgentNameKey(item && item.agent_name);
      if (!key) continue;
      const fromItem = buildAgentAnalysisRecordFromItem(item);
      const existing = state.agentPolicyAnalysisByName[key];
      if (resetAll || !existing || typeof existing !== 'object') {
        next[key] = fromItem;
        continue;
      }
      // Item-derived stale/cleared state has higher priority and must invalidate local cache.
      if (fromItem.requires_manual || safe(fromItem.status).trim().toLowerCase() !== 'analyzed') {
        next[key] = fromItem;
        continue;
      }
      // Keep local "analyzing" status while async analyze call is in flight.
      if (existing.analyzing) {
        next[key] = Object.assign({}, existing);
        continue;
      }
      // If local record is not analyzed but server has analyzed state, promote to server-derived state.
      if (safe(existing.status).trim().toLowerCase() !== 'analyzed') {
        next[key] = fromItem;
        continue;
      }
      // Preserve local analyzed state (e.g. policy_confirmed) when server item is also analyzed.
      next[key] = Object.assign({}, existing);
    }
    state.agentPolicyAnalysisByName = next;
  }

  function getAgentPolicyAnalysisRecord(agentName) {
    const key = normalizeAgentNameKey(agentName);
    if (!key) return defaultAgentPolicyAnalysisRecord();
    const existing = state.agentPolicyAnalysisByName[key];
    if (existing && typeof existing === 'object') return existing;
    const created = defaultAgentPolicyAnalysisRecord();
    state.agentPolicyAnalysisByName[key] = created;
    return created;
  }

  function setAgentPolicyAnalysisRecord(agentName, patch) {
    const key = normalizeAgentNameKey(agentName);
    if (!key) return;
    const next = Object.assign({}, getAgentPolicyAnalysisRecord(key), patch || {});
    state.agentPolicyAnalysisByName[key] = next;
  }

  function isPolicyAnalysisCompletedGate(gateValue) {
    const gate = safe(gateValue).trim().toLowerCase();
    return (
      gate === 'policy_ready' ||
      gate === 'policy_confirmed' ||
      gate === 'policy_needs_confirm' ||
      gate === 'policy_failed'
    );
  }

  function resolveAgentPolicyGateInfo(agentName) {
    const name = safe(agentName).trim();
    if (!name) {
      return {
        agent_name: '',
        gate: 'idle_unselected',
        analysis_completed: false,
        reason: '会话未绑定有效 agent，禁止发送新对话内容。',
      };
    }
    const item = state.agents.find((node) => safe(node && node.agent_name).trim() === name) || null;
    if (item) {
      const cacheStatus = safe(item.policy_cache_status).trim().toLowerCase();
      const reasonCodes = parsePolicyCacheReasonCodes(item.policy_cache_reason);
      if (cacheStatus === 'cleared' || reasonCodes.includes('manual_clear')) {
        return {
          agent_name: name,
          gate: 'policy_cache_missing',
          analysis_completed: false,
          reason: '会话 agent 角色缓存为空，请先生成缓存并完成分析。',
        };
      }
      if (isAgentPolicyReanalyzeRequired(cacheStatus, reasonCodes)) {
        const staleByAgents =
          reasonCodes.includes('agents_hash_mismatch') ||
          reasonCodes.includes('cached_before_agents_mtime');
        return {
          agent_name: name,
          gate: 'policy_cache_stale',
          analysis_completed: false,
          reason: staleByAgents
            ? '检测到 AGENTS.md 已更新，需重新分析后才能对话。请点击“生成缓存”。'
            : '角色缓存已过期或无效，需重新分析后才能对话。请点击“生成缓存”。',
        };
      }
    }
    const record = getAgentPolicyAnalysisRecord(name);
    if (record && record.requires_manual) {
      return {
        agent_name: name,
        gate: 'policy_cache_missing',
        analysis_completed: false,
        reason: '会话 agent 角色缓存为空，请先生成缓存并完成分析。',
      };
    }
    if (record && record.analyzing) {
      return {
        agent_name: name,
        gate: 'analyzing_policy',
        analysis_completed: false,
        reason: '会话 agent 角色分析中，请稍候。',
      };
    }
    if (record && safe(record.status).trim().toLowerCase() === 'analyzed') {
      const gate = safe(record.gate).trim().toLowerCase() || 'policy_failed';
      return {
        agent_name: name,
        gate: gate,
        analysis_completed: isPolicyAnalysisCompletedGate(gate),
        reason: safe(record.reason).trim() || '会话 agent 角色分析已完成。',
      };
    }
    if (item && hasPolicyGateFields(item)) {
      const derived = derivePolicyGateFromAgent(item);
      const gate = safe(derived.gate).trim().toLowerCase() || 'policy_failed';
      return {
        agent_name: name,
        gate: gate,
        analysis_completed: isPolicyAnalysisCompletedGate(gate),
        reason: safe(derived.reason).trim() || '会话 agent 角色分析已完成。',
      };
    }
    return {
      agent_name: name,
      gate: 'idle_unselected',
      analysis_completed: false,
      reason: '会话 agent 角色尚未完成分析，请先完成分析后再发送。',
    };
  }

  function resolveSessionPolicyGateInfo(session) {
    const node = session && typeof session === 'object' ? session : {};
    const info = resolveAgentPolicyGateInfo(node.agent_name);
    const sessionHash = safe(node.agents_hash).trim();
    const item = state.agents.find((it) => safe(it && it.agent_name).trim() === safe(node.agent_name).trim()) || null;
    const latestHash = safe(item && item.agents_hash).trim();
    if (!info.analysis_completed && safe(info.gate).trim().toLowerCase() === 'policy_cache_stale') {
      if (sessionHash && latestHash && sessionHash !== latestHash) {
        return Object.assign({}, info, {
          reason:
            safe(info.reason).trim() +
            ' 当前会话hash=' +
            short(sessionHash, 12) +
            '，最新hash=' +
            short(latestHash, 12) +
            '。',
        });
      }
    }
    return info;
  }

  function trySelectAgentFromSessionIfMissing(session) {
    const node = session && typeof session === 'object' ? session : {};
    const sessionAgent = safe(node.agent_name).trim();
    if (!sessionAgent) return false;
    if (selectedAgent()) return false;
    const selectNode = $('agentSelect');
    if (!selectNode) return false;
    const optionValues = Array.from(selectNode.options || []).map((opt) => safe(opt && opt.value).trim());
    if (!optionValues.includes(sessionAgent)) return false;
    selectNode.value = sessionAgent;
    localStorage.setItem(agentCacheKey, sessionAgent);
    renderAgentSelectOptions(true);
    startPolicyAnalysisForSelection();
    return true;
  }

  function setAgentPolicyProgressSnapshot(agentName, rawSnapshot) {
    const key = normalizeAgentNameKey(agentName);
    if (!key) return;
    const normalized = normalizePolicyAnalyzeProgress(
      rawSnapshot && typeof rawSnapshot === 'object' ? rawSnapshot : {}
    );
    if (!Array.isArray(normalized.stages) || !normalized.stages.length) {
      delete state.agentPolicyProgressByName[key];
      return;
    }
    state.agentPolicyProgressByName[key] = normalized;
  }

  function getAgentPolicyProgressSnapshot(agentName) {
    const key = normalizeAgentNameKey(agentName);
    if (!key) return null;
    const snapshot = state.agentPolicyProgressByName[key];
    if (!snapshot || typeof snapshot !== 'object') return null;
    const normalized = normalizePolicyAnalyzeProgress(snapshot);
    if (!Array.isArray(normalized.stages) || !normalized.stages.length) return null;
    return normalized;
  }

  function persistPolicyProgressToAgent(agentName) {
    const name = safe(agentName).trim();
    if (!name) return;
    const snapshot = policyAnalyzeProgressSnapshot(name);
    if (!snapshot || !Array.isArray(snapshot.stages) || !snapshot.stages.length) return;
    setAgentPolicyProgressSnapshot(name, snapshot);
    const idx = state.agents.findIndex((item) => safe(item && item.agent_name).trim() === name);
    if (idx < 0) return;
    const current = state.agents[idx] && typeof state.agents[idx] === 'object' ? state.agents[idx] : {};
    const chain =
      current.analysis_chain && typeof current.analysis_chain === 'object'
        ? Object.assign({}, current.analysis_chain)
        : {};
    chain.ui_progress = snapshot;
    state.agents[idx] = Object.assign({}, current, { analysis_chain: chain });
  }

  function agentStatusInfoByRecord(record) {
    const rec = record && typeof record === 'object' ? record : defaultAgentPolicyAnalysisRecord();
    if (rec.status !== 'analyzed') {
      if (rec.requires_manual) {
        return {
          code: 'manual',
          text: '未分析',
          icon: 'cache',
          spinning: false,
          chipClass: 'pending',
        };
      }
      return {
        code: 'unanalyzed',
        text: rec.analyzing ? '未分析（分析中）' : '未分析',
        icon: 'pending',
        spinning: !!rec.analyzing,
        chipClass: 'pending',
      };
    }
    const gate = safe(rec.gate).toLowerCase();
    if (gate === 'policy_ready' || gate === 'policy_confirmed') {
      return {
        code: 'ready',
        text: '可创建',
        icon: 'success',
        spinning: false,
        chipClass: 'done',
      };
    }
    if (gate === 'policy_needs_confirm') {
      return {
        code: 'confirm',
        text: '需确认',
        icon: 'sent',
        spinning: false,
        chipClass: 'pending',
      };
    }
    return {
      code: 'blocked',
      text: '已阻断',
      icon: 'failed',
      spinning: false,
      chipClass: 'blocked',
    };
  }

  function agentStatusInfo(item) {
    const name = safe(item && item.agent_name).trim();
    return agentStatusInfoByRecord(getAgentPolicyAnalysisRecord(name));
  }

  function resetAgentDropdownPanelPosition() {
    const panel = $('agentSelectPanel');
    const options = $('agentSelectOptions');
    state.agentDropdownPanelWidth = 0;
    if (panel) {
      panel.style.position = '';
      panel.style.left = '';
      panel.style.top = '';
      panel.style.right = '';
      panel.style.bottom = '';
      panel.style.width = '';
      panel.style.maxHeight = '';
    }
    if (options) {
      options.style.maxHeight = '';
    }
  }

  function positionAgentDropdownPanel() {
    if (!state.agentDropdownOpen) return;
    const panel = $('agentSelectPanel');
    const trigger = $('agentSelectTrigger');
    const options = $('agentSelectOptions');
    if (!panel || !trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewportW = Math.max(0, Number(window.innerWidth || 0));
    const viewportH = Math.max(0, Number(window.innerHeight || 0));
    if (viewportW <= 0 || viewportH <= 0) return;
    const margin = 8;
    const gap = 6;
    const triggerWidth = Math.max(0, Math.floor(rect.width));
    const baseWidth = Math.max(1, Number(state.agentDropdownPanelWidth || triggerWidth));
    const width = Math.max(1, Math.min(baseWidth, viewportW - margin * 2));
    const maxLeft = Math.max(margin, viewportW - width - margin);
    const left = Math.min(Math.max(Math.floor(rect.left), margin), maxLeft);
    const spaceBelow = viewportH - rect.bottom - gap - margin;
    const spaceAbove = rect.top - gap - margin;
    const shouldOpenUp = spaceBelow < 180 && spaceAbove > spaceBelow;
    const panelMaxHeight = Math.max(140, Math.min(320, Math.floor(shouldOpenUp ? spaceAbove : spaceBelow)));
    const preferredOptionsMaxHeight = 34 * 5 + 4 * 4;
    const optionsMaxHeight = Math.max(64, Math.min(preferredOptionsMaxHeight, panelMaxHeight - 46));

    panel.style.position = 'fixed';
    panel.style.left = String(left) + 'px';
    panel.style.right = 'auto';
    panel.style.width = String(width) + 'px';
    panel.style.maxHeight = String(panelMaxHeight) + 'px';
    if (shouldOpenUp) {
      panel.style.top = 'auto';
      panel.style.bottom = String(Math.max(margin, Math.floor(viewportH - rect.top + gap))) + 'px';
    } else {
      panel.style.bottom = 'auto';
      panel.style.top = String(Math.max(margin, Math.floor(rect.bottom + gap))) + 'px';
    }
    if (options) {
      options.style.maxHeight = String(optionsMaxHeight) + 'px';
    }
  }

  function handleAgentDropdownViewportChange() {
    if (!state.agentDropdownOpen) return;
    positionAgentDropdownPanel();
  }

  function setAgentDropdownOpen(nextOpen) {
    const host = $('agentDropdown');
    const trigger = $('agentSelectTrigger');
    const panel = $('agentSelectPanel');
    const canOpen = !!host && !!trigger && !!panel && !trigger.disabled;
    const wasOpen = !!state.agentDropdownOpen;
    const open = !!nextOpen && canOpen;
    state.agentDropdownOpen = open;
    if (host) {
      host.classList.toggle('open', open);
    }
    if (trigger) {
      trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    const search = $('agentSelectSearch');
    if (search) {
      search.disabled = !open;
      if (!open && wasOpen) {
        search.value = '';
      }
      if (open && !wasOpen) {
        window.setTimeout(() => {
          try {
            search.focus();
          } catch (_) {
            // ignore focus errors
          }
        }, 0);
      }
    }
    if (open) {
      if (!wasOpen && trigger) {
        state.agentDropdownPanelWidth = Math.max(1, Math.floor(trigger.getBoundingClientRect().width));
      }
      positionAgentDropdownPanel();
    } else {
      resetAgentDropdownPanelPosition();
    }
  }
