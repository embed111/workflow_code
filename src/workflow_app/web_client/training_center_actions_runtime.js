  // Training center action runtime helpers.
  function trainingCenterPlanPayload() {
    return {
      target_agent_id: trainingCenterSelectedTargetAgent(),
      capability_goal: safe($('tcPlanGoalInput') ? $('tcPlanGoalInput').value : '').trim(),
      training_tasks: parseTrainingTasksInput(),
      acceptance_criteria: safe($('tcPlanAcceptanceInput') ? $('tcPlanAcceptanceInput').value : '').trim(),
      priority: safe($('tcPlanPrioritySelect') ? $('tcPlanPrioritySelect').value : '').trim(),
      execution_engine: 'workflow_native',
      operator: 'web-user',
      created_by: 'web-user',
    };
  }

  async function enqueueTrainingCenterPlan(source) {
    const mode = safe(source).toLowerCase() === 'auto_analysis' ? 'auto_analysis' : 'manual';
    const payload = trainingCenterPlanPayload();
    const endpoint = mode === 'manual' ? '/api/training/plans/manual' : '/api/training/plans/auto';
    const data = await postJSON(endpoint, payload);
    setTrainingCenterError('');
    setTrainingCenterRunResult(data);
    await refreshTrainingCenterQueue();
    await refreshTrainingCenterAgents();
    return data;
  }

  async function submitTrainingCenterPlanFromLoop(action) {
    const mode = safe(action).toLowerCase() === 'start' ? 'start' : 'draft';
    const created = await enqueueTrainingCenterPlan('manual');
    const queueTaskId = safe(created && created.queue_task_id).trim();
    if (!queueTaskId) {
      renderTrainingLoop();
      return created;
    }
    state.tcLoopSelectedQueueTaskId = queueTaskId;
    state.tcLoopSelectedNodeId = queueTaskId;
    state.tcLoopMode = 'status';
    state.tcLoopStatusTab = 'overview';
    if (mode === 'start') {
      await executeTrainingCenterQueueTask(queueTaskId);
    }
    await refreshTrainingLoopServerData(queueTaskId, { force: true });
    renderTrainingCenterQueue();
    renderTrainingLoop();
    return created;
  }

  async function renameTrainingCenterQueueTask(queueTaskId, nextTitle) {
    const qid = safe(queueTaskId).trim();
    if (!qid) throw new Error('请先选择训练任务');
    const title = safe(nextTitle).trim();
    if (!title) throw new Error('任务名称不能为空');
    const data = await postJSON('/api/training/queue/' + encodeURIComponent(qid) + '/rename', {
      capability_goal: title,
      operator: 'web-user',
    });
    setTrainingCenterError('');
    setTrainingCenterRunResult(data);
    await refreshTrainingCenterQueue();
  }

  async function removeTrainingCenterQueueTask(queueTaskId) {
    const data = await postJSON('/api/training/queue/' + encodeURIComponent(queueTaskId) + '/remove', {
      operator: 'web-user',
      reason: 'manual_remove_from_ui',
    });
    setTrainingCenterError('');
    setTrainingCenterRunResult(data);
    await refreshTrainingCenterQueue(false);
    await refreshTrainingCenterAgents();
  }

  async function executeTrainingCenterQueueTask(queueTaskId) {
    const data = await postJSON('/api/training/queue/' + encodeURIComponent(queueTaskId) + '/execute', {
      operator: 'web-user',
    });
    setTrainingCenterError('');
    setTrainingCenterRunResult(data);
    if (safe(data.run_id)) {
      const run = await getJSON('/api/training/runs/' + encodeURIComponent(safe(data.run_id)));
      setTrainingCenterRunResult(run);
    }
    await refreshTrainingCenterQueue(false);
    await refreshTrainingCenterAgents();
    if (safe(state.tcLoopSelectedQueueTaskId).trim() === safe(queueTaskId).trim()) {
      await refreshTrainingLoopServerData(queueTaskId, { force: true });
    }
  }

  async function dispatchNextTrainingCenterQueue() {
    const data = await postJSON('/api/training/queue/dispatch-next', {
      operator: 'web-user',
    });
    setTrainingCenterError('');
    setTrainingCenterRunResult(data);
    await refreshTrainingCenterQueue(false);
    await refreshTrainingCenterAgents();
  }

  function selectedTrainingCenterAgentId() {
    const fromState = safe(state.tcSelectedAgentId).trim();
    if (fromState) return fromState;
    return safe(trainingCenterSelectedTargetAgent()).trim();
  }

  async function switchTrainingCenterAgentVersion() {
    const agentId = selectedTrainingCenterAgentId();
    if (!agentId) throw new Error('请先选择角色');
    const versionLabel = safe($('tcSwitchVersionSelect') ? $('tcSwitchVersionSelect').value : '').trim();
    if (!versionLabel) throw new Error('请选择已发布版本');
    const currentVersion = currentTrainingCenterDisplayedVersion(state.tcSelectedAgentDetail || {});
    if (versionLabel === currentVersion) {
      return null;
    }
    const data = await postJSON('/api/training/agents/' + encodeURIComponent(agentId) + '/switch', {
      version_label: versionLabel,
      operator: 'web-user',
    });
    setTrainingCenterDetailError('');
    setTrainingCenterAgentActionResult(data);
    setTrainingCenterRunResult(data);
    await refreshTrainingCenterAgents();
    await refreshTrainingCenterQueue(false);
  }

  async function cloneTrainingCenterAgentFromCurrent() {
    const agentId = selectedTrainingCenterAgentId();
    if (!agentId) throw new Error('请先选择角色');
    const newAgentName = safe($('tcCloneAgentNameInput') ? $('tcCloneAgentNameInput').value : '').trim();
    if (!newAgentName) throw new Error('克隆角色名称必填');
    const data = await postJSON('/api/training/agents/' + encodeURIComponent(agentId) + '/clone', {
      new_agent_name: newAgentName,
      operator: 'web-user',
    });
    state.tcSelectedAgentId = safe(data.agent_id || '').trim();
    state.tcSelectedAgentName = safe(data.agent_name || '').trim();
    setTrainingCenterDetailError('');
    setTrainingCenterAgentActionResult(data);
    setTrainingCenterRunResult(data);
    await refreshTrainingCenterAgents();
    await refreshTrainingCenterQueue(false);
  }

  async function setTrainingCenterAgentAvatar() {
    const agentId = selectedTrainingCenterAgentId();
    if (!agentId) throw new Error('请先选择角色');
    const fileInput = $('tcAvatarFileInput');
    const file = fileInput && fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
    if (!file) throw new Error('请选择本地头像文件');
    const name = safe(file.name).trim();
    const ext = name.includes('.') ? safe(name.split('.').pop()).toLowerCase() : '';
    if (!['png', 'jpg', 'jpeg', 'webp'].includes(ext)) {
      throw new Error('头像格式仅支持 png/jpg/webp');
    }
    const size = Number(file.size) || 0;
    if (size <= 0) {
      throw new Error('头像文件内容为空');
    }
    if (size > 2 * 1024 * 1024) {
      throw new Error('头像文件超过 2MB 限制');
    }
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(safe(reader.result));
      reader.onerror = () => reject(new Error('头像文件读取失败'));
      reader.readAsDataURL(file);
    });
    const rawUrl = safe(dataUrl).trim();
    const splitIndex = rawUrl.indexOf(',');
    if (splitIndex <= 0) {
      throw new Error('头像文件读取失败');
    }
    const meta = rawUrl.slice(0, splitIndex);
    const payloadBase64 = rawUrl.slice(splitIndex + 1);
    const contentType = meta.replace(/^data:/i, '').replace(/;base64$/i, '').trim();
    try {
      const data = await postJSON('/api/training/agents/' + encodeURIComponent(agentId) + '/avatar', {
        upload_name: name,
        upload_content_type: contentType || safe(file.type),
        upload_base64: payloadBase64,
        operator: 'web-user',
      });
      if (fileInput) {
        fileInput.value = '';
      }
      setTrainingCenterDetailError('');
      setTrainingCenterAgentActionResult(data);
      setTrainingCenterRunResult(data);
      await refreshTrainingCenterAgents();
    } catch (err) {
      renderTrainingCenterAvatarPreview(state.tcSelectedAgentDetail || {});
      throw err;
    }
  }

  async function discardTrainingCenterPreRelease() {
    const agentId = selectedTrainingCenterAgentId();
    if (!agentId) throw new Error('请先选择角色');
    if (!hasTrainingCenterPublishedRelease(state.tcSelectedAgentDetail || {})) {
      throw new Error('没有首个发布版本，不能舍弃修改');
    }
    const data = await postJSON(
      '/api/training/agents/' + encodeURIComponent(agentId) + '/pre-release/discard',
      {
        operator: 'web-user',
      }
    );
    setTrainingCenterDetailError('');
    setTrainingCenterAgentActionResult(data);
    setTrainingCenterRunResult(data);
    await refreshTrainingCenterAgents();
    await refreshTrainingCenterQueue(false);
  }

  async function enterTrainingCenterReleaseReview() {
    const agentId = selectedTrainingCenterAgentId();
    if (!agentId) throw new Error('请先选择角色');
    startTrainingCenterReleaseReviewProgress(agentId, 'enter');
    try {
      const data = await postJSON(
        '/api/training/agents/' + encodeURIComponent(agentId) + '/release-review/enter',
        {
          operator: 'web-user',
        }
      );
      if (!state.tcReleaseReviewByAgent || typeof state.tcReleaseReviewByAgent !== 'object') {
        state.tcReleaseReviewByAgent = {};
      }
      state.tcReleaseReviewByAgent[agentId] = normalizeTrainingCenterReleaseReviewPayload(agentId, data);
      finishTrainingCenterReleaseReviewProgress(agentId);
      setTrainingCenterDetailError('');
      setTrainingCenterAgentActionResult(data);
      setTrainingCenterRunResult(data);
      renderTrainingCenterReleaseReview(agentId);
      await refreshTrainingCenterAgents();
    } catch (err) {
      failTrainingCenterReleaseReviewProgress(agentId, err);
      throw err;
    }
  }

  async function discardTrainingCenterReleaseReview() {
    const agentId = selectedTrainingCenterAgentId();
    if (!agentId) throw new Error('请先选择角色');
    const reason = safe($('tcEvalSummaryInput') ? $('tcEvalSummaryInput').value : '').trim();
    const data = await postJSON(
      '/api/training/agents/' + encodeURIComponent(agentId) + '/release-review/discard',
      {
        operator: 'web-user',
        reason: reason,
      }
    );
    if (!state.tcReleaseReviewByAgent || typeof state.tcReleaseReviewByAgent !== 'object') {
      state.tcReleaseReviewByAgent = {};
    }
    state.tcReleaseReviewByAgent[agentId] = normalizeTrainingCenterReleaseReviewPayload(agentId, data);
    setTrainingCenterDetailError('');
    setTrainingCenterAgentActionResult(data);
    setTrainingCenterRunResult(data);
    renderTrainingCenterReleaseReview(agentId);
    await refreshTrainingCenterAgents();
  }

  async function submitTrainingCenterManualEvaluation() {
    const agentId = selectedTrainingCenterAgentId();
    if (!agentId) throw new Error('请先选择角色');
    const decision = safe($('tcEvalDecisionSelect') ? $('tcEvalDecisionSelect').value : '').trim();
    const reviewer = safe($('tcEvalReviewerInput') ? $('tcEvalReviewerInput').value : '').trim();
    const summary = safe($('tcEvalSummaryInput') ? $('tcEvalSummaryInput').value : '').trim();
    if (decision === 'reject_discard_pre_release' && !hasTrainingCenterPublishedRelease(state.tcSelectedAgentDetail || {})) {
      throw new Error('没有首个发布版本，不能舍弃修改');
    }
    const data = await postJSON(
      '/api/training/agents/' + encodeURIComponent(agentId) + '/release-review/manual',
      {
        decision: decision,
        reviewer: reviewer,
        review_comment: summary,
        operator: 'web-user',
      }
    );
    if (!state.tcReleaseReviewByAgent || typeof state.tcReleaseReviewByAgent !== 'object') {
      state.tcReleaseReviewByAgent = {};
    }
    state.tcReleaseReviewByAgent[agentId] = normalizeTrainingCenterReleaseReviewPayload(agentId, data);
    setTrainingCenterDetailError('');
    setTrainingCenterAgentActionResult(data);
    setTrainingCenterRunResult(data);
    renderTrainingCenterReleaseReview(agentId);
    await refreshTrainingCenterAgents();
  }

  async function confirmTrainingCenterReleaseReview() {
    const agentId = selectedTrainingCenterAgentId();
    if (!agentId) throw new Error('请先选择角色');
    startTrainingCenterReleaseReviewProgress(agentId, 'confirm');
    try {
      const data = await postJSON(
        '/api/training/agents/' + encodeURIComponent(agentId) + '/release-review/confirm',
        {
          operator: 'web-user',
        }
      );
      if (!state.tcReleaseReviewByAgent || typeof state.tcReleaseReviewByAgent !== 'object') {
        state.tcReleaseReviewByAgent = {};
      }
      state.tcReleaseReviewByAgent[agentId] = normalizeTrainingCenterReleaseReviewPayload(agentId, data);
      finishTrainingCenterReleaseReviewProgress(agentId);
      setTrainingCenterDetailError('');
      setTrainingCenterAgentActionResult(data);
      setTrainingCenterRunResult(data);
      renderTrainingCenterReleaseReview(agentId);
      await refreshTrainingCenterAgents();
    } catch (err) {
      failTrainingCenterReleaseReviewProgress(agentId, err);
      throw err;
    }
  }

