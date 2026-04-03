  function normalizeCodexFailure(raw) {
    const node = raw && typeof raw === 'object' ? raw : {};
    const retryActionRaw = node.retry_action && typeof node.retry_action === 'object' ? node.retry_action : {};
    const traceRefsRaw = Array.isArray(node.trace_refs) ? node.trace_refs : [];
    const traceRefs = traceRefsRaw
      .map((item) => {
        const row = item && typeof item === 'object' ? item : {};
        return {
          label: safe(row.label).trim() || 'evidence',
          path: safe(row.path).trim(),
        };
      })
      .filter((item) => !!item.path);
    const featureKey = safe(node.feature_key).trim();
    const failureMessage = safe(node.failure_message).trim();
    const failureDetailCode = safe(node.failure_detail_code).trim().toLowerCase();
    if (!featureKey && !failureMessage && !failureDetailCode && !traceRefs.length) {
      return null;
    }
    const retryAction = {
      kind: safe(retryActionRaw.kind).trim(),
      label: safe(retryActionRaw.label).trim() || '重试',
      retryable: retryActionRaw.retryable !== false,
      blocked_reason: safe(retryActionRaw.blocked_reason).trim(),
      payload: retryActionRaw.payload && typeof retryActionRaw.payload === 'object' ? retryActionRaw.payload : {},
    };
    if (!retryAction.kind) {
      retryAction.retryable = false;
    }
    return {
      feature_key: featureKey,
      attempt_id: safe(node.attempt_id).trim(),
      attempt_count: Math.max(1, Number(node.attempt_count || 0) || 1),
      failure_code: safe(node.failure_code).trim().toLowerCase(),
      failure_detail_code: failureDetailCode,
      failure_stage: safe(node.failure_stage).trim().toLowerCase(),
      failure_message: failureMessage,
      retryable: !!node.retryable && retryAction.retryable,
      retry_action: retryAction,
      trace_refs: traceRefs,
      failed_at: safe(node.failed_at).trim(),
      next_step_suggestion: safe(node.next_step_suggestion).trim(),
    };
  }

  function codexFailureHasValue(raw) {
    return !!normalizeCodexFailure(raw);
  }

  function codexFailurePrimaryMessage(raw) {
    const failure = normalizeCodexFailure(raw);
    return failure ? safe(failure.failure_message).trim() : '';
  }

  function codexFailureStageText(value) {
    const key = safe(value).trim().toLowerCase();
    const map = {
      input_prepare: '输入准备',
      scope_validate: '范围校验',
      workspace_prepare: '工作区准备',
      runtime_prepare: '运行环境准备',
      metadata_validate: '元数据校验',
      contract_validate: '契约校验',
      codex_exec: 'Codex 执行',
      result_parse: '结果解析',
      publish_prepare: '发布准备',
      publish_execute: '发布执行',
      publish_verify: '发布校验',
      retry_dispatch: '重试分发',
    };
    return map[key] || (key ? key : '未知阶段');
  }

  function codexFailureEvidenceUrl(path) {
    const value = safe(path).trim();
    if (!value) return '';
    if (/^https?:\/\//i.test(value)) return value;
    return '/api/runtime-file?path=' + encodeURIComponent(value);
  }

  async function dispatchCodexFailureRetry(action, context) {
    const retryAction = action && typeof action === 'object' ? action : {};
    const kind = safe(retryAction.kind).trim();
    const payload = retryAction.payload && typeof retryAction.payload === 'object' ? retryAction.payload : {};
    const ctx = context && typeof context === 'object' ? context : {};
    if (!kind) {
      throw new Error('缺少 retry_action.kind');
    }
    if (retryAction.retryable === false) {
      throw new Error(safe(retryAction.blocked_reason).trim() || '当前失败不允许重试');
    }
    if (kind === 'retry_policy_analysis') {
      const request = ctx.request && typeof ctx.request === 'object' ? Object.assign({}, ctx.request) : {};
      const agentName = safe(request.agent_name || payload.agent_name || selectedAgent()).trim();
      const rootInput = $('agentSearchRoot');
      const requestPayload = Object.assign({}, request, {
        agent_name: agentName,
        agent_search_root: safe(request.agent_search_root || (rootInput && rootInput.value) || '').trim(),
      });
      const data = await postJSON('/api/policy/analyze', requestPayload);
      if (typeof ctx.onPolicyResult === 'function') {
        await ctx.onPolicyResult(data, requestPayload);
      } else if (typeof openPolicyConfirmModal === 'function') {
        openPolicyConfirmModal(data.policy_confirmation || data, requestPayload);
      }
      return data;
    }
    if (kind === 'retry_session_round') {
      if (typeof runTask !== 'function') {
        throw new Error('前端未加载会话任务重试能力');
      }
      return runTask(true);
    }
    if (kind === 'retry_role_creation_analysis') {
      const sessionId = safe(ctx.sessionId || payload.session_id || state.tcRoleCreationSelectedSessionId).trim();
      if (!sessionId) {
        throw new Error('缺少角色创建 session_id');
      }
      const data = await postJSON(
        '/api/training/role-creation/sessions/' + encodeURIComponent(sessionId) + '/retry-analysis',
        { operator: 'web-user' },
      );
      if (typeof applyRoleCreationDetailPayload === 'function') {
        applyRoleCreationDetailPayload(data, { skipRender: true });
      }
      if (typeof renderRoleCreationWorkbench === 'function') {
        renderRoleCreationWorkbench();
      }
      return data;
    }
    if (kind === 'retry_release_review') {
      if (typeof enterTrainingCenterReleaseReview !== 'function') {
        throw new Error('前端未加载发布评审重试能力');
      }
      return enterTrainingCenterReleaseReview();
    }
    if (kind === 'retry_publish') {
      if (typeof confirmTrainingCenterReleaseReview !== 'function') {
        throw new Error('前端未加载发布重试能力');
      }
      return confirmTrainingCenterReleaseReview();
    }
    if (kind === 'rerun_assignment_node') {
      const ticketId = safe(ctx.ticketId || payload.ticket_id).trim();
      const nodeId = safe(ctx.nodeId || payload.node_id).trim();
      if (!ticketId || !nodeId) {
        throw new Error('缺少任务节点重跑参数');
      }
      if (
        typeof selectedAssignmentTicketId === 'function' &&
        typeof selectedAssignmentNode === 'function' &&
        typeof rerunSelectedAssignmentNode === 'function' &&
        ticketId === safe(selectedAssignmentTicketId()).trim() &&
        nodeId === safe((selectedAssignmentNode() || {}).node_id).trim()
      ) {
        return rerunSelectedAssignmentNode();
      }
      const data = await postJSON(
        '/api/assignments/' + encodeURIComponent(ticketId) + '/nodes/' + encodeURIComponent(nodeId) + '/rerun',
        { operator: 'web-user' },
      );
      if (typeof refreshAssignmentGraphData === 'function') {
        await refreshAssignmentGraphData({ ticketId: ticketId });
      }
      if (typeof maybeDispatchAssignmentTicket === 'function') {
        await maybeDispatchAssignmentTicket(ticketId);
      }
      return data;
    }
    throw new Error('未知重试动作：' + kind);
  }

  function renderCodexFailureCard(host, rawFailure, options) {
    const target = host && typeof host === 'object' ? host : null;
    if (!target) return false;
    const failure = normalizeCodexFailure(rawFailure);
    target.innerHTML = '';
    if (!failure) return false;
    const opts = options && typeof options === 'object' ? options : {};
    const card = document.createElement('section');
    card.className = 'codex-failure-card' + (opts.compact ? ' compact' : '');
    const head = document.createElement('div');
    head.className = 'codex-failure-head';
    const titleNode = document.createElement('div');
    titleNode.className = 'codex-failure-title';
    titleNode.textContent = safe(opts.title).trim() || '失败治理';
    head.appendChild(titleNode);
    const stageNode = document.createElement('span');
    stageNode.className = 'codex-failure-stage';
    stageNode.textContent = codexFailureStageText(failure.failure_stage);
    head.appendChild(stageNode);
    card.appendChild(head);

    const messageNode = document.createElement('div');
    messageNode.className = 'codex-failure-message';
    messageNode.textContent = failure.failure_message || '执行失败';
    card.appendChild(messageNode);

    const meta = document.createElement('div');
    meta.className = 'codex-failure-meta';
    [
      ['失败阶段', codexFailureStageText(failure.failure_stage)],
      ['最近尝试', failure.failed_at ? formatDateTime(failure.failed_at) : '-'],
      ['尝试次数', String(failure.attempt_count)],
    ].forEach((entry) => {
      const row = document.createElement('div');
      row.className = 'codex-failure-meta-row';
      const label = document.createElement('span');
      label.className = 'codex-failure-meta-label';
      label.textContent = entry[0];
      const value = document.createElement('span');
      value.className = 'codex-failure-meta-value';
      value.textContent = entry[1];
      row.appendChild(label);
      row.appendChild(value);
      meta.appendChild(row);
    });
    card.appendChild(meta);

    if (failure.trace_refs.length) {
      const evidence = document.createElement('div');
      evidence.className = 'codex-failure-evidence';
      const evidenceTitle = document.createElement('div');
      evidenceTitle.className = 'codex-failure-subtitle';
      evidenceTitle.textContent = '证据';
      evidence.appendChild(evidenceTitle);
      failure.trace_refs.forEach((item) => {
        const link = document.createElement('a');
        link.className = 'codex-failure-evidence-link';
        link.href = codexFailureEvidenceUrl(item.path);
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = safe(item.label).trim() + ' · ' + safe(item.path).trim();
        evidence.appendChild(link);
      });
      card.appendChild(evidence);
    }

    const suggestionNode = document.createElement('div');
    suggestionNode.className = 'codex-failure-suggestion';
    suggestionNode.textContent = failure.next_step_suggestion || '建议先处理失败原因后再继续。';
    card.appendChild(suggestionNode);

    const actionRow = document.createElement('div');
    actionRow.className = 'codex-failure-actions';
    const inlineError = document.createElement('div');
    inlineError.className = 'codex-failure-inline-error';
    if (failure.retryable && failure.retry_action.kind) {
      const retryBtn = document.createElement('button');
      retryBtn.type = 'button';
      retryBtn.className = 'alt';
      retryBtn.textContent = failure.retry_action.label || '重试';
      retryBtn.onclick = async () => {
        retryBtn.disabled = true;
        inlineError.textContent = '';
        try {
          await dispatchCodexFailureRetry(failure.retry_action, opts.context || {});
          if (typeof opts.onRetrySuccess === 'function') {
            await opts.onRetrySuccess(failure);
          }
        } catch (err) {
          const text = safe(err && err.message ? err.message : err).trim() || '重试失败';
          inlineError.textContent = text;
          if (typeof opts.onRetryError === 'function') {
            opts.onRetryError(err, failure);
          }
        } finally {
          retryBtn.disabled = false;
        }
      };
      actionRow.appendChild(retryBtn);
    } else {
      const blocked = document.createElement('div');
      blocked.className = 'codex-failure-blocked';
      blocked.textContent = safe(failure.retry_action.blocked_reason).trim() || '当前不允许自动重试';
      actionRow.appendChild(blocked);
    }
    actionRow.appendChild(inlineError);
    card.appendChild(actionRow);

    target.appendChild(card);
    return true;
  }
