  // Training center release review report helpers.

  function trainingCenterReleaseReviewFieldLabel(fieldName) {
    const key = safe(fieldName).trim().toLowerCase();
    if (key === 'target_version') return '目标版本';
    if (key === 'current_workspace_ref') return '工作区基线';
    if (key === 'first_person_summary') return '第一人称摘要';
    if (key === 'full_capability_inventory') return '全量能力清单';
    if (key === 'knowledge_scope') return '知识范围';
    if (key === 'agent_skills') return 'Agent Skills';
    if (key === 'applicable_scenarios') return '适用场景';
    if (key === 'change_summary') return '变更摘要';
    if (key === 'release_recommendation') return '发布建议';
    if (key === 'next_action_suggestion') return '下一步建议';
    return safe(fieldName).trim() || '未知字段';
  }

  function trainingCenterReleaseReviewFieldPresent(value) {
    if (Array.isArray(value)) {
      return value.some((item) => !!safe(item).trim());
    }
    if (value && typeof value === 'object') {
      return Object.keys(value).length > 0;
    }
    return !!safe(value).trim();
  }

  function trainingCenterReleaseReviewMissingReportFields(review) {
    const reviewNode = review && typeof review === 'object' ? review : {};
    const node = reviewNode.report && typeof reviewNode.report === 'object' ? reviewNode.report : {};
    const requiredFields = Array.isArray(reviewNode.required_report_fields) ? reviewNode.required_report_fields : [];
    return requiredFields
      .filter((fieldName) => !trainingCenterReleaseReviewFieldPresent(node[fieldName]))
      .map((fieldName) => trainingCenterReleaseReviewFieldLabel(fieldName));
  }

  function describeTrainingCenterReleaseReportFailure(review, localError) {
    const reviewNode = review && typeof review === 'object' ? review : {};
    const localNode = localError && typeof localError === 'object' ? localError : {};
    const chain = reviewNode.analysis_chain && typeof reviewNode.analysis_chain === 'object' ? reviewNode.analysis_chain : {};
    const rawMessage = safe(reviewNode.report_error).trim() || (safe(localNode.mode).trim().toLowerCase() === 'enter' ? safe(localNode.error_message).trim() : '');
    const errorCode = safe(reviewNode.report_error_code || chain.report_error_code || localNode.error_code).trim().toLowerCase();
    const missingFields = errorCode === 'release_review_report_incomplete' ? trainingCenterReleaseReviewMissingReportFields(reviewNode) : [];
    const chainError = safe(chain.error || localNode.error_reason || localNode.error_code).trim().toLowerCase();
    const exitCode = Number(chain.codex_summary && chain.codex_summary.exit_code);
    let summary = rawMessage;
    if (!summary || safe(summary).trim().toLowerCase() === 'release review report failed') {
      if (errorCode === 'release_review_report_incomplete' && missingFields.length) {
        summary = '生成发布报告失败：结构化报告缺少关键字段（' + missingFields.join(' / ') + '）。';
      } else if (chainError === 'codex_command_not_found') {
        summary = '生成发布报告失败：当前环境未找到 codex 命令。';
      } else if (chainError === 'codex_exec_timeout') {
        summary = '生成发布报告失败：Codex 执行超时。';
      } else if (chainError.startsWith('codex_exec_failed_exit_')) {
        summary = '生成发布报告失败：Codex 执行异常退出（exit=' + chainError.slice('codex_exec_failed_exit_'.length) + '）。';
      } else if (chainError === 'codex_result_missing') {
        summary = '生成发布报告失败：Codex 已执行，但没有产出可解析的结构化 JSON 报告。';
      } else if (Number.isFinite(exitCode) && exitCode > 0) {
        summary = '生成发布报告失败：Codex 执行异常退出（exit=' + String(exitCode) + '）。';
      }
    }
    if (!summary) return null;

    let suggestion = '';
    if (!/请先|建议|重新进入发布评审/.test(summary)) {
      if (errorCode === 'release_review_report_incomplete' && missingFields.length) {
        suggestion = '建议先检查报告文件是否缺少 ' + missingFields.join(' / ') + '，修正后点击“重新进入发布评审”。';
      } else if (safe(chain.stderr_path).trim() || safe(chain.stdout_path).trim() || safe(chain.report_path).trim()) {
        suggestion = '建议先查看分析链路里的 stderr / stdout / 报告文件，定位原因后点击“重新进入发布评审”。';
      } else {
        suggestion = '建议先处理环境或工作区问题，再点击“重新进入发布评审”。';
      }
    } else if (errorCode === 'release_review_report_incomplete' && missingFields.length && !/stderr|stdout|报告文件/.test(summary)) {
      suggestion = '建议先检查报告文件是否缺少 ' + missingFields.join(' / ') + '，修正后点击“重新进入发布评审”。';
    }

    const inspectParts = [];
    if (safe(chain.stderr_path).trim()) inspectParts.push('stderr');
    if (safe(chain.stdout_path).trim()) inspectParts.push('stdout');
    if (safe(chain.report_path).trim()) inspectParts.push('报告文件');
    return {
      summary: summary,
      suggestion: suggestion,
      inspect_hint: inspectParts.length ? '优先排查：' + inspectParts.join(' / ') : '',
    };
  }

  function findTrainingCenterReleaseFailedLog(review) {
    const logs = Array.isArray(review && review.execution_logs) ? review.execution_logs : [];
    return logs.find((item) => safe(item && item.status).trim().toLowerCase() === 'failed') || null;
  }

  function describeTrainingCenterReleasePublishFailure(review, localError) {
    const reviewNode = review && typeof review === 'object' ? review : {};
    const localNode = localError && typeof localError === 'object' ? localError : {};
    const fallback = reviewNode.fallback && typeof reviewNode.fallback === 'object' ? reviewNode.fallback : {};
    const failedLog = findTrainingCenterReleaseFailedLog(reviewNode);
    const message = safe(reviewNode.publish_error).trim() || (safe(localNode.mode).trim().toLowerCase() === 'confirm' ? safe(localNode.error_message).trim() : '');
    if (!message && !failedLog && !safe(fallback.failure_reason || fallback.error).trim()) return null;

    const phase = safe(failedLog && failedLog.phase).trim().toLowerCase();
    let suggestion = safe(fallback.next_action_suggestion).trim();
    if (!suggestion) {
      if (phase === 'git_execute') {
        suggestion = reviewNode.can_confirm
          ? '建议先检查 Git 标签/提交是否可写、是否存在冲突；修复后可直接点击“重试发布”。'
          : '建议先检查 Git 标签/提交是否可写、是否存在冲突，然后重新点击“确认发布”。';
      } else if (phase === 'release_note') {
        suggestion = reviewNode.can_confirm
          ? '建议先检查 release note 是否成功写入并符合当前版本识别规则；修正后可直接点击“重试发布”。'
          : '建议先检查 release note 是否成功写入并符合当前版本识别规则，修正后重新点击“确认发布”。';
      } else if (phase === 'verify') {
        suggestion = reviewNode.can_confirm
          ? '建议先检查 Git 标签和 release note 是否都已落盘并可被当前版本规则识别；修复后可直接点击“重试发布”。'
          : '建议先检查 Git 标签和 release note 是否都已落盘并可被当前版本规则识别，再重新点击“确认发布”。';
      } else if (safe(fallback.status).trim()) {
        suggestion = reviewNode.can_confirm
          ? '自动兜底已执行但仍未完成；请根据兜底结果修复问题后直接点击“重试发布”，若报告本身需要变化再重新进入发布评审。'
          : '自动兜底已执行但仍未完成，请根据兜底结果人工处理后再重试。';
      } else {
        suggestion = reviewNode.can_confirm
          ? '建议先查看执行日志中的失败阶段，修复后可直接点击“重试发布”。'
          : '建议先查看执行日志中的失败阶段，修复后再重新点击“确认发布”。';
      }
    }

    const detailText =
      safe(failedLog && failedLog.message).trim() ||
      safe(fallback.repair_summary).trim() ||
      safe(fallback.failure_reason || fallback.error).trim() ||
      message;
    return {
      summary: message || detailText,
      suggestion: suggestion,
      inspect_hint: phase ? '失败阶段：' + phase : '',
    };
  }

  function applyTrainingCenterReleaseReviewProgress(review, progress) {
    if (!progress) return review;
    const next = Object.assign({}, review || {});
    const mode = safe(progress.mode).trim().toLowerCase();
    if (mode === 'confirm') {
      next.release_review_state = progress.failed ? 'publish_failed' : 'publish_running';
      next.can_discard = false;
      if (progress.active) next.can_confirm = false;
      if (progress.active) next.publish_codex_failure = null;
      if (progress.failed && !safe(next.publish_error).trim()) {
        next.publish_error = safe(progress.error_message).trim();
      }
    } else {
      next.release_review_state = progress.failed ? 'report_failed' : 'report_generating';
      next.analysis_chain = {};
      next.report = {};
      next.report_error_code = '';
      next.report_missing_fields = [];
      next.review_decision = '';
      next.reviewer = '';
      next.review_comment = '';
      next.reviewed_at = '';
      next.publish_version = '';
      next.publish_status = '';
      next.publish_error = '';
      next.codex_failure = null;
      next.publish_codex_failure = null;
      next.execution_logs = [];
      next.fallback = {};
      next.can_discard = false;
      if (progress.active) {
        next.can_enter = false;
        next.can_review = false;
      }
      if (progress.failed && !safe(next.report_error).trim()) {
        next.report_error = safe(progress.error_message).trim();
      }
    }
    if (!safe(next.review_id).trim()) {
      next.review_id = '__local_progress__';
    }
    return next;
  }

  function trainingCenterReleaseReviewStateText(value) {
    const key = safe(value).trim().toLowerCase();
    if (key === 'report_generating') return '生成发布报告中';
    if (key === 'report_ready') return '发布报告已就绪';
    if (key === 'review_approved') return '人工审核已通过';
    if (key === 'review_rejected') return '人工审核未通过';
    if (key === 'review_discarded') return '当前评审已废弃';
    if (key === 'publish_running') return '确认发布执行中';
    if (key === 'publish_failed') return '确认发布失败';
    if (key === 'report_failed') return '发布报告生成失败';
    return '待进入发布评审';
  }

  function trainingCenterReleaseReviewDecisionText(value) {
    const key = safe(value).trim().toLowerCase();
    if (key === 'approve_publish') return '通过并进入确认发布';
    if (key === 'reject_continue_training') return '不通过：继续训练';
    if (key === 'reject_discard_pre_release') return '不通过：舍弃预发布';
    if (key === 'discard_review') return '已废弃当前评审记录';
    return key ? safe(value) : '未提交';
  }

  function trainingCenterReleaseLogStatus(logs, phase) {
    const rows = Array.isArray(logs) ? logs.filter((item) => safe(item && item.phase).trim() === phase) : [];
    if (!rows.length) return 'pending';
    for (let index = rows.length - 1; index >= 0; index -= 1) {
      const status = safe(rows[index] && rows[index].status).trim().toLowerCase();
      if (status === 'failed') return 'failed';
      if (status === 'running') return 'current';
      if (status === 'done') return 'done';
    }
    return 'pending';
  }

  function trainingCenterReleaseSubstepLabel(kind, status) {
    const key = safe(kind).trim().toLowerCase();
    const phaseStatus = safe(status).trim().toLowerCase();
    if (key === 'git') {
      if (phaseStatus === 'done') return 'Git 发布完成';
      if (phaseStatus === 'failed') return 'Git 发布失败';
      if (phaseStatus === 'current') return 'Git 发布中';
      return 'Git 发布待执行';
    }
    if (key === 'release_note') {
      if (phaseStatus === 'done') return 'release note 已完成';
      if (phaseStatus === 'failed') return 'release note 失败';
      if (phaseStatus === 'current') return 'release note 处理中';
      return 'release note 待处理';
    }
    if (key === 'verify') {
      if (phaseStatus === 'done') return '成功校验通过';
      if (phaseStatus === 'failed') return '成功校验失败';
      if (phaseStatus === 'current') return '成功校验中';
      return '成功校验待执行';
    }
    return safe(kind).trim();
  }

  function trainingCenterReleaseReviewSteps(review) {
    const stateKey = safe(review && review.release_review_state).trim().toLowerCase();
    const publishSuccess = safe(review && review.publish_status).trim().toLowerCase() === 'success';
    return [
      {
        label: '进入发布评审',
        status: safe(review && review.review_id).trim() ? 'done' : 'current',
      },
      {
        label: '生成发布报告',
        status:
          stateKey === 'report_failed'
            ? 'failed'
            : stateKey === 'report_generating'
              ? 'current'
              : safe(review && review.review_id).trim()
                ? 'done'
                : 'pending',
      },
      {
        label: '人工审核',
        status:
          stateKey === 'review_rejected'
            || stateKey === 'review_discarded'
            ? 'failed'
            : stateKey === 'report_ready'
              ? 'current'
              : stateKey === 'review_approved' || stateKey === 'publish_running' || stateKey === 'publish_failed' || publishSuccess
                ? 'done'
                : safe(review && review.review_id).trim()
                  ? 'pending'
                  : 'pending',
      },
      {
        label: '确认发布',
        status:
          publishSuccess
            ? 'done'
            : stateKey === 'publish_failed'
              ? 'failed'
              : stateKey === 'review_approved' || stateKey === 'publish_running'
                ? 'current'
                : 'pending',
      },
    ];
  }

  function trainingCenterReleaseReviewSubsteps(review) {
    const logs = Array.isArray(review && review.execution_logs) ? review.execution_logs : [];
    const stateKey = safe(review && review.release_review_state).trim().toLowerCase();
    const publishSuccess = safe(review && review.publish_status).trim().toLowerCase() === 'success';
    const gitStatus = trainingCenterReleaseLogStatus(logs, 'git_execute');
    const releaseNoteStatus = trainingCenterReleaseLogStatus(logs, 'release_note');
    const verifyStatus = trainingCenterReleaseLogStatus(logs, 'verify');
    const hasPublishTrace =
      stateKey === 'publish_running' ||
      stateKey === 'publish_failed' ||
      publishSuccess ||
      logs.some((item) => ['prepare', 'git_execute', 'release_note', 'verify'].includes(safe(item && item.phase).trim()));
    if (!hasPublishTrace) return [];
    const finalStatus = publishSuccess ? 'done' : stateKey === 'publish_failed' ? 'failed' : stateKey === 'publish_running' ? 'current' : 'pending';
    return [
      {
        label: trainingCenterReleaseSubstepLabel('git', gitStatus === 'pending' && stateKey === 'publish_running' ? 'current' : gitStatus),
        status: gitStatus === 'pending' && stateKey === 'publish_running' ? 'current' : gitStatus,
      },
      {
        label: trainingCenterReleaseSubstepLabel('release_note', releaseNoteStatus === 'pending' && stateKey === 'publish_running' ? 'current' : releaseNoteStatus),
        status: releaseNoteStatus === 'pending' && stateKey === 'publish_running' ? 'current' : releaseNoteStatus,
      },
      {
        label: trainingCenterReleaseSubstepLabel('verify', verifyStatus === 'pending' && stateKey === 'publish_running' ? 'current' : verifyStatus),
        status: verifyStatus === 'pending' && stateKey === 'publish_running' ? 'current' : verifyStatus,
      },
      {
        label: publishSuccess ? '发布完成' : stateKey === 'publish_failed' ? '发布失败' : '完成 / 失败',
        status: finalStatus,
      },
    ];
  }

  function trainingCenterReleaseFallbackSteps(review) {
    const fallback = review && review.fallback && typeof review.fallback === 'object' ? review.fallback : {};
    const status = safe(fallback.status).trim().toLowerCase();
    if (!status) return [];
    return [
      {
        label: '兜底中',
        status: status === 'fallback_done' || status === 'fallback_failed' ? 'done' : 'current',
      },
      {
        label: '兜底完成',
        status: status === 'fallback_done' ? 'done' : 'pending',
      },
      {
        label: '兜底失败',
        status: status === 'fallback_failed' ? 'failed' : 'pending',
      },
    ];
  }

  function renderTrainingCenterReleaseReviewSteps(host, items, emptyText) {
    if (!host) return;
    host.innerHTML = '';
    if (!Array.isArray(items) || !items.length) {
      const empty = document.createElement('div');
      empty.className = 'tc-empty';
      empty.textContent = safe(emptyText || '暂无阶段信息');
      host.appendChild(empty);
      return;
    }
    items.forEach((item, index) => {
      const node = document.createElement('div');
      node.className = 'tc-release-review-step ' + safe(item && item.status).trim();
      const indexNode = document.createElement('span');
      indexNode.className = 'tc-release-review-step-index';
      indexNode.textContent = String(index + 1);
      const labelNode = document.createElement('span');
      labelNode.className = 'tc-release-review-step-label';
      labelNode.textContent = safe(item && item.label);
      node.appendChild(indexNode);
      node.appendChild(labelNode);
      host.appendChild(node);
    });
  }

  function renderTrainingCenterReleaseReviewPills(host, items, emptyText) {
    if (!host) return;
    host.innerHTML = '';
    if (!Array.isArray(items) || !items.length) {
      const empty = document.createElement('div');
      empty.className = 'tc-empty';
      empty.textContent = safe(emptyText || '暂无子阶段信息');
      host.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const badge = document.createElement('span');
      badge.className = 'tc-release-review-pill ' + safe(item && item.status).trim();
      badge.textContent = safe(item && item.label);
      host.appendChild(badge);
    });
  }

  function createTrainingCenterReleaseReportModule(title, description) {
    const section = document.createElement('section');
    section.className = 'tc-release-report-module';
    const head = document.createElement('div');
    head.className = 'tc-release-report-module-head';
    const titleNode = document.createElement('div');
    titleNode.className = 'tc-release-report-module-title';
    titleNode.textContent = safe(title);
    head.appendChild(titleNode);
    const descText = safe(description).trim();
    if (descText) {
      const descNode = document.createElement('div');
      descNode.className = 'tc-release-report-module-desc';
      descNode.textContent = descText;
      head.appendChild(descNode);
    }
    const body = document.createElement('div');
    body.className = 'tc-release-report-module-body';
    section.appendChild(head);
    section.appendChild(body);
    return {
      section,
      body,
    };
  }

  function createTrainingCenterReleaseReportCard(label, value, options) {
    const card = document.createElement('section');
    card.className = 'tc-release-report-card';
    const labelNode = document.createElement('div');
    labelNode.className = 'tc-release-report-card-label';
    labelNode.textContent = safe(label);
    const valueNode = document.createElement('div');
    const classes = ['tc-release-report-card-value'];
    if (options && options.code) classes.push('code');
    if (options && options.tag) classes.push('tag');
    if (options && options.strong) classes.push('strong');
    valueNode.className = classes.join(' ');
    valueNode.textContent = safe(value).trim() || safe(options && options.emptyText).trim() || '—';
    card.appendChild(labelNode);
    card.appendChild(valueNode);
    return card;
  }

  function createTrainingCenterReleaseReportList(items, tone) {
    const values = (Array.isArray(items) ? items : []).map((item) => safe(item).trim()).filter(Boolean);
    if (!values.length) return null;
    const list = document.createElement('ul');
    list.className = 'tc-release-report-list' + (safe(tone).trim() ? ' ' + safe(tone).trim() : '');
    values.forEach((text) => {
      const item = document.createElement('li');
      item.className = 'tc-release-report-list-item';
      item.textContent = text;
      list.appendChild(item);
    });
    return list;
  }

  function renderTrainingCenterReleaseReport(host, effectiveReview, progress, reportCodexFailure, reportFailure) {
    if (!host) return;
    host.innerHTML = '';
    const stack = document.createElement('div');
    stack.className = 'tc-release-report-stack';
    host.appendChild(stack);
    let moduleCount = 0;

    if (codexFailureHasValue(reportCodexFailure)) {
      const failureHost = document.createElement('div');
      stack.appendChild(failureHost);
      renderCodexFailureCard(failureHost, reportCodexFailure, {
        title: '发布报告失败',
        context: {
          agentId: safe(effectiveReview && effectiveReview.agent_id).trim(),
        },
      });
      moduleCount += 1;
    } else if (reportFailure) {
      const alert = document.createElement('section');
      alert.className = 'tc-release-report-alert danger';
      const titleNode = document.createElement('div');
      titleNode.className = 'tc-release-report-alert-title';
      titleNode.textContent = '生成发布报告失败';
      alert.appendChild(titleNode);
      [reportFailure.summary, reportFailure.suggestion, reportFailure.inspect_hint]
        .map((item) => safe(item).trim())
        .filter(Boolean)
        .forEach((text, index) => {
          const line = document.createElement('div');
          line.className = 'tc-release-report-alert-line' + (index === 0 ? ' strong' : '');
          line.textContent = text;
          alert.appendChild(line);
        });
      stack.appendChild(alert);
      moduleCount += 1;
    }

    const report = effectiveReview && effectiveReview.report && typeof effectiveReview.report === 'object'
      ? effectiveReview.report
      : {};
    const coreEntries = [
      {
        label: '目标版本',
        value: safe(report.target_version).trim(),
        options: {
          tag: true,
        },
      },
      {
        label: '工作区基线',
        value: safe(report.current_workspace_ref).trim(),
        options: {
          code: true,
        },
      },
      {
        label: '上一正式版本',
        value: safe(report.previous_release_version).trim(),
        options: {
          tag: true,
        },
      },
      {
        label: '发布建议',
        value: safe(report.release_recommendation).trim(),
        options: {
          strong: true,
        },
      },
      {
        label: '下一步建议',
        value: safe(report.next_action_suggestion).trim(),
      },
    ].filter((entry) => !!entry.value);
    if (coreEntries.length) {
      const module = createTrainingCenterReleaseReportModule('核心信息', '先看版本、基线与发布结论');
      const grid = document.createElement('div');
      grid.className = 'tc-release-report-core-grid';
      coreEntries.forEach((entry) => {
        grid.appendChild(createTrainingCenterReleaseReportCard(entry.label, entry.value, entry.options));
      });
      module.body.appendChild(grid);
      stack.appendChild(module.section);
      moduleCount += 1;
    }

    const firstPersonSummary = safe(report.first_person_summary).trim();
    const fullCapabilityInventory = Array.isArray(report.full_capability_inventory) ? report.full_capability_inventory : [];
    const knowledgeScope = safe(report.knowledge_scope).trim();
    const agentSkills = Array.isArray(report.agent_skills) ? report.agent_skills : [];
    const applicableScenarios = Array.isArray(report.applicable_scenarios) ? report.applicable_scenarios : [];
    const roleProfilePreviewParts = [];
    if (firstPersonSummary) {
      const summaryNode = document.createElement('div');
      summaryNode.className = 'tc-release-report-text';
      summaryNode.textContent = firstPersonSummary;
      roleProfilePreviewParts.push(summaryNode);
    }
    const inventoryList = createTrainingCenterReleaseReportList(fullCapabilityInventory, 'capability');
    if (inventoryList) {
      roleProfilePreviewParts.push(inventoryList);
    }
    const previewFacts = [
      ['角色知识范围', knowledgeScope],
      ['Agent Skills', agentSkills.join('、')],
      ['适用场景', applicableScenarios.join('、')],
    ].filter((entry) => !!safe(entry[1]).trim());
    if (previewFacts.length) {
      const previewGrid = document.createElement('div');
      previewGrid.className = 'tc-release-report-core-grid';
      previewFacts.forEach((entry) => {
        previewGrid.appendChild(createTrainingCenterReleaseReportCard(entry[0], entry[1], {}));
      });
      roleProfilePreviewParts.push(previewGrid);
    }
    if (roleProfilePreviewParts.length) {
      const module = createTrainingCenterReleaseReportModule('正式发布角色介绍预览', '确认发布成功后，角色详情页优先展示这里的第一人称全量介绍');
      roleProfilePreviewParts.forEach((node) => module.body.appendChild(node));
      stack.appendChild(module.section);
      moduleCount += 1;
    }

    const changeSummary = safe(report.change_summary).trim();
    const capabilityDeltaList = createTrainingCenterReleaseReportList(report.capability_delta, 'capability');
    if (changeSummary || capabilityDeltaList) {
      const module = createTrainingCenterReleaseReportModule('功能差异报告', '重点说明相对上一正式发布版本的变化');
      const text = document.createElement('div');
      text.className = 'tc-release-report-text';
      text.textContent = changeSummary || '当前未补充结构化变更摘要。';
      module.body.appendChild(text);
      if (capabilityDeltaList) {
        module.body.appendChild(capabilityDeltaList);
      }
      stack.appendChild(module.section);
      moduleCount += 1;
    }

    [
      ['风险清单', report.risk_list, 'risk', '发布前需要继续确认或补齐的风险点'],
      ['验证证据', report.validation_evidence, 'evidence', '报告中引用的验证动作与结果'],
      ['补充提示', report.warnings, 'warning', '非阻断但建议关注的附加说明'],
    ].forEach((entry) => {
      const title = entry[0];
      const values = entry[1];
      const tone = entry[2];
      const description = entry[3];
      const list = createTrainingCenterReleaseReportList(values, tone);
      if (!list) return;
      const module = createTrainingCenterReleaseReportModule(title, description);
      module.body.appendChild(list);
      stack.appendChild(module.section);
      moduleCount += 1;
    });

    if (!moduleCount) {
      const empty = document.createElement('section');
      empty.className = 'tc-release-report-empty';
      const titleNode = document.createElement('div');
      titleNode.className = 'tc-release-report-empty-title';
      titleNode.textContent = '结构化发布报告';
      const bodyNode = document.createElement('div');
      bodyNode.className = 'tc-release-report-empty-text';
      bodyNode.textContent = progress && safe(progress.mode).trim().toLowerCase() === 'enter'
        ? '正在生成发布报告，请稍候...'
        : safe(effectiveReview && effectiveReview.report_error).trim()
          ? '请先处理报告失败原因，再重新进入发布评审'
          : '进入发布评审后，这里会按模块展示结构化发布报告';
      empty.appendChild(titleNode);
      empty.appendChild(bodyNode);
      stack.appendChild(empty);
    }
  }

  async function fetchTrainingCenterJsonRef(refPath) {
    const path = safe(refPath).trim();
    if (!path) {
      throw new Error('当前发布版本未绑定发布报告文件。');
    }
    const requestUrl = /^https?:\/\//i.test(path)
      ? path
      : '/api/runtime-file?path=' + encodeURIComponent(path);
    const resp = await fetch(requestUrl, { cache: 'no-store' });
    const text = await resp.text();
    if (!resp.ok) {
      throw new Error('读取发布报告失败：' + path);
    }
    let payload = {};
    try {
      payload = JSON.parse(text || '{}');
    } catch (_) {
      throw new Error('发布报告文件不是有效 JSON：' + path);
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error('发布报告文件格式不正确：' + path);
    }
    return payload;
  }

  function ensureTrainingCenterPublishedReleaseReportDialog() {
    let dialog = $('tcPublishedReleaseReportDialog');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'tcPublishedReleaseReportDialog';
      dialog.className = 'tc-report-dialog';

      const shell = document.createElement('div');
      shell.className = 'tc-report-dialog-shell';

      const head = document.createElement('div');
      head.className = 'tc-report-dialog-head';
      const titleWrap = document.createElement('div');
      titleWrap.className = 'tc-report-dialog-title-wrap';
      const titleNode = document.createElement('div');
      titleNode.className = 'tc-report-dialog-title';
      const metaNode = document.createElement('div');
      metaNode.className = 'tc-report-dialog-meta';
      titleWrap.appendChild(titleNode);
      titleWrap.appendChild(metaNode);
      const closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'alt';
      closeBtn.textContent = '关闭';
      closeBtn.onclick = () => dialog.close();
      head.appendChild(titleWrap);
      head.appendChild(closeBtn);

      const errorNode = document.createElement('div');
      errorNode.className = 'tc-report-dialog-error';

      const bodyNode = document.createElement('div');
      bodyNode.className = 'tc-report-dialog-body';

      shell.appendChild(head);
      shell.appendChild(errorNode);
      shell.appendChild(bodyNode);
      dialog.appendChild(shell);
      dialog.addEventListener('click', (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const inside =
          event.clientX >= rect.left &&
          event.clientX <= rect.right &&
          event.clientY >= rect.top &&
          event.clientY <= rect.bottom;
        if (!inside) dialog.close();
      });
      document.body.appendChild(dialog);
    }
    return {
      dialog: dialog,
      titleNode: dialog.querySelector('.tc-report-dialog-title'),
      metaNode: dialog.querySelector('.tc-report-dialog-meta'),
      errorNode: dialog.querySelector('.tc-report-dialog-error'),
      bodyNode: dialog.querySelector('.tc-report-dialog-body'),
    };
  }

  async function openTrainingCenterPublishedReleaseReport(agentId, releaseRow) {
    const release = releaseRow && typeof releaseRow === 'object' ? releaseRow : {};
    const detail = trainingCenterAgentDetailById(agentId);
    const reportRef = safe(release.release_source_ref).trim() || safe(release.capability_snapshot_ref).trim();
    const reportRefType = safe(release.release_source_ref).trim() ? '发布报告' : '能力快照';
    const refs = ensureTrainingCenterPublishedReleaseReportDialog();
    if (refs.titleNode) {
      refs.titleNode.textContent = safe(release.version_label).trim()
        ? safe(release.version_label).trim() + ' 发布报告'
        : '发布报告';
    }
    if (refs.metaNode) {
      const metaParts = [];
      if (safe(release.released_at).trim()) metaParts.push('发布时间：' + safe(release.released_at).trim());
      if (safe(reportRefType).trim() && safe(reportRef).trim()) metaParts.push(reportRefType + '：' + safe(reportRef).trim());
      refs.metaNode.textContent = metaParts.join(' · ');
    }
    if (refs.errorNode) refs.errorNode.textContent = '';
    if (refs.bodyNode) {
      refs.bodyNode.innerHTML = '';
      const loading = document.createElement('div');
      loading.className = 'tc-empty';
      loading.textContent = '正在读取发布报告...';
      refs.bodyNode.appendChild(loading);
    }
    if (refs.dialog && !refs.dialog.open && typeof refs.dialog.showModal === 'function') {
      refs.dialog.showModal();
    }
    if (refs.dialog) {
      refs.dialog.dataset.releaseVersion = safe(release.version_label).trim();
      refs.dialog.dataset.agentId = safe(detail.agent_id || release.agent_id).trim();
    }
    const report = await fetchTrainingCenterJsonRef(reportRef);
    const review = defaultTrainingCenterReleaseReview(detail);
    review.review_id = safe(release.release_id).trim();
    review.agent_id = safe(detail.agent_id || release.agent_id).trim();
    review.agent_name = safe(detail.agent_name || release.agent_id).trim();
    review.target_version = safe(release.version_label).trim();
    review.publish_version = safe(release.version_label).trim();
    review.current_workspace_ref = safe(report.current_workspace_ref).trim();
    review.publish_status = 'success';
    review.publish_succeeded = true;
    review.report = report;
    review.analysis_chain = {
      report_path: safe(release.release_source_ref).trim(),
    };
    review.public_profile_markdown_path = safe(release.public_profile_ref).trim();
    review.capability_snapshot_json_path = safe(release.capability_snapshot_ref).trim();
    if (refs.bodyNode) {
      refs.bodyNode.innerHTML = '';
      const host = document.createElement('div');
      refs.bodyNode.appendChild(host);
      renderTrainingCenterReleaseReport(host, review, null, null, null);
    }
  }
