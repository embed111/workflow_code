  // Training center release review main rendering.

  function renderTrainingCenterReleaseReview(agentId) {
    const reviewCard = $('tcReleaseReviewCard');
    const hintNode = $('tcReleaseReviewHint');
    const stepperNode = $('tcReleaseReviewStepper');
    const progressNode = $('tcReleaseReviewProgress');
    const substageNode = $('tcReleaseReviewSubstage');
    const reportNode = $('tcReleaseReviewReport');
    const chainNode = $('tcReleaseReviewChain');
    const manualMetaNode = $('tcReleaseReviewManualMeta');
    const logsNode = $('tcReleaseReviewLogs');
    const fallbackNode = $('tcReleaseReviewFallback');
    const enterBtn = $('tcEnterReleaseReviewBtn');
    const discardBtn = $('tcDiscardReleaseReviewBtn');
    const confirmBtn = $('tcConfirmReleaseReviewBtn');
    const decisionSelect = $('tcEvalDecisionSelect');
    const reviewerInput = $('tcEvalReviewerInput');
    const summaryInput = $('tcEvalSummaryInput');
    const submitBtn = $('tcSubmitEvalBtn');
    const reviewGrids = reviewCard ? Array.from(reviewCard.querySelectorAll('.tc-release-review-grid')) : [];
    if (!reviewCard) return;

    const key = safe(agentId).trim();
    const detail = trainingCenterAgentDetailById(key);
    const review = currentTrainingCenterReleaseReview(key);
    const progress = currentTrainingCenterReleaseReviewProgress(key);
    const localError = currentTrainingCenterReleaseReviewError(key);
    const progressMode = progress ? safe(progress.mode).trim().toLowerCase() : '';
    const effectiveReview = applyTrainingCenterReleaseReviewProgress(review, progress);
    const localErrorData = localError && localError.error_data && typeof localError.error_data === 'object'
      ? localError.error_data
      : {};
    const localErrorReview = localErrorData.review && typeof localErrorData.review === 'object'
      ? localErrorData.review
      : {};
    const reportCodexFailure = normalizeCodexFailure(
      effectiveReview.codex_failure ||
      localErrorData.codex_failure ||
      localErrorReview.codex_failure
    );
    const publishCodexFailure = normalizeCodexFailure(
      effectiveReview.publish_codex_failure ||
      localErrorData.publish_codex_failure ||
      localErrorReview.publish_codex_failure
    );
    const reportFailure = describeTrainingCenterReleaseReportFailure(effectiveReview, localError);
    const publishFailure = describeTrainingCenterReleasePublishFailure(effectiveReview, localError);
    const hasAgent = !!key;
    const hasPublishedRelease = !!currentTrainingCenterPublishedRelease(detail);
    const canReview = !!effectiveReview.can_review && !progress;
    const hasActiveReview = trainingCenterReleaseReviewIsActive(effectiveReview);
    const contextLoading =
      !!state.tcSelectedAgentContextLoading &&
      safe(state.tcSelectedAgentId).trim() === key;

    reviewCard.dataset.reviewMode = hasActiveReview ? 'active' : 'inactive';
    [stepperNode, progressNode, substageNode].forEach((node) => {
      if (node) node.hidden = !hasActiveReview;
    });
    reviewGrids.forEach((node) => {
      node.hidden = !hasActiveReview;
    });

    reviewCard.classList.toggle('disabled', !hasAgent);
    if (!hasAgent) {
      reviewCard.dataset.reviewMode = 'inactive';
      if (hintNode) hintNode.textContent = '请选择左侧角色后查看发布评审链路';
      renderTrainingCenterReleaseReviewProgress(progressNode, null);
      renderTrainingCenterReleaseReviewSteps(stepperNode, [], '未选择角色');
      renderTrainingCenterReleaseReviewPills(substageNode, [], '发布后子阶段会显示在这里');
      [reportNode, chainNode, manualMetaNode, logsNode, fallbackNode].forEach((node) => {
        if (!node) return;
        node.innerHTML = '';
        const empty = document.createElement('div');
        empty.className = 'tc-empty';
        empty.textContent = '暂无内容';
        node.appendChild(empty);
      });
      if (enterBtn) enterBtn.disabled = true;
      if (discardBtn) discardBtn.disabled = true;
      if (confirmBtn) confirmBtn.disabled = true;
      if (decisionSelect) decisionSelect.disabled = true;
      if (reviewerInput) reviewerInput.disabled = true;
      if (summaryInput) summaryInput.disabled = true;
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    if (hintNode) {
      if (contextLoading && !safe(review.review_id).trim() && !progress) {
        hintNode.textContent = '正在同步发布版本与评审上下文...';
      } else if (!hasActiveReview) {
        const stateKey = safe(effectiveReview.release_review_state).trim().toLowerCase();
        if (stateKey === 'review_discarded') {
          hintNode.textContent = '当前没有进行中的发布评审；上一条评审已废弃，如需继续请重新进入发布评审。历史正式发布记录请从“发布版本”列表点击“查看发布报告”查看。';
        } else if (safe(effectiveReview.publish_status).trim().toLowerCase() === 'success') {
          hintNode.textContent = '当前没有进行中的发布评审；本次发布已完成。历史正式发布记录请从“发布版本”列表点击“查看发布报告”查看。';
        } else if (effectiveReview.can_enter) {
          hintNode.textContent = '当前还没有进行中的发布评审；点击“进入发布评审”后，这里会展示完整评审链路。';
        } else {
          hintNode.textContent = '当前没有进行中的发布评审；历史正式发布记录请从“发布版本”列表点击“查看发布报告”查看。';
        }
      } else if (progress) {
        const snapshot = describeTrainingCenterReleaseReviewProgress(progress);
        hintNode.textContent = snapshot.headline + ' · ' + (snapshot.detail || '请稍候...');
      } else {
        const targetVersion = safe(effectiveReview.target_version).trim();
        const workspaceRef = safe(effectiveReview.current_workspace_ref).trim();
        const stateText = trainingCenterReleaseReviewStateText(effectiveReview.release_review_state);
        hintNode.textContent =
          stateText +
          (targetVersion ? ' · 目标版本 ' + targetVersion : '') +
          (workspaceRef ? ' · 工作区基线 ' + workspaceRef : '');
      }
    }

    renderTrainingCenterReleaseReviewProgress(progressNode, progress);
    renderTrainingCenterReleaseReviewSteps(stepperNode, trainingCenterReleaseReviewSteps(effectiveReview), '待进入发布评审');
    const substeps = trainingCenterReleaseReviewSubsteps(effectiveReview);
    const fallbackSteps = trainingCenterReleaseFallbackSteps(effectiveReview);
    renderTrainingCenterReleaseReviewPills(
      substageNode,
      substeps.concat(fallbackSteps),
      '确认发布后会持续展示 Git / release note / 校验 / 兜底阶段'
    );

    if (enterBtn) {
      enterBtn.disabled = !!progress || !effectiveReview.can_enter;
      enterBtn.textContent =
        progressMode === 'enter'
          ? '进入中...'
          : safe(review.review_id).trim()
            ? '重新进入发布评审'
            : '进入发布评审';
    }
    if (discardBtn) {
      discardBtn.disabled = !!progress || !effectiveReview.can_discard;
      discardBtn.textContent = '废弃当前评审';
      discardBtn.hidden = !hasActiveReview;
    }
    if (confirmBtn) {
      confirmBtn.disabled = !!progress || !effectiveReview.can_confirm;
      confirmBtn.textContent =
        progressMode === 'confirm'
          ? '发布中...'
          : safe(review.publish_status).trim().toLowerCase() === 'success'
            ? '已发布成功'
            : safe(effectiveReview.release_review_state).trim() === 'publish_failed'
              ? '重试发布'
              : '确认发布';
      confirmBtn.hidden = !hasActiveReview;
    }
    if (decisionSelect) {
      const rejectDiscardOption = Array.from(decisionSelect.options || []).find(
        (option) => safe(option && option.value).trim() === 'reject_discard_pre_release'
      );
      if (rejectDiscardOption) rejectDiscardOption.disabled = !hasPublishedRelease;
      decisionSelect.disabled = !canReview;
      decisionSelect.value = safe(effectiveReview.review_decision).trim() || (hasPublishedRelease ? 'approve_publish' : 'reject_continue_training');
      if (!hasPublishedRelease && safe(decisionSelect.value).trim() === 'reject_discard_pre_release') {
        decisionSelect.value = 'reject_continue_training';
      }
    }
    if (reviewerInput) {
      reviewerInput.disabled = !canReview;
      reviewerInput.value = safe(effectiveReview.reviewer).trim() || '';
    }
    if (summaryInput) {
      summaryInput.disabled = !canReview;
      summaryInput.value = safe(effectiveReview.review_comment).trim() || '';
    }
    if (submitBtn) {
      submitBtn.disabled = !canReview;
      submitBtn.textContent = progressMode === 'enter'
        ? '报告生成中...'
        : progressMode === 'confirm'
          ? '发布执行中...'
          : canReview
            ? '提交审核结论'
            : '等待发布报告完成';
    }

    if (!hasActiveReview) {
      const emptyStateText =
        contextLoading && !safe(review.review_id).trim() && !progress
          ? '正在同步发布评审链路'
          : '当前没有进行中的发布评审';
      const emptyHintText =
        contextLoading && !safe(review.review_id).trim() && !progress
          ? '正在同步历史发布版本与评审上下文，请稍候...'
          : '历史正式发布记录请从“发布版本”列表点击“查看发布报告”查看';
      renderTrainingCenterReleaseReviewProgress(progressNode, null);
      renderTrainingCenterReleaseReviewSteps(stepperNode, [], emptyStateText);
      renderTrainingCenterReleaseReviewPills(substageNode, [], emptyHintText);
      [reportNode, chainNode, manualMetaNode, logsNode, fallbackNode].forEach((node) => {
        if (!node) return;
        node.innerHTML = '';
        if (contextLoading && !safe(review.review_id).trim() && !progress) {
          const empty = document.createElement('div');
          empty.className = 'tc-empty';
          empty.textContent = '正在同步发布评审链路...';
          node.appendChild(empty);
        }
      });
      return;
    }

    renderTrainingCenterReleaseReport(reportNode, effectiveReview, progress, reportCodexFailure, reportFailure);

    if (chainNode) {
      chainNode.innerHTML = '';
      const analysisChain = effectiveReview.analysis_chain && typeof effectiveReview.analysis_chain === 'object' ? effectiveReview.analysis_chain : {};
      const codexSummary = analysisChain.codex_summary && typeof analysisChain.codex_summary === 'object' ? analysisChain.codex_summary : {};
      const chainRows = [
        ['提示词版本', safe(analysisChain.prompt_version || review.prompt_version).trim()],
        ['提示词文件', safe(analysisChain.prompt_path).trim()],
        ['报告文件', safe(analysisChain.report_path).trim()],
        ['公开介绍快照', safe(effectiveReview.public_profile_markdown_path || analysisChain.public_profile_markdown_path).trim()],
        ['能力快照', safe(effectiveReview.capability_snapshot_json_path || analysisChain.capability_snapshot_json_path).trim()],
        ['stdout', safe(analysisChain.stdout_path).trim()],
        ['stderr', safe(analysisChain.stderr_path).trim()],
        ['trace 目录', safe(analysisChain.trace_dir).trim()],
        ['执行摘要', safe(analysisChain.command_summary).trim()],
      ].filter((entry) => !!entry[1]);
      chainRows.forEach((entry) => {
        const row = document.createElement('div');
        row.className = 'tc-release-review-row';
        const labelNode = document.createElement('span');
        labelNode.className = 'tc-release-review-row-label';
        labelNode.textContent = entry[0];
        const valueNode = document.createElement('span');
        valueNode.className = 'tc-release-review-row-value code';
        valueNode.textContent = entry[1];
        row.appendChild(labelNode);
        row.appendChild(valueNode);
        chainNode.appendChild(row);
      });
      if (Object.keys(codexSummary).length) {
        const summaryNode = document.createElement('div');
        summaryNode.className = 'tc-release-review-note';
        summaryNode.textContent =
          'Codex 摘要：exit=' +
          safe(codexSummary.exit_code) +
          ' · events=' +
          safe(codexSummary.event_count) +
          ' · duration_ms=' +
          safe(codexSummary.duration_ms);
        chainNode.appendChild(summaryNode);
      }
      const promptText = safe(analysisChain.prompt_text).trim();
      if (promptText) {
        const promptPre = document.createElement('pre');
        promptPre.className = 'tc-release-review-pre';
        promptPre.textContent = promptText;
        chainNode.appendChild(promptPre);
      }
      if (!chainRows.length && !promptText) {
        const empty = document.createElement('div');
        empty.className = 'tc-empty';
        empty.textContent = progress && safe(progress.mode).trim().toLowerCase() === 'enter'
          ? '正在委派 Codex 分析，完成后会展示提示词、stdout/stderr 与报告路径'
          : '生成发布报告后，这里会展示提示词、Codex 摘要以及 stdout/stderr/report 路径';
        chainNode.appendChild(empty);
      }
    }

    if (manualMetaNode) {
      manualMetaNode.innerHTML = '';
      const statusNode = document.createElement('div');
      statusNode.className = 'tc-release-review-note';
      statusNode.textContent = '当前状态：' + trainingCenterReleaseReviewStateText(effectiveReview.release_review_state);
      manualMetaNode.appendChild(statusNode);
      if (safe(effectiveReview.release_review_state).trim().toLowerCase() === 'review_discarded') {
        const discardedNode = document.createElement('div');
        discardedNode.className = 'tc-release-review-note';
        discardedNode.textContent = '当前评审记录已废弃；如需继续，请重新进入发布评审。';
        manualMetaNode.appendChild(discardedNode);
      }
      if (safe(effectiveReview.review_decision).trim()) {
        [
          ['审核结论', trainingCenterReleaseReviewDecisionText(effectiveReview.review_decision)],
          ['审核人', safe(effectiveReview.reviewer).trim() || '-'],
          ['审核时间', safe(effectiveReview.reviewed_at).trim() || '-'],
          ['审核意见', safe(effectiveReview.review_comment).trim() || '-'],
        ].forEach((entry) => {
          const row = document.createElement('div');
          row.className = 'tc-release-review-row';
          const labelNode = document.createElement('span');
          labelNode.className = 'tc-release-review-row-label';
          labelNode.textContent = entry[0];
          const valueNode = document.createElement('span');
          valueNode.className = 'tc-release-review-row-value';
          valueNode.textContent = entry[1];
          row.appendChild(labelNode);
          row.appendChild(valueNode);
          manualMetaNode.appendChild(row);
        });
      } else if (!canReview) {
        const empty = document.createElement('div');
        empty.className = 'tc-empty';
        empty.textContent = progressMode === 'enter'
          ? '发布报告生成中，人工审核入口暂不可用'
          : progressMode === 'confirm'
            ? '确认发布执行中，人工审核结论已锁定'
            : '发布报告完成后，才允许提交人工审核结论';
        manualMetaNode.appendChild(empty);
      }
    }

    if (logsNode) {
      logsNode.innerHTML = '';
      const logs = Array.isArray(effectiveReview.execution_logs) ? effectiveReview.execution_logs : [];
      if (codexFailureHasValue(publishCodexFailure)) {
        const failureHost = document.createElement('div');
        logsNode.appendChild(failureHost);
        renderCodexFailureCard(failureHost, publishCodexFailure, {
          title: '确认发布失败',
          compact: true,
          context: {
            agentId: key,
          },
        });
      } else if (publishFailure) {
        const errorNode = document.createElement('div');
        errorNode.className = 'tc-release-review-note danger';
        errorNode.textContent = publishFailure.summary;
        logsNode.appendChild(errorNode);
        const suggestionNode = document.createElement('div');
        suggestionNode.className = 'tc-release-review-note';
        suggestionNode.textContent = publishFailure.suggestion;
        logsNode.appendChild(suggestionNode);
        if (safe(publishFailure.inspect_hint).trim()) {
          const inspectNode = document.createElement('div');
          inspectNode.className = 'tc-release-review-note';
          inspectNode.textContent = publishFailure.inspect_hint;
          logsNode.appendChild(inspectNode);
        }
      }
      if (!logs.length) {
        const empty = document.createElement('div');
        empty.className = 'tc-empty';
        empty.textContent = progress && safe(progress.mode).trim().toLowerCase() === 'confirm'
          ? '确认发布运行中，执行日志返回后会持续展示 prepare / git_execute / release_note / verify / fallback 摘要'
          : '确认发布后，这里会持续显示 prepare / git_execute / release_note / verify / fallback 摘要';
        logsNode.appendChild(empty);
      } else {
        logs.forEach((log) => {
          const item = document.createElement('div');
          item.className = 'tc-release-review-log-item';
          const head = document.createElement('div');
          head.className = 'tc-release-review-log-head';
          const phase = document.createElement('span');
          phase.className = 'tc-release-review-log-phase';
          phase.textContent = safe(log && log.phase).trim() || 'unknown';
          const status = document.createElement('span');
          status.className = 'tc-release-review-pill ' + (safe(log && log.status).trim() || 'pending');
          status.textContent = safe(log && log.status).trim() || 'pending';
          head.appendChild(phase);
          head.appendChild(status);
          item.appendChild(head);
          const message = document.createElement('div');
          message.className = 'tc-release-review-log-message';
          message.textContent = safe(log && log.message).trim() || '-';
          item.appendChild(message);
          const meta = [];
          if (safe(log && log.path).trim()) meta.push('path=' + safe(log.path).trim());
          if (safe(log && log.ts).trim()) meta.push('ts=' + safe(log.ts).trim());
          if (meta.length) {
            const metaNode = document.createElement('div');
            metaNode.className = 'tc-release-review-log-meta';
            metaNode.textContent = meta.join(' · ');
            item.appendChild(metaNode);
          }
          if (log && log.details && typeof log.details === 'object' && Object.keys(log.details).length) {
            const detailsNode = document.createElement('pre');
            detailsNode.className = 'tc-release-review-pre compact';
            detailsNode.textContent = JSON.stringify(log.details, null, 2);
            item.appendChild(detailsNode);
          }
          logsNode.appendChild(item);
        });
      }
    }

    if (fallbackNode) {
      fallbackNode.innerHTML = '';
      const fallback = effectiveReview.fallback && typeof effectiveReview.fallback === 'object' ? effectiveReview.fallback : {};
      if (!safe(fallback.status).trim()) {
        const empty = document.createElement('div');
        empty.className = 'tc-empty';
        empty.textContent = '发布失败时，这里会展示失败原因、自动重试结果与下一步建议';
        fallbackNode.appendChild(empty);
      } else {
        [
          ['兜底状态', safe(fallback.status).trim()],
          ['失败原因', safe(fallback.failure_reason || fallback.error).trim() || '-'],
          ['修复摘要', safe(fallback.repair_summary).trim() || '-'],
          ['下一步建议', safe(fallback.next_action_suggestion).trim() || '-'],
        ].forEach((entry) => {
          const row = document.createElement('div');
          row.className = 'tc-release-review-row';
          const labelNode = document.createElement('span');
          labelNode.className = 'tc-release-review-row-label';
          labelNode.textContent = entry[0];
          const valueNode = document.createElement('span');
          valueNode.className = 'tc-release-review-row-value';
          valueNode.textContent = entry[1];
          row.appendChild(labelNode);
          row.appendChild(valueNode);
          fallbackNode.appendChild(row);
        });
        const repairActions = Array.isArray(fallback.repair_actions) ? fallback.repair_actions.filter((item) => safe(item).trim()) : [];
        if (repairActions.length) {
          const actionsPre = document.createElement('pre');
          actionsPre.className = 'tc-release-review-pre compact';
          actionsPre.textContent = repairActions.join('\n');
          fallbackNode.appendChild(actionsPre);
        }
        const retryResult = fallback.retry_result && typeof fallback.retry_result === 'object' ? fallback.retry_result : {};
        if (Object.keys(retryResult).length) {
          const retryPre = document.createElement('pre');
          retryPre.className = 'tc-release-review-pre compact';
          retryPre.textContent = JSON.stringify(retryResult, null, 2);
          fallbackNode.appendChild(retryPre);
        }
      }
    }
  }
