  // Training center loop create-mode dialogue helpers.

  function trainingLoopCreateReadiness(snapshot, validationItems) {
    const items = Array.isArray(validationItems) ? validationItems : [];
    const missingItems = items.filter((item) => !(item && item.ok));
    const frozen = !!(snapshot && snapshot.frozen);
    const rootReady = !!state.agentSearchRootReady;
    const allReady = !missingItems.length && rootReady && !frozen;
    let statusText = '继续收敛';
    let statusClass = 'orange';
    let summaryText = '当前还在启动前收敛阶段，先把能力对象补齐后再进入首轮。';
    if (!rootReady) {
      statusText = '根路径未就绪';
      statusClass = 'red';
      summaryText = 'agent_search_root 未就绪，当前只能整理本轮能力对象，不能启动优化。';
    } else if (frozen) {
      statusText = '当前角色禁训';
      statusClass = 'red';
      summaryText = '当前角色处于禁训态，请先切回可训练版本后再继续优化。';
    } else if (allReady) {
      statusText = '可启动首轮';
      statusClass = 'green';
      summaryText = '当前输入已经满足 Gate-A，启动后会把真实效果、评分和 Gate-B / Gate-C 继续回收到当前聊天壳。';
    }
    return {
      allReady: allReady,
      rootReady: rootReady,
      frozen: frozen,
      missingItems: missingItems,
      statusText: statusText,
      statusClass: statusClass,
      summaryText: summaryText,
    };
  }

  function trainingLoopCreateStarterCapabilityName(snapshot) {
    const targetName = safe(snapshot && snapshot.targetName).trim();
    if (targetName) {
      return targetName + ' 训练优化能力';
    }
    return '当前训练优化能力对象';
  }

  function trainingLoopCreateDraftCapabilityNames(snapshot) {
    const tasks = Array.isArray(snapshot && snapshot.trainingTasks) ? snapshot.trainingTasks : [];
    const goal = safe(snapshot && snapshot.capabilityGoal).trim();
    const seen = {};
    const names = [];
    const source = tasks.length ? tasks : goal ? [goal] : [trainingLoopCreateStarterCapabilityName(snapshot)];
    source.forEach((item) => {
      const name = safe(item).trim();
      if (!name) return;
      const key = name.toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      names.push(name);
    });
    return names.slice(0, 8);
  }

  function trainingLoopCreateBaselineSummary(snapshot) {
    const detail =
      snapshot && snapshot.targetDetail && typeof snapshot.targetDetail === 'object'
        ? snapshot.targetDetail
        : {};
    const roleProfile =
      typeof trainingCenterRoleProfile === 'function' ? trainingCenterRoleProfile(detail) : {};
    const currentVersion =
      safe(detail.bound_release_version || detail.latest_release_version || detail.current_version).trim() ||
      '未绑定正式版本';
    const profileSummary =
      safe(
        roleProfile.first_person_summary ||
          detail.capability_summary ||
          detail.knowledge_scope ||
          detail.core_capabilities
      ).trim() || '当前还没有可展示的正式角色画像摘要。';
    const historyItems = (
      Array.isArray(roleProfile.full_capability_inventory) && roleProfile.full_capability_inventory.length
        ? roleProfile.full_capability_inventory
        : typeof trainingCenterWhatICanDoLines === 'function'
          ? trainingCenterWhatICanDoLines(detail)
          : []
    )
      .map((item) => safe(item).trim())
      .filter(Boolean)
      .slice(0, 6);
    return {
      currentVersion: currentVersion,
      profileSummary: profileSummary,
      historyItems: historyItems,
      sourceText:
        typeof trainingCenterRoleProfileSourceText === 'function'
          ? trainingCenterRoleProfileSourceText(roleProfile.profile_source || '')
          : '未绑定',
    };
  }

  function trainingLoopCreateDraftCapabilityObjects(snapshot, readiness, baseline) {
    const names = trainingLoopCreateDraftCapabilityNames(snapshot);
    const tasks = Array.isArray(snapshot && snapshot.trainingTasks) ? snapshot.trainingTasks : [];
    const goal = safe(snapshot && snapshot.capabilityGoal).trim();
    const seededFromEmpty = !tasks.length && !goal;
    const missingLabels = readiness.missingItems
      .map((item) => safe(item && item.label).trim())
      .filter(Boolean);
    const targetName = safe(snapshot && snapshot.targetName).trim() || '待选择角色';
    const acceptance = safe(snapshot && snapshot.acceptanceCriteria).trim();
    const historySummary = Array.isArray(baseline && baseline.historyItems) ? baseline.historyItems : [];
    const baselineVersion = safe(baseline && baseline.currentVersion).trim();
    const hasBaselineVersion = baselineVersion && baselineVersion !== '未绑定正式版本';
    return names.map((name, index) => ({
      capability_id: 'draft-capability-' + safe(index + 1),
      capability_name: name,
      capability_goal:
        goal ||
        (seededFromEmpty
          ? '先补齐能力目标、验收标准与本轮能力，当前工作台会持续更新这张能力卡。'
          : name),
      current_status: readiness.allReady ? '待启动' : '待收敛',
      seeded_from_empty: seededFromEmpty,
      preview_evidence: {
        title: readiness.allReady
          ? '启动后回收真实效果证据'
          : seededFromEmpty
            ? '当前先渲染能力对象卡'
            : '先收敛后生成效果证据',
        summary: acceptance
          ? '当前验收关注：' + acceptance + '。启动首轮后，这里会回收页面块、结构化输出或截图引用。'
          : seededFromEmpty
            ? '当前还是 fresh session，但主视图先固定渲染 1 条能力对象卡；后续输入会直接改写这张卡，而不是退回字段说明文案。'
            : '当前还没有真实效果证据。先补齐验收标准，启动后这里会回收页面块、结构化输出或截图引用。',
        evidence_ref: safe(snapshot && snapshot.targetName).trim() ? 'create-draft:' + targetName : 'create-draft:pending-target',
        updated_at: '草案阶段',
      },
      score_baseline: hasBaselineVersion ? '引用 ' + baselineVersion : '待建立',
      score_current: '待评测',
      score_target: acceptance ? '按验收标准' : '待补标准',
      score_delta: '待评测',
      score_conclusion: readiness.allReady
        ? '输入已满足首轮启动条件，真实评分会在首轮执行后回写。'
        : '先补齐 ' + (missingLabels.length ? missingLabels.join('、') : '能力对象字段') + '，再生成真实评分。',
      gate_status: {
        gate_b: {
          status: 'pending',
          reason: readiness.allReady
            ? '启动首轮后会对该能力逐项验收，并把结果直接绑定到这张能力卡。'
            : '仍缺 ' + (missingLabels.length ? missingLabels.join('、') : '关键输入') + '，暂不能生成 Gate-B 结果。',
        },
        gate_c: {
          status: 'pending',
          reason:
            safe(baseline && baseline.currentVersion).trim() && safe(baseline.currentVersion).trim() !== '未绑定正式版本'
              ? '当前正式版本已可作为基线，执行后会验证该能力是否拖累历史能力。'
              : '当前还没有可回归的正式基线，启动后需先建立回归对照。',
        },
      },
      historical_regression_result: {
        status: 'pending',
        summary: historySummary.length
          ? '待对 ' + historySummary.slice(0, 2).join('、') + ' 做历史能力回归验证。'
          : '选择角色并进入首轮后，这里会显示历史能力影响结论。',
      },
      impact_scope: targetName + ' · 当前训练优化会话',
    }));
  }

  function renderTrainingLoopCreateCapabilityEmptyState(snapshot, readiness, baseline) {
    const missingLabels = readiness.missingItems
      .map((item) => safe(item && item.label).trim())
      .filter(Boolean);
    const historyItems = Array.isArray(baseline && baseline.historyItems) ? baseline.historyItems : [];
    return (
      "<section class='tc-loop-capability-wrap tc-loop-capability-empty-wrap'>" +
      "<div class='tc-loop-capability-wrap-head'>" +
      '<div>' +
      "<div class='tc-loop-capability-wrap-title'>能力列表空态</div>" +
      "<div class='tc-loop-capability-wrap-desc'>即使当前 queue=0、还没有真实能力对象，也保持同一工作台结构，不回退旧创建器。</div>" +
      '</div>' +
      "<div class='tc-loop-chip-row'>" +
      "<span class='tc-loop-chip blue'>queue=0</span>" +
      "<span class='tc-loop-chip " +
      safe(readiness.statusClass) +
      "'>" +
      safe(readiness.statusText) +
      '</span>' +
      '</div>' +
      '</div>' +
      "<div class='tc-loop-capability-empty'>" +
      "<div class='tc-loop-capability-empty-title'>当前还没有本轮能力对象</div>" +
      "<div class='tc-loop-capability-empty-desc'>先在底部输入能力目标、验收标准或按行补充能力。系统会在当前聊天壳里直接生成能力卡，而不是切回“基础信息 / 首轮工作集 / 启动确认”的旧路径。</div>" +
      "<div class='tc-loop-capability-empty-grid'>" +
      "<section class='tc-loop-capability-empty-card'>" +
      "<div class='tc-loop-capability-empty-card-title'>生成后直接可见</div>" +
      "<div class='tc-loop-capability-empty-card-desc'>能力卡会固定包含以下信息：</div>" +
      "<ul class='tc-loop-bullet-list tc-loop-capability-empty-list'>" +
      '<li>能力名称</li>' +
      '<li>当前状态</li>' +
      '<li>能力展示效果</li>' +
      '<li>能力评分</li>' +
      '<li>Gate-B / Gate-C</li>' +
      '<li>历史能力影响</li>' +
      '</ul>' +
      '</section>' +
      "<section class='tc-loop-capability-empty-card'>" +
      "<div class='tc-loop-capability-empty-card-title'>当前建议先补齐</div>" +
      "<div class='tc-loop-capability-empty-card-desc'>" +
      (missingLabels.length
        ? '仍缺：' + missingLabels.join('、')
        : '已经满足 Gate-A，可直接启动首轮。') +
      '</div>' +
      "<div class='tc-loop-capability-empty-note'>当前角色：" +
      (safe(snapshot && snapshot.targetName).trim() || '待选择角色') +
      '</div>' +
      "<div class='tc-loop-capability-empty-note'>正式基线：" +
      safe(baseline && baseline.currentVersion).trim() +
      '</div>' +
      "<div class='tc-loop-capability-empty-note'>" +
      (historyItems.length
        ? '历史关键能力：' + historyItems.slice(0, 2).join('、')
        : '选择角色后，这里会显示历史关键能力和回归对照。') +
      '</div>' +
      '</section>' +
      '</div>' +
      '</div>' +
      '</section>'
    );
  }

  function renderTrainingLoopCreateDraftCapabilityCard(capability, index) {
    const item = capability && typeof capability === 'object' ? capability : {};
    const gateStatus = item.gate_status && typeof item.gate_status === 'object' ? item.gate_status : {};
    const gateB = gateStatus.gate_b && typeof gateStatus.gate_b === 'object' ? gateStatus.gate_b : {};
    const gateC = gateStatus.gate_c && typeof gateStatus.gate_c === 'object' ? gateStatus.gate_c : {};
    const historical = item.historical_regression_result && typeof item.historical_regression_result === 'object'
      ? item.historical_regression_result
      : {};
    const preview = item.preview_evidence && typeof item.preview_evidence === 'object' ? item.preview_evidence : {};
    const baselineScore = trainingLoopScoreText(item.score_baseline, '待建立');
    const currentScore = trainingLoopScoreText(item.score_current, '待评测');
    const targetScore = trainingLoopScoreText(item.score_target, '待补标准');
    const deltaScore = item.score_delta === null || item.score_delta === undefined || item.score_delta === ''
      ? '待评测'
      : (Number(item.score_delta) > 0 ? '+' : '') + safe(trainingLoopScoreText(item.score_delta, '0'));
    const previewMeta = [
      safe(preview.evidence_ref).trim() ? 'evidence=' + safe(preview.evidence_ref) : '',
      safe(preview.updated_at).trim() ? 'updated=' + safe(preview.updated_at) : '',
    ].filter(Boolean).join(' · ');

    return (
      "<article class='tc-loop-capability-card tc-loop-capability-draft-card'>" +
      "<div class='tc-loop-capability-head'>" +
      '<div>' +
      "<div class='tc-loop-capability-title'>能力 " +
      safe(index + 1) +
      ' · ' +
      safe(item.capability_name || '未命名能力') +
      '</div>' +
      "<div class='tc-loop-capability-goal'>" +
      safe(item.capability_goal || item.impact_scope || '当前能力暂无额外目标说明') +
      '</div>' +
      '</div>' +
      "<span class='tc-loop-chip " +
      trainingLoopCapabilityChipClass(item.current_status) +
      "'>" +
      safe(item.current_status || '待评测') +
      '</span>' +
      '</div>' +
      "<div class='tc-loop-capability-draft-grid'>" +
      "<section class='tc-loop-capability-draft-panel'>" +
      "<div class='tc-loop-capability-draft-title'>展示效果</div>" +
      "<div class='tc-loop-capability-draft-text'>" +
      safe(short(preview.summary || '当前没有结构化效果证据', 96)) +
      '</div>' +
      "<div class='tc-loop-capability-draft-meta'>" +
      safe(previewMeta || '草案阶段，启动后补真实证据') +
      '</div>' +
      '</section>' +
      "<section class='tc-loop-capability-draft-panel'>" +
      "<div class='tc-loop-capability-draft-title'>评分草案</div>" +
      "<div class='tc-loop-capability-draft-score-grid'>" +
      "<div><span>基线</span><strong>" +
      safe(baselineScore) +
      "</strong></div>" +
      "<div><span>当前</span><strong>" +
      safe(currentScore) +
      "</strong></div>" +
      "<div><span>目标</span><strong>" +
      safe(targetScore) +
      "</strong></div>" +
      "<div><span>分差</span><strong>" +
      safe(deltaScore) +
      "</strong></div>" +
      '</div>' +
      "<div class='tc-loop-capability-draft-text'>" +
      safe(short(item.score_conclusion || '当前暂无评分结论', 88)) +
      '</div>' +
      '</section>' +
      "<section class='tc-loop-capability-draft-panel'>" +
      "<div class='tc-loop-capability-draft-title'>Gate-B</div>" +
      "<div class='tc-loop-capability-draft-text'>" +
      safe(short(gateB.reason || '等待新能力验收结果', 88)) +
      '</div>' +
      "<div class='tc-loop-capability-draft-meta'>状态：<span class='tc-loop-chip " +
      trainingLoopGateChipClass(gateB.status) +
      "'>" +
      safe(gateB.status || 'pending') +
      '</span></div>' +
      '</section>' +
      "<section class='tc-loop-capability-draft-panel'>" +
      "<div class='tc-loop-capability-draft-title'>Gate-C / 历史影响</div>" +
      "<div class='tc-loop-capability-draft-text'>" +
      safe(short(gateC.reason || historical.summary || '等待历史能力回归结果', 88)) +
      '</div>' +
      "<div class='tc-loop-capability-draft-meta'>影响范围：" +
      safe(short(item.impact_scope || '未声明', 56)) +
      '</div>' +
      '</section>' +
      '</div>' +
      '</article>'
    );
  }

  function renderTrainingLoopCreateCapabilityList(snapshot, readiness, baseline) {
    const capabilities = trainingLoopCreateDraftCapabilityObjects(snapshot, readiness, baseline);
    if (!capabilities.length) {
      return renderTrainingLoopCreateCapabilityEmptyState(snapshot, readiness, baseline);
    }
    const seededOnly = capabilities.length === 1 && !!(capabilities[0] && capabilities[0].seeded_from_empty);
    return (
      "<section class='tc-loop-capability-wrap'>" +
      "<div class='tc-loop-capability-wrap-head'>" +
      '<div>' +
      "<div class='tc-loop-capability-wrap-title'>本轮能力列表</div>" +
      "<div class='tc-loop-capability-wrap-desc'>" +
      (seededOnly
        ? '即使当前还是 fresh session，也先固定渲染 1 条真实能力对象卡。后续输入会直接改写这张卡，不再回退到字段说明文案。'
        : '当前先按能力对象草案直接占据主视图。启动首轮后，效果证据、评分和 Gate-B / Gate-C 会继续回写到这些卡片。') +
      '</div>' +
      '</div>' +
      "<div class='tc-loop-chip-row'>" +
      "<span class='tc-loop-chip blue'>" +
      safe(capabilities.length) +
      ' 项能力</span>' +
      "<span class='tc-loop-chip " +
      safe(readiness.statusClass) +
      "'>" +
      safe(readiness.allReady ? '首轮待启动' : '继续补齐') +
      '</span>' +
      '</div>' +
      '</div>' +
      "<div class='tc-loop-capability-list'>" +
      capabilities.map((item, index) => renderTrainingLoopCreateDraftCapabilityCard(item, index)).join('') +
      '</div>' +
      (seededOnly
        ? "<div class='tc-loop-capability-create-note'>当前这张卡是系统保底能力对象。继续在底部补充目标、验收标准或本轮能力后，页面会直接更新这张卡。</div>"
        : '') +
      '</section>'
    );
  }

  function renderTrainingLoopCreateComposer(snapshot, readiness, missingLabels) {
    return (
      "<section class='tc-loop-create-composer'>" +
      "<div class='tc-loop-create-composer-head'>" +
      '<div>' +
      "<div class='tc-loop-create-composer-title'>继续在当前会话补充要求</div>" +
      "<div class='tc-loop-create-composer-desc'>底部保持类似创建角色的会话输入区。继续补充目标、验收和本轮能力时，中部能力卡会沿用同一套会话壳。</div>" +
      '</div>' +
      "<div class='tc-loop-chip-row'>" +
      "<span class='tc-loop-chip blue'>" +
      (safe(snapshot && snapshot.targetName).trim() || '待选择角色') +
      '</span>' +
      "<span class='tc-loop-chip " +
      safe(readiness.statusClass) +
      "'>" +
      safe(readiness.statusText) +
      '</span>' +
      '</div>' +
      '</div>' +
      "<div class='tc-loop-create-composer-shell'>" +
      "<div class='tc-loop-create-toolbar'>" +
      "<div class='tc-loop-create-toolbar-item tc-loop-create-toolbar-item-wide'><label class='hint' for='tcPlanTargetAgentSelect'>目标角色</label><div id='tcLoopFieldMountTarget'></div></div>" +
      "<div class='tc-loop-create-toolbar-item'><label class='hint' for='tcPlanPrioritySelect'>优先级</label><div id='tcLoopFieldMountPriority'></div></div>" +
      "<div class='tc-loop-create-toolbar-item'><label class='hint'>执行主体</label><div class='tc-loop-static-field'>" +
      safe(snapshot.executionLabel) +
      '</div></div>' +
      '</div>' +
      "<div class='tc-loop-create-input-panel'>" +
      "<div class='tc-loop-create-input-head'>" +
      "<div class='tc-loop-create-input-title'>会话输入</div>" +
      "<div class='tc-loop-create-input-desc'>参考创建角色会话窗口，保留明确的底部输入框。先写本轮目标，再补验收标准和能力清单。</div>" +
      '</div>' +
      "<div class='tc-loop-create-primary-field'>" +
      "<label class='hint' for='tcPlanGoalInput'>本轮目标</label>" +
      "<div class='tc-loop-create-primary-box'><div id='tcLoopFieldMountGoal'></div></div>" +
      '</div>' +
      "<div class='tc-loop-create-secondary-grid'>" +
      "<section class='tc-loop-create-secondary-card'>" +
      "<div class='tc-loop-create-secondary-title'>验收标准</div>" +
      "<div class='tc-loop-create-secondary-desc'>写清通过标准、证据形式或界面块表现。</div>" +
      "<div class='tc-loop-create-field-shell'><div id='tcLoopFieldMountAcceptance'></div></div>" +
      '</section>' +
      "<section class='tc-loop-create-secondary-card'>" +
      "<div class='tc-loop-create-secondary-title'>本轮能力</div>" +
      "<div class='tc-loop-create-secondary-desc'>每行一项，系统会直接把这些条目收敛为能力对象卡。</div>" +
      "<div class='tc-loop-create-field-shell'><div id='tcLoopFieldMountTasks'></div></div>" +
      '</section>' +
      '</div>' +
      "<div class='tc-loop-create-composer-meta'>" +
      (missingLabels.length
        ? '当前仍缺：' + missingLabels.join('、') + '。Gate-A 未通过前，不会创建优化任务。'
        : '当前已满足 Gate-A，可保存草稿或直接启动首轮。') +
      '</div>' +
      "<div class='tc-loop-action-row tc-loop-launch-actions tc-loop-create-actions'>" +
      "<button id='tcSaveAndStartBtn' type='button' " +
      (readiness.allReady ? '' : 'disabled') +
      '>保存并启动首轮</button>' +
      "<button id='tcSaveDraftBtn' class='alt' type='button' " +
      (readiness.allReady ? '' : 'disabled') +
      '>保存草稿</button>' +
      '</div>' +
      '</div>' +
      '</section>'
    );
  }

  function renderTrainingLoopCreateDialogueBody() {
    const box = $('tcLoopDetailBody');
    if (!box) return;
    const snapshot = trainingLoopPlanSnapshot();
    const validationItems = trainingLoopValidationItems(snapshot);
    const readiness = trainingLoopCreateReadiness(snapshot, validationItems);
    const baseline = trainingLoopCreateBaselineSummary(snapshot);
    const capabilityNames = trainingLoopCreateDraftCapabilityNames(snapshot);
    const missingLabels = readiness.missingItems
      .map((item) => safe(item && item.label).trim())
      .filter(Boolean);
    const userText = [
      '目标角色：' + (safe(snapshot.targetName).trim() || '待选择'),
      '本轮目标：' + (safe(snapshot.capabilityGoal).trim() || '待补充'),
      safe(snapshot.acceptanceCriteria).trim() ? '验收：' + short(safe(snapshot.acceptanceCriteria).trim(), 42) : '',
    ].join('\n');
    const assistantText = readiness.allReady
      ? 'Gate-A 已通过。启动后会把真实效果、评分和 Gate-B / Gate-C 继续回收到当前能力卡。'
      : '仍缺：' +
        (missingLabels.length ? missingLabels.join('、') : '能力对象输入') +
        '。继续在底部补齐，页面只会更新当前能力卡。';
    const systemText = capabilityNames.length
      ? '当前能力卡已占住主视图，后续输入不会再切回旧表单。'
      : 'queue=0 时也保留同一工作台结构。';

    box.innerHTML =
      "<div class='tc-loop-chat-shell tc-loop-create-shell'>" +
      "<div class='tc-loop-chat-shell-head tc-loop-create-shell-head'>" +
      "<div class='tc-loop-chat-shell-head-top'>" +
      "<div class='tc-loop-chat-head-main'>" +
      "<div class='tc-loop-detail-title'>训练优化会话</div>" +
      "<div class='tc-loop-detail-desc'>中部直接复用创建角色的单壳体结构：头部固定、消息区滚动、底部输入区贴底。</div>" +
      "<div class='tc-loop-chat-hero-title'>" +
      safe(snapshot.capabilityGoal || '先定义本轮训练优化目标') +
      '</div>' +
      "<div class='tc-loop-chat-hero-sub'>" +
      safe(readiness.summaryText) +
      '</div>' +
      '</div>' +
      "<div class='tc-loop-chip-row'>" +
      "<span class='tc-loop-chip blue'>" +
      (safe(snapshot.targetName).trim() || '待选择角色') +
      '</span>' +
      "<span class='tc-loop-chip " +
      safe(readiness.statusClass) +
      "'>" +
      safe(readiness.statusText) +
      '</span>' +
      '</div>' +
      '</div>' +
      "<div class='tc-loop-chat-metrics'>" +
      "<div class='tc-loop-chat-metric'><span>目标角色</span><strong>" +
      (safe(snapshot.targetName).trim() || '待选择') +
      "</strong></div>" +
      "<div class='tc-loop-chat-metric'><span>能力对象</span><strong>" +
      safe(capabilityNames.length || 0) +
      " 项</strong></div>" +
      "<div class='tc-loop-chat-metric'><span>当前基线</span><strong>" +
      safe(baseline.currentVersion) +
      "</strong></div>" +
      "<div class='tc-loop-chat-metric'><span>下一步</span><strong>" +
      (readiness.allReady ? '启动首轮' : '继续补齐') +
      "</strong></div>" +
      '</div>' +
      '</div>' +
      "<div class='tc-loop-chat-stream'>" +
      renderTrainingLoopChatBubble('user', '当前目标', userText, '本轮优化输入') +
      renderTrainingLoopChatBubble('assistant', '系统收敛', assistantText, readiness.allReady ? '能力对象已成形' : '继续收敛') +
      renderTrainingLoopCreateCapabilityList(snapshot, readiness, baseline) +
      renderTrainingLoopChatBubble('system', '结构说明', systemText, '能力对象驱动工作台') +
      '</div>' +
      renderTrainingLoopCreateComposer(snapshot, readiness, missingLabels) +
      '</div>';

    mountTrainingLoopField('tcPlanTargetAgentSelect', 'tcLoopFieldMountTarget');
    mountTrainingLoopField('tcPlanPrioritySelect', 'tcLoopFieldMountPriority');
    mountTrainingLoopField('tcPlanGoalInput', 'tcLoopFieldMountGoal', {
      rows: 4,
      placeholder: '例如：把训练优化页收口成“角色中心 -> 训练优化”的能力对象工作台',
    });
    mountTrainingLoopField('tcPlanAcceptanceInput', 'tcLoopFieldMountAcceptance', {
      rows: 3,
      placeholder: '例如：中部默认看到能力列表；每项都展示效果、评分、Gate-B / Gate-C 和历史影响',
    });
    mountTrainingLoopField('tcPlanTasksInput', 'tcLoopFieldMountTasks', {
      rows: 4,
      placeholder: '- 本轮能力 1\n- 本轮能力 2\n- 本轮能力 3',
    });

    const startBtn = $('tcSaveAndStartBtn');
    if (startBtn) {
      startBtn.onclick = async () => {
        try {
          await withButtonLock('tcSaveAndStartBtn', async () => {
            await submitTrainingCenterPlanFromLoop('start');
          });
        } catch (err) {
          setTrainingCenterError(err.message || String(err));
        }
      };
    }
    const draftBtn = $('tcSaveDraftBtn');
    if (draftBtn) {
      draftBtn.onclick = async () => {
        try {
          await withButtonLock('tcSaveDraftBtn', async () => {
            await submitTrainingCenterPlanFromLoop('draft');
          });
        } catch (err) {
          setTrainingCenterError(err.message || String(err));
        }
      };
    }
    updateTrainingCenterOpsGateState();
  }

  function renderTrainingLoopCreateRightPane() {
    const box = $('tcLoopRightPane');
    if (!box) return;
    const snapshot = trainingLoopPlanSnapshot();
    const validationItems = trainingLoopValidationItems(snapshot);
    const readiness = trainingLoopCreateReadiness(snapshot, validationItems);
    const baseline = trainingLoopCreateBaselineSummary(snapshot);
    const activeRightTab = normalizeTrainingLoopRightTab(state.tcLoopRightTab);
    const missingLabels = readiness.missingItems
      .map((item) => safe(item && item.label).trim())
      .filter(Boolean);
    const capabilityNames = trainingLoopCreateDraftCapabilityNames(snapshot);
    const baselineRegression = safe(snapshot.targetName).trim()
      ? [
          '当前角色已有正式版本时，首轮执行后会在这里回写 Gate-C 回归结果。',
          '若触发历史能力退化，右侧会直接显示阻塞项和回补路径。',
        ]
      : ['先选择目标角色，系统才能建立当前能力基线。'];
    const taskHints = capabilityNames.length
      ? capabilityNames.map((item) => '待推进：' + safe(item))
      : ['当前还没有能力对象，先在中部补齐目标与能力列表。'];

    box.innerHTML =
      "<div class='tc-loop-right-tabs' role='tablist' aria-label='训练优化右侧视图'>" +
      "<button class='tc-loop-tab" +
      (activeRightTab === 'tasks' ? ' active' : '') +
      "' type='button' data-right-tab='tasks' aria-selected='" +
      (activeRightTab === 'tasks' ? 'true' : 'false') +
      "'>任务 / 能力演进</button>" +
      "<button class='tc-loop-tab" +
      (activeRightTab === 'baseline' ? ' active' : '') +
      "' type='button' data-right-tab='baseline' aria-selected='" +
      (activeRightTab === 'baseline' ? 'true' : 'false') +
      "'>当前能力基线</button>" +
      '</div>' +
      "<div class='tc-loop-right-pane-shell" +
      (activeRightTab === 'tasks' ? ' active' : '') +
      "' data-right-pane='tasks'>" +
      "<div class='tc-loop-right-pane-scroll'>" +
      renderTrainingLoopSection(
        '当前推进',
        '默认先看任务推进与能力演进，不再用上下堆叠卡近似代替标签。',
        renderTrainingLoopSummaryRows([
          ['当前阶段', readiness.allReady ? '等待启动首轮' : '目标收敛'],
          ['当前阻塞', missingLabels.length ? missingLabels.join('、') : '无'],
          ['能力对象', safe(capabilityNames.length || 0) + ' 项'],
          ['自动发布', '待 Gate-A / Gate-B / Gate-C'],
        ])
      ) +
      renderTrainingLoopSection(
        '本轮任务',
        '即使当前 queue=0，也保留真实的任务 / 能力演进容器。',
        renderTrainingLoopBulletList(taskHints),
        'tone-soft'
      ) +
      renderTrainingLoopSection(
        '能力演进',
        '红色分支表示历史能力退化后需要回补；通过后才会回到发布主线。',
        "<div class='tc-loop-evolution-canvas'>" + renderTrainingLoopPreviewSvg() + '</div>',
        'tone-soft'
      ) +
      '</div>' +
      '</div>' +
      "<div class='tc-loop-right-pane-shell" +
      (activeRightTab === 'baseline' ? ' active' : '') +
      "' data-right-pane='baseline'>" +
      "<div class='tc-loop-right-pane-scroll'>" +
      renderTrainingLoopSection(
        '当前能力基线',
        '',
        renderTrainingLoopSummaryRows([
          ['当前正式版本', safe(baseline.currentVersion)],
          ['当前角色画像', safe(baseline.profileSummary)],
          ['来源', safe(baseline.sourceText)],
        ])
      ) +
      renderTrainingLoopSection(
        '历史关键能力清单',
        '',
        renderTrainingLoopBulletList(
          Array.isArray(baseline.historyItems) && baseline.historyItems.length
            ? baseline.historyItems
            : ['当前还没有可回看的正式能力清单。']
        ),
        'tone-soft'
      ) +
      renderTrainingLoopSection(
        '本轮回归验证结果',
        '',
        renderTrainingLoopBulletList(baselineRegression),
        'tone-soft'
      ) +
      '</div>' +
      '</div>';
    box.onclick = (event) => {
      const target = event && event.target ? event.target : null;
      if (!(target instanceof Element)) return;
      const tabBtn = target.closest('button[data-right-tab]');
      if (tabBtn) {
        setTrainingLoopRightTab(tabBtn.getAttribute('data-right-tab'));
      }
    };
  }
