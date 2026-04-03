  function ensureTestDataToggleProbeOutputNode() {
    let node = $('testDataToggleProbeOutput');
    if (node) return node;
    node = document.createElement('pre');
    node.id = 'testDataToggleProbeOutput';
    node.style.display = 'none';
    document.body.appendChild(node);
    return node;
  }

  async function runTestDataToggleProbe() {
    const output = {
      ts: new Date().toISOString(),
      case: testDataToggleProbeCase(),
      pass: false,
      error: '',
      environment: '',
      show_test_data: false,
      show_test_data_source: '',
      session_toggle_exists: false,
      settings_toggle_exists: false,
      settings_policy_meta: '',
    };
    try {
      const probeCase = output.case;
      const refreshAll = async () => {
        await refreshAgents(true, { autoAnalyze: false });
        await refreshSessions();
        await refreshWorkflows();
        await refreshDashboard();
        await refreshTrainingCenterAgents();
        await refreshTrainingCenterQueue(true);
      };
      const syncPolicyOutput = () => {
        output.environment = safe(state.runtimeEnvironment).trim();
        output.show_test_data = !!state.showTestData;
        output.show_test_data_source = safe(state.showTestDataSource).trim();
      };
      const capturePolicyTuple = (payload) => ({
        environment: safe(payload && payload.environment).trim(),
        show_test_data: !!(payload && payload.show_test_data),
        show_test_data_source: safe(payload && payload.show_test_data_source).trim(),
      });
      const policiesMatch = (items) => {
        const rows = Array.isArray(items) ? items.filter((item) => !!item) : [];
        if (!rows.length) return false;
        const baseline = rows[0];
        return rows.every((item) =>
          safe(item.environment).trim() === safe(baseline.environment).trim() &&
          !!item.show_test_data === !!baseline.show_test_data &&
          safe(item.show_test_data_source).trim() === safe(baseline.show_test_data_source).trim()
        );
      };
      const postDeprecatedToggle = async (nextValue) => {
        const response = await fetch('/api/config/show-test-data', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ show_test_data: !!nextValue }),
        });
        let body = {};
        try {
          body = await response.json();
        } catch (_) {
          body = {};
        }
        return {
          status: Number(response.status || 0),
          body: body && typeof body === 'object' ? body : {},
        };
      };
      await refreshAll();
      syncPolicyOutput();
      if (probeCase === 'ac_td_01') {
        switchTab('chat');
        output.session_toggle_exists = !!$('showSystemAgentsCheck');
        switchTab('settings');
        output.settings_toggle_exists = !!$('showTestDataCheck');
        output.settings_policy_meta = safe($('showTestDataPolicyMeta') ? $('showTestDataPolicyMeta').textContent : '').trim();
        output.pass = !output.session_toggle_exists && !output.settings_toggle_exists && !!output.settings_policy_meta;
      } else if (probeCase === 'ac_td_02') {
        switchTab('settings');
        const before = !!state.showTestData;
        localStorage.setItem(showSystemAgentsLegacyCacheKey, '1');
        localStorage.setItem(showTestDataCacheKey, before ? '0' : '1');
        await refreshAgents(true, { autoAnalyze: false });
        output.before_state = before;
        output.after_state = !!state.showTestData;
        output.legacy_show_system_after_refresh = safe(localStorage.getItem(showSystemAgentsLegacyCacheKey)).trim();
        output.legacy_show_test_after_refresh = safe(localStorage.getItem(showTestDataCacheKey)).trim();
        output.pass =
          output.after_state === before &&
          !output.legacy_show_system_after_refresh &&
          !output.legacy_show_test_after_refresh;
      } else if (probeCase === 'ac_td_03') {
        switchTab('chat');
        await refreshAgents(true, { autoAnalyze: false });
        output.total_agents = Array.isArray(state.agents) ? state.agents.length : 0;
        output.system_like_agents = (state.agents || []).filter((item) => isSystemOrTestAgent(item)).length;
        output.visible_agents = visibleAgents().length;
        output.visible_system_agents = visibleAgents().filter((item) => isSystemOrTestAgent(item)).length;
        setAgentDropdownOpen(true);
        output.pass =
          output.total_agents >= output.visible_agents &&
          (state.showTestData
            ? output.visible_system_agents === output.system_like_agents
            : output.visible_system_agents === 0);
      } else if (probeCase === 'ac_td_04') {
        switchTab('training');
        switchTab('training-center');
        await refreshTrainingCenterAgents();
        await refreshDashboard();
        const dashboard = await getJSON('/api/dashboard');
        const trainingAgents = await getJSON('/api/training/agents');
        output.dashboard_policy = capturePolicyTuple(dashboard);
        output.training_policy = capturePolicyTuple(trainingAgents);
        output.training_test_items = Array.isArray(trainingAgents.items)
          ? trainingAgents.items.filter((item) => !!(item && item.is_test_data)).length
          : 0;
        output.pass =
          policiesMatch([output.dashboard_policy, output.training_policy]) &&
          (state.showTestData || output.training_test_items === 0);
      } else if (probeCase === 'ac_td_05') {
        switchTab('training-center');
        setTrainingCenterModule('ops');
        await refreshSessions();
        await refreshTrainingCenterQueue(true);
        const sessionsPayload = await getJSON('/api/chat/sessions');
        const queuePayload = await getJSON('/api/training/queue?include_removed=1');
        output.sessions_policy = capturePolicyTuple(sessionsPayload);
        output.queue_policy = capturePolicyTuple(queuePayload);
        output.session_test_rows = Array.isArray(sessionsPayload.sessions)
          ? sessionsPayload.sessions.filter((item) => !!(item && item.is_test_data)).length
          : 0;
        output.queue_test_rows = Array.isArray(queuePayload.items)
          ? queuePayload.items.filter((item) => !!(item && item.is_test_data)).length
          : 0;
        output.pass =
          policiesMatch([output.sessions_policy, output.queue_policy]) &&
          (state.showTestData || (output.session_test_rows === 0 && output.queue_test_rows === 0));
      } else if (probeCase === 'ac_td_06') {
        switchTab('settings');
        await refreshAgents(true, { autoAnalyze: false });
        const before = !!state.showTestData;
        const result = await postDeprecatedToggle(!before);
        const afterPayload = await getJSON('/api/agents');
        output.before_state = before;
        output.write_status = result.status;
        output.write_code = safe(result.body && result.body.code).trim();
        output.after_state = !!afterPayload.show_test_data;
        output.pass =
          output.after_state === before &&
          output.write_status === 410 &&
          output.write_code === 'show_test_data_toggle_removed';
      } else if (probeCase === 'ac_td_07') {
        switchTab('settings');
        const agentsPayload = await getJSON('/api/agents');
        const statusPayload = await getJSON('/api/status');
        const dashboardPayload = await getJSON('/api/dashboard');
        const trainingPayload = await getJSON('/api/training/agents');
        output.policy_payloads = {
          agents: capturePolicyTuple(agentsPayload),
          status: capturePolicyTuple(statusPayload),
          dashboard: capturePolicyTuple(dashboardPayload),
          training: capturePolicyTuple(trainingPayload),
        };
        output.pass = policiesMatch([
          output.policy_payloads.agents,
          output.policy_payloads.status,
          output.policy_payloads.dashboard,
          output.policy_payloads.training,
        ]);
      } else if (probeCase === 'ac_td_08') {
        switchTab('task-center');
        if (state.agentSearchRootReady && typeof refreshAssignmentGraphs === 'function') {
          await refreshAssignmentGraphs({ preserveSelection: true });
        }
        output.assignment_test_rows = Array.isArray(state.assignmentGraphs)
          ? state.assignmentGraphs.filter((item) => !!(item && item.is_test_data)).length
          : 0;
        output.pass = state.showTestData || output.assignment_test_rows === 0;
      } else {
        output.pass = true;
      }
      syncPolicyOutput();
    } catch (err) {
      output.error = safe(err && err.message ? err.message : err);
    }
    const node = ensureTestDataToggleProbeOutputNode();
    node.textContent = JSON.stringify(output);
    node.setAttribute('data-pass', output.pass ? '1' : '0');
  }

  function waitForNextPaint() {
    return new Promise((resolve) => {
      window.requestAnimationFrame(() => {
        window.setTimeout(resolve, 0);
      });
    });
  }

  async function bootstrap() {
    setStartupProgress({
      stage: 'shell',
      title: '正在准备工作台',
      detail: '初始化页面布局、基础交互和本地缓存。',
      percent: 6,
      hint: '首次启动通常会更慢，因为需要做环境检查、运行态恢复和数据预热。',
    });
    initSplitters();
    bindEvents();
    setupSessionEntryToolbarIcons();
    const deepLinkTrainingLoop = !!(
      queryParam('tc_loop_mode') ||
      queryParam('tc_loop_tab') ||
      queryParam('tc_loop_node') ||
      queryParam('tc_loop_task')
    );
    const initialTab = deepLinkTrainingLoop ? 'training-center' : readSavedAppTab();
    setTrainingCenterModule(deepLinkTrainingLoop ? 'ops' : readSavedTrainingCenterModule());
    state.requirementBugModule = readSavedRequirementBugModule();
    renderTrainingCenterAgentStats();
    renderTrainingCenterAgentList();
    renderTrainingCenterAgentDetail();
    if (typeof renderRoleCreationWorkbench === 'function') {
      renderRoleCreationWorkbench();
    }
    renderTrainingCenterQueue();
    renderAssignmentCenter();
    if (typeof renderDefectCenter === 'function') {
      renderDefectCenter();
    }
    syncTrainingCenterPlanAgentOptions();
    updateTrainingCenterSelectedMeta();
    cleanupLegacyTestDataCaches();
    updateShowTestDataMeta();
    updateClearPolicyCacheButton();
    setWorkflowQueueMode('records');
    await waitForNextPaint();
    setStartupProgress({
      stage: 'connect',
      title: '正在连接运行时',
      detail: '读取环境信息、升级状态和基础配置。',
      percent: 14,
    });
    const cachedSession = safe(localStorage.getItem(sessionCacheKey)).trim();
    const runtimeUpgradeReady = refreshRuntimeUpgradeStatus({ silent: true }).catch(() => {});
    await refreshAgents(false, { autoAnalyze: false });
    setStartupProgress({
      stage: 'agents',
      title: '角色与环境策略已加载',
      detail: state.agentSearchRootReady
        ? '角色池已刷新，正在恢复最近的会话与工作记录。'
        : '环境策略已读取完成，接下来恢复基础页面数据。',
      percent: 36,
    });
    const sessionRefreshPromise = refreshSessions({
      skipInitialMessages: true,
      preferredSessionId: cachedSession,
    });
    const workflowRefreshPromise = refreshWorkflows();
    const dashboardRefreshPromise = refreshDashboard();
    setStartupProgress({
      stage: 'sessions',
      title: '正在恢复数据',
      detail: '并行加载会话列表、工作记录和仪表盘概览。',
      percent: 58,
    });
    await Promise.all([
      sessionRefreshPromise,
      workflowRefreshPromise,
      dashboardRefreshPromise,
      runtimeUpgradeReady,
    ]);
    setStartupProgress({
      stage: 'workspace',
      title: '正在恢复工作台',
      detail: state.selectedSessionId
        ? '恢复最近一次会话内容和上次停留的页面位置。'
        : '恢复上次停留的页面位置并准备基础交互。',
      percent: 84,
    });
    if (state.selectedSessionId) {
      await loadSessionMessages(state.selectedSessionId);
    } else {
      renderFeed();
    }
    switchTab(initialTab, { persist: false });
    applyGateState();
    startWorkflowPoller();
    startRuntimeUpgradePoller();
    const finalStatus = state.agentSearchRootReady ? '就绪' : '等待设置 agent路径';
    setStatus(finalStatus);
    finishStartupProgress(
      state.agentSearchRootReady
        ? '基础界面与最近工作状态已恢复完成。'
        : '基础界面已加载完成，请先到设置页配置有效的 agent路径。'
    );
    if (state.agentSearchRootReady && visibleAgents().length > 0) {
      window.setTimeout(() => {
        startPolicyAnalysisForSelection();
      }, 0);
    }
    if (isLayoutProbeEnabled()) {
      await runLayoutProbe();
    }
    if (isPolicyProbeEnabled()) {
      await runPolicyProbe();
    }
    if (isTrainingCenterProbeEnabled()) {
      await runTrainingCenterProbe();
    }
    if (isAssignmentProbeEnabled()) {
      await runAssignmentCenterProbe();
    }
    if (isDefectProbeEnabled()) {
      await runDefectCenterProbe();
    }
    if (queryParam('schedule_probe') === '1' && typeof runScheduleCenterProbe === 'function') {
      await runScheduleCenterProbe();
    }
    if (isTestDataToggleProbeEnabled()) {
      await runTestDataToggleProbe();
    }
  }

  bootstrap().catch((err) => {
    setChatError(err.message || String(err));
    setStatus('失败');
    failStartupProgress(err.message || String(err));
  });
})();
