  function policyRecommendStatusText(status) {
    const key = safe(status).trim().toLowerCase();
    if (key === 'applied') return '已应用';
    if (key === 'no_change') return '无有效变化';
    if (key === 'blocked') return '输入不通过';
    if (key === 'failed') return '调用失败';
    return key || '-';
  }

  function formatPolicyDraftSnapshotText(draft) {
    const node = draft && typeof draft === 'object' ? draft : {};
    const role = safe(node.role_profile).trim() || '(空)';
    const goal = safe(node.session_goal).trim() || '(空)';
    const dutyItems = Array.isArray(node.duty_constraints)
      ? node.duty_constraints
      : normalizeDutyEditorItems(node.duty_constraints_text || '');
    const dutyText = dutyItems.length ? dutyItems.map((item) => '- ' + safe(item)).join('\n') : '(空)';
    return ['角色', role, '', '目标', goal, '', '职责边界', dutyText].join('\n');
  }

  function renderPolicyRecommendTrace() {
    const details = $('policyRecommendTrace');
    const body = $('policyRecommendTraceBody');
    if (!details || !body) return;
    details.open = !!state.policyRecommendTraceOpen;
    details.ontoggle = () => {
      state.policyRecommendTraceOpen = !!details.open;
    };
    body.innerHTML = '';
    const pending = state.pendingPolicyConfirmation;
    const traces =
      pending && Array.isArray(pending.recommend_trace) ? pending.recommend_trace.filter((item) => item && typeof item === 'object') : [];
    if (!traces.length) {
      const hint = document.createElement('div');
      hint.className = 'hint';
      hint.textContent = '暂无优化记录。';
      body.appendChild(hint);
      return;
    }
    const list = document.createElement('div');
    list.className = 'policy-recommend-trace-list';
    for (let i = traces.length - 1; i >= 0; i -= 1) {
      const item = traces[i] || {};
      const statusKey = safe(item.status || '').trim().toLowerCase() || 'applied';
      const card = document.createElement('section');
      card.className = 'policy-recommend-trace-item';
      const head = document.createElement('div');
      head.className = 'policy-recommend-trace-head';
      const status = document.createElement('div');
      status.className = 'policy-recommend-trace-status ' + statusKey;
      status.textContent = policyRecommendStatusText(statusKey);
      head.appendChild(status);
      const meta = document.createElement('div');
      meta.className = 'policy-recommend-trace-meta';
      const source = safe(item.source).trim() || '-';
      const atMs = Number(item.at_ms || 0);
      const when = Number.isFinite(atMs) && atMs > 0 ? formatDateTime(new Date(atMs).toISOString()) : '-';
      meta.textContent = 'time=' + when + ' · source=' + source;
      head.appendChild(meta);
      card.appendChild(head);

      const warnList = Array.isArray(item.warnings) ? item.warnings.map((v) => safe(v).trim()).filter((v) => !!v) : [];
      const reason = safe(item.reason || '').trim();
      if (reason || warnList.length) {
        const tip = document.createElement('div');
        tip.className = 'policy-recommend-trace-meta';
        tip.style.marginTop = '4px';
        tip.textContent = reason ? reason + (warnList.length ? ' · ' : '') + (warnList.length ? warnList.join('；') : '') : warnList.join('；');
        card.appendChild(tip);
      }

      const instructionBlock = document.createElement('pre');
      instructionBlock.className = 'policy-recommend-trace-block';
      instructionBlock.textContent = '一句话输入\n' + (safe(item.instruction).trim() || '(空)');
      card.appendChild(instructionBlock);

      const beforeBlock = document.createElement('pre');
      beforeBlock.className = 'policy-recommend-trace-block';
      beforeBlock.textContent = '优化前草稿\n' + formatPolicyDraftSnapshotText(item.before);
      card.appendChild(beforeBlock);

      const afterBlock = document.createElement('pre');
      afterBlock.className = 'policy-recommend-trace-block';
      afterBlock.textContent = '优化后草稿\n' + formatPolicyDraftSnapshotText(item.after);
      card.appendChild(afterBlock);

      list.appendChild(card);
    }
    body.appendChild(list);
  }

  function pushPolicyRecommendTrace(entry) {
    const pending = state.pendingPolicyConfirmation;
    if (!pending || typeof pending !== 'object') return;
    if (!Array.isArray(pending.recommend_trace)) {
      pending.recommend_trace = [];
    }
    pending.recommend_trace.push(entry && typeof entry === 'object' ? entry : {});
    if (pending.recommend_trace.length > 20) {
      pending.recommend_trace.splice(0, pending.recommend_trace.length - 20);
    }
    renderPolicyRecommendTrace();
  }

  function clearPolicyEditScorePreview(metaText) {
    const box = $('policyEditScorePreview');
    if (box) {
      box.innerHTML = '';
      box.classList.add('hidden');
    }
    if (metaText !== undefined) {
      setPolicyRescoreMeta(metaText);
    }
    if (state.pendingPolicyConfirmation && typeof state.pendingPolicyConfirmation === 'object') {
      state.pendingPolicyConfirmation.rescore_preview = null;
      state.pendingPolicyConfirmation.rescore_fingerprint = '';
    }
  }

  function formatSignedScoreDelta(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) return '0';
    const rounded = Math.round(num);
    if (rounded > 0) return '+' + safe(rounded);
    return safe(rounded);
  }

  function normalizePolicyRescorePreview(raw) {
    const node = raw && typeof raw === 'object' ? raw : {};
    const normalizeBlock = (value) => {
      const src = value && typeof value === 'object' ? value : {};
      const scoreWeights = normalizeScoreWeights(src.score_weights);
      const scoreDimensions = normalizeScoreDimensions(src.score_dimensions, scoreWeights);
      return {
        parse_status: safe(src.parse_status || 'failed').trim().toLowerCase(),
        clarity_gate: safe(src.clarity_gate || 'block').trim().toLowerCase(),
        clarity_gate_reason: safe(src.clarity_gate_reason || '').trim(),
        score_model: safe(src.score_model || 'v2').trim() || 'v2',
        score_total: Math.max(0, Math.min(100, Number(src.score_total || src.clarity_score || 0))),
        score_weights: scoreWeights,
        score_dimensions: scoreDimensions,
        risk_tips: Array.isArray(src.risk_tips)
          ? src.risk_tips.map((item) => safe(item).trim()).filter((item) => !!item)
          : [],
      };
    };
    const before = normalizeBlock(node.before);
    const after = normalizeBlock(node.after);
    const diffRaw = node.diff && typeof node.diff === 'object' ? node.diff : {};
    const beforeTotal = Math.round(before.score_total);
    const afterTotal = Math.round(after.score_total);
    const scoreDelta = Number.isFinite(Number(diffRaw.score_total_delta))
      ? Number(diffRaw.score_total_delta)
      : afterTotal - beforeTotal;
    const dimRowsRaw = Array.isArray(diffRaw.dimensions) ? diffRaw.dimensions : [];
    const dimRows = [];
    if (dimRowsRaw.length) {
      for (const row of dimRowsRaw) {
        const key = safe((row || {}).key).trim().toLowerCase();
        const beforeScore = Math.max(0, Math.min(100, Number((row || {}).before_score || 0)));
        const afterScore = Math.max(0, Math.min(100, Number((row || {}).after_score || 0)));
        const label =
          safe((row || {}).label).trim() ||
          safe((after.score_dimensions.items[key] || {}).label).trim() ||
          safe((before.score_dimensions.items[key] || {}).label).trim() ||
          key ||
          '-';
        dimRows.push({
          key: key,
          label: label,
          before_score: beforeScore,
          after_score: afterScore,
          delta: Number.isFinite(Number((row || {}).delta)) ? Number((row || {}).delta) : afterScore - beforeScore,
        });
      }
    } else {
      for (const key of after.score_dimensions.order) {
        const beforeDim = before.score_dimensions.items[key] || {};
        const afterDim = after.score_dimensions.items[key] || {};
        const beforeScore = Math.max(0, Math.min(100, Number(beforeDim.score || 0)));
        const afterScore = Math.max(0, Math.min(100, Number(afterDim.score || 0)));
        dimRows.push({
          key: key,
          label: safe(afterDim.label || beforeDim.label || key),
          before_score: beforeScore,
          after_score: afterScore,
          delta: afterScore - beforeScore,
        });
      }
    }
    return {
      before: before,
      after: after,
      diff: {
        score_total_before: beforeTotal,
        score_total_after: afterTotal,
        score_total_delta: scoreDelta,
        unchanged_input: diffRaw.unchanged_input === true || node.unchanged_input === true,
        clarity_gate_before: safe(diffRaw.clarity_gate_before || before.clarity_gate).trim().toLowerCase(),
        clarity_gate_after: safe(diffRaw.clarity_gate_after || after.clarity_gate).trim().toLowerCase(),
        clarity_gate_changed:
          diffRaw.clarity_gate_changed === true ||
          safe(diffRaw.clarity_gate_before || before.clarity_gate).trim().toLowerCase() !==
            safe(diffRaw.clarity_gate_after || after.clarity_gate).trim().toLowerCase(),
        dimensions: dimRows,
      },
    };
  }

  function renderPolicyEditScorePreview(preview) {
    const box = $('policyEditScorePreview');
    if (!box) return;
    const node = preview && typeof preview === 'object' ? preview : null;
    if (!node) {
      box.innerHTML = '';
      box.classList.add('hidden');
      return;
    }
    const diff = node.diff && typeof node.diff === 'object' ? node.diff : {};
    const rows = Array.isArray(diff.dimensions) ? diff.dimensions : [];
    const delta = Number(diff.score_total_delta || 0);
    const deltaClass = delta > 0 ? 'up' : delta < 0 ? 'down' : '';
    const beforeGate = clarityGateText(safe(diff.clarity_gate_before));
    const afterGate = clarityGateText(safe(diff.clarity_gate_after));
    const head = [
      "<div class='policy-edit-score-head'>",
      "<div class='policy-edit-score-title'>编辑前后评分对比</div>",
      "<div class='policy-edit-score-delta " + deltaClass + "'>总分变化 " + formatSignedScoreDelta(delta) + '</div>',
      '</div>',
    ].join('');
    const meta =
      "<div class='policy-edit-score-meta'>" +
      '编辑前: ' +
      safe(Math.round(Number(diff.score_total_before || 0))) +
      '/100（' +
      beforeGate +
      '） · 编辑后: ' +
      safe(Math.round(Number(diff.score_total_after || 0))) +
      '/100（' +
      afterGate +
      '）' +
      (diff.clarity_gate_changed ? ' · 门禁发生变化' : '') +
      '</div>';
    const listItems = [];
    for (const row of rows) {
      const rowDelta = Number((row || {}).delta || 0);
      const rowClass = rowDelta > 0 ? 'up' : rowDelta < 0 ? 'down' : '';
      listItems.push(
        "<li class='policy-edit-score-item " +
          rowClass +
          "'>" +
          safe((row || {}).label || '-') +
          ': ' +
          safe(Math.round(Number((row || {}).before_score || 0))) +
          ' -> ' +
          safe(Math.round(Number((row || {}).after_score || 0))) +
          '（' +
          formatSignedScoreDelta(rowDelta) +
          '）' +
          '</li>'
      );
    }
    box.innerHTML = head + meta + "<ul class='policy-edit-score-list'>" + listItems.join('') + '</ul>';
    box.classList.remove('hidden');
  }

  async function rescoreEditedPolicy() {
    const pending = state.pendingPolicyConfirmation;
    if (!pending || !pending.payload) {
      throw new Error('请先打开角色与职责确认/兜底弹窗');
    }
    const currentFingerprint = policyEditFingerprint();
    if (pending.rescore_preview && pending.rescore_fingerprint && pending.rescore_fingerprint === currentFingerprint) {
      renderPolicyEditScorePreview(pending.rescore_preview);
      setPolicyRescoreMeta('内容未变化，复用上次评分结果。');
      return pending.rescore_preview;
    }
    const req = {
      agent_name: safe((pending.payload || {}).agent_name),
      agent_search_root: safe($('agentSearchRoot').value).trim(),
      role_profile: safe($('policyEditRole').value).trim(),
      session_goal: safe($('policyEditGoal').value).trim(),
      duty_constraints: safe($('policyEditDuty').value).trim(),
    };
    const data = await postJSON('/api/policy/rescore', req);
    const rawPreview = data && data.preview && typeof data.preview === 'object' ? data.preview : data;
    const preview = normalizePolicyRescorePreview(rawPreview);
    pending.rescore_preview = preview;
    pending.rescore_fingerprint = policyEditFingerprint();
    renderPolicyEditScorePreview(preview);
    if (preview.diff.unchanged_input) {
      setPolicyRescoreMeta('内容未变更，评分与门禁保持不变。');
    } else {
      setPolicyRescoreMeta(
        '已更新评分：总分 ' +
          safe(preview.diff.score_total_before) +
          ' -> ' +
          safe(preview.diff.score_total_after) +
          '（' +
          formatSignedScoreDelta(preview.diff.score_total_delta) +
          '）'
      );
    }
    return preview;
  }

  function normalizePolicyConfirmPayload(raw) {
    const payload = raw && typeof raw === 'object' ? raw : {};
    const extracted = payload.extracted_policy && typeof payload.extracted_policy === 'object' ? payload.extracted_policy : {};
    const evidence = payload.evidence_snippets && typeof payload.evidence_snippets === 'object' ? payload.evidence_snippets : {};
    const analysisRaw = payload.analysis_chain && typeof payload.analysis_chain === 'object' ? payload.analysis_chain : {};
    const analysisFiles = analysisRaw.files && typeof analysisRaw.files === 'object' ? analysisRaw.files : {};
    const analysisContent = analysisRaw.content && typeof analysisRaw.content === 'object' ? analysisRaw.content : {};
    const analysisUiProgress = normalizePolicyAnalyzeProgress(
      analysisRaw.ui_progress && typeof analysisRaw.ui_progress === 'object' ? analysisRaw.ui_progress : {}
    );
    const constraintsRaw = payload.constraints && typeof payload.constraints === 'object' ? payload.constraints : {};
    const scoreWeights = normalizeScoreWeights(payload.score_weights);
    const scoreDimensions = normalizeScoreDimensions(payload.score_dimensions, scoreWeights);
    const dutyItems = normalizeAgentTextItems(extracted.duty_constraints, extracted.duty_constraints_text || '');
    const mustItems = normalizeConstraintEntries(constraintsRaw.must);
    const mustNotItems = normalizeConstraintEntries(constraintsRaw.must_not);
    const preItems = normalizeConstraintEntries(constraintsRaw.preconditions);
    const constraintIssues = Array.isArray(constraintsRaw.issues)
      ? constraintsRaw.issues
          .map((item) => {
            if (!item || typeof item !== 'object') return null;
            const code = safe(item.code).trim();
            const message = safe(item.message).trim();
            if (!code && !message) return null;
            return { code, message: message || code };
          })
          .filter((item) => !!item)
      : [];
    const conflicts = Array.isArray(constraintsRaw.conflicts)
      ? constraintsRaw.conflicts.map((v) => safe(v).trim()).filter((v) => !!v)
      : [];
    const constraintTotal =
      Number(constraintsRaw.total || 0) > 0
        ? Number(constraintsRaw.total || 0)
        : mustItems.length + mustNotItems.length + preItems.length;
    return {
      agent_name: safe(payload.agent_name),
      agents_hash: safe(payload.agents_hash),
      agents_version: safe(payload.agents_version),
      agents_path: safe(payload.agents_path),
      parse_status: safe(payload.parse_status || 'failed').toLowerCase(),
      parse_warnings: normalizeWarnList(payload.parse_warnings),
      clarity_score: Number(payload.clarity_score || 0),
      clarity_details:
        payload.clarity_details && typeof payload.clarity_details === 'object'
          ? payload.clarity_details
          : {},
      clarity_gate: safe(payload.clarity_gate || '').toLowerCase(),
      clarity_gate_reason: safe(payload.clarity_gate_reason || ''),
      allow_manual_policy_input: !!payload.allow_manual_policy_input,
      manual_fallback_allowed: !!payload.manual_fallback_allowed,
      risk_tips: Array.isArray(payload.risk_tips) ? payload.risk_tips.map((v) => safe(v)).filter((v) => !!v) : [],
      score_model: safe(payload.score_model || ''),
      score_total: Number(payload.score_total || payload.clarity_score || 0),
      score_weights: scoreWeights,
      score_dimensions: scoreDimensions,
      constraints: {
        must: mustItems,
        must_not: mustNotItems,
        preconditions: preItems,
        issues: constraintIssues,
        conflicts: conflicts,
        missing_evidence_count: Number(constraintsRaw.missing_evidence_count || 0),
        total: constraintTotal,
      },
      policy_cache_hit: !!payload.policy_cache_hit,
      policy_cache_status: safe(payload.policy_cache_status),
      policy_cache_reason: safe(payload.policy_cache_reason),
      policy_cache_cached_at: safe(payload.policy_cache_cached_at),
      policy_cache_trace: normalizeCacheTrace(payload.policy_cache_trace),
      extracted_policy: {
        role_profile: safe(extracted.role_profile),
        session_goal: safe(extracted.session_goal),
        duty_constraints: dutyItems,
      },
      evidence_snippets: {
        role: safe(evidence.role),
        goal: safe(evidence.goal),
        duty: safe(evidence.duty),
      },
      policy_extract_source: safe(payload.policy_extract_source || payload.source && payload.source.extract_source || ''),
      policy_prompt_version: safe(payload.policy_prompt_version || ''),
      policy_contract_status: safe(payload.policy_contract_status || ''),
      policy_contract_missing_fields: Array.isArray(payload.policy_contract_missing_fields)
        ? payload.policy_contract_missing_fields.map((v) => safe(v)).filter((v) => !!v)
        : [],
      policy_contract_issues: Array.isArray(payload.policy_contract_issues)
        ? payload.policy_contract_issues.map((v) => safe(v)).filter((v) => !!v)
        : [],
      analysis_chain: {
        source: safe(analysisRaw.source || payload.policy_extract_source || ''),
        prompt_version: safe(analysisRaw.prompt_version || payload.policy_prompt_version || ''),
        workspace_root: safe(analysisRaw.workspace_root || ''),
        workspace_root_valid: analysisRaw.workspace_root_valid !== false,
        workspace_root_error: safe(analysisRaw.workspace_root_error || ''),
        target_agent_workspace: safe(analysisRaw.target_agent_workspace || ''),
        target_agents_path: safe(analysisRaw.target_agents_path || ''),
        target_in_scope: analysisRaw.target_in_scope !== false,
        scope_hint: safe(analysisRaw.scope_hint || ''),
        command_summary: safe(analysisRaw.command_summary || ''),
        codex_exit_code:
          analysisRaw.codex_exit_code === null || analysisRaw.codex_exit_code === undefined
            ? ''
            : safe(analysisRaw.codex_exit_code),
        contract_status: safe(analysisRaw.contract_status || payload.policy_contract_status || ''),
        contract_missing_fields: Array.isArray(analysisRaw.contract_missing_fields)
          ? analysisRaw.contract_missing_fields.map((v) => safe(v)).filter((v) => !!v)
          : [],
        contract_issues: Array.isArray(analysisRaw.contract_issues)
          ? analysisRaw.contract_issues.map((v) => safe(v)).filter((v) => !!v)
          : [],
        files: {
          trace_dir: safe(analysisFiles.trace_dir || ''),
          prompt: safe(analysisFiles.prompt || ''),
          stdout: safe(analysisFiles.stdout || ''),
          stderr: safe(analysisFiles.stderr || ''),
          codex_result_raw: safe(analysisFiles.codex_result_raw || ''),
          parsed_result: safe(analysisFiles.parsed_result || ''),
          gate_decision: safe(analysisFiles.gate_decision || ''),
        },
        content: {
          prompt: safe(analysisContent.prompt || ''),
          stdout: safe(analysisContent.stdout || ''),
          stderr: safe(analysisContent.stderr || ''),
          codex_result_raw: safe(analysisContent.codex_result_raw || ''),
          parsed_result: safe(analysisContent.parsed_result || ''),
          gate_decision: safe(analysisContent.gate_decision || ''),
        },
        ui_progress: analysisUiProgress,
      },
      codex_failure: normalizeCodexFailure(payload.codex_failure),
    };
  }

  function closePolicyConfirmModal() {
    const mask = $('policyConfirmMask');
    if (mask) mask.classList.add('hidden');
    state.pendingPolicyConfirmation = null;
    const promptNode = $('policyRecommendPrompt');
    if (promptNode) promptNode.value = '';
    const recommendMeta = $('policyRecommendMeta');
    if (recommendMeta) recommendMeta.textContent = '';
    const traceBody = $('policyRecommendTraceBody');
    if (traceBody) traceBody.innerHTML = '';
    const rescoreMeta = $('policyRescoreMeta');
    if (rescoreMeta) rescoreMeta.textContent = '';
    const preview = $('policyEditScorePreview');
    if (preview) {
      preview.innerHTML = '';
      preview.classList.add('hidden');
    }
    setPolicyConfirmError('');
  }

  function policyConfirmCopyText() {
    const lines = [];
    const title = safe($('policyConfirmTitle') && $('policyConfirmTitle').textContent).trim();
    const meta = safe($('policyConfirmMeta') && $('policyConfirmMeta').textContent).trim();
    const alert = safe($('policyConfirmAlert') && $('policyConfirmAlert').textContent).trim();
    lines.push('# ' + (title || '角色与职责确认/兜底'));
    if (meta) lines.push(meta);
    if (alert) lines.push('\n## 提示\n' + alert);

    const modules = Array.from(document.querySelectorAll('#policyConfirmSummary [data-policy-module]'));
    if (modules.length) {
      lines.push('\n## 首屏模块（按界面顺序）');
      for (const module of modules) {
        const head = safe(module.querySelector('.policy-confirm-module-head') && module.querySelector('.policy-confirm-module-head').textContent).trim();
        const body = safe(module.querySelector('.policy-confirm-module-body') && module.querySelector('.policy-confirm-module-body').innerText).trim();
        lines.push('\n### ' + (head || '未命名模块'));
        lines.push(body || '(无)');
      }
    }

    const analysisBodyText = safe($('policyConfirmAnalysisChainBody') && $('policyConfirmAnalysisChainBody').innerText).trim();
    if (analysisBodyText) {
      lines.push('\n## 分析链路');
      lines.push(analysisBodyText);
    }

    const gateBodyText = safe($('policyConfirmGateBody') && $('policyConfirmGateBody').innerText).trim();
    if (gateBodyText) {
      lines.push('\n## 门禁与来源（治理层）');
      lines.push(gateBodyText);
    }

    const evidence = Array.from(document.querySelectorAll('#policyConfirmEvidenceBody .agent-policy-pre'));
    if (evidence.length) {
      lines.push('\n## 证据片段');
      for (const block of evidence) {
        const text = safe(block.innerText).trim();
        if (text) lines.push('\n' + text);
      }
    }

    const riskText = safe($('policyConfirmRisk') && $('policyConfirmRisk').innerText).trim();
    if (riskText) {
      lines.push('\n## 风险提示');
      lines.push(riskText);
    }

    lines.push('\n## 编辑草稿');
    lines.push('角色\n' + (safe($('policyEditRole') && $('policyEditRole').value).trim() || '(空)'));
    lines.push('\n目标\n' + (safe($('policyEditGoal') && $('policyEditGoal').value).trim() || '(空)'));
    lines.push('\n职责\n' + (safe($('policyEditDuty') && $('policyEditDuty').value).trim() || '(空)'));
    lines.push('\nAI推荐指令\n' + (safe($('policyRecommendPrompt') && $('policyRecommendPrompt').value).trim() || '(空)'));
    lines.push('\n原因\n' + (safe($('policyConfirmReason') && $('policyConfirmReason').value).trim() || '(空)'));

    lines.push('\n## 布局结构');
    lines.push('1. 顶部：标题 + 元信息 + 风险提示');
    lines.push('2. 首屏：角色/目标 -> 职责边界 -> 门禁得分项');
    lines.push('3. 下钻：分析链路（默认折叠） -> 门禁与来源（治理层，默认折叠） -> 原文证据（默认折叠）');
    lines.push('4. 底部：编辑草稿区 + 操作按钮');
    return lines.join('\n').trim();
  }

  function appendInlineStyle(node, cssText) {
    if (!node || !cssText) return;
    const prev = safe(node.getAttribute('style')).trim();
    node.setAttribute('style', (prev ? prev + ';' : '') + cssText);
  }

  function applyInlinePolicyConfirmCopyStyles(clone) {
    if (!clone) return;
    const apply = (selector, cssText) => {
      Array.from(clone.querySelectorAll(selector)).forEach((node) => appendInlineStyle(node, cssText));
    };
    appendInlineStyle(
      clone,
      'border:1px solid #e5e6eb;border-radius:12px;padding:14px;background:#fff;max-width:920px;'
    );
    apply(
      '.policy-confirm-head',
      'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;'
    );
    apply('.policy-confirm-title', 'font-size:16px;font-weight:700;color:#1f2329;');
    apply('.policy-confirm-meta', 'margin-top:6px;font-size:12px;color:#4e5969;');
    apply(
      '.policy-confirm-alert',
      'margin-top:10px;border:1px solid #ffd591;border-radius:8px;background:#fffaf0;color:#8c5f00;padding:8px 10px;font-size:12px;line-height:1.45;'
    );
    apply('.policy-confirm-alert.block', 'border-color:#ffccc7;background:#fff2f0;color:#a8071a;');
    apply(
      '.policy-confirm-grid',
      'margin-top:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;'
    );
    apply('.policy-confirm-stack', 'margin-top:10px;display:flex;flex-direction:column;gap:10px;');
    apply('.policy-confirm-module', 'border:1px solid #e5e6eb;border-radius:8px;background:#fff;padding:10px;');
    apply('.policy-confirm-module-head', 'font-size:13px;font-weight:700;color:#1f2329;margin-bottom:8px;');
    apply('.policy-confirm-core-grid', 'display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;');
    apply('.policy-constraint-grid', 'display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;');
    apply('.policy-constraint-group', 'border:1px solid #eff0f2;border-radius:8px;background:#fafbfc;padding:8px;');
    apply('.policy-constraint-title', 'font-size:12px;font-weight:600;color:#2d3a4a;');
    apply('.policy-constraint-empty', 'font-size:12px;color:#667085;');
    apply('.policy-constraint-body', 'margin-top:6px;max-height:180px;overflow:auto;');
    apply('.policy-constraint-list', 'margin:0 0 0 18px;padding:0;display:flex;flex-direction:column;gap:6px;');
    apply('.policy-constraint-list li', 'font-size:12px;color:#2d3a4a;line-height:1.45;');
    apply('.policy-constraint-evidence', 'margin-top:2px;font-size:12px;color:#667085;white-space:pre-wrap;');
    apply('.policy-score-summary', 'font-size:12px;color:#2d3a4a;line-height:1.45;');
    apply('.policy-score-dimensions', 'margin-top:8px;display:flex;flex-direction:column;gap:8px;');
    apply('.policy-score-dim', 'border:1px solid #eff0f2;border-radius:8px;background:#fafbfc;padding:8px;');
    apply('.policy-score-dim.low', 'border-color:#ffd591;background:#fffaf0;');
    apply('.policy-score-dim.manual_review', 'border-color:#ffccc7;background:#fff2f0;');
    apply('.policy-score-dim-head', 'display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;');
    apply('.policy-score-dim-title', 'font-size:12px;font-weight:600;color:#1f2329;');
    apply('.policy-score-dim-meta', 'font-size:12px;color:#4e5969;');
    apply('.policy-score-dim-reason', 'margin-top:6px;font-size:12px;color:#8c5f00;line-height:1.45;');
    apply('.policy-score-dim.manual_review .policy-score-dim-reason', 'color:#a8071a;');
    apply('.policy-score-evidence', 'margin:6px 0 0 18px;padding:0;display:flex;flex-direction:column;gap:4px;');
    apply('.policy-score-evidence li', 'font-size:12px;color:#2d3a4a;line-height:1.45;');
    apply('.policy-score-repair', 'margin-top:6px;font-size:12px;color:#33465a;line-height:1.45;white-space:pre-wrap;');
    apply(
      '.policy-confirm-card',
      'border:1px solid #e5e6eb;border-radius:8px;padding:8px;background:#fff;'
    );
    apply('.policy-confirm-card-head', 'font-size:12px;font-weight:600;margin-bottom:6px;');
    apply('.agent-policy-card', 'border:1px solid #e5e6eb;border-radius:8px;padding:8px;background:#fff;');
    apply('.agent-policy-card-head', 'font-size:12px;font-weight:600;margin-bottom:6px;color:#1f2329;');
    apply(
      '.agent-policy-card-body',
      'white-space:pre-wrap;word-break:break-word;font-size:12px;color:#33465a;line-height:1.5;max-height:180px;overflow:auto;'
    );
    apply('.agent-policy-list', 'margin:0;padding-left:18px;display:flex;flex-direction:column;gap:4px;');
    apply('.agent-policy-more', 'margin-top:5px;font-size:11px;color:#667085;');
    apply(
      '.policy-confirm-card-body',
      'white-space:pre-wrap;word-break:break-word;font-size:12px;color:#33465a;line-height:1.5;max-height:180px;overflow:auto;'
    );
    apply(
      '.policy-confirm-risk,.policy-confirm-edit,.agent-policy-details',
      'border:1px solid #eff0f2;border-radius:8px;padding:8px;margin-top:10px;'
    );
    apply('.policy-confirm-risk ul', 'margin:6px 0 0 18px;padding:0;');
    apply(
      '.policy-confirm-risk li',
      'font-size:12px;color:#4e5969;line-height:1.45;margin:0 0 4px;'
    );
    apply('.policy-confirm-edit-grid', 'display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;');
    apply(
      '.policy-confirm-edit-grid > .policy-edit-duty,.policy-confirm-edit-grid > .policy-edit-recommend,.policy-confirm-edit-grid > .policy-edit-reason,.policy-confirm-edit-grid > .policy-edit-rescore,.policy-confirm-edit-grid > .policy-edit-recommend-trace',
      'grid-column:1 / -1;'
    );
    apply('.policy-confirm-ai-row', 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;');
    apply('.policy-confirm-ai-row input', 'flex:1 1 260px;min-width:0;');
    apply('.policy-confirm-ai-meta', 'margin-top:4px;font-size:12px;color:#4e5969;line-height:1.45;');
    apply('#policyEditRole,#policyEditGoal', 'min-height:132px;');
    apply('#policyEditDuty', 'min-height:248px;');
    apply('.policy-recommend-trace-list', 'display:flex;flex-direction:column;gap:8px;');
    apply('.policy-recommend-trace-item', 'border:1px solid #eff0f2;border-radius:8px;background:#fafbfc;padding:8px;');
    apply('.policy-recommend-trace-head', 'display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;');
    apply('.policy-recommend-trace-status', 'font-size:12px;font-weight:600;color:#2d3a4a;');
    apply('.policy-recommend-trace-status.applied', 'color:#237804;');
    apply('.policy-recommend-trace-status.blocked,.policy-recommend-trace-status.failed', 'color:#a8071a;');
    apply('.policy-recommend-trace-status.no_change', 'color:#8c5f00;');
    apply('.policy-recommend-trace-meta', 'font-size:12px;color:#4e5969;line-height:1.45;');
    apply(
      '.policy-recommend-trace-block',
      'margin-top:6px;border:1px solid #eff0f2;border-radius:6px;background:#fff;padding:6px;font-size:12px;line-height:1.45;white-space:pre-wrap;word-break:break-word;max-height:180px;overflow:auto;'
    );
    apply('.policy-edit-score-preview', 'margin-top:8px;border:1px solid #eff0f2;border-radius:8px;background:#fafbfc;padding:8px;');
    apply('.policy-edit-score-preview.hidden', 'display:none;');
    apply('.policy-edit-score-head', 'display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;');
    apply('.policy-edit-score-title', 'font-size:12px;font-weight:600;color:#1f2329;');
    apply('.policy-edit-score-delta', 'font-size:12px;font-weight:600;border:1px solid #eff0f2;border-radius:999px;padding:2px 8px;color:#4e5969;background:#fff;');
    apply('.policy-edit-score-delta.up', 'border-color:#b7eb8f;color:#237804;background:#f6ffed;');
    apply('.policy-edit-score-delta.down', 'border-color:#ffccc7;color:#a8071a;background:#fff2f0;');
    apply('.policy-edit-score-meta', 'margin-top:6px;font-size:12px;color:#4e5969;line-height:1.45;');
    apply('.policy-edit-score-list', 'margin:8px 0 0 18px;padding:0;display:flex;flex-direction:column;gap:4px;');
    apply('.policy-edit-score-item', 'font-size:12px;color:#2d3a4a;line-height:1.45;');
    apply('.policy-edit-score-item.up', 'color:#237804;');
    apply('.policy-edit-score-item.down', 'color:#a8071a;');
    apply('.policy-confirm-actions', 'display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;');
    apply(
      'input,textarea',
      'width:100%;border:1px solid #d0d5dd;border-radius:8px;padding:6px 8px;font:inherit;color:inherit;background:#fff;'
    );
    apply('textarea', 'min-height:72px;resize:vertical;');
    apply(
      'button',
      'border:1px solid #d0d5dd;border-radius:8px;background:#fff;padding:6px 10px;font:inherit;color:inherit;'
    );
    apply('.hint', 'font-size:12px;color:#667085;');
    apply(
      '.agent-policy-pre',
      'margin:8px 0 0;white-space:pre-wrap;word-break:break-word;font-size:12px;line-height:1.45;color:#33465a;border:1px solid #e5e7eb;border-radius:6px;background:#fff;padding:8px;max-height:none;overflow:visible;'
    );
    apply(
      '.policy-confirm-error',
      'font-size:12px;color:#d92d20;min-height:16px;white-space:pre-wrap;word-break:break-word;'
    );
  }

  function policyConfirmCopyHtml() {
    const modal = document.querySelector('#policyConfirmMask .policy-confirm-modal');
    if (!modal) return '';
    const clone = modal.cloneNode(true);
    Array.from(clone.querySelectorAll('textarea')).forEach((node) => {
      node.textContent = safe(node.value);
    });
    Array.from(clone.querySelectorAll('input')).forEach((node) => {
      const type = safe(node.getAttribute('type')).toLowerCase();
      if (type !== 'checkbox' && type !== 'radio') {
        node.setAttribute('value', safe(node.value));
      }
    });
    applyInlinePolicyConfirmCopyStyles(clone);
    const style = [
      '<style>',
      ".policy-copy-root{font-family:'Segoe UI','PingFang SC',sans-serif;color:#1f2329;line-height:1.5;padding:16px;background:#f8fafc;}",
      '.policy-copy-root *{box-sizing:border-box;}',
      '.policy-confirm-modal{border:1px solid #e5e6eb;border-radius:12px;padding:14px;background:#fff;max-width:920px;}',
      '.policy-confirm-head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;}',
      '.policy-confirm-title{font-size:16px;font-weight:700;}',
      '.policy-confirm-meta{margin-top:6px;font-size:12px;color:#4e5969;}',
      '.policy-confirm-alert{margin-top:10px;border:1px solid #ffd591;border-radius:8px;background:#fffaf0;color:#8c5f00;padding:8px 10px;font-size:12px;line-height:1.45;}',
      '.policy-confirm-alert.block{border-color:#ffccc7;background:#fff2f0;color:#a8071a;}',
      '.policy-confirm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;}',
      '.policy-confirm-stack{margin-top:10px;display:flex;flex-direction:column;gap:10px;}',
      '.policy-confirm-module{border:1px solid #e5e6eb;border-radius:8px;background:#fff;padding:10px;}',
      '.policy-confirm-module-head{font-size:13px;font-weight:700;color:#1f2329;margin-bottom:8px;}',
      '.policy-confirm-core-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;}',
      '.policy-constraint-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;}',
      '.policy-constraint-group{border:1px solid #eff0f2;border-radius:8px;background:#fafbfc;padding:8px;}',
      '.policy-constraint-title{font-size:12px;font-weight:600;color:#2d3a4a;}',
      '.policy-constraint-empty{font-size:12px;color:#667085;}',
      '.policy-constraint-body{margin-top:6px;max-height:180px;overflow:auto;}',
      '.policy-constraint-list{margin:0 0 0 18px;padding:0;display:flex;flex-direction:column;gap:6px;}',
      '.policy-constraint-list li{font-size:12px;color:#2d3a4a;line-height:1.45;}',
      '.policy-constraint-evidence{margin-top:2px;font-size:12px;color:#667085;white-space:pre-wrap;}',
      '.policy-score-summary{font-size:12px;color:#2d3a4a;line-height:1.45;}',
      '.policy-score-dimensions{margin-top:8px;display:flex;flex-direction:column;gap:8px;}',
      '.policy-score-dim{border:1px solid #eff0f2;border-radius:8px;background:#fafbfc;padding:8px;}',
      '.policy-score-dim.low{border-color:#ffd591;background:#fffaf0;}',
      '.policy-score-dim.manual_review{border-color:#ffccc7;background:#fff2f0;}',
      '.policy-score-dim-head{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;}',
      '.policy-score-dim-title{font-size:12px;font-weight:600;color:#1f2329;}',
      '.policy-score-dim-meta{font-size:12px;color:#4e5969;}',
      '.policy-score-dim-reason{margin-top:6px;font-size:12px;color:#8c5f00;line-height:1.45;}',
      '.policy-score-dim.manual_review .policy-score-dim-reason{color:#a8071a;}',
      '.policy-score-evidence{margin:6px 0 0 18px;padding:0;display:flex;flex-direction:column;gap:4px;}',
      '.policy-score-evidence li{font-size:12px;color:#2d3a4a;line-height:1.45;}',
      '.policy-score-repair{margin-top:6px;font-size:12px;color:#33465a;line-height:1.45;white-space:pre-wrap;}',
      '.agent-policy-card{border:1px solid #e5e6eb;border-radius:8px;padding:8px;background:#fff;}',
      '.agent-policy-card-head{font-size:12px;font-weight:600;margin-bottom:6px;color:#1f2329;}',
      '.agent-policy-card-body{white-space:pre-wrap;word-break:break-word;font-size:12px;color:#33465a;line-height:1.5;max-height:180px;overflow:auto;}',
      '.agent-policy-list{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:4px;}',
      '.agent-policy-more{margin-top:5px;font-size:11px;color:#667085;}',
      '.policy-confirm-card{border:1px solid #e5e6eb;border-radius:8px;padding:8px;background:#fff;}',
      '.policy-confirm-card-head{font-size:12px;font-weight:600;margin-bottom:6px;}',
      '.policy-confirm-card-body{white-space:pre-wrap;word-break:break-word;font-size:12px;color:#33465a;line-height:1.5;max-height:180px;overflow:auto;}',
      '.policy-confirm-risk,.policy-confirm-edit,.agent-policy-details{border:1px solid #eff0f2;border-radius:8px;padding:8px;margin-top:10px;}',
      '.policy-confirm-risk ul{margin:6px 0 0 18px;padding:0;}',
      '.policy-confirm-risk li{font-size:12px;color:#4e5969;line-height:1.45;margin:0 0 4px;}',
      '.policy-confirm-edit-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}',
      '.policy-confirm-edit-grid > .policy-edit-duty,.policy-confirm-edit-grid > .policy-edit-recommend,.policy-confirm-edit-grid > .policy-edit-reason,.policy-confirm-edit-grid > .policy-edit-rescore,.policy-confirm-edit-grid > .policy-edit-recommend-trace{grid-column:1 / -1;}',
      '.policy-confirm-ai-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}',
      '.policy-confirm-ai-row input{flex:1 1 260px;min-width:0;}',
      '.policy-confirm-ai-meta{margin-top:4px;font-size:12px;color:#4e5969;line-height:1.45;}',
      '#policyEditRole,#policyEditGoal{min-height:132px;}',
      '#policyEditDuty{min-height:248px;}',
      '.policy-recommend-trace-list{display:flex;flex-direction:column;gap:8px;}',
      '.policy-recommend-trace-item{border:1px solid #eff0f2;border-radius:8px;background:#fafbfc;padding:8px;}',
      '.policy-recommend-trace-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;}',
      '.policy-recommend-trace-status{font-size:12px;font-weight:600;color:#2d3a4a;}',
      '.policy-recommend-trace-status.applied{color:#237804;}',
      '.policy-recommend-trace-status.blocked,.policy-recommend-trace-status.failed{color:#a8071a;}',
      '.policy-recommend-trace-status.no_change{color:#8c5f00;}',
      '.policy-recommend-trace-meta{font-size:12px;color:#4e5969;line-height:1.45;}',
      '.policy-recommend-trace-block{margin-top:6px;border:1px solid #eff0f2;border-radius:6px;background:#fff;padding:6px;font-size:12px;line-height:1.45;white-space:pre-wrap;word-break:break-word;max-height:180px;overflow:auto;}',
      '.policy-edit-score-preview{margin-top:8px;border:1px solid #eff0f2;border-radius:8px;background:#fafbfc;padding:8px;}',
      '.policy-edit-score-preview.hidden{display:none;}',
      '.policy-edit-score-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;}',
      '.policy-edit-score-title{font-size:12px;font-weight:600;color:#1f2329;}',
      '.policy-edit-score-delta{font-size:12px;font-weight:600;border:1px solid #eff0f2;border-radius:999px;padding:2px 8px;color:#4e5969;background:#fff;}',
      '.policy-edit-score-delta.up{border-color:#b7eb8f;color:#237804;background:#f6ffed;}',
      '.policy-edit-score-delta.down{border-color:#ffccc7;color:#a8071a;background:#fff2f0;}',
      '.policy-edit-score-meta{margin-top:6px;font-size:12px;color:#4e5969;line-height:1.45;}',
      '.policy-edit-score-list{margin:8px 0 0 18px;padding:0;display:flex;flex-direction:column;gap:4px;}',
      '.policy-edit-score-item{font-size:12px;color:#2d3a4a;line-height:1.45;}',
      '.policy-edit-score-item.up{color:#237804;}',
      '.policy-edit-score-item.down{color:#a8071a;}',
      '.policy-confirm-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;}',
      'input,textarea{width:100%;border:1px solid #d0d5dd;border-radius:8px;padding:6px 8px;font:inherit;color:inherit;background:#fff;}',
      'textarea{min-height:72px;resize:vertical;}',
      'button{border:1px solid #d0d5dd;border-radius:8px;background:#fff;padding:6px 10px;font:inherit;color:inherit;}',
      '.hint{font-size:12px;color:#667085;}',
      'pre{white-space:pre-wrap;word-break:break-word;}',
      '</style>',
    ].join('');
    return style + "<div class='policy-copy-root'>" + clone.outerHTML + '</div>';
  }

  async function tryCopyPolicyConfirmHtml(html) {
    if (!html) return false;
    const plain = html;
    if (navigator.clipboard && window.ClipboardItem && navigator.clipboard.write) {
      try {
        const item = new ClipboardItem({
          'text/plain': new Blob([plain], { type: 'text/plain' }),
          'text/html': new Blob([html], { type: 'text/html' }),
        });
        await navigator.clipboard.write([item]);
        return true;
      } catch (_) {
        // fallback to execCommand path below
      }
    }
    return copyPolicyConfirmHtmlByExecCommand(html);
  }
