
      const reason = safe(dim.deduction_reason).trim();
      if (reason) {
        const reasonNode = document.createElement('div');
        reasonNode.className = 'policy-score-dim-reason';
        reasonNode.textContent = '原因：' + reason;
        box.appendChild(reasonNode);
      }

      const evidenceMap = Array.isArray(dim.evidence_map) ? dim.evidence_map : [];
      if (evidenceMap.length) {
        const list = document.createElement('ul');
        list.className = 'policy-score-evidence';
        let evidenceCount = 0;
        for (const ev of evidenceMap) {
          const li = document.createElement('li');
          const ref = safe((ev || {}).ref).trim() || 'unknown';
          const snippet = safe((ev || {}).snippet).trim();
          if (!snippet) continue;
          li.textContent = ref + ': ' + snippet;
          list.appendChild(li);
          evidenceCount += 1;
        }
        if (evidenceCount > 0) {
          box.appendChild(list);
        }
      }

      const repair = safe(dim.repair_suggestion).trim();
      if (repair) {
        const repairNode = document.createElement('div');
        repairNode.className = 'policy-score-repair';
        repairNode.textContent = '最小修复建议：' + repair;
        box.appendChild(repairNode);
      }
      scoreDimensions.appendChild(box);
    }
    if (!scoreDimensions.childElementCount) {
      const fallback = document.createElement('div');
      fallback.className = 'hint';
      fallback.textContent = '评分信息不足，需人工确认。';
      scoreDimensions.appendChild(fallback);
    }
    scoreModule.body.appendChild(scoreDimensions);
    summary.appendChild(scoreModule.section);

    if (analysisChainBody) {
      analysisChainBody.innerHTML = '';
      const chain = info.analysis_chain && typeof info.analysis_chain === 'object' ? info.analysis_chain : {};
      const chainSummary = [
        'source=' + (safe(chain.source) || safe(info.policy_extract_source) || '-'),
        'prompt_version=' + (safe(chain.prompt_version) || safe(info.policy_prompt_version) || '-'),
        'contract_status=' + (safe(chain.contract_status) || safe(info.policy_contract_status) || '-'),
        'workspace_root=' + (safe(chain.workspace_root) || '-'),
        'target_agents_path=' + (safe(chain.target_agents_path) || safe(info.agents_path) || '-'),
        'target_in_scope=' + (chain.target_in_scope ? 'yes' : 'no'),
        'workspace_root_valid=' + (chain.workspace_root_valid ? 'yes' : 'no'),
      ];
      if (safe(chain.workspace_root_error)) {
        chainSummary.push('workspace_root_error=' + safe(chain.workspace_root_error));
      }
      if (safe(chain.codex_exit_code)) {
        chainSummary.push('codex_exit_code=' + safe(chain.codex_exit_code));
      }
      if (safe(chain.command_summary)) {
        chainSummary.push('command=' + safe(chain.command_summary));
      }
      if (safe(chain.scope_hint)) {
        chainSummary.push('scope_hint=' + safe(chain.scope_hint));
      }
      if (Array.isArray(chain.contract_missing_fields) && chain.contract_missing_fields.length) {
        chainSummary.push('missing_fields=' + chain.contract_missing_fields.join(', '));
      }
      if (Array.isArray(chain.contract_issues) && chain.contract_issues.length) {
        chainSummary.push('contract_issues=' + chain.contract_issues.join(', '));
      }
      const summaryList = document.createElement('ul');
      summaryList.className = 'agent-policy-list';
      for (const item of chainSummary) {
        const li = document.createElement('li');
        li.textContent = safe(item);
        summaryList.appendChild(li);
      }
      analysisChainBody.appendChild(summaryList);

      const uiProgress = chain.ui_progress && typeof chain.ui_progress === 'object' ? chain.ui_progress : {};
      const uiTimeline = buildPolicyStageTimeline(uiProgress);
      const uiStages = Array.isArray(uiTimeline.stages) ? uiTimeline.stages : [];
      if (uiStages.length) {
        const pipelineTitle = document.createElement('div');
        pipelineTitle.className = 'hint';
        pipelineTitle.style.marginTop = '8px';
        pipelineTitle.textContent = '阶段流水线（与会话入口一致）：';
        analysisChainBody.appendChild(pipelineTitle);

        const pipeline = document.createElement('div');
        pipeline.className = 'policy-gate-stage-line';
        pipeline.style.marginTop = '6px';
        const lastIndex = uiStages.length - 1;
        const pipelineStatus = uiTimeline.active ? 'running' : uiTimeline.failed ? 'failed' : 'done';
        const pipelineTip = '状态: ' + pipelineStatus + '\n总耗时: ' + formatDurationMs(uiTimeline.total_ms);
        pipeline.title = pipelineTip;
        pipeline.setAttribute('aria-label', pipelineTip.replace(/\n/g, ' ; '));
        for (let i = 0; i < uiStages.length; i += 1) {
          const stage = uiStages[i] && typeof uiStages[i] === 'object' ? uiStages[i] : {};
          const label = safe(stage.label).trim() || policyAnalyzeStageLabel(stage.key);
          const shortLabel = safe(stage.short_label).trim() || policyStageShortLabel(stage.key);
          const stageStatus = safe(stage.status).trim().toLowerCase() || 'pending';
          const stageStatusText = policyStageStatusText(stageStatus);
          const isFailed = stageStatus === 'failed';
          const isRunning = stageStatus === 'running';
          const isPending = stageStatus === 'pending';
          const iconKind = isFailed ? 'failed' : isPending ? 'pending' : policyStageIconKind(stage.key);
          const icon = createStatusIcon(iconKind, {
            compact: true,
            spinning: isRunning,
          });
          const stageNode = document.createElement('span');
          stageNode.className = 'policy-gate-stage-node';
          if (i === 0) stageNode.classList.add('first');
          if (i === lastIndex) stageNode.classList.add('last');
          stageNode.setAttribute('tabindex', '0');
          if (isFailed) {
            stageNode.classList.add('failed');
          } else if (isRunning) {
            stageNode.classList.add('running');
          } else if (isPending) {
            stageNode.classList.add('pending');
          } else {
            stageNode.classList.add('done');
          }
          const anchor = document.createElement('span');
          anchor.className = 'policy-gate-stage-anchor';
          stageNode.appendChild(anchor);
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
                ? '等待上一阶段完成：' + (safe(uiStages[i - 1] && uiStages[i - 1].label).trim() || '前序阶段')
                : '等待启动分析'
              : '';
          const startedText = isPending ? '未开始' : formatClockMs(stage.started_at_ms);
          const durationText = isPending ? '-' : formatDurationMs(stage.duration_ms);
          const tip =
            '#' +
            String(i + 1) +
            ' ' +
            label +
            '\n说明: ' +
            safe(stage.detail).trim() +
            '\n图标: ' +
            iconKind +
            '\n状态: ' +
            stageStatusText +
            (pendingHint ? '\n进度提示: ' + pendingHint : '') +
            '\n开始: ' +
            startedText +
            '\n耗时: ' +
            durationText;
          stageNode.setAttribute('aria-label', tip.replace(/\n/g, ' ; '));
          const tooltip = document.createElement('div');
          tooltip.className = 'policy-gate-stage-tooltip';
          const title = document.createElement('div');
          title.className = 'policy-gate-stage-tooltip-title';
          title.textContent = label;
          tooltip.appendChild(title);
          const details = [
            '阶段 #' + String(i + 1),
            '状态: ' + stageStatusText,
            '说明: ' + safe(stage.detail).trim(),
            pendingHint ? '进度提示: ' + pendingHint : '',
            '开始: ' + startedText,
            '耗时: ' + durationText,
          ];
          for (const part of details) {
            if (!safe(part).trim()) continue;
            const row = document.createElement('div');
            row.className = 'policy-gate-stage-tooltip-line';
            row.textContent = part;
            tooltip.appendChild(row);
          }
          anchor.appendChild(tooltip);
          pipeline.appendChild(stageNode);
          if (i < lastIndex) {
            const arrowWrap = document.createElement('span');
            arrowWrap.className = 'policy-gate-stage-arrow';
            arrowWrap.appendChild(createFlowArrowIcon());
            pipeline.appendChild(arrowWrap);
          }
        }
        analysisChainBody.appendChild(pipeline);
        const detailTitle = document.createElement('div');
        detailTitle.className = 'hint';
        detailTitle.style.marginTop = '6px';
        detailTitle.textContent = '阶段明细：';
        analysisChainBody.appendChild(detailTitle);
        const detailList = document.createElement('ul');
        detailList.className = 'agent-policy-list';
        for (const stage of uiStages) {
          const li = document.createElement('li');
          const statusText = policyStageStatusText(stage.status);
          const isPending = safe(stage.status).trim().toLowerCase() === 'pending';
          const stageStartedText = isPending ? '未开始' : formatClockMs(stage.started_at_ms);
          const stageDurationText = isPending ? '-' : formatDurationMs(stage.duration_ms);
          li.textContent =
            '#' +
            safe(stage.index) +
            ' ' +
            safe(stage.label) +
            ' · 状态=' +
            statusText +
            ' · 开始=' +
            stageStartedText +
            ' · 耗时=' +
            stageDurationText +
            ' · 说明=' +
            safe(stage.detail);
          detailList.appendChild(li);
        }
        const totalLi = document.createElement('li');
        totalLi.textContent = '总耗时=' + formatDurationMs(uiTimeline.total_ms);
        detailList.appendChild(totalLi);
        analysisChainBody.appendChild(detailList);
      }

      const files = chain.files && typeof chain.files === 'object' ? chain.files : {};
      const fileItems = [
        ['trace_dir', files.trace_dir],
        ['prompt.txt', files.prompt],
        ['stdout.txt', files.stdout],
        ['stderr.txt', files.stderr],
        ['codex-result.raw.json', files.codex_result_raw || '(无)'],
        ['parsed-result.json', files.parsed_result],
        ['gate-decision.json', files.gate_decision],
      ];
      const fileTitle = document.createElement('div');
      fileTitle.className = 'hint';
      fileTitle.style.marginTop = '8px';
      fileTitle.textContent = '证据文件路径：';
      analysisChainBody.appendChild(fileTitle);
      const fileList = document.createElement('ul');
      fileList.className = 'agent-policy-list';
      for (const [label, value] of fileItems) {
        const li = document.createElement('li');
        li.textContent = safe(label) + ': ' + safe(value || '-');
        fileList.appendChild(li);
      }
      analysisChainBody.appendChild(fileList);

      const content = chain.content && typeof chain.content === 'object' ? chain.content : {};
      const appendContentBlock = (title, text) => {
        const block = document.createElement('pre');
        block.className = 'agent-policy-pre';
        block.textContent = safe(title) + '\n' + (safe(text) || '(无)');
        analysisChainBody.appendChild(block);
      };
      appendContentBlock('prompt.txt', content.prompt);
      appendContentBlock('stdout.txt', content.stdout);
      appendContentBlock('stderr.txt', content.stderr);
      if (safe(content.codex_result_raw)) {
        appendContentBlock('codex-result.raw.json', content.codex_result_raw);
      } else if (safe(files.codex_result_raw)) {
        appendContentBlock('codex-result.raw.json', '(文件已生成，内容为空)');
      }
      appendContentBlock('parsed-result.json', content.parsed_result);
      appendContentBlock('gate-decision.json', content.gate_decision);
    }
    if (analysisDetails) {
      analysisDetails.open = !!state.policyConfirmAnalysisOpen;
      analysisDetails.ontoggle = () => {
        state.policyConfirmAnalysisOpen = !!analysisDetails.open;
      };
    }

    if (gateBody) {
      gateBody.innerHTML = '';
      const gateSummaryItems = [
        '门禁=' + gateLabel,
        'parse_status=' + parseStatusText(info.parse_status),
        'clarity=' + safe(info.clarity_score) + '/100',
        'score_model=' + (safe(info.score_model) || 'v1'),
        'hash=' + short(info.agents_hash, 12),
        'path=' + safe(info.agents_path),
        '缓存=' +
          (info.policy_cache_hit ? '命中' : '重算') +
          (info.policy_cache_reason ? '（' + cacheReasonText(info.policy_cache_reason) + '）' : ''),
      ];
      if (safe(info.policy_extract_source)) {
        gateSummaryItems.push('source=' + safe(info.policy_extract_source));
      }
      if (safe(info.policy_prompt_version)) {
        gateSummaryItems.push('prompt_version=' + safe(info.policy_prompt_version));
      }
      if (safe(info.policy_contract_status)) {
        gateSummaryItems.push('contract_status=' + safe(info.policy_contract_status));
      }
      if (safe(info.clarity_gate_reason)) {
        gateSummaryItems.push('gate_reason=' + clarityGateReasonText(info.clarity_gate_reason));
      }
      const gateList = document.createElement('ul');
      gateList.className = 'agent-policy-list';
      for (const item of gateSummaryItems) {
        const li = document.createElement('li');
        li.textContent = safe(item);
        gateList.appendChild(li);
      }
      gateBody.appendChild(gateList);
      if (Array.isArray(info.parse_warnings) && info.parse_warnings.length) {
        const warnTitle = document.createElement('div');
        warnTitle.className = 'hint';
        warnTitle.style.marginTop = '8px';
        warnTitle.textContent = '解析告警：';
        gateBody.appendChild(warnTitle);
        const warnList = document.createElement('ul');
        warnList.className = 'agent-policy-list';
        for (const warn of info.parse_warnings) {
          const li = document.createElement('li');
          li.textContent = safe(warn);
          warnList.appendChild(li);
        }
        gateBody.appendChild(warnList);
      }
      if (Array.isArray(info.policy_cache_trace) && info.policy_cache_trace.length) {
        const flowTitle = document.createElement('div');
        flowTitle.className = 'hint';
        flowTitle.style.marginTop = '8px';
        flowTitle.textContent = '缓存生成过程：';
        gateBody.appendChild(flowTitle);
        const flowList = document.createElement('ul');
        flowList.className = 'agent-policy-list';
        for (const step of info.policy_cache_trace) {
          const li = document.createElement('li');
          li.textContent =
            cacheStepText(step.step) +
            ' · ' +
            cacheStepStatusText(step.status) +
            (step.detail ? ' · ' + safe(step.detail) : '');
          flowList.appendChild(li);
        }
        gateBody.appendChild(flowList);
      }
    }
    if (gateDetails) {
      gateDetails.open = !!state.policyConfirmGateOpen;
      gateDetails.ontoggle = () => {
        state.policyConfirmGateOpen = !!gateDetails.open;
      };
    }

    evidenceBody.innerHTML = '';
    const roleEvidence = document.createElement('pre');
    roleEvidence.className = 'agent-policy-pre';
    roleEvidence.textContent = '角色证据\n' + (info.evidence_snippets.role || '(无)');
    evidenceBody.appendChild(roleEvidence);
    const goalEvidence = document.createElement('pre');
    goalEvidence.className = 'agent-policy-pre';
    goalEvidence.textContent = '目标证据\n' + (info.evidence_snippets.goal || '(无)');
    evidenceBody.appendChild(goalEvidence);
    const dutyEvidence = document.createElement('pre');
    dutyEvidence.className = 'agent-policy-pre';
    dutyEvidence.textContent = '职责证据\n' + (info.evidence_snippets.duty || '(无)');
    evidenceBody.appendChild(dutyEvidence);
    if (evidenceDetails) {
      evidenceDetails.open = !!state.policyConfirmEvidenceOpen;
      evidenceDetails.ontoggle = () => {
        state.policyConfirmEvidenceOpen = !!evidenceDetails.open;
      };
    }

    const riskItems = [...info.risk_tips];
    if (info.parse_warnings.length) {
      for (const warn of info.parse_warnings) {
        if (!riskItems.includes(warn)) riskItems.push(warn);
      }
    }
    if (Array.isArray(info.constraints.issues)) {
      for (const issue of info.constraints.issues) {
        const text = safe((issue || {}).message).trim();
        if (text && !riskItems.includes(text)) riskItems.push(text);
      }
    }
    if (risk && 'open' in risk) {
      risk.open = state.policyConfirmRiskOpen !== false;
      risk.ontoggle = () => {
        state.policyConfirmRiskOpen = !!risk.open;
      };
    }
    const riskContainer = riskBody || risk;
    if (riskContainer) {
      riskContainer.innerHTML = '';
      if (!riskBody) {
        const title = document.createElement('div');
        title.className = 'card-title';
        title.textContent = '风险提示';
        riskContainer.appendChild(title);
      }
      if (riskItems.length) {
        const ul = document.createElement('ul');
        for (const item of riskItems) {
          const li = document.createElement('li');
          li.textContent = safe(item);
          ul.appendChild(li);
        }
        riskContainer.appendChild(ul);
      } else {
        const hint = document.createElement('div');
        hint.className = 'hint';
        hint.textContent = '无额外风险提示。';
        riskContainer.appendChild(hint);
      }
    }
    $('policyEditRole').value = safe(info.extracted_policy.role_profile);
    $('policyEditGoal').value = safe(info.extracted_policy.session_goal);
    $('policyEditDuty').value = dutyEditorText;
    if (state.pendingPolicyConfirmation && typeof state.pendingPolicyConfirmation === 'object') {
      state.pendingPolicyConfirmation.base_fingerprint = policyEditFingerprint();
      state.pendingPolicyConfirmation.recommend_trace = [];
    }
    $('policyConfirmReason').value = '';
    if (recommendPrompt) recommendPrompt.value = '';
    if (recommendTrace) {
      recommendTrace.open = !!state.policyRecommendTraceOpen;
      recommendTrace.ontoggle = () => {
        state.policyRecommendTraceOpen = !!recommendTrace.open;
      };
    }
    renderPolicyRecommendTrace();
    if (recommendMeta) {
      recommendMeta.textContent = canEdit ? '支持一句话生成或优化当前角色/职责草稿。' : '';
    }
    clearPolicyEditScorePreview(canEdit ? '可先编辑内容，再点击“重新评分并对比”。' : '');
    if (confirmBtn) {
      confirmBtn.disabled = !canConfirm;
      confirmBtn.title = canConfirm ? '' : '当前角色与职责结果不支持直接确认';
    }
    if (editBtn) {
      editBtn.disabled = !canEdit;
      editBtn.title = canEdit ? '' : '管理员未开启手动兜底，或当前门禁不允许编辑';
    }
    if (rescoreBtn) {
      rescoreBtn.disabled = !canEdit;
      rescoreBtn.title = canEdit ? '' : '仅在允许手动兜底时可重新评分';
    }
    if (cancelBtn) {
      cancelBtn.disabled = false;
      cancelBtn.title = '关闭当前弹窗，不创建会话';
    }
    if (editPanel) {
      editPanel.style.display = canEdit ? 'block' : 'none';
    }
    setPolicyConfirmError('');
    if (mask) {
      mask.classList.remove('hidden');
    }
  }

  function buildPolicyConfirmPayloadFromAgent(item) {
    const agent = item && typeof item === 'object' ? item : {};
    const baseAnalysisChain =
      agent.analysis_chain && typeof agent.analysis_chain === 'object'
        ? Object.assign({}, agent.analysis_chain)
        : {};
    const uiProgress = policyAnalyzeProgressSnapshot(safe(agent.agent_name));
    if (uiProgress) {
      baseAnalysisChain.ui_progress = uiProgress;
    } else if (!baseAnalysisChain.ui_progress) {
      const cachedProgress = getAgentPolicyProgressSnapshot(safe(agent.agent_name));
      if (cachedProgress) {
        baseAnalysisChain.ui_progress = cachedProgress;
      }
    }
    return {
      agent_name: safe(agent.agent_name),
      agents_hash: safe(agent.agents_hash),
      agents_version: safe(agent.agents_version),
      agents_path: safe(agent.agents_md_path),
      parse_status: safe(agent.parse_status || 'failed'),
      parse_warnings: Array.isArray(agent.parse_warnings) ? agent.parse_warnings : [],
      clarity_score: Number(agent.clarity_score || 0),
      clarity_details:
        agent.clarity_details && typeof agent.clarity_details === 'object'
          ? agent.clarity_details
          : {},
      score_model: safe(agent.score_model || ''),
      score_total: Number(agent.score_total || agent.clarity_score || 0),
      score_weights:
        agent.score_weights && typeof agent.score_weights === 'object'
          ? agent.score_weights
          : {},
      score_dimensions:
        agent.score_dimensions && typeof agent.score_dimensions === 'object'
          ? agent.score_dimensions
          : {},
      constraints:
        agent.constraints && typeof agent.constraints === 'object'
          ? agent.constraints
          : {
              must: [],
              must_not: [],
              preconditions: [],
              issues: [],
              conflicts: [],
              missing_evidence_count: 0,
              total: 0,
            },
      clarity_gate: safe(agent.clarity_gate || ''),
      risk_tips: Array.isArray(agent.risk_tips) ? agent.risk_tips : [],
      allow_manual_policy_input: !!state.allowManualPolicyInput,
      manual_fallback_allowed: !!state.allowManualPolicyInput,
      policy_cache_hit: !!agent.policy_cache_hit,
      policy_cache_status: safe(agent.policy_cache_status),
      policy_cache_reason: safe(agent.policy_cache_reason),
      policy_cache_cached_at: safe(agent.policy_cache_cached_at),
      policy_cache_trace: normalizeCacheTrace(agent.policy_cache_trace),
      clarity_gate_reason: safe(agent.clarity_gate_reason),
      policy_extract_source: safe(agent.policy_extract_source || ''),
      policy_prompt_version: safe(agent.policy_prompt_version || ''),
      policy_contract_status: safe(agent.policy_contract_status || ''),
      policy_contract_missing_fields: Array.isArray(agent.policy_contract_missing_fields)
        ? agent.policy_contract_missing_fields
        : [],
      policy_contract_issues: Array.isArray(agent.policy_contract_issues) ? agent.policy_contract_issues : [],
      extracted_policy: {
        role_profile: safe(agent.role_profile),
        session_goal: safe(agent.session_goal),
        duty_constraints: normalizeAgentTextItems(agent.duty_constraints, agent.duty_constraints_text || ''),
      },
      evidence_snippets: agent.evidence_snippets && typeof agent.evidence_snippets === 'object'
        ? agent.evidence_snippets
        : {},
      analysis_chain: baseAnalysisChain,
      policy_error: safe(agent.policy_error),
      codex_failure: normalizeCodexFailure(agent.codex_failure),
    };
  }

  function openPolicyConfirmForSelectedAgent() {
    const item = selectedAgentItem();
    if (!item) {
      throw new Error('请先选择 agent');
    }
    if (safe(state.sessionPolicyGateState || '').trim().toLowerCase() === 'policy_cache_missing') {
      throw new Error('当前角色缓存为空，请先点击“生成缓存”图标。');
    }
    const payload = buildPolicyConfirmPayloadFromAgent(item);
    const request = {
      agent_name: safe(item.agent_name),
      focus: 'Workflow baseline: web workbench + real-agent gate execution',
      agent_search_root: safe($('agentSearchRoot').value).trim(),
      is_test_data: false,
    };
    openPolicyConfirmModal(payload, request);
    setStatus('角色与职责确认/兜底弹窗已打开');
  }

  function markLocalAgentCacheCleared(agentName) {
    const name = safe(agentName).trim();
    if (!name) return;
    delete state.agentPolicyProgressByName[name];
    for (const item of state.agents || []) {
      if (safe(item && item.agent_name).trim() !== name) continue;
      item.policy_cache_hit = false;
      item.policy_cache_status = 'cleared';
      item.policy_cache_reason = 'manual_clear';
      item.policy_cache_cached_at = '';
      item.policy_cache_trace = [];
      if (item.analysis_chain && typeof item.analysis_chain === 'object') {
        item.analysis_chain = Object.assign({}, item.analysis_chain, {
          ui_progress: {},
        });
      }
      break;
    }
  }

  async function clearPolicyCache(scopeMode) {
    const mode = safe(scopeMode || 'selected').trim().toLowerCase() === 'all' ? 'all' : 'selected';
    const agent = selectedAgent();
    if (mode === 'selected' && !agent) {
      throw new Error('请先选择 agent');
    }
    const tip =
      mode === 'all'
        ? '将清理所有角色缓存。清理后需手动点击“生成缓存”图标进行分析。是否继续？'
        : '将清理当前角色缓存。清理后需手动点击“生成缓存”图标进行分析。是否继续？';
    if (!window.confirm(tip)) return false;
    const req = {
      scope: mode,
      agent_name: mode === 'all' ? '' : agent,
    };
    const data = await postJSON('/api/policy/cache/clear', req);
    resetPolicyAnalyzeProgress();
    state.sessionPolicyCacheLine = '';
    if (mode === 'all') {
      for (const item of state.agents || []) {
        const name = safe(item && item.agent_name).trim();
        if (!name) continue;
        markLocalAgentCacheCleared(name);
        setAgentPolicyAnalysisRecord(name, {
          status: 'unanalyzed',
          analyzing: false,
          gate: '',
          reason: '',
          cacheLine: '',
          requires_manual: true,
        });
      }
    } else if (agent) {
      markLocalAgentCacheCleared(agent);
      setAgentPolicyAnalysisRecord(agent, {
        status: 'unanalyzed',
        analyzing: false,
        gate: '',
        reason: '',
        cacheLine: '',
        requires_manual: true,
      });
    }
    if (selectedAgent()) {
      setSessionPolicyGateState('policy_cache_missing', '当前角色缓存已清理，请点击“生成缓存”图标后继续。', '');
    } else {
      setSessionPolicyGateState('idle_unselected', '请先选择 agent', '');
    }
    renderAgentSelectOptions(true);
    updateAgentMeta();
    applyGateState();
    await refreshDashboard();
    const deleted = Number(data.deleted_count || 0);
    setStatus(
      (mode === 'all' ? '全部角色缓存已清理' : '当前角色缓存已清理') +
        '，删除 ' +
        safe(deleted) +
        ' 条记录。请手动点击“生成缓存”图标重新分析。',
    );
    return true;
  }

  function regenerateSelectedPolicyCache() {
    const agent = selectedAgent();
    if (!agent) {
      throw new Error('请先选择 agent');
    }
    setStatus('正在生成当前角色缓存...');
    setAgentPolicyAnalysisRecord(agent, {
      status: 'unanalyzed',
      analyzing: false,
      gate: '',
      reason: '',
      cacheLine: '',
      requires_manual: false,
    });
    startPolicyAnalysisForSelection();
  }

  async function recommendPolicyDraft() {
    const pending = state.pendingPolicyConfirmation;
    if (!pending || !pending.payload) {
      throw new Error('请先打开角色与职责确认/兜底弹窗');
    }
    const instruction = safe($('policyRecommendPrompt').value).trim();
    const beforeDraft = policyEditorDraftSnapshot();
    const validation = validatePolicyRecommendInstruction(instruction);
    if (!validation.ok) {
      const meta = $('policyRecommendMeta');
      if (meta) {
        meta.textContent = '输入校验未通过: ' + safe(validation.message);
      }
      pushPolicyRecommendTrace({
        at_ms: Date.now(),
        status: 'blocked',
        instruction: instruction,
        reason: validation.message,
        source: 'local_validation',
        warnings: [],
        before: beforeDraft,
        after: beforeDraft,
      });
      window.alert(validation.message);
      throw new Error(validation.message);
    }
    const req = {
      agent_name: safe((pending.payload || {}).agent_name),
      instruction: instruction,
      role_profile: safe($('policyEditRole').value).trim(),
      session_goal: safe($('policyEditGoal').value).trim(),
      duty_constraints: safe($('policyEditDuty').value).trim(),
    };
    let data = null;
    try {
      data = await postJSON('/api/policy/recommend', req);
    } catch (err) {
      const message = safe(err && err.message).trim() || '优化失败';
      pushPolicyRecommendTrace({
        at_ms: Date.now(),
        status: 'failed',
        instruction: instruction,
        reason: message,
        source: 'api_error',
        warnings: [],
        before: beforeDraft,
        after: beforeDraft,
      });
      if (safe(err && err.code).trim() === 'policy_recommend_instruction_invalid') {
        window.alert(message);
      }
      throw err;
    }
    const rec = data.recommendation && typeof data.recommendation === 'object' ? data.recommendation : {};
    const dutyItems = normalizeAgentTextItems(rec.duty_constraints, rec.duty_constraints_text || '');
    const dutyEditorText = buildDutyEditorTextFromConstraints(rec.constraints, dutyItems);
    const afterDraft = {
      role_profile: safe(rec.role_profile).trim(),
      session_goal: safe(rec.session_goal).trim(),
      duty_constraints_text: dutyEditorText,
      duty_constraints: normalizeDutyEditorItems(dutyEditorText),
    };
    const beforeSignature = policyDraftComparableSignature(beforeDraft);
    const afterSignature = policyDraftComparableSignature(afterDraft);
    const warnings = Array.isArray(data.warnings) ? data.warnings.map((item) => safe(item)).filter((item) => !!item) : [];
    const sourceText = safe(data.source || '-');
    if (!afterSignature || beforeSignature === afterSignature) {
      const msg = '未得到有效优化结果，请补充更具体的一句话需求（目标/边界/场景）。';
      pushPolicyRecommendTrace({
        at_ms: Date.now(),
        status: 'no_change',
        instruction: instruction,
        reason: msg,
        source: sourceText,
        warnings: warnings,
        before: beforeDraft,
        after: afterDraft,
      });
      window.alert(msg);
      throw new Error(msg);
    }
    $('policyEditRole').value = safe(rec.role_profile).trim();
    $('policyEditGoal').value = safe(rec.session_goal).trim();
    $('policyEditDuty').value = dutyEditorText;
    clearPolicyEditScorePreview('已应用推荐草稿，请点击“重新评分并对比”。');
    const meta = $('policyRecommendMeta');
    if (meta) {
      meta.textContent =
        '推荐来源: ' +
        sourceText +
        (warnings.length ? ' · 提示: ' + warnings.join('；') : '');
    }
    pushPolicyRecommendTrace({
      at_ms: Date.now(),
      status: 'applied',
      instruction: instruction,
      reason: '',
      source: sourceText,
      warnings: warnings,
      before: beforeDraft,
      after: afterDraft,
    });
  }

  async function submitPolicyConfirmation(action) {
    const pending = state.pendingPolicyConfirmation;
    if (!pending) return null;
    const act = safe(action).toLowerCase();
    if (!['confirm', 'edit'].includes(act)) {
      throw new Error('无效确认动作');
    }
    const req = Object.assign({}, pending.request || {}, {
      action: act,
      operator: 'web-user',
      reason: safe($('policyConfirmReason').value).trim(),
    });
    if (act === 'edit') {
      req.role_profile = safe($('policyEditRole').value).trim();
      req.session_goal = safe($('policyEditGoal').value).trim();
      req.duty_constraints = safe($('policyEditDuty').value).trim();
    }
    const data = await postJSON('/api/sessions/policy-confirm', req);
    if (data.terminated) {
      closePolicyConfirmModal();
      setStatus('已取消角色与职责确认/兜底');
      return null;
    }
    const session = ensureSessionEntry(data);
    if (!session) throw new Error('会话创建失败');
    state.selectedSessionId = safe(session.session_id);
    moveSessionToTop(state.selectedSessionId);
    localStorage.setItem(sessionCacheKey, state.selectedSessionId);
    localStorage.setItem(agentCacheKey, safe(session.agent_name));
    appendSessionMessage(
      state.selectedSessionId,
      'system',
      '[角色与职责确认] action=' +
        safe(data.action || act) +
        ' audit_id=' +
        safe(data.audit_id || '-') +
        ' patch_task=' +
        safe(data.patch_task_id || '-'),
    );
    await loadSessionMessages(state.selectedSessionId);
    renderSessionList();
    closePolicyConfirmModal();
    if (safe(session.agent_name) === selectedAgent()) {
      const gateReason = act === 'edit' ? '角色与职责已手动兜底确认，可创建会话。' : '角色与职责已确认，可创建会话。';
      setSessionPolicyGateState('policy_confirmed', gateReason, state.sessionPolicyCacheLine);
      updateAgentMeta();
      applyGateState();
    }
    return session;
  }
