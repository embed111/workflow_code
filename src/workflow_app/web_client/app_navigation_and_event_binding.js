  function switchTab(name, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const tabName = normalizeAppTab(name);
    document.querySelectorAll('.tab').forEach((node) => {
      node.classList.toggle('active', safe(node.getAttribute('data-tab')) === tabName);
    });
    document.querySelectorAll('.pane').forEach((node) => {
      node.classList.toggle('active', safe(node.id) === 'pane-' + tabName);
    });
    if (opts.persist !== false) {
      writeSavedAppTab(tabName);
    }
    if (tabName !== 'task-center' && typeof stopAssignmentExecutionRealtime === 'function') {
      stopAssignmentExecutionRealtime();
    } else if (tabName !== 'task-center' && typeof stopAssignmentExecutionPoller === 'function') {
      stopAssignmentExecutionPoller();
    }
    if (tabName === 'training-center') {
      refreshTrainingCenterAgents()
        .then(async () => {
          await refreshTrainingCenterQueue(false);
          if (safe(state.tcModule).trim() === 'create-role' && typeof refreshRoleCreationSessions === 'function') {
            await refreshRoleCreationSessions({ preserveSelection: true });
          }
        })
        .catch((err) => {
          setTrainingCenterError(err.message || String(err));
        });
    }
    if (tabName === 'task-center') {
      if (!state.agentSearchRootReady) {
        renderAssignmentCenter();
        return;
      }
      refreshAssignmentGraphs({ preserveSelection: true }).catch((err) => {
        setAssignmentError(err.message || String(err));
      });
    }
    if (tabName === 'schedule-center') {
      if (!state.agentSearchRootReady) {
        renderScheduleCenter();
        return;
      }
      refreshSchedulePlans({ preserveSelection: true }).catch((err) => {
        setScheduleError(err.message || String(err));
      });
      refreshScheduleCalendar(state.scheduleCalendarMonth || '').catch((err) => {
        setScheduleError(err.message || String(err));
      });
    }
    if (tabName === 'requirement-bug') {
      renderDefectCenter();
      refreshDefectList({ preserveSelection: true }).catch((err) => {
        setDefectError(err.message || String(err));
      });
    }
    if (tabName === 'settings') {
      updateArtifactRootMeta();
      updateDeveloperWorkspaceMeta();
      updateAssignmentExecutionSettingsMeta();
    }
  }

  function bindEvents() {
    bindAssignmentCenterEvents();
    if (typeof bindScheduleCenterEvents === 'function') {
      bindScheduleCenterEvents();
    }
    if (typeof bindDefectCenterEvents === 'function') {
      bindDefectCenterEvents();
    }
    if (typeof bindRoleCreationEvents === 'function') {
      bindRoleCreationEvents();
    }
    $('agentSelect').onchange = () => {
      const agent = selectedAgent();
      if (agent) localStorage.setItem(agentCacheKey, agent);
      state.agentMetaPanelOpen = false;
      state.agentMetaDetailsOpen = false;
      state.agentMetaClarityOpen = false;
      startPolicyAnalysisForSelection();
    };
    $('agentSelectTrigger').onclick = (event) => {
      event.preventDefault();
      if ($('agentSelectTrigger').disabled) return;
      const willOpen = !state.agentDropdownOpen;
      if (willOpen) {
        const search = $('agentSelectSearch');
        if (search) {
          search.value = '';
        }
        renderAgentStatusList(visibleAgents());
      }
      setAgentDropdownOpen(willOpen);
    };
    $('agentSelectSearch').addEventListener('input', () => {
      renderAgentStatusList(visibleAgents());
    });
    $('agentSelectSearch').addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setAgentDropdownOpen(false);
      }
    });
    $('loadAgentsBtn').onclick = async () => {
      try {
        await withButtonLock('loadAgentsBtn', async () => {
          setStatus('正在刷新角色...');
          await refreshAgents(true, { forceRefresh: true });
          await refreshDashboard();
          setStatus('就绪');
        });
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('clearPolicyCacheBtn').onclick = async () => {
      try {
        await withButtonLock('clearPolicyCacheBtn', async () => {
          await clearPolicyCache('selected');
        });
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('clearAllPolicyCacheBtn').onclick = async () => {
      try {
        await withButtonLock('clearAllPolicyCacheBtn', async () => {
          await clearPolicyCache('all');
        });
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('regeneratePolicyCacheBtn').onclick = async () => {
      try {
        await withButtonLock('regeneratePolicyCacheBtn', async () => {
          regenerateSelectedPolicyCache();
        });
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('newSessionBtn').onclick = async () => {
      try {
        await withButtonLock('newSessionBtn', async () => {
          setStatus('正在创建会话...');
          const created = await createSession();
          await refreshSessions();
          if (created) {
            setStatus('就绪');
          }
        });
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('policyGateBtn').onclick = async () => {
      try {
        await withButtonLock('policyGateBtn', async () => {
          openPolicyConfirmForSelectedAgent();
        });
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('reloadSessionsBtn').onclick = async () => {
      try {
        await withButtonLock('reloadSessionsBtn', async () => {
          await refreshSessions();
          setStatus('会话列表已刷新');
        });
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('deleteSessionBtn').onclick = async () => {
      try {
        await withButtonLock('deleteSessionBtn', async () => {
          await deleteCurrentSession();
        });
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('sendBtn').onclick = async () => {
      try {
        await runTask(false);
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('retryBtn').onclick = async () => {
      try {
        await runTask(true);
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('stopBtn').onclick = async () => {
      try {
        await interruptCurrentTask();
      } catch (err) {
        setChatError(err.message || String(err));
      }
    };
    $('msg').addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        $('sendBtn').click();
      }
    });
    $('feed').addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const btn = target.closest('button.trace-toggle');
      if (!btn) return;
      const taskId = safe(btn.getAttribute('data-task-id'));
      if (!taskId) return;
      const expanded = !!state.taskTraceExpanded[taskId];
      if (expanded) {
        delete state.taskTraceExpanded[taskId];
        renderFeed();
        return;
      }
      state.taskTraceExpanded[taskId] = true;
      ensureTaskTrace(taskId).catch((err) => {
        setChatError(err.message || String(err));
      });
    });
    $('refreshWorkflowBtn').onclick = async () => {
      try {
        await withButtonLock('refreshWorkflowBtn', async () => {
          await refreshWorkflows();
        });
      } catch (err) {
        setWorkflowResult(err.message || String(err));
      }
    };
    $('workflowDialogue').addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const btn = target.closest('button.workflow-delete-msg');
      if (!btn) return;
      event.stopPropagation();
      const sid = safe(btn.getAttribute('data-session-id'));
      const mid = safe(btn.getAttribute('data-message-id'));
      deleteSessionMessage(sid, mid, btn).catch((err) => {
        setWorkflowResult(err.message || String(err));
      });
    });
    $('workflowSelectionToggleCheck').onclick = (event) => {
      event.stopPropagation();
      toggleWorkflowSelectionState();
    };
    $('queueModeRecordsBtn').onclick = () => {
      setWorkflowQueueMode('records');
    };
    $('queueModeTrainingBtn').onclick = () => {
      setWorkflowQueueMode('training');
    };
    $('batchAnalystInput').addEventListener('change', () => {
      const value = safe($('batchAnalystInput').value).trim();
      if (value) $('analystInput').value = value;
      updateBatchActionState();
    });
    $('analystInput').addEventListener('change', () => {
      const value = safe($('analystInput').value).trim();
      if (value) $('batchAnalystInput').value = value;
      updateBatchActionState();
    });
    $('batchAnalyzeBtn').onclick = async () => {
      try {
        await batchAnalyzeRecords();
      } catch (err) {
        setWorkflowResult(err.message || String(err));
      }
    };
    $('batchDeleteRecordsBtn').onclick = async () => {
      try {
        await batchDeleteRecords();
      } catch (err) {
        setWorkflowResult(err.message || String(err));
      }
    };
    $('assignBtn').onclick = async () => {
      try {
        await withButtonLock('assignBtn', async () => {
          await assignAnalyst();
        });
      } catch (err) {
        setWorkflowResult(err.message || String(err));
      }
    };
    $('generatePlanBtn').onclick = async () => {
      try {
        await withButtonLock('generatePlanBtn', async () => {
          await generateWorkflowPlan();
        });
      } catch (err) {
        setWorkflowResult(err.message || String(err));
      }
    };
    $('executePlanBtn').onclick = async () => {
      try {
        await withButtonLock('executePlanBtn', async () => {
          await executeWorkflowPlan();
        });
      } catch (err) {
        setWorkflowResult(err.message || String(err));
      }
    };
    $('deleteWorkflowBtn').onclick = async () => {
      try {
        await withButtonLock('deleteWorkflowBtn', async () => {
          await deleteSelectedWorkflow();
        });
      } catch (err) {
        setWorkflowResult(err.message || String(err));
      }
    };
    $('refreshEventsBtn').onclick = async () => {
      try {
        await refreshWorkflowEvents(state.selectedWorkflowId);
      } catch (err) {
        setWorkflowResult(err.message || String(err));
      }
    };
    $('tcTabAgentsBtn').onclick = () => {
      setTrainingCenterModule('agents');
    };
    $('tcTabCreateRoleBtn').onclick = () => {
      setTrainingCenterModule('create-role');
    };
    $('tcTabOpsBtn').onclick = () => {
      setTrainingCenterModule('ops');
    };
    $('tcEnterOpsBtn').onclick = () => {
      setTrainingCenterModule('ops');
      enterTrainingLoopCreateMode();
    };
    $('tcLoopTaskSearchInput').addEventListener('input', () => {
      renderTrainingCenterQueue();
    });
    const loopFilterRow = $('tcLoopQueueFilterRow');
    if (loopFilterRow) {
      loopFilterRow.querySelectorAll('button[data-filter]').forEach((btn) => {
        btn.onclick = () => {
          setTrainingLoopQueueFilter(btn.getAttribute('data-filter'));
        };
      });
    }
    $('tcAgentSearchInput').addEventListener('input', () => {
      renderTrainingCenterAgentList();
    });
    $('tcPlanTargetAgentSelect').addEventListener('change', () => {
      const agentId = safe($('tcPlanTargetAgentSelect').value).trim();
      state.tcSelectedAgentId = agentId;
      const matched =
        agentId && state.tcAgents.find((item) => safe(item.agent_id).trim() === agentId);
      if (matched) {
        state.tcSelectedAgentDetail = matched;
        state.tcSelectedAgentName = safe(matched.agent_name || '');
      }
      updateTrainingCenterSelectedMeta();
      renderTrainingCenterAgentList();
      if (agentId) {
        refreshTrainingCenterSelectedAgentContext(agentId).catch((err) => {
          setTrainingCenterDetailError(err.message || String(err));
        });
      } else {
        renderTrainingCenterAgentDetail();
      }
      renderTrainingLoop();
      applyGateState();
    });
    ['tcPlanGoalInput', 'tcPlanTasksInput', 'tcPlanAcceptanceInput'].forEach((id) => {
      const node = $(id);
      if (!node) return;
      // Text fields should stay editable; avoid full loop re-render on every keystroke.
      node.addEventListener('change', () => {
        renderTrainingLoop();
      });
    });
    if ($('tcPlanPrioritySelect')) {
      $('tcPlanPrioritySelect').addEventListener('change', () => {
        renderTrainingLoop();
      });
    }
    $('tcRefreshAgentsBtn').onclick = async () => {
      try {
        await withButtonLock('tcRefreshAgentsBtn', async () => {
          await refreshTrainingCenterAgents();
          await refreshTrainingCenterQueue();
          setTrainingCenterDetailError('');
          setTrainingCenterError('');
        });
      } catch (err) {
        setTrainingCenterDetailError(err.message || String(err));
      }
    };
    $('tcRefreshQueueBtn').onclick = async () => {
      try {
        await withButtonLock('tcRefreshQueueBtn', async () => {
          await refreshTrainingCenterQueue();
          setTrainingCenterError('');
        });
      } catch (err) {
        setTrainingCenterError(err.message || String(err));
      }
    };
    $('tcDispatchNextBtn').onclick = async () => {
      try {
        await withButtonLock('tcDispatchNextBtn', async () => {
          await dispatchNextTrainingCenterQueue();
        });
      } catch (err) {
        setTrainingCenterError(err.message || String(err));
      }
    };
    $('tcSwitchVersionTrigger').onclick = (event) => {
      event.preventDefault();
      const trigger = $('tcSwitchVersionTrigger');
      if (!trigger || trigger.disabled) return;
      setTrainingCenterVersionDropdownOpen(!state.tcVersionDropdownOpen);
    };
    $('tcSwitchVersionOptions').onclick = (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const option = target.closest('.tc-version-option');
      if (!option) return;
      const version = safe(option.getAttribute('data-version')).trim();
      const select = $('tcSwitchVersionSelect');
      if (!version || !select) return;
      if (version === safe(select.value).trim()) {
        setTrainingCenterVersionDropdownOpen(false);
        return;
      }
      select.value = version;
      setTrainingCenterVersionDropdownOpen(false);
      select.dispatchEvent(new Event('change', { bubbles: true }));
    };
    $('tcSwitchVersionSelect').onchange = async () => {
      const select = $('tcSwitchVersionSelect');
      const trigger = $('tcSwitchVersionTrigger');
      const previous = currentTrainingCenterDisplayedVersion(state.tcSelectedAgentDetail || {});
      const next = safe(select ? select.value : '').trim();
      if (!next || next === previous) {
        return;
      }
      try {
        if (select) select.disabled = true;
        if (trigger) trigger.disabled = true;
        await switchTrainingCenterAgentVersion();
      } catch (err) {
        if (select) {
          select.value = previous;
        }
        setTrainingCenterDetailError(err.message || String(err));
      } finally {
        if (select) select.disabled = false;
        if (trigger) trigger.disabled = false;
      }
    };
    $('tcCloneAgentBtn').onclick = async () => {
      try {
        await withButtonLock('tcCloneAgentBtn', async () => {
          await cloneTrainingCenterAgentFromCurrent();
        });
      } catch (err) {
        setTrainingCenterDetailError(err.message || String(err));
      }
    };
    $('tcSetAvatarBtn').onclick = async () => {
      const fileInput = $('tcAvatarFileInput');
      if (!safe(state.tcSelectedAgentId).trim()) {
        setTrainingCenterDetailError('请先选择角色');
        return;
      }
      if (fileInput) {
        fileInput.value = '';
        fileInput.click();
      }
    };
    $('tcAvatarFileInput').addEventListener('change', async () => {
      const fileInput = $('tcAvatarFileInput');
      const hasFile = !!(fileInput && fileInput.files && fileInput.files[0]);
      if (!hasFile) return;
      try {
        await withButtonLock('tcSetAvatarBtn', async () => {
          await setTrainingCenterAgentAvatar();
        });
      } catch (err) {
        setTrainingCenterDetailError(err.message || String(err));
      }
    });
    $('tcDiscardPreReleaseBtn').onclick = async () => {
      try {
        await withButtonLock('tcDiscardPreReleaseBtn', async () => {
          await discardTrainingCenterPreRelease();
        });
      } catch (err) {
        setTrainingCenterDetailError(err.message || String(err));
      }
    };
    $('tcEnterReleaseReviewBtn').onclick = async () => {
      try {
        await withButtonLock('tcEnterReleaseReviewBtn', async () => {
          await enterTrainingCenterReleaseReview();
        });
      } catch (err) {
        const agentId = typeof selectedTrainingCenterAgentId === 'function' ? selectedTrainingCenterAgentId() : '';
        const review = agentId && typeof currentTrainingCenterReleaseReview === 'function'
          ? currentTrainingCenterReleaseReview(agentId)
          : {};
        const localError = agentId && typeof currentTrainingCenterReleaseReviewError === 'function'
          ? currentTrainingCenterReleaseReviewError(agentId)
          : null;
        const hasStructuredError = !!(
          safe(review && review.report_error).trim() ||
          safe(review && review.publish_error).trim() ||
          (localError && safe(localError.error_message).trim())
        );
        if (agentId && typeof renderTrainingCenterReleaseReview === 'function') {
          setTrainingCenterDetailError(hasStructuredError ? '' : err.message || String(err));
          renderTrainingCenterReleaseReview(agentId);
        } else {
          setTrainingCenterDetailError(err.message || String(err));
        }
      }
    };
    $('tcDiscardReleaseReviewBtn').onclick = async () => {
      try {
        await withButtonLock('tcDiscardReleaseReviewBtn', async () => {
          await discardTrainingCenterReleaseReview();
        });
      } catch (err) {
        setTrainingCenterDetailError(err.message || String(err));
      }
    };
    $('tcSubmitEvalBtn').onclick = async () => {
      try {
        await withButtonLock('tcSubmitEvalBtn', async () => {
          await submitTrainingCenterManualEvaluation();
        });
      } catch (err) {
        setTrainingCenterDetailError(err.message || String(err));
      }
    };
    $('tcConfirmReleaseReviewBtn').onclick = async () => {
      try {
        await withButtonLock('tcConfirmReleaseReviewBtn', async () => {
          await confirmTrainingCenterReleaseReview();
        });
      } catch (err) {
        const agentId = typeof selectedTrainingCenterAgentId === 'function' ? selectedTrainingCenterAgentId() : '';
        const review = agentId && typeof currentTrainingCenterReleaseReview === 'function'
          ? currentTrainingCenterReleaseReview(agentId)
          : {};
        const localError = agentId && typeof currentTrainingCenterReleaseReviewError === 'function'
          ? currentTrainingCenterReleaseReviewError(agentId)
          : null;
        const hasStructuredError = !!(
          safe(review && review.report_error).trim() ||
          safe(review && review.publish_error).trim() ||
          (localError && safe(localError.error_message).trim())
        );
        if (agentId && typeof renderTrainingCenterReleaseReview === 'function') {
          setTrainingCenterDetailError(hasStructuredError ? '' : err.message || String(err));
          renderTrainingCenterReleaseReview(agentId);
        } else {
          setTrainingCenterDetailError(err.message || String(err));
        }
      }
    };
    $('allowManualPolicyInputCheck').onchange = async () => {
      const checked = !!$('allowManualPolicyInputCheck').checked;
      try {
        const data = await postJSON('/api/config/manual-policy-input', {
          allow_manual_policy_input: checked,
        });
        state.allowManualPolicyInput = !!data.allow_manual_policy_input;
        $('allowManualPolicyInputCheck').checked = state.allowManualPolicyInput;
        updateManualPolicyInputMeta();
        startPolicyAnalysisForSelection();
        setStatus(state.allowManualPolicyInput ? '已开启手动角色与职责兜底' : '已关闭手动角色与职责兜底');
      } catch (err) {
        $('allowManualPolicyInputCheck').checked = state.allowManualPolicyInput;
        updateManualPolicyInputMeta();
        setSettingsError(err.message || String(err));
      }
    };
    $('switchRootBtn').onclick = async () => {
      try {
        setSettingsError('');
        await withButtonLock('switchRootBtn', async () => {
          await switchAgentSearchRoot();
        });
      } catch (err) {
        setSettingsError(err.message || String(err));
      }
    };
    if ($('switchArtifactRootBtn')) {
      $('switchArtifactRootBtn').onclick = async () => {
        try {
          setSettingsError('');
          await withButtonLock('switchArtifactRootBtn', async () => {
            await switchArtifactRoot();
          });
        } catch (err) {
          setSettingsError(err.message || String(err));
        }
      };
    }
    if ($('assignmentExecutionSaveBtn')) {
      $('assignmentExecutionSaveBtn').onclick = async () => {
        try {
          setSettingsError('');
          await withButtonLock('assignmentExecutionSaveBtn', async () => {
            await saveAssignmentExecutionSettings();
          });
        } catch (err) {
          setSettingsError(err.message || String(err));
        }
      };
    }
    $('refreshSettingsBtn').onclick = async () => {
      try {
        await withButtonLock('refreshSettingsBtn', async () => {
          await refreshAgents(true, { forceRefresh: true });
          await refreshAssignmentExecutionSettings();
          await refreshSessions();
          await refreshWorkflows();
          await refreshDashboard();
          setStatus('设置已刷新');
        });
      } catch (err) {
        setSettingsError(err.message || String(err));
      }
    };
    $('cleanupHistoryBtn').onclick = async () => {
      try {
        setSettingsError('');
        await withButtonLock('cleanupHistoryBtn', async () => {
          await cleanupHistory();
        });
      } catch (err) {
        setSettingsError(err.message || String(err));
      }
    };
    $('policyConfirmUseBtn').onclick = async () => {
      try {
        await withButtonLock('policyConfirmUseBtn', async () => {
          await submitPolicyConfirmation('confirm');
          await refreshAgents(true);
          await refreshSessions();
          await refreshDashboard();
          setStatus('角色与职责确认成功，已创建会话');
        });
      } catch (err) {
        setPolicyConfirmError(err.message || String(err));
      }
    };
    $('policyEditUseBtn').onclick = async () => {
      try {
        await withButtonLock('policyEditUseBtn', async () => {
          await submitPolicyConfirmation('edit');
          await refreshAgents(true);
          await refreshSessions();
          await refreshDashboard();
          setStatus('角色与职责编辑确认成功，已创建会话');
        });
      } catch (err) {
        setPolicyConfirmError(err.message || String(err));
      }
    };
    $('policyRescoreBtn').onclick = async () => {
      try {
        await withButtonLock('policyRescoreBtn', async () => {
          await rescoreEditedPolicy();
        });
      } catch (err) {
        setPolicyConfirmError(err.message || String(err));
      }
    };
    $('policyCancelBtn').onclick = () => {
      closePolicyConfirmModal();
      setStatus('已取消角色与职责确认/兜底');
    };
    $('policyConfirmMask').onclick = (event) => {
      if (event.target === $('policyConfirmMask')) {
        closePolicyConfirmModal();
      }
    };
    document.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (state.agentDropdownOpen) {
        const host = $('agentDropdown');
        if (host && !host.contains(target)) {
          setAgentDropdownOpen(false);
        }
      }
      if (state.tcVersionDropdownOpen) {
        const versionHost = $('tcVersionDropdown');
        if (versionHost && !versionHost.contains(target)) {
          setTrainingCenterVersionDropdownOpen(false);
        }
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      if (!$('policyConfirmMask').classList.contains('hidden')) {
        closePolicyConfirmModal();
        return;
      }
      if (state.tcVersionDropdownOpen) {
        setTrainingCenterVersionDropdownOpen(false);
        return;
      }
      if (state.agentDropdownOpen) {
        setAgentDropdownOpen(false);
      }
    });
    window.addEventListener('resize', handleAgentDropdownViewportChange);
    window.addEventListener('scroll', handleAgentDropdownViewportChange, true);
    $('policyRecommendBtn').onclick = async () => {
      try {
        await withButtonLock('policyRecommendBtn', async () => {
          await recommendPolicyDraft();
        });
      } catch (err) {
        setPolicyConfirmError(err.message || String(err));
      }
    };
    const handlePolicyEditInput = () => {
      const pending = state.pendingPolicyConfirmation;
      if (!pending || !pending.rescore_fingerprint) return;
      if (pending.rescore_fingerprint === policyEditFingerprint()) return;
      clearPolicyEditScorePreview('内容已变更，请点击“重新评分并对比”。');
    };
    ['policyEditRole', 'policyEditGoal', 'policyEditDuty'].forEach((id) => {
      const node = $(id);
      if (!node) return;
      node.addEventListener('input', handlePolicyEditInput);
    });
    $('policyCopyBtn').onclick = async () => {
      try {
        const result = await withButtonLock('policyCopyBtn', async () => {
          return copyPolicyConfirmHtmlView();
        });
        setPolicyConfirmError('');
        if (result && result.mode === 'html') {
          setStatus('已复制网页富文本视图到剪贴板');
        } else {
          setStatus('复制完成');
        }
      } catch (err) {
        setPolicyConfirmError('复制失败：' + safe(err.message || String(err)));
      }
    };
    document.querySelectorAll('.tab').forEach((node) => {
      node.onclick = () => switchTab(safe(node.getAttribute('data-tab')));
    });
  }

  function findTrainingCenterProbeAgent(options) {
    const opts = options || {};
    const rows = Array.isArray(state.tcAgents) ? state.tcAgents : [];
    if (!rows.length) return null;
    const expected = safe(queryParam('tc_probe_agent')).trim().toLowerCase();
    if (expected) {
      const matched = rows.find((row) => {
        const byName = safe(row && row.agent_name).trim().toLowerCase();
        const byId = safe(row && row.agent_id).trim().toLowerCase();
        return byName === expected || byId === expected;
      });
      if (matched) return matched;
    }
    if (opts.nonGitFirst) {
      const nonGit = rows.find((row) => !row.git_available);
      if (nonGit) return nonGit;
    }
    return rows[0] || null;
  }

  async function selectTrainingCenterProbeAgent(options) {
    const selected = findTrainingCenterProbeAgent(options);
    if (!selected) return null;
    const agentId = safe(selected.agent_id).trim();
    if (!agentId) return null;
    state.tcSelectedAgentId = agentId;
    state.tcSelectedAgentName = safe(selected.agent_name || '');
    state.tcSelectedAgentDetail = selected;
    syncTrainingCenterPlanAgentOptions();
    updateTrainingCenterSelectedMeta();
    renderTrainingCenterAgentList();
    await refreshTrainingCenterSelectedAgentContext(agentId);
    return selected;
  }

  function fillTrainingCenterProbePlan(agentId, suffix, priority) {
    const sid = safe(suffix).trim() || String(Date.now());
    const target = safe(agentId).trim();
    if ($('tcPlanTargetAgentSelect')) $('tcPlanTargetAgentSelect').value = target;
    if ($('tcPlanGoalInput')) $('tcPlanGoalInput').value = 'probe capability ' + sid;
    if ($('tcPlanTasksInput')) $('tcPlanTasksInput').value = 'probe task ' + sid + '\nverify traceability ' + sid;
    if ($('tcPlanAcceptanceInput')) $('tcPlanAcceptanceInput').value = 'probe acceptance ' + sid;
    if ($('tcPlanPrioritySelect')) $('tcPlanPrioritySelect').value = safe(priority).trim();
    state.tcSelectedAgentId = target;
    const matched = Array.isArray(state.tcAgents)
      ? state.tcAgents.find((item) => safe(item.agent_id).trim() === target)
      : null;
    if (matched) {
      state.tcSelectedAgentDetail = matched;
      state.tcSelectedAgentName = safe(matched.agent_name || '');
    }
    updateTrainingCenterSelectedMeta();
    renderTrainingCenterAgentList();
    renderTrainingCenterAgentDetail();
  }

  function ensureTrainingCenterProbeOutputNode() {
    let node = $('trainingCenterProbeOutput');
    if (node) return node;
    node = document.createElement('pre');
    node.id = 'trainingCenterProbeOutput';
    node.style.display = 'none';
    document.body.appendChild(node);
    return node;
  }

  function ensureAssignmentCenterProbeOutputNode() {
    let node = $('assignmentCenterProbeOutput');
    if (node) return node;
    node = document.createElement('pre');
    node.id = 'assignmentCenterProbeOutput';
    node.style.display = 'none';
    document.body.appendChild(node);
    return node;
  }
