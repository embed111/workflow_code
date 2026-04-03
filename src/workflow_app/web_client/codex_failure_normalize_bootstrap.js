  function normalizeCodexFailure(raw) {
    const safeText = (value) => (value === null || value === undefined ? '' : String(value));
    const node = raw && typeof raw === 'object' ? raw : {};
    const retryActionRaw = node.retry_action && typeof node.retry_action === 'object' ? node.retry_action : {};
    const traceRefsRaw = Array.isArray(node.trace_refs) ? node.trace_refs : [];
    const traceRefs = traceRefsRaw
      .map((item) => {
        const row = item && typeof item === 'object' ? item : {};
        return {
          label: safeText(row.label).trim() || 'evidence',
          path: safeText(row.path).trim(),
        };
      })
      .filter((item) => !!item.path);
    const featureKey = safeText(node.feature_key).trim();
    const failureMessage = safeText(node.failure_message).trim();
    const failureDetailCode = safeText(node.failure_detail_code).trim().toLowerCase();
    if (!featureKey && !failureMessage && !failureDetailCode && !traceRefs.length) {
      return null;
    }
    const retryAction = {
      kind: safeText(retryActionRaw.kind).trim(),
      label: safeText(retryActionRaw.label).trim() || '重试',
      retryable: retryActionRaw.retryable !== false,
      blocked_reason: safeText(retryActionRaw.blocked_reason).trim(),
      payload: retryActionRaw.payload && typeof retryActionRaw.payload === 'object' ? retryActionRaw.payload : {},
    };
    if (!retryAction.kind) {
      retryAction.retryable = false;
    }
    return {
      feature_key: featureKey,
      attempt_id: safeText(node.attempt_id).trim(),
      attempt_count: Math.max(1, Number(node.attempt_count || 0) || 1),
      failure_code: safeText(node.failure_code).trim().toLowerCase(),
      failure_detail_code: failureDetailCode,
      failure_stage: safeText(node.failure_stage).trim().toLowerCase(),
      failure_message: failureMessage,
      retryable: !!node.retryable && retryAction.retryable,
      retry_action: retryAction,
      trace_refs: traceRefs,
      failed_at: safeText(node.failed_at).trim(),
      next_step_suggestion: safeText(node.next_step_suggestion).trim(),
    };
  }
