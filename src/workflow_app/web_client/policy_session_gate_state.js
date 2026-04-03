  function applyGateState() {
    const rootReady = !!state.agentSearchRootReady;
    const hasAgentOptions = visibleAgents().length > 0;
    const hasAgent = !!selectedAgent();
    const session = currentSession();
    const task = session ? state.runningTasks[session.session_id] : null;
    const sessionPolicyInfo = session ? resolveSessionPolicyGateInfo(session) : null;
    const sessionAnalysisCompleted = !session || !!(sessionPolicyInfo && sessionPolicyInfo.analysis_completed);
    const gate = safe(state.sessionPolicyGateState || 'idle_unselected');
    const analyzing = gate === 'analyzing_policy';
    const createEnabled =
      hasAgentOptions &&
      hasAgent &&
      (gate === 'policy_ready' || gate === 'policy_confirmed');
    const policyActionEnabled = hasAgentOptions && hasAgent && !analyzing && gate !== 'policy_cache_missing';
    const policyActionBtn = $('policyGateBtn');
    const clearCacheBtn = $('clearPolicyCacheBtn');
    const clearAllCacheBtn = $('clearAllPolicyCacheBtn');
    const regenerateCacheBtn = $('regeneratePolicyCacheBtn');
    const loadAgentsBtn = $('loadAgentsBtn');
    const agentSelectTrigger = $('agentSelectTrigger');
    const agentSelectSearch = $('agentSelectSearch');
    const reloadSessionsBtn = $('reloadSessionsBtn');
    const allowManualPolicyInputCheck = $('allowManualPolicyInputCheck');
    const cleanupHistoryBtn = $('cleanupHistoryBtn');
    const refreshWorkflowBtn = $('refreshWorkflowBtn');
    const refreshEventsBtn = $('refreshEventsBtn');
    const queueModeRecordsBtn = $('queueModeRecordsBtn');
    const queueModeTrainingBtn = $('queueModeTrainingBtn');
    const tcRootMeta = $('tcRootMeta');
    const tcRefreshAgentsBtn = $('tcRefreshAgentsBtn');
    const tcTabOpsBtn = $('tcTabOpsBtn');
    const tcEnterOpsBtn = $('tcEnterOpsBtn');
    const tcSaveAndStartBtn = $('tcSaveAndStartBtn');
    const tcSaveDraftBtn = $('tcSaveDraftBtn');
    const tcRefreshQueueBtn = $('tcRefreshQueueBtn');
    const tcDispatchNextBtn = $('tcDispatchNextBtn');
    const tcAgentSearchInput = $('tcAgentSearchInput');
    const tcPlanTargetAgentSelect = $('tcPlanTargetAgentSelect');
    const tcPlanGoalInput = $('tcPlanGoalInput');
    const tcPlanTasksInput = $('tcPlanTasksInput');
    const tcPlanAcceptanceInput = $('tcPlanAcceptanceInput');
    const tcPlanPrioritySelect = $('tcPlanPrioritySelect');
    const tcSwitchVersionSelect = $('tcSwitchVersionSelect');
    const tcSwitchVersionTrigger = $('tcSwitchVersionTrigger');
    const tcCloneAgentNameInput = $('tcCloneAgentNameInput');
    const tcCloneAgentBtn = $('tcCloneAgentBtn');
    const tcAvatarFileInput = $('tcAvatarFileInput');
    const tcSetAvatarBtn = $('tcSetAvatarBtn');
    const tcDiscardPreReleaseBtn = $('tcDiscardPreReleaseBtn');
    const tcDiscardReleaseReviewBtn = $('tcDiscardReleaseReviewBtn');
    const tcEvalDecisionSelect = $('tcEvalDecisionSelect');
    const tcEvalReviewerInput = $('tcEvalReviewerInput');
    const tcEvalSummaryInput = $('tcEvalSummaryInput');
    const tcSubmitEvalBtn = $('tcSubmitEvalBtn');
    const artifactRootPathInput = $('artifactRootPathInput');
    const switchArtifactRootBtn = $('switchArtifactRootBtn');
    const assignmentExecutionProviderSelect = $('assignmentExecutionProviderSelect');
    const assignmentCodexCommandPathInput = $('assignmentCodexCommandPathInput');
    const assignmentCommandTemplateInput = $('assignmentCommandTemplateInput');
    const assignmentExecutionConcurrencyInput = $('assignmentExecutionConcurrencyInput');
    const assignmentExecutionSaveBtn = $('assignmentExecutionSaveBtn');
    const assignmentPauseBtn = $('assignmentPauseBtn');
    const assignmentResumeBtn = $('assignmentResumeBtn');
    const assignmentCreateBtn = $('assignmentCreateBtn');
    const assignmentRefreshBtn = $('assignmentRefreshBtn');
    const assignmentLoadHistoryBtn = $('assignmentLoadHistoryBtn');
    const assignmentDrawerSubmitBtn = $('assignmentDrawerSubmitBtn');
    const assignmentTaskNameInput = $('assignmentTaskNameInput');
    const assignmentAgentSelect = $('assignmentAgentSelect');
    const assignmentPrioritySelect = $('assignmentPrioritySelect');
    const assignmentGoalInput = $('assignmentGoalInput');
    const assignmentArtifactInput = $('assignmentArtifactInput');
    const assignmentDeliveryModeSelect = $('assignmentDeliveryModeSelect');
    const assignmentDeliveryReceiverSelect = $('assignmentDeliveryReceiverSelect');
    const assignmentUpstreamSearch = $('assignmentUpstreamSearch');
    const messageInput = $('msg');
    const assignmentData = state.assignmentGraphData && typeof state.assignmentGraphData === 'object'
      ? state.assignmentGraphData
      : {};
    const assignmentOverview = assignmentData.graph && typeof assignmentData.graph === 'object'
      ? assignmentData.graph
      : null;
    const assignmentMetrics = assignmentOverview && assignmentOverview.metrics_summary && typeof assignmentOverview.metrics_summary === 'object'
      ? assignmentOverview.metrics_summary
      : assignmentData.metrics_summary && typeof assignmentData.metrics_summary === 'object'
      ? assignmentData.metrics_summary
      : {};
    const assignmentHasNodes = !!assignmentOverview && Number(assignmentMetrics.total_nodes || 0) > 0;
    const assignmentSchedulerState = safe(
      (assignmentOverview && assignmentOverview.scheduler_state) ||
      (state.assignmentScheduler && state.assignmentScheduler.state) ||
      'idle',
    ).trim().toLowerCase();
    const assignmentRunningNodeCount = Math.max(
      0,
      Number(
        (assignmentOverview &&
          assignmentOverview.scheduler &&
          assignmentOverview.scheduler.graph_running_node_count) ||
        (assignmentMetrics.status_counts || {}).running ||
        0
      ),
    );
    const assignmentDisplayState = typeof assignmentSchedulerDisplayState === 'function'
      ? assignmentSchedulerDisplayState(assignmentSchedulerState, assignmentRunningNodeCount)
      : { tone: assignmentSchedulerState };
    const assignmentIsEffectivelyRunning =
      assignmentDisplayState.tone === 'running' || assignmentDisplayState.tone === 'pause_pending';
    const assignmentCanResume =
      ['idle', 'paused'].includes(assignmentSchedulerState) ||
      (assignmentSchedulerState === 'running' && assignmentRunningNodeCount <= 0);
    const tcHasSelectedAgent = !!safe(state.tcSelectedAgentId).trim();
    const tcHasTargetAgent = !!trainingCenterSelectedTargetAgent();
    const tcSelectedDetail = state.tcSelectedAgentDetail || {};
    const tcAgentFrozen = safe(tcSelectedDetail.training_gate_state).toLowerCase() === 'frozen_switched';
    const tcAgentPreRelease = safe(tcSelectedDetail.lifecycle_state).toLowerCase() === 'pre_release';
    const tcReleaseRows =
      tcHasSelectedAgent && Array.isArray(state.tcReleasesByAgent[safe(state.tcSelectedAgentId).trim()])
        ? state.tcReleasesByAgent[safe(state.tcSelectedAgentId).trim()]
        : [];
    const tcHasPublishedRelease =
      tcReleaseRows.length > 0 ||
      !!safe(tcSelectedDetail.bound_release_version || tcSelectedDetail.latest_release_version).trim();

    if (reloadSessionsBtn) reloadSessionsBtn.disabled = !rootReady;
    if (allowManualPolicyInputCheck) allowManualPolicyInputCheck.disabled = !rootReady;
    if (artifactRootPathInput) artifactRootPathInput.disabled = !rootReady;
    if (switchArtifactRootBtn) switchArtifactRootBtn.disabled = !rootReady;
    if (assignmentExecutionProviderSelect) assignmentExecutionProviderSelect.disabled = !rootReady;
    if (assignmentCodexCommandPathInput) assignmentCodexCommandPathInput.disabled = !rootReady;
    if (assignmentCommandTemplateInput) assignmentCommandTemplateInput.disabled = !rootReady;
    if (assignmentExecutionConcurrencyInput) assignmentExecutionConcurrencyInput.disabled = !rootReady;
    if (assignmentExecutionSaveBtn) assignmentExecutionSaveBtn.disabled = !rootReady;
    if (cleanupHistoryBtn) cleanupHistoryBtn.disabled = !rootReady;
    if (refreshWorkflowBtn) refreshWorkflowBtn.disabled = !rootReady;
    if (refreshEventsBtn) refreshEventsBtn.disabled = !rootReady;
    if (queueModeRecordsBtn) queueModeRecordsBtn.disabled = !rootReady;
    if (queueModeTrainingBtn) queueModeTrainingBtn.disabled = !rootReady;
    if (tcRefreshAgentsBtn) tcRefreshAgentsBtn.disabled = !rootReady;
    if (tcTabOpsBtn) tcTabOpsBtn.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcEnterOpsBtn) tcEnterOpsBtn.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcSaveAndStartBtn) tcSaveAndStartBtn.disabled = !rootReady || !tcHasTargetAgent || tcAgentFrozen;
    if (tcSaveDraftBtn) tcSaveDraftBtn.disabled = !rootReady || !tcHasTargetAgent || tcAgentFrozen;
    if (tcRefreshQueueBtn) tcRefreshQueueBtn.disabled = !rootReady;
    if (tcDispatchNextBtn) tcDispatchNextBtn.disabled = !rootReady;
    if (tcAgentSearchInput) tcAgentSearchInput.disabled = !rootReady;
    if (tcPlanTargetAgentSelect) tcPlanTargetAgentSelect.disabled = !rootReady;
    if (tcPlanGoalInput) tcPlanGoalInput.disabled = !rootReady;
    if (tcPlanTasksInput) tcPlanTasksInput.disabled = !rootReady;
    if (tcPlanAcceptanceInput) tcPlanAcceptanceInput.disabled = !rootReady;
    if (tcPlanPrioritySelect) tcPlanPrioritySelect.disabled = !rootReady;
    if (tcSwitchVersionSelect) tcSwitchVersionSelect.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcSwitchVersionTrigger) tcSwitchVersionTrigger.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcSwitchVersionTrigger && tcSwitchVersionTrigger.disabled && state.tcVersionDropdownOpen) {
      setTrainingCenterVersionDropdownOpen(false);
    }
    if (tcCloneAgentNameInput) tcCloneAgentNameInput.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcCloneAgentBtn) tcCloneAgentBtn.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcAvatarFileInput) tcAvatarFileInput.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcSetAvatarBtn) tcSetAvatarBtn.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcDiscardPreReleaseBtn) {
      tcDiscardPreReleaseBtn.disabled = !rootReady || !tcHasSelectedAgent || !tcAgentPreRelease || !tcHasPublishedRelease;
    }
    if (tcDiscardReleaseReviewBtn) tcDiscardReleaseReviewBtn.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcEvalDecisionSelect) tcEvalDecisionSelect.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcEvalReviewerInput) tcEvalReviewerInput.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcEvalSummaryInput) tcEvalSummaryInput.disabled = !rootReady || !tcHasSelectedAgent;
    if (tcSubmitEvalBtn) tcSubmitEvalBtn.disabled = !rootReady || !tcHasSelectedAgent;
    if (assignmentPauseBtn) {
      assignmentPauseBtn.disabled =
        !rootReady || !assignmentHasNodes || !!state.assignmentLoading || !assignmentIsEffectivelyRunning;
    }
    if (assignmentResumeBtn) {
      assignmentResumeBtn.disabled =
        !rootReady ||
        !assignmentHasNodes ||
        !!state.assignmentLoading ||
        !assignmentCanResume;
    }
    if (assignmentCreateBtn) assignmentCreateBtn.disabled = !rootReady;
    if (assignmentRefreshBtn) assignmentRefreshBtn.disabled = !rootReady;
    if (assignmentLoadHistoryBtn) assignmentLoadHistoryBtn.disabled = !rootReady;
    if (assignmentDrawerSubmitBtn) assignmentDrawerSubmitBtn.disabled = !rootReady;
    if (assignmentTaskNameInput) assignmentTaskNameInput.disabled = !rootReady;
    if (assignmentAgentSelect) assignmentAgentSelect.disabled = !rootReady;
    if (assignmentPrioritySelect) assignmentPrioritySelect.disabled = !rootReady;
    if (assignmentGoalInput) assignmentGoalInput.disabled = !rootReady;
    if (assignmentArtifactInput) assignmentArtifactInput.disabled = !rootReady;
    if (assignmentDeliveryModeSelect) assignmentDeliveryModeSelect.disabled = !rootReady;
    if (assignmentDeliveryReceiverSelect) assignmentDeliveryReceiverSelect.disabled = !rootReady;
    if (assignmentUpstreamSearch) assignmentUpstreamSearch.disabled = !rootReady;
    if (tcRootMeta) {
      tcRootMeta.textContent = rootReady
        ? '训练对象是 agent 工作区能力，独立于会话流程'
        : 'agent路径未设置或无效，训练中心功能已锁定';
    }

    $('agentSelect').disabled = !rootReady || !hasAgentOptions || analyzing;
    if (agentSelectTrigger) {
      agentSelectTrigger.disabled = !rootReady || !hasAgentOptions || analyzing;
    }
    if (agentSelectSearch) {
      agentSelectSearch.disabled = !rootReady || !state.agentDropdownOpen || !hasAgentOptions || analyzing;
    }
    if (!rootReady || analyzing || !hasAgentOptions) {
      setAgentDropdownOpen(false);
    }
    $('newSessionBtn').disabled = !rootReady || !createEnabled || analyzing;
    if (loadAgentsBtn) {
      loadAgentsBtn.disabled = !rootReady || analyzing;
    }
    if (clearCacheBtn) {
      clearCacheBtn.disabled = !rootReady || !hasAgentOptions || !hasAgent || analyzing;
    }
    if (clearAllCacheBtn) {
      clearAllCacheBtn.disabled = !rootReady || !hasAgentOptions || analyzing;
    }
    if (regenerateCacheBtn) {
      regenerateCacheBtn.disabled = !rootReady || !hasAgentOptions || !hasAgent || analyzing;
    }
    if (policyActionBtn) {
      policyActionBtn.disabled = !rootReady || !policyActionEnabled;
      policyActionBtn.textContent = '角色与职责确认/兜底';
      const policyTitle =
        !rootReady
          ? 'agent路径未设置，当前功能已锁定'
          : gate === 'policy_cache_missing'
          ? '当前角色缓存为空，请先点击“生成缓存”图标'
          : '';
      policyActionBtn.title = policyTitle;
      policyActionBtn.setAttribute('aria-label', policyTitle || '角色与职责确认/兜底');
    }
    $('sendBtn').disabled = !rootReady || !hasAgentOptions || !hasAgent || !session || !!task || !sessionAnalysisCompleted;
    $('retryBtn').disabled = !rootReady || !hasAgentOptions || !hasAgent || !session || !!task || !sessionAnalysisCompleted;
    $('stopBtn').disabled = !rootReady || !session || !task;
    $('deleteSessionBtn').disabled = !rootReady || !session || !!task;
    if (messageInput) {
      messageInput.disabled = !rootReady || !session || !!task;
    }
    $('activeTaskInfo').textContent = '运行中任务: ' + activeTaskCount();
    renderRunningTaskPanel();
    renderGlobalRuntimeMetricLine();

    if (!rootReady) {
      setSessionPolicyGateState('idle_unselected', 'agent路径未设置，请先在设置页配置。', '');
      setChatError('agent路径未设置或无效，所有功能已禁用。请先在设置页配置。');
      setTrainingCenterError('agent路径未设置或无效，训练中心功能已锁定。');
      state.assignmentGraphs = [];
      state.assignmentSelectedTicketId = '';
      state.assignmentGraphData = null;
      state.assignmentSelectedNodeId = '';
      state.assignmentScheduler = null;
      state.assignmentActiveLoaded = 0;
      state.assignmentHistoryLoaded = 0;
      state.assignmentCreateOpen = false;
      state.assignmentDetail = null;
      state.assignmentLoading = false;
      setAssignmentError('agent路径未设置或无效，任务中心功能已锁定。');
      setAssignmentDetailError('');
      setAssignmentDrawerError('');
      renderAssignmentCenter();
      updateBatchActionState();
      return;
    }

    if (!hasAgentOptions) {
      setChatError('无可用 agent，禁止创建会话');
    } else if (!hasAgent) {
      setChatError('请先选择 agent');
    } else if (session && !sessionAnalysisCompleted) {
      const target = safe((sessionPolicyInfo && sessionPolicyInfo.agent_name) || session.agent_name).trim();
      const reason = safe(sessionPolicyInfo && sessionPolicyInfo.reason).trim();
      setChatError(
        '当前会话 agent=' +
          (target || '-') +
          ' 角色分析未完成，禁止发送新对话内容。' +
          (reason ? ' ' + reason : ''),
      );
    } else if (gate === 'analyzing_policy') {
      setChatError('角色与职责分析中，请稍候...');
    } else if (gate === 'policy_cache_missing') {
      setChatError('当前角色缓存为空，请先点击“生成缓存”图标。');
    } else if (gate === 'policy_needs_confirm') {
      setChatError('角色与职责待确认，请先完成“角色与职责确认/兜底”');
    } else if (gate === 'policy_failed') {
      setChatError(
        state.allowManualPolicyInput
          ? '角色与职责提取失败或清晰度不足，可通过“角色与职责确认/兜底”手动编辑。'
          : '角色与职责提取失败或清晰度不足，创建会话已阻断（管理员可开启手动兜底）。',
      );
    } else {
      setChatError('');
    }
    if (state.assignmentError === 'agent路径未设置或无效，任务中心功能已锁定。') {
      setAssignmentError('');
      renderAssignmentCenter();
    }
    updateBatchActionState();
    if (!state.agentSearchRootReady) {
      state.tcAgents = [];
      state.tcQueue = [];
      state.tcSelectedAgentId = '';
      state.tcSelectedAgentName = '';
      state.tcSelectedAgentDetail = null;
      state.tcReleasesByAgent = {};
      state.tcNormalCommitsByAgent = {};
      state.tcStats = {
        agent_total: 0,
        git_available_count: 0,
        latest_release_at: '',
        training_queue_pending: 0,
      };
      renderTrainingCenterAgentStats();
      renderTrainingCenterAgentList();
      renderTrainingCenterAgentDetail();
      renderTrainingCenterQueue();
      syncTrainingCenterPlanAgentOptions();
      updateTrainingCenterSelectedMeta();
    } else {
      refreshTrainingCenterAgents()
        .then(() => refreshTrainingCenterQueue())
        .catch((err) => {
          setTrainingCenterError(err.message || String(err));
        });
    }
  }
