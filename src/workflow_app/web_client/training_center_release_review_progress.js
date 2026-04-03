  // Training center release review progress helpers.

  // Training center release review helpers and rendering.

  function defaultTrainingCenterReleaseReview(agentLike) {
    const detail = agentLike && typeof agentLike === 'object' ? agentLike : {};
    const lifecycleState = safe(detail.lifecycle_state || 'released').trim().toLowerCase() || 'released';
    return {
      review_id: '',
      agent_id: safe(detail.agent_id).trim(),
      agent_name: safe(detail.agent_name).trim(),
      release_review_state: 'idle',
      target_version: '',
      current_workspace_ref: safe(detail.current_version).trim(),
      prompt_version: '',
      analysis_chain: {},
      report: {},
      report_error: '',
      report_error_code: '',
      report_missing_fields: [],
      required_report_fields: [],
      review_decision: '',
      reviewer: '',
      review_comment: '',
      reviewed_at: '',
      publish_version: '',
      publish_status: '',
      publish_error: '',
      codex_failure: null,
      publish_codex_failure: null,
      execution_logs: [],
      fallback: {},
      created_at: '',
      updated_at: '',
      can_enter: lifecycleState === 'pre_release',
      can_discard: false,
      can_review: false,
      can_confirm: false,
      publish_succeeded: false,
      lifecycle_state: lifecycleState,
    };
  }

  function normalizeTrainingCenterReleaseReviewPayload(agentId, payload) {
    const detail = trainingCenterAgentDetailById(agentId);
    const rawReview =
      payload && payload.review && typeof payload.review === 'object'
        ? payload.review
        : payload && typeof payload === 'object'
          ? payload
          : {};
    const review = Object.assign({}, defaultTrainingCenterReleaseReview(detail), rawReview || {});
    review.analysis_chain =
      rawReview && rawReview.analysis_chain && typeof rawReview.analysis_chain === 'object'
        ? rawReview.analysis_chain
        : {};
    review.report =
      rawReview && rawReview.report && typeof rawReview.report === 'object'
        ? rawReview.report
        : {};
    review.report_error_code = safe(rawReview && rawReview.report_error_code).trim();
    review.report_missing_fields =
      rawReview && Array.isArray(rawReview.report_missing_fields)
        ? rawReview.report_missing_fields.map((item) => safe(item).trim()).filter(Boolean)
        : [];
    review.required_report_fields =
      rawReview && Array.isArray(rawReview.required_report_fields)
        ? rawReview.required_report_fields.map((item) => safe(item).trim()).filter(Boolean)
        : [];
    review.execution_logs =
      rawReview && Array.isArray(rawReview.execution_logs)
        ? rawReview.execution_logs
        : [];
    review.fallback =
      rawReview && rawReview.fallback && typeof rawReview.fallback === 'object'
        ? rawReview.fallback
        : {};
    review.agent_id = safe(review.agent_id || agentId).trim();
    review.agent_name = safe(review.agent_name || detail.agent_name).trim();
    review.release_review_state = safe(review.release_review_state || 'idle').trim() || 'idle';
    review.review_decision = safe(review.review_decision).trim();
    review.publish_status = safe(review.publish_status).trim();
    review.codex_failure = normalizeCodexFailure(rawReview && rawReview.codex_failure);
    review.publish_codex_failure = normalizeCodexFailure(rawReview && rawReview.publish_codex_failure);
    review.lifecycle_state = safe(review.lifecycle_state || detail.lifecycle_state || 'released').trim().toLowerCase() || 'released';
    review.can_enter = !!review.can_enter;
    review.can_discard = !!review.can_discard;
    review.can_review = !!review.can_review;
    review.can_confirm = !!review.can_confirm;
    review.publish_succeeded = !!review.publish_succeeded;
    return review;
  }

  function currentTrainingCenterReleaseReview(agentId) {
    const key = safe(agentId).trim();
    const store =
      state.tcReleaseReviewByAgent && typeof state.tcReleaseReviewByAgent === 'object'
        ? state.tcReleaseReviewByAgent
        : {};
    if (key && store[key] && typeof store[key] === 'object') {
      return normalizeTrainingCenterReleaseReviewPayload(key, store[key]);
    }
    return normalizeTrainingCenterReleaseReviewPayload(key, {});
  }

  function trainingCenterReleaseReviewIsActive(review) {
    const node = review && typeof review === 'object' ? review : {};
    const reviewId = safe(node.review_id).trim();
    const stateKey = safe(node.release_review_state).trim().toLowerCase();
    if (!reviewId) return false;
    return stateKey !== 'idle' && stateKey !== 'review_discarded';
  }

  function trainingCenterReleaseReviewProgressTemplates(mode) {
    const key = safe(mode).trim().toLowerCase();
    if (key === 'confirm') {
      return [
        {
          key: 'prepare',
          label: '准备发布',
          detail: '正在整理目标版本、release note 与工作区上下文',
          handoff_after_ms: 800,
        },
        {
          key: 'git_execute',
          label: 'Git / release note',
          detail: '正在执行 Git 提交、打标签与 release note 处理',
          handoff_after_ms: 3200,
        },
        {
          key: 'verify',
          label: '发布后校验',
          detail: '正在按当前版本识别规则回读并校验发布结果',
          handoff_after_ms: 0,
        },
      ];
    }
    return [
      {
        key: 'enter',
        label: '创建评审记录',
        detail: '正在进入发布评审并创建评审记录',
        handoff_after_ms: 700,
      },
      {
        key: 'codex',
        label: 'Codex 生成报告',
        detail: '正在委派工作区 agent 生成结构化发布报告，并在完成后回填分析链路与报告结果',
        handoff_after_ms: 0,
      },
    ];
  }

  function currentTrainingCenterReleaseReviewProgress(agentId) {
    const key = safe(agentId).trim();
    const store =
      state.tcReleaseReviewProgressByAgent && typeof state.tcReleaseReviewProgressByAgent === 'object'
        ? state.tcReleaseReviewProgressByAgent
        : {};
    const progress = key && store[key] && typeof store[key] === 'object' ? store[key] : null;
    return progress || null;
  }

  function currentTrainingCenterReleaseReviewError(agentId) {
    const key = safe(agentId).trim();
    const store =
      state.tcReleaseReviewErrorByAgent && typeof state.tcReleaseReviewErrorByAgent === 'object'
        ? state.tcReleaseReviewErrorByAgent
        : {};
    const item = key && store[key] && typeof store[key] === 'object' ? store[key] : null;
    return item || null;
  }

  function clearTrainingCenterReleaseReviewError(agentId) {
    const key = safe(agentId).trim();
    if (!key) return;
    const store =
      state.tcReleaseReviewErrorByAgent && typeof state.tcReleaseReviewErrorByAgent === 'object'
        ? state.tcReleaseReviewErrorByAgent
        : {};
    if (store[key]) {
      delete store[key];
    }
  }

  function clearTrainingCenterReleaseReviewProgressTickerIfIdle() {
    const store =
      state.tcReleaseReviewProgressByAgent && typeof state.tcReleaseReviewProgressByAgent === 'object'
        ? state.tcReleaseReviewProgressByAgent
        : {};
    const hasRunning = Object.keys(store).some((agentId) => {
      const item = store[agentId];
      return !!(item && item.active);
    });
    if (!hasRunning && state.tcReleaseReviewProgressTicker) {
      window.clearInterval(state.tcReleaseReviewProgressTicker);
      state.tcReleaseReviewProgressTicker = 0;
    }
  }

  function ensureTrainingCenterReleaseReviewProgressTicker() {
    if (state.tcReleaseReviewProgressTicker) return;
    state.tcReleaseReviewProgressTicker = window.setInterval(() => {
      const selectedAgentId = safe(state.tcSelectedAgentId).trim();
      if (selectedAgentId && currentTrainingCenterReleaseReviewProgress(selectedAgentId)) {
        renderTrainingCenterReleaseReview(selectedAgentId);
      }
      clearTrainingCenterReleaseReviewProgressTickerIfIdle();
    }, 480);
  }

  function startTrainingCenterReleaseReviewProgress(agentId, mode) {
    const key = safe(agentId).trim();
    if (!key) return null;
    if (!state.tcReleaseReviewProgressByAgent || typeof state.tcReleaseReviewProgressByAgent !== 'object') {
      state.tcReleaseReviewProgressByAgent = {};
    }
    if (!state.tcReleaseReviewErrorByAgent || typeof state.tcReleaseReviewErrorByAgent !== 'object') {
      state.tcReleaseReviewErrorByAgent = {};
    }
    clearTrainingCenterReleaseReviewError(key);
    const progress = {
      agent_id: key,
      mode: safe(mode).trim().toLowerCase() || 'enter',
      active: true,
      failed: false,
      error_message: '',
      started_at_ms: Date.now(),
      finished_at_ms: 0,
      stages: trainingCenterReleaseReviewProgressTemplates(mode),
    };
    state.tcReleaseReviewProgressByAgent[key] = progress;
    ensureTrainingCenterReleaseReviewProgressTicker();
    if (safe(state.tcSelectedAgentId).trim() === key) {
      renderTrainingCenterReleaseReview(key);
    }
    return progress;
  }

  function finishTrainingCenterReleaseReviewProgress(agentId) {
    const key = safe(agentId).trim();
    if (!key) return;
    clearTrainingCenterReleaseReviewError(key);
    const store =
      state.tcReleaseReviewProgressByAgent && typeof state.tcReleaseReviewProgressByAgent === 'object'
        ? state.tcReleaseReviewProgressByAgent
        : {};
    if (store[key]) {
      delete store[key];
    }
    if (safe(state.tcSelectedAgentId).trim() === key) {
      renderTrainingCenterReleaseReview(key);
    }
    clearTrainingCenterReleaseReviewProgressTickerIfIdle();
  }

  function failTrainingCenterReleaseReviewProgress(agentId, errorLike) {
    const key = safe(agentId).trim();
    if (!key) return;
    const current = currentTrainingCenterReleaseReviewProgress(key);
    if (!current) return;
    if (!state.tcReleaseReviewErrorByAgent || typeof state.tcReleaseReviewErrorByAgent !== 'object') {
      state.tcReleaseReviewErrorByAgent = {};
    }
    const data = errorLike && errorLike.data && typeof errorLike.data === 'object' ? errorLike.data : {};
    const message = safe(errorLike && errorLike.message ? errorLike.message : errorLike).trim();
    current.active = false;
    current.failed = true;
    current.error_message = message;
    current.finished_at_ms = Date.now();
    state.tcReleaseReviewErrorByAgent[key] = {
      mode: safe(current.mode).trim().toLowerCase(),
      error_message: safe(current.error_message).trim(),
      error_code: safe(errorLike && errorLike.code).trim().toLowerCase(),
      error_reason: safe(data.reason).trim(),
      error_status: Number(errorLike && errorLike.status) || 0,
      error_data: data,
      failed_at_ms: current.finished_at_ms,
    };
    if (safe(state.tcSelectedAgentId).trim() === key) {
      renderTrainingCenterReleaseReview(key);
    }
    window.setTimeout(() => {
      const latest = currentTrainingCenterReleaseReviewProgress(key);
      if (latest !== current) return;
      finishTrainingCenterReleaseReviewProgress(key);
    }, 2600);
    clearTrainingCenterReleaseReviewProgressTickerIfIdle();
  }

  function describeTrainingCenterReleaseReviewProgress(progress) {
    const node = progress && typeof progress === 'object' ? progress : {};
    const stages = Array.isArray(node.stages) ? node.stages : [];
    if (!stages.length) {
      return {
        active: !!node.active,
        failed: !!node.failed,
        elapsed_ms: 0,
        headline: '',
        detail: '',
        items: [],
      };
    }
    const nowMs = Date.now();
    const startedAtMs = Number(node.started_at_ms || nowMs);
    const finishedAtMs = Number(node.finished_at_ms || 0);
    const elapsedMs = node.active
      ? Math.max(0, nowMs - startedAtMs)
      : Math.max(0, (finishedAtMs || nowMs) - startedAtMs);
    let currentIndex = 0;
    let cursorMs = 0;
    for (let i = 0; i < stages.length - 1; i += 1) {
      cursorMs += Math.max(0, Number(stages[i] && stages[i].handoff_after_ms) || 0);
      if (elapsedMs < cursorMs) {
        currentIndex = i;
        break;
      }
      currentIndex = i + 1;
    }
    const items = stages.map((stage, index) => {
      let status = 'pending';
      if (node.failed) {
        status = index < currentIndex ? 'done' : index === currentIndex ? 'failed' : 'pending';
      } else if (node.active) {
        status = index < currentIndex ? 'done' : index === currentIndex ? 'running' : 'pending';
      } else {
        status = 'done';
      }
      return {
        key: safe(stage && stage.key).trim(),
        label: safe(stage && stage.label).trim(),
        detail: safe(stage && stage.detail).trim(),
        status: status,
      };
    });
    const currentStage = items[currentIndex] || items[0];
    const modeText = safe(node.mode).trim().toLowerCase() === 'confirm' ? '确认发布' : '进入发布评审';
    const headline = node.failed
      ? modeText + '失败'
      : currentStage && currentStage.status === 'running'
        ? modeText + '运行中'
        : modeText + '处理中';
    const detail = node.failed
      ? safe(node.error_message).trim() || '执行失败，请稍后重试'
      : safe(currentStage && currentStage.detail).trim();
    return {
      active: !!node.active,
      failed: !!node.failed,
      elapsed_ms: elapsedMs,
      headline: headline,
      detail: detail,
      items: items,
    };
  }

  function renderTrainingCenterReleaseReviewProgress(host, progress) {
    if (!host) return;
    host.innerHTML = '';
    host.classList.remove('active');
    host.classList.remove('failed');
    if (!progress) return;
    const snapshot = describeTrainingCenterReleaseReviewProgress(progress);
    host.classList.add('active');
    if (snapshot.failed) host.classList.add('failed');

    const head = document.createElement('div');
    head.className = 'tc-release-review-progress-head';
    const title = document.createElement('div');
    title.className = 'tc-release-review-progress-title';
    const titleIcon = createStatusIcon(snapshot.failed ? 'failed' : 'spinner', {
      compact: true,
      spinning: !snapshot.failed,
    });
    title.appendChild(titleIcon);
    const titleText = document.createElement('span');
    titleText.textContent =
      snapshot.headline +
      ' · 已耗时 ' +
      (typeof formatDurationMs === 'function' ? formatDurationMs(snapshot.elapsed_ms) : Math.floor(snapshot.elapsed_ms / 1000) + 's');
    title.appendChild(titleText);
    head.appendChild(title);
    host.appendChild(head);

    const detail = document.createElement('div');
    detail.className = 'tc-release-review-progress-detail';
    detail.textContent = snapshot.detail || '请稍候...';
    host.appendChild(detail);

    const stageWrap = document.createElement('div');
    stageWrap.className = 'tc-release-review-progress-stages';
    snapshot.items.forEach((item) => {
      const node = document.createElement('div');
      node.className = 'tc-release-review-progress-stage ' + safe(item.status).trim();
      const iconBox = document.createElement('span');
      iconBox.className = 'tc-release-review-progress-stage-icon';
      iconBox.appendChild(
        createStatusIcon(
          item.status === 'done' ? 'success' : item.status === 'failed' ? 'failed' : item.status === 'running' ? 'spinner' : 'pending',
          {
            compact: true,
            spinning: item.status === 'running',
          }
        )
      );
      node.appendChild(iconBox);
      const textBox = document.createElement('span');
      textBox.className = 'tc-release-review-progress-stage-text';
      textBox.textContent = safe(item.label);
      node.appendChild(textBox);
      stageWrap.appendChild(node);
    });
    host.appendChild(stageWrap);
  }
