  function copyPolicyConfirmHtmlByExecCommand(html) {
    if (!html) return false;
    if (!document.queryCommandSupported || !document.queryCommandSupported('copy')) {
      return false;
    }
    const selection = window.getSelection ? window.getSelection() : null;
    const active = document.activeElement;
    const holder = document.createElement('div');
    holder.setAttribute('contenteditable', 'true');
    holder.setAttribute('aria-hidden', 'true');
    holder.style.position = 'fixed';
    holder.style.left = '-9999px';
    holder.style.top = '0';
    holder.style.opacity = '0';
    holder.style.pointerEvents = 'none';
    holder.innerHTML = html;
    document.body.appendChild(holder);

    let copiedAsHtml = false;
    const onCopy = (event) => {
      try {
        if (!event || !event.clipboardData) return;
        event.preventDefault();
        event.clipboardData.setData('text/html', html);
        event.clipboardData.setData('text/plain', html);
        copiedAsHtml = true;
      } catch (_) {
        copiedAsHtml = false;
      }
    };
    document.addEventListener('copy', onCopy, true);

    let ok = false;
    try {
      const range = document.createRange();
      range.selectNodeContents(holder);
      if (selection) {
        selection.removeAllRanges();
        selection.addRange(range);
      }
      ok = document.execCommand('copy');
    } catch (_) {
      ok = false;
    } finally {
      document.removeEventListener('copy', onCopy, true);
      if (selection) {
        try {
          selection.removeAllRanges();
        } catch (_) {
          // ignore selection cleanup error
        }
      }
      document.body.removeChild(holder);
      if (active && typeof active.focus === 'function') {
        try {
          active.focus();
        } catch (_) {
          // ignore focus restore error
        }
      }
    }
    return !!(ok && copiedAsHtml);
  }

  async function copyPolicyConfirmHtmlView() {
    const html = policyConfirmCopyHtml();
    if (!html) {
      throw new Error('当前无可复制内容');
    }
    if (await tryCopyPolicyConfirmHtml(html)) {
      return {
        mode: 'html',
      };
    }
    throw new Error('当前环境不支持 HTML 富文本复制，请使用 Chromium 浏览器并通过 localhost/https 访问');
  }

  function openPolicyConfirmModal(payload, requestContext) {
    const info = normalizePolicyConfirmPayload(payload);
    const chain = info.analysis_chain && typeof info.analysis_chain === 'object' ? info.analysis_chain : {};
    const chainUiProgress = chain.ui_progress && typeof chain.ui_progress === 'object' ? chain.ui_progress : {};
    const hasChainProgress =
      Array.isArray(chainUiProgress.stages) && chainUiProgress.stages.length > 0;
    if (!hasChainProgress) {
      const liveProgress = policyAnalyzeProgressSnapshot(info.agent_name);
      if (liveProgress) {
        chain.ui_progress = liveProgress;
      } else {
        const cachedProgress = getAgentPolicyProgressSnapshot(info.agent_name);
        if (cachedProgress) {
          chain.ui_progress = cachedProgress;
        } else {
          chain.ui_progress = buildPolicyFallbackProgressFromInfo(info);
        }
      }
    }
    state.pendingPolicyConfirmation = {
      payload: info,
      request: Object.assign({}, requestContext || {}),
      rescore_preview: null,
      rescore_fingerprint: '',
      base_fingerprint: '',
      recommend_trace: [],
    };
    const mask = $('policyConfirmMask');
    const meta = $('policyConfirmMeta');
    const alert = $('policyConfirmAlert');
    const summary = $('policyConfirmSummary');
    const analysisChainBody = $('policyConfirmAnalysisChainBody');
    const evidenceBody = $('policyConfirmEvidenceBody');
    const risk = $('policyConfirmRisk');
    const riskBody = $('policyConfirmRiskBody');
    const dutyEditorText = buildDutyEditorTextFromConstraints(
      info.constraints,
      info.extracted_policy.duty_constraints,
    );
    const canConfirm = info.parse_status !== 'failed' && info.clarity_gate === 'confirm';
    const canEdit = !!info.manual_fallback_allowed;
    const confirmBtn = $('policyConfirmUseBtn');
    const editBtn = $('policyEditUseBtn');
    const rescoreBtn = $('policyRescoreBtn');
    const cancelBtn = $('policyCancelBtn');
    const editPanel = document.querySelector('#policyConfirmMask .policy-confirm-edit');
    const recommendPrompt = $('policyRecommendPrompt');
    const recommendMeta = $('policyRecommendMeta');
    const recommendTrace = $('policyRecommendTrace');

    meta.textContent =
      'agent=' +
      safe(info.agent_name) +
      ' · hash=' +
      short(info.agents_hash, 12) +
      ' · version=' +
      safe(info.agents_version) +
      ' · parse_status=' +
      parseStatusText(info.parse_status) +
      ' · 清晰度=' +
      safe(info.clarity_score) +
      '/100' +
      ' · score_model=' +
      (safe(info.score_model) || 'v1') +
      ' · gate=' +
      clarityGateText(info.clarity_gate) +
      ' · source=' +
      (safe(info.policy_extract_source) || 'unknown') +
      (safe(info.policy_prompt_version) ? ' · prompt_version=' + safe(info.policy_prompt_version) : '') +
      (info.policy_cache_status ? ' · cache=' + safe(info.policy_cache_status) : '');
    const gateLabel =
      info.clarity_gate === 'block'
        ? '已阻断'
        : info.clarity_gate === 'confirm'
          ? '需人工确认'
          : '自动生效';
    alert.className = 'policy-confirm-alert ' + (info.clarity_gate === 'block' ? 'block' : '');
    let alertText = '';
    if (info.clarity_gate === 'auto' && info.parse_status === 'ok') {
      alertText =
        '当前角色与职责可自动生效。' +
        (canEdit ? ' 你也可以通过“编辑后使用本会话”做优化。' : '');
    } else {
      alertText =
        '风险提示：当前角色与职责提取结果' +
        (info.parse_status === 'incomplete' ? '不完整' : info.parse_status === 'failed' ? '失败' : '存在歧义') +
        '，门禁=' +
        gateLabel +
        '。若直接使用，可能出现职责漂移。';
    }
    alert.innerHTML = '';
    const alertTextNode = document.createElement('div');
    alertTextNode.textContent = alertText;
    alert.appendChild(alertTextNode);
    if (codexFailureHasValue(info.codex_failure)) {
      const failureHost = document.createElement('div');
      failureHost.className = 'policy-confirm-failure-host';
      alert.appendChild(failureHost);
      renderCodexFailureCard(failureHost, info.codex_failure, {
        title: '策略失败原因',
        compact: true,
        context: {
          request: Object.assign({}, requestContext || {}),
          onPolicyResult(data, requestPayload) {
            openPolicyConfirmModal(data.policy_confirmation || data, requestPayload);
          },
        },
      });
    }

    summary.innerHTML = '';
    const analysisDetails = $('policyConfirmAnalysisChain');
    const gateDetails = $('policyConfirmGateDetails');
    const gateBody = $('policyConfirmGateBody');
    const evidenceDetails = $('policyConfirmEvidence');

    const coreModule = createPolicyModule('角色/目标', 'core');
    const coreGrid = document.createElement('div');
    coreGrid.className = 'policy-confirm-core-grid';
    coreGrid.appendChild(
      createPolicyCard('角色', [previewTextFromRole(info.extracted_policy.role_profile, info.agent_name)], 1, '未提取'),
    );
    coreGrid.appendChild(
      createPolicyCard('目标', normalizeAgentTextItems(info.extracted_policy.session_goal, ''), 4, '未提取'),
    );
    coreModule.body.appendChild(coreGrid);
    summary.appendChild(coreModule.section);

    const constraintsModule = createPolicyModule('职责边界（must / must_not / preconditions）', 'constraints');
    const constraintsGrid = document.createElement('div');
    constraintsGrid.className = 'policy-constraint-grid';
    const appendConstraintGroup = (title, entries) => {
      const group = document.createElement('section');
      group.className = 'policy-constraint-group';
      const head = document.createElement('div');
      head.className = 'policy-constraint-title';
      head.textContent = safe(title);
      group.appendChild(head);
      const body = document.createElement('div');
      body.className = 'policy-constraint-body';
      const listItems = Array.isArray(entries) ? entries : [];
      if (!listItems.length) {
        const empty = document.createElement('div');
        empty.className = 'policy-constraint-empty';
        empty.textContent = '(无)';
        body.appendChild(empty);
      } else {
        const list = document.createElement('ul');
        list.className = 'policy-constraint-list';
        for (const item of listItems) {
          const li = document.createElement('li');
          const text = safe((item || {}).text).trim() || '(空)';
          li.textContent = text;
          const evidenceText = safe((item || {}).evidence).trim();
          if (evidenceText) {
            const evidenceNode = document.createElement('div');
            evidenceNode.className = 'policy-constraint-evidence';
            evidenceNode.textContent = '证据：' + evidenceText;
            li.appendChild(evidenceNode);
          }
          list.appendChild(li);
        }
        body.appendChild(list);
      }
      group.appendChild(body);
      constraintsGrid.appendChild(group);
    };
    appendConstraintGroup('must（必须项）', info.constraints.must);
    appendConstraintGroup('must_not（禁止项）', info.constraints.must_not);
    appendConstraintGroup('preconditions（前置条件）', info.constraints.preconditions);
    constraintsModule.body.appendChild(constraintsGrid);
    const constraintIssues = [];
    if (Array.isArray(info.constraints.issues)) {
      for (const issue of info.constraints.issues) {
        const text = safe((issue || {}).message).trim();
        if (text) constraintIssues.push(text);
      }
    }
    if (Array.isArray(info.constraints.conflicts)) {
      for (const conflict of info.constraints.conflicts) {
        const text = safe(conflict).trim();
        if (text) constraintIssues.push(text);
      }
    }
    if (constraintIssues.length) {
      const issueList = document.createElement('ul');
      issueList.className = 'policy-score-evidence';
      for (const text of constraintIssues) {
        const li = document.createElement('li');
        li.textContent = '职责边界风险：' + text;
        issueList.appendChild(li);
      }
      constraintsModule.body.appendChild(issueList);
    }
    summary.appendChild(constraintsModule.section);

    const scoreModule = createPolicyModule('角色设定门禁得分项', 'score', {
      collapsible: true,
      expanded: false,
    });
    const scoreSummary = document.createElement('div');
    scoreSummary.className = 'policy-score-summary';
    const weightParts = [];
    for (const key of info.score_dimensions.order) {
      const dim = info.score_dimensions.items[key];
      if (!dim) continue;
      weightParts.push(safe(dim.label) + '=' + safe(Math.round(Number(dim.weight || 0) * 100)) + '%');
    }
    scoreSummary.textContent =
      '总分=' +
      safe(info.score_total) +
      '/100 · model=' +
      (safe(info.score_model) || 'v1') +
      (weightParts.length ? ' · 权重：' + weightParts.join('，') : '');
    scoreModule.body.appendChild(scoreSummary);

    const scoreDimensions = document.createElement('div');
    scoreDimensions.className = 'policy-score-dimensions';
    const scoreOrder = Array.isArray(info.score_dimensions.order) ? info.score_dimensions.order : [];
    for (const key of scoreOrder) {
      const dim = info.score_dimensions.items[key];
      if (!dim) continue;
      const status = safe(dim.status).trim().toLowerCase();
      const box = document.createElement('section');
      box.className = 'policy-score-dim ' + (status === 'low' || status === 'manual_review' ? status : '');
      const head = document.createElement('div');
      head.className = 'policy-score-dim-head';
      const title = document.createElement('div');
      title.className = 'policy-score-dim-title';
      title.textContent = safe(dim.label);
      head.appendChild(title);
      const metaLine = document.createElement('div');
      metaLine.className = 'policy-score-dim-meta';
      metaLine.textContent =
        'score=' +
        safe(dim.score) +
        '/100 · weight=' +
        safe(Math.round(Number(dim.weight || 0) * 100)) +
        '% · status=' +
        (status === 'manual_review' ? '待人工确认' : status === 'low' ? '偏低' : '正常');
      head.appendChild(metaLine);
      box.appendChild(head);
