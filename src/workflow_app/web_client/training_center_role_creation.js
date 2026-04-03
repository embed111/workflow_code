  // Training center role creation view/rendering helpers.
  function roleCreationSessionSubtitle(session) {
    const summary = session && typeof session === 'object' ? session : {};
    const processing = roleCreationSessionProcessingInfo(summary);
    if (processing.active) {
      return processing.unhandledCount > 0
        ? (processing.text + ' · 待处理 ' + String(processing.unhandledCount) + ' 条')
        : processing.text;
    }
    if (processing.failed && processing.unhandledCount > 0) {
      return '有 ' + String(processing.unhandledCount) + ' 条消息处理失败，请点击“重试本轮分析”';
    }
    const preview = safe(summary.last_message_preview).trim();
    if (preview) return preview;
    const missing = Array.isArray(summary.missing_fields) ? summary.missing_fields.length : 0;
    if (safe(summary.status).trim().toLowerCase() === 'draft' && missing > 0) {
      return '还缺 ' + String(missing) + ' 项关键信息';
    }
    return '等待继续补充';
  }

  function renderRoleCreationSessionList() {
    const box = $('rcSessionList');
    if (!box) return;
    const allRows = Array.isArray(state.tcRoleCreationSessions) ? state.tcRoleCreationSessions : [];
    const rows = roleCreationFilteredSessions();
    if (!allRows.length) {
      box.innerHTML = "<div class='rc-empty'>当前还没有创建草稿。</div>";
      return;
    }
    if (!rows.length) {
      box.innerHTML = "<div class='rc-empty'>没有匹配的草稿，试试调整搜索词或状态筛选。</div>";
      return;
    }
    box.innerHTML = rows.map((session) => {
      const sessionId = safe(session && session.session_id).trim();
      const current = sessionId && sessionId === safe(state.tcRoleCreationSelectedSessionId).trim();
      const missing = Array.isArray(session && session.missing_fields) ? session.missing_fields.length : 0;
      const status = safe(session && session.status).trim().toLowerCase();
      const processing = roleCreationSessionProcessingInfo(session);
      const canDelete = !!(session && session.delete_available) && !processing.active;
      const deleteLabel = safe(session && session.delete_label).trim()
        || (status === 'completed' ? '删除记录' : status === 'creating' ? '清理删除' : '删除草稿');
      return (
        "<div class='rc-session-card" + (current ? ' active' : '') + "'>" +
          "<button class='rc-session-card-main' type='button' data-session-id='" + roleCreationEscapeHtml(sessionId) + "'>" +
            "<div class='rc-session-card-top'>" +
              "<div class='rc-session-card-title'>" + roleCreationEscapeHtml(safe(session && session.session_title).trim() || '未命名角色草稿') + '</div>' +
              "<div class='rc-session-card-statuses'>" +
                "<span class='rc-chip " + roleCreationStatusTone(session && session.status) + "'>" + roleCreationEscapeHtml(roleCreationSessionStatusText(session && session.status)) + '</span>' +
                (
                  processing.active || processing.failed
                    ? "<span class='rc-chip " + roleCreationStatusTone(processing.status) + "'>" + roleCreationEscapeHtml(processing.text) + '</span>'
                    : ''
                ) +
              '</div>' +
            '</div>' +
            "<div class='rc-session-card-sub'>" + roleCreationEscapeHtml(roleCreationSessionSubtitle(session)) + '</div>' +
            "<div class='rc-session-card-meta'>" +
              "<span>" + roleCreationEscapeHtml(formatDateTime(session && session.updated_at)) + '</span>' +
              (
                missing > 0 && status === 'draft'
                  ? "<span>缺失 " + roleCreationEscapeHtml(String(missing)) + ' 项</span>'
                  : ''
              ) +
            '</div>' +
          '</button>' +
          (
            canDelete
              ? "<div class='rc-session-card-actions'><button class='bad rc-session-card-delete' type='button' data-rc-delete-session='" + roleCreationEscapeHtml(sessionId) + "'>" + roleCreationEscapeHtml(deleteLabel) + '</button></div>'
              : ''
          ) +
        '</div>'
      );
    }).join('');
  }

  function renderRoleCreationDraftAttachments() {
    const box = $('rcDraftFiles');
    if (!box) return;
    const rows = Array.isArray(state.tcRoleCreationDraftAttachments) ? state.tcRoleCreationDraftAttachments : [];
    if (!rows.length) {
      box.innerHTML = '';
      return;
    }
    box.innerHTML = rows.map((item) => roleCreationAttachmentThumbHtml(item, true)).join('');
  }

  function renderRoleCreationMeta() {
    const session = roleCreationCurrentSession();
    const detail = roleCreationCurrentDetail();
    const profile = roleCreationCurrentProfile();
    const startGate = roleCreationCurrentStartGate();
    const analysisProgress = roleCreationCurrentAnalysisProgress();
    const createdAgent = roleCreationCurrentCreatedAgent();
    const dialogueAgent = roleCreationCurrentDialogueAgent();
    const processing = roleCreationCurrentProcessingInfo();
    const failureHost = $('rcFailureCardHost');
    const mainGraphTicketId = roleCreationMainGraphTicketId(session, detail);
    const draftMeta = $('rcDraftMeta');
    const sessionTitle = $('rcSessionTitle');
    const sessionMeta = $('rcSessionMeta');
    const composerMeta = $('rcComposerMeta');
    const composerBox = $('rcComposerBox');
    const startBtn = $('rcStartSessionBtn');
    const completeBtn = $('rcCompleteSessionBtn');
    const input = $('rcInput');
    const sendBtn = $('rcSendBtn');
    const pickImageBtn = $('rcPickImageBtn');
    const collapsedCount = $('rcDraftCollapsedCount');
    const collapsedCurrent = $('rcDraftCollapsedCurrent');
    const totalSessionCount = Array.isArray(state.tcRoleCreationSessions) ? state.tcRoleCreationSessions.length : 0;
    const filteredSessionCount = roleCreationFilteredSessions().length;
    const statusFilter = normalizeRoleCreationStatusFilter(state.tcRoleCreationStatusFilter);
    const searchQuery = safe(state.tcRoleCreationQuery).trim();
    const sessionId = safe(session.session_id).trim();
    const status = safe(session.status).trim().toLowerCase();
    const missingLabels = Array.isArray(profile.missing_labels) ? profile.missing_labels : [];
    const startBlockers = Array.isArray(startGate.blockers) ? startGate.blockers.filter((item) => !!safe(item).trim()) : [];
    const seedPlan = profile.seed_delivery_plan && typeof profile.seed_delivery_plan === 'object' ? profile.seed_delivery_plan : {};
    const capabilityObjectCount = Array.isArray(seedPlan.capability_objects) ? seedPlan.capability_objects.length : 0;
    const taskSuggestionCount = Array.isArray(seedPlan.task_suggestions) ? seedPlan.task_suggestions.length : 0;
    if (draftMeta) {
      draftMeta.textContent = state.agentSearchRootReady
        ? (
          totalSessionCount <= 0
            ? '新建后通过对话逐步收口角色画像、能力包、知识沉淀与首批任务'
            : (
              searchQuery || statusFilter !== 'all'
                ? ('共 ' + String(totalSessionCount) + ' 条，当前显示 ' + String(filteredSessionCount) + ' 条 · ' + (statusFilter === 'all' ? '全部状态' : roleCreationSessionStatusText(statusFilter)))
                : ('共 ' + String(totalSessionCount) + ' 条草稿，可按名称、结构草稿内容、任务图快速搜索')
            )
        )
        : '根路径未就绪，创建角色功能已锁定';
    }
    if (collapsedCount) {
      collapsedCount.textContent = String(searchQuery || statusFilter !== 'all' ? filteredSessionCount : totalSessionCount);
    }
    if (collapsedCurrent) {
      collapsedCurrent.hidden = !safe(state.tcRoleCreationSelectedSessionId).trim();
    }
    if (sessionTitle) {
      sessionTitle.textContent = safe(session.session_title).trim() || '创建角色';
    }
    if (sessionMeta) {
      if (!sessionId) {
        sessionMeta.textContent = '先创建草稿，再通过对话收口角色画像、能力包、知识沉淀与首批任务。';
      } else if (status === 'draft') {
        const draftSegments = [
          safe(dialogueAgent.agent_name).trim() ? '对话分析师：' + safe(dialogueAgent.agent_name).trim() : '',
          processing.active || processing.failed
            ? ('当前状态：' + (safe(analysisProgress.status_text).trim() || processing.text) + (processing.unhandledCount > 0 ? '（' + String(processing.unhandledCount) + ' 条待处理）' : ''))
            : '',
          startGate.can_start
            ? ('开工门槛：已满足 · 首批对象 ' + String(capabilityObjectCount) + ' 项 · 任务建议 ' + String(taskSuggestionCount) + ' 条')
            : (
              startBlockers.length
                ? '待补：' + startBlockers.join(' / ')
                : (missingLabels.length ? '画像待补：' + missingLabels.join('、') : '继续补齐能力包与知识沉淀')
            ),
        ].filter((item) => !!item);
        sessionMeta.textContent = draftSegments.join(' · ');
      } else if (status === 'creating') {
        const segments = [
          safe(dialogueAgent.agent_name).trim() ? '对话分析师：' + safe(dialogueAgent.agent_name).trim() : '',
          processing.active || processing.failed
            ? ('当前状态：' + (safe(analysisProgress.status_text).trim() || processing.text) + (processing.unhandledCount > 0 ? '（' + String(processing.unhandledCount) + ' 条待处理）' : ''))
            : '',
          safe(session.current_stage_title).trim() ? '当前阶段：' + safe(session.current_stage_title).trim() : '',
          capabilityObjectCount > 0 ? ('首批对象：' + String(capabilityObjectCount) + ' 项') : '',
          taskSuggestionCount > 0 ? ('任务建议：' + String(taskSuggestionCount) + ' 条') : '',
          mainGraphTicketId ? '主图：' + mainGraphTicketId : '',
          safe(createdAgent.agent_name).trim() ? '执行主体：' + safe(createdAgent.agent_name).trim() : '',
        ].filter((item) => !!item);
        sessionMeta.textContent = segments.join(' · ');
      } else {
        sessionMeta.textContent = safe(createdAgent.agent_name).trim()
          ? '已完成，角色工作区：' + safe(createdAgent.agent_name).trim()
          : '当前角色创建已完成';
      }
    }
    if (composerMeta) {
      const count = Array.isArray(state.tcRoleCreationDraftAttachments) ? state.tcRoleCreationDraftAttachments.length : 0;
      if (!sessionId) {
        composerMeta.textContent = '先点“新建”，草稿创建成功后输入区会自动激活。';
      } else if (!state.agentSearchRootReady) {
        composerMeta.textContent = 'agent_search_root 未就绪，输入区已锁定。';
      } else if (status === 'completed') {
        composerMeta.textContent = '当前草稿已完成，输入区已锁定。';
      } else if (processing.active) {
        composerMeta.textContent = processing.unhandledCount > 0
          ? ((safe(analysisProgress.status_text).trim() || processing.text) + ' · 当前累计待处理 ' + String(processing.unhandledCount) + ' 条，可继续追加消息')
          : ((safe(analysisProgress.status_text).trim() || processing.text) + ' · 可继续追加消息');
      } else if (processing.failed && processing.unhandledCount > 0) {
        composerMeta.textContent = (safe(analysisProgress.status_text).trim() || '上一轮分析失败') + '，请点击“重试本轮分析”，当前草稿不会丢失。';
      } else {
        composerMeta.textContent = count > 0
          ? ('当前消息已挂载 ' + String(count) + ' 张图片，草稿已激活，可继续补充结构化要求')
          : '草稿已激活，可直接补充角色画像、能力包、知识沉淀或首批任务';
      }
    }
    if (failureHost) {
      renderCodexFailureCard(failureHost, detail.codex_failure || session.codex_failure, {
        title: '分析失败原因',
        compact: true,
        context: {
          sessionId: safe(session.session_id).trim(),
        },
      });
    }
    const canStart = !!profile.can_start
      && status === 'draft'
      && state.agentSearchRootReady
      && !processing.active
      && processing.unhandledCount <= 0;
    const canComplete = roleCreationCanComplete(roleCreationCurrentDetail())
      && state.agentSearchRootReady
      && !processing.active
      && processing.unhandledCount <= 0;
    if (startBtn) {
      startBtn.disabled = !canStart;
      startBtn.title = canStart
        ? '当前草稿已满足开始创建门槛'
        : (startBlockers.join(' / ') || '当前草稿仍未满足开始创建门槛');
    }
    if (completeBtn) completeBtn.disabled = !canComplete;
    const inputLocked = !sessionId || status === 'completed' || !state.agentSearchRootReady;
    if (input) {
      input.disabled = inputLocked;
      input.placeholder = !sessionId
        ? '先点“新建”，再描述你想创建的角色。'
        : status === 'completed'
          ? '当前草稿已完成，不能继续追加消息。'
          : '直接补充角色画像、能力包、知识沉淀、格式边界或首批任务优先级。';
    }
    if (sendBtn) sendBtn.disabled = inputLocked;
    if (pickImageBtn) pickImageBtn.disabled = inputLocked;
    if (composerBox) {
      composerBox.classList.toggle('is-disabled', inputLocked);
      composerBox.classList.toggle('is-ready', !inputLocked && !processing.active && !processing.failed);
      composerBox.classList.toggle('is-processing', !inputLocked && processing.active);
      composerBox.classList.toggle('is-failed', !inputLocked && processing.failed);
    }
  }

  function roleCreationListHtml(value, emptyText) {
    const rows = Array.isArray(value)
      ? value
        .map((item) => {
          if (item && typeof item === 'object') {
            return safe(item.file_name || item.name || item.attachment_id).trim();
          }
          return safe(item).trim();
        })
        .filter((item) => !!item)
      : [];
    if (!rows.length) {
      return "<div class='rc-profile-empty'>" + roleCreationEscapeHtml(emptyText) + '</div>';
    }
    return "<ul class='rc-profile-list'>" + rows.map((item) => '<li>' + roleCreationEscapeHtml(item) + '</li>').join('') + '</ul>';
  }

  function roleCreationProfileChipHtml(tone, text) {
    return "<span class='rc-chip " + roleCreationEscapeHtml(tone) + "'>" + roleCreationEscapeHtml(text) + '</span>';
  }

  function roleCreationConfirmationTone(status) {
    const key = safe(status).trim().toLowerCase();
    if (key === 'ready' || key === 'confirmed') return 'done';
    if (key === 'missing') return 'danger';
    return 'pending';
  }

  function roleCreationConfirmationText(status) {
    const key = safe(status).trim().toLowerCase();
    if (key === 'ready' || key === 'confirmed') return '已收口';
    if (key === 'missing') return '待补齐';
    return '待确认';
  }

  function roleCreationProfileStageLine(session, detail) {
    const currentTitle = safe(session.current_stage_title || (detail.stage_meta && detail.stage_meta.current_stage_title)).trim();
    const currentIndex = Number(session.current_stage_index || (detail.stage_meta && detail.stage_meta.current_stage_index) || 1) || 1;
    if (!currentTitle) {
      return '初始化工作区 · 1 / 6';
    }
    return currentTitle + ' · ' + String(Math.max(1, currentIndex)) + ' / 6';
  }

  function roleCreationProfileDraftStatus(session, profile, processing) {
    const status = safe(session.status).trim().toLowerCase();
    const missingLabels = Array.isArray(profile.missing_labels) ? profile.missing_labels.filter((item) => !!safe(item).trim()) : [];
    if (status === 'completed') {
      return { chipTone: 'done', chipText: '已完成', text: '已完成创建，画像收口结果已落到角色工作区。' };
    }
    if (status === 'creating') {
      return { chipTone: 'active', chipText: '创建中', text: '已开始创建，当前按真实任务和阶段推进。' };
    }
    if (processing && processing.failed) {
      return { chipTone: 'danger', chipText: '待重试', text: '最近一轮分析失败，仍需继续对齐草稿字段。' };
    }
    if ((processing && processing.active) || missingLabels.length) {
      return { chipTone: 'pending', chipText: '待对齐', text: '待对齐，尚未收口。' };
    }
    return { chipTone: 'done', chipText: '已收口', text: '当前草稿字段已收口，可进入开始前确认。' };
  }

  function roleCreationProfileStartStatus(session, profile) {
    const status = safe(session.status).trim().toLowerCase();
    const missingLabels = Array.isArray(profile.missing_labels) ? profile.missing_labels.filter((item) => !!safe(item).trim()) : [];
    if (status === 'completed') {
      return { chipTone: 'done', chipText: '已完成创建', text: '角色已经完成创建，可继续进入训练和发布治理。' };
    }
    if (status === 'creating') {
      return { chipTone: 'active', chipText: '已开始创建', text: '已点击开始创建，真实任务已映射到任务中心主图，工作区也已建立。' };
    }
    if (profile.can_start) {
      return { chipTone: 'active', chipText: '可开始未开始', text: '最小字段已满足，但尚未真正开始创建。' };
    }
    return {
      chipTone: 'pending',
      chipText: '未达开始门槛',
      text: missingLabels.length
        ? ('仍需补齐：' + missingLabels.join(' / '))
        : '仍需补齐角色名、角色目标和至少一条核心能力后才能开始。',
    };
  }

  function roleCreationProfileTaskStatus(session, detail) {
    const ticketId = roleCreationMainGraphTicketId(session, detail);
    if (!ticketId) {
      return { chipTone: 'pending', chipText: '当前未映射主图', text: '--', ticketId: '' };
    }
    return { chipTone: 'active', chipText: '已映射主图', text: ticketId, ticketId: ticketId };
  }

  function roleCreationProfileAttachmentSummary(profile) {
    const assets = Array.isArray(profile.example_assets) ? profile.example_assets : [];
    const count = assets.filter((item) => {
      if (item && typeof item === 'object') {
        return !!safe(item.file_name || item.name || item.attachment_id).trim();
      }
      return !!safe(item).trim();
    }).length;
    if (count <= 0) {
      return '当前暂无附件引用。';
    }
    return String(count) + ' 项附件/引用，仅用于字段对齐，不直接写进角色正文。';
  }

  function roleCreationTextBlockHtml(text, emptyText) {
    const content = safe(text).trim();
    if (!content) {
      return "<div class='rc-profile-empty'>" + roleCreationEscapeHtml(emptyText) + '</div>';
    }
    return "<div class='rc-field-note'>" + roleCreationEscapeHtml(content) + '</div>';
  }

  function roleCreationInlineTagsHtml(items, emptyText) {
    const rows = Array.isArray(items)
      ? items.map((item) => safe(item).trim()).filter((item) => !!item)
      : [];
    if (!rows.length) {
      return "<div class='rc-profile-empty'>" + roleCreationEscapeHtml(emptyText) + '</div>';
    }
    return "<div class='rc-inline-tags'>" + rows.map((item) => "<span class='rc-inline-tag'>" + roleCreationEscapeHtml(item) + '</span>').join('') + '</div>';
  }

  function roleCreationSummaryGridHtml(rows) {
    const items = Array.isArray(rows) ? rows.filter((item) => item && typeof item === 'object') : [];
    return "<div class='rc-profile-summary'>" + items.map((item) => (
      "<div class='rc-profile-kv'>" +
        "<div class='rc-profile-k'>" + roleCreationEscapeHtml(safe(item.label).trim()) + '</div>' +
        "<div class='rc-profile-v" + (item.mono ? ' mono' : '') + "'>" + safe(item.valueHtml) + '</div>' +
      '</div>'
    )).join('') + '</div>';
  }

  function roleCreationEntityCardsHtml(items, renderItem, emptyText) {
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) {
      return "<div class='rc-profile-empty'>" + roleCreationEscapeHtml(emptyText) + '</div>';
    }
    return "<div class='rc-entity-grid'>" + rows.map((item, index) => renderItem(item, index)).join('') + '</div>';
  }

  function roleCreationLayerSourceHtml(layer) {
    const node = layer && typeof layer === 'object' ? layer : {};
    const lines = [];
    if (safe(node.source_preview).trim()) {
      lines.push('最近来源：' + safe(node.source_preview).trim());
    }
    if (safe(node.last_updated_at).trim()) {
      lines.push('更新时间：' + formatDateTime(node.last_updated_at));
    }
    if (!lines.length) {
      return '';
    }
    return "<div class='rc-layer-source'>" + lines.map((text) => "<div>" + roleCreationEscapeHtml(text) + '</div>').join('') + '</div>';
  }

  function roleCreationLayerListHtml(items, emptyText, attrName) {
    const rows = Array.isArray(items)
      ? items.map((item) => safe(item).trim()).filter((item) => !!item)
      : [];
    if (!rows.length) {
      return "<div class='rc-profile-empty'>" + roleCreationEscapeHtml(emptyText) + '</div>';
    }
    return "<ul class='rc-layer-list'>" + rows.map((item) => (
      '<li' + (attrName ? " data-" + roleCreationEscapeHtml(attrName) + "='1'" : '') + '>' + roleCreationEscapeHtml(item) + '</li>'
    )).join('') + '</ul>';
  }

  function roleCreationStructuredSectionHtml(title, layer, bodyHtml) {
    const node = layer && typeof layer === 'object' ? layer : {};
    const pendingCount = Array.isArray(node.pending_items) ? node.pending_items.length : 0;
    return (
      "<section class='rc-profile-card rc-structured-section' data-rc-profile-kind='structured' data-rc-profile-title='" + roleCreationEscapeHtml(title) + "' data-rc-structured-section='" + roleCreationEscapeHtml(title) + "'>" +
        "<div class='rc-field-head'>" +
          "<div class='rc-field-title-row'>" +
            "<div class='rc-profile-section-title'>" + roleCreationEscapeHtml(title) + '</div>' +
            roleCreationProfileChipHtml(roleCreationConfirmationTone(node.confirmation_status), roleCreationConfirmationText(node.confirmation_status)) +
          '</div>' +
          (
            pendingCount
              ? ("<div class='rc-field-actions'><span class='rc-field-action'>待确认 " + roleCreationEscapeHtml(String(pendingCount)) + ' 项</span></div>')
              : ''
          ) +
        '</div>' +
        bodyHtml +
        roleCreationLayerSourceHtml(node) +
      '</section>'
    );
  }

  function roleCreationProgressCardHtml(progress) {
    const node = progress && typeof progress === 'object' ? progress : {};
    const steps = Array.isArray(node.steps) ? node.steps : [];
    return (
      "<section class='rc-profile-card rc-progress-card' data-rc-profile-kind='progress' data-rc-profile-title='分析进度'>" +
        "<div class='rc-field-head'>" +
          "<div class='rc-field-title-row'>" +
            "<div class='rc-profile-section-title'>分析进度</div>" +
            roleCreationProfileChipHtml(
              node.failed ? 'danger' : node.active ? 'active' : 'done',
              safe(node.status_text).trim() || '结构化草稿已完成'
            ) +
          '</div>' +
        '</div>' +
        "<div class='rc-progress-steps'>" +
          steps.map((step) => (
            "<div class='rc-progress-step " + roleCreationEscapeHtml(safe(step.state).trim() || 'pending') + "' data-rc-progress-step='" + roleCreationEscapeHtml(safe(step.step_key).trim()) + "'>" +
              "<div class='rc-progress-step-head'>" +
                "<span class='rc-progress-step-label'>" + roleCreationEscapeHtml(safe(step.label).trim()) + '</span>' +
                roleCreationProfileChipHtml(roleCreationStatusTone(step.state), safe(step.state).trim() === 'completed' ? '完成' : safe(step.state).trim() === 'failed' ? '失败' : safe(step.state).trim() === 'current' ? '当前' : '待执行') +
              '</div>' +
              "<div class='rc-field-note'>" + roleCreationEscapeHtml(safe(step.description).trim()) + '</div>' +
            '</div>'
          )).join('') +
        '</div>' +
      '</section>'
    );
  }

  function renderRoleCreationProfile() {
    const box = $('rcProfileView');
    if (!box) return;
    const detail = roleCreationCurrentDetail();
    const session = detail.session && typeof detail.session === 'object' ? detail.session : {};
    const profile = roleCreationCurrentProfile();
    const structured = roleCreationCurrentStructuredSpecs();
    const startGate = roleCreationCurrentStartGate();
    const analysisProgress = roleCreationCurrentAnalysisProgress();
    const processing = roleCreationCurrentProcessingInfo();
    if (!safe(session.session_id).trim()) {
      box.innerHTML = "<div class='rc-empty'>先创建或选择一个草稿，结构化草稿会在这里持续收口。</div>";
      return;
    }
    const roleProfileSpec = structured.role_profile_spec && typeof structured.role_profile_spec === 'object' ? structured.role_profile_spec : {};
    const capabilitySpec = structured.capability_package_spec && typeof structured.capability_package_spec === 'object' ? structured.capability_package_spec : {};
    const knowledgePlan = structured.knowledge_asset_plan && typeof structured.knowledge_asset_plan === 'object' ? structured.knowledge_asset_plan : {};
    const seedPlan = structured.seed_delivery_plan && typeof structured.seed_delivery_plan === 'object' ? structured.seed_delivery_plan : {};
    const sections = [];
    const draftStatus = roleCreationProfileDraftStatus(session, profile, processing);
    const startStatus = roleCreationProfileStartStatus(session, profile);
    const taskStatus = roleCreationProfileTaskStatus(session, detail);
    const recentChanges = Array.isArray(profile.recent_changes) ? profile.recent_changes : [];
    const pendingQuestions = Array.isArray(profile.pending_questions) ? profile.pending_questions : [];
    const startBlockers = Array.isArray(profile.start_gate_blockers) ? profile.start_gate_blockers : [];
    const capabilityModules = Array.isArray(capabilitySpec.capability_modules) ? capabilitySpec.capability_modules : [];
    const decisionRules = Array.isArray(capabilitySpec.decision_rules) ? capabilitySpec.decision_rules : [];
    const priorityScenarios = Array.isArray(capabilitySpec.priority_scenarios) ? capabilitySpec.priority_scenarios : [];
    const knowledgeAssets = Array.isArray(knowledgePlan.assets) ? knowledgePlan.assets : [];
    const capabilityObjects = Array.isArray(seedPlan.capability_objects) ? seedPlan.capability_objects : [];
    const taskSuggestions = Array.isArray(seedPlan.task_suggestions) ? seedPlan.task_suggestions : [];
    const priorityOrder = Array.isArray(seedPlan.priority_order) ? seedPlan.priority_order : [];
    sections.push(
      "<section class='rc-profile-card rc-profile-card-summary' data-rc-profile-kind='summary' data-rc-profile-title='summary'>" +
        "<div class='rc-profile-head'>" +
          "<div class='rc-profile-head-main'>" +
            "<div class='rc-profile-head-title'>" + roleCreationEscapeHtml((safe(profile.role_name).trim() || safe(session.session_title).trim() || '未命名角色') + ' 结构化草稿') + '</div>' +
          '</div>' +
          "<div class='rc-chip-row'>" +
            roleCreationProfileChipHtml(draftStatus.chipTone, draftStatus.chipText) +
            roleCreationProfileChipHtml(startStatus.chipTone, startStatus.chipText) +
            roleCreationProfileChipHtml(taskStatus.chipTone, taskStatus.chipText) +
          '</div>' +
        '</div>' +
        roleCreationSummaryGridHtml([
          { label: '当前阶段', valueHtml: roleCreationEscapeHtml(roleCreationProfileStageLine(session, detail)) },
          { label: '分析状态', valueHtml: roleCreationEscapeHtml(safe(analysisProgress.status_text).trim() || '结构化草稿已完成') },
          {
            label: '开工门槛',
            valueHtml: roleCreationEscapeHtml(startGate.can_start ? '四层草稿已形成，可直接开始创建' : (startBlockers.join(' / ') || '仍需继续收口')),
          },
          {
            label: '结构层状态',
            valueHtml:
              roleCreationProfileChipHtml(profile.profile_ready ? 'done' : 'pending', '画像') +
              roleCreationProfileChipHtml(profile.capability_package_ready ? 'done' : 'pending', '能力包') +
              roleCreationProfileChipHtml(profile.knowledge_asset_ready ? 'done' : 'pending', '知识沉淀') +
              roleCreationProfileChipHtml(profile.seed_delivery_ready ? 'done' : 'pending', '首批任务'),
          },
          {
            label: '首批对象',
            valueHtml: roleCreationEscapeHtml(String(capabilityObjects.length) + ' 项能力对象 · ' + String(taskSuggestions.length) + ' 条任务建议'),
          },
          {
            label: '任务中心',
            valueHtml: safe(taskStatus.ticketId).trim()
              ? ("<button class='alt' type='button' data-rc-open-summary-task-center='" + roleCreationEscapeHtml(taskStatus.ticketId) + "'>打开主图定位任务</button>")
              : roleCreationEscapeHtml('--'),
          },
        ]) +
      '</section>'
    );
    sections.push(roleCreationProgressCardHtml(analysisProgress));
    sections.push(
      "<section class='rc-profile-card' data-rc-profile-kind='delta' data-rc-profile-title='结构化变化'>" +
        "<div class='rc-field-head'><div class='rc-field-title-row'><div class='rc-profile-section-title'>最近结构化变化</div>" +
        roleCreationProfileChipHtml(recentChanges.length ? 'active' : 'pending', recentChanges.length ? ('+' + String(recentChanges.length)) : '无新增') +
        "</div></div>" +
        (
          recentChanges.length
            ? "<div class='rc-change-list'>" + recentChanges.map((item) => (
              "<div class='rc-change-item' data-rc-recent-change='1'><div class='rc-change-title'>" +
                roleCreationEscapeHtml((safe(item.layer_label).trim() || '结构层') + ' · ' + (safe(item.item_label).trim() || '变更')) +
              "</div><div class='rc-field-note'>" + roleCreationEscapeHtml(safe(item.summary).trim() || '') + '</div></div>'
            )).join('') + '</div>'
            : "<div class='rc-profile-empty'>当前还没有新的结构化变化。</div>"
        ) +
      '</section>'
    );
    sections.push(
      "<section class='rc-profile-card' data-rc-profile-kind='questions' data-rc-profile-title='待确认问题'>" +
        "<div class='rc-field-head'><div class='rc-field-title-row'><div class='rc-profile-section-title'>待确认问题</div>" +
        roleCreationProfileChipHtml((pendingQuestions.length || startBlockers.length) ? 'pending' : 'done', (pendingQuestions.length || startBlockers.length) ? '待确认' : '已收口') +
        "</div></div>" +
        roleCreationLayerListHtml(pendingQuestions.length ? pendingQuestions : startBlockers, '当前没有待确认问题。', 'rc-pending-question') +
      '</section>'
    );
    sections.push(
      roleCreationStructuredSectionHtml(
        '角色画像',
        roleProfileSpec,
        roleCreationSummaryGridHtml([
          { label: '角色名', valueHtml: roleCreationEscapeHtml(safe(profile.role_name).trim() || safe(session.session_title).trim() || '未命名角色') },
          { label: '角色目标', valueHtml: roleCreationEscapeHtml(safe(profile.role_goal).trim() || '待补充') },
          { label: '协作方式', valueHtml: roleCreationEscapeHtml(safe(profile.collaboration_style).trim() || '待补充') },
          { label: '附件状态', valueHtml: roleCreationEscapeHtml(roleCreationProfileAttachmentSummary(profile)) },
        ]) +
        "<div class='rc-structured-block'><div class='rc-structured-label'>核心能力</div>" + roleCreationInlineTagsHtml(profile.core_capabilities, '当前还没有明确核心能力。') + '</div>' +
        "<div class='rc-structured-block'><div class='rc-structured-label'>边界</div>" + roleCreationListHtml(profile.boundaries, '当前还没有明确边界。') + '</div>' +
        "<div class='rc-structured-block'><div class='rc-structured-label'>适用场景</div>" + roleCreationInlineTagsHtml(profile.applicable_scenarios, '当前还没有明确适用场景。') + '</div>'
      )
    );
    sections.push(
      roleCreationStructuredSectionHtml(
        '能力包',
        capabilitySpec,
        "<div class='rc-structured-block'><div class='rc-structured-label'>能力模块</div>" +
        roleCreationEntityCardsHtml(capabilityModules, (item) => (
          "<article class='rc-entity-card'><div class='rc-entity-title'>" + roleCreationEscapeHtml(safe(item.module_name).trim() || '未命名模块') + '</div>' +
          "<div class='rc-field-note'>" + roleCreationEscapeHtml(safe(item.module_goal).trim() || '') + '</div>' +
          "<div class='rc-entity-meta'>输出：" + roleCreationEscapeHtml((Array.isArray(item.module_outputs) ? item.module_outputs : []).join(' / ') || '待补充') + '</div>' +
          "<div class='rc-entity-meta'>依赖：" + roleCreationEscapeHtml((Array.isArray(item.dependencies) ? item.dependencies : []).join(' / ') || '待补充') + '</div></article>'
        ), '当前还没有形成能力模块。') + '</div>' +
        "<div class='rc-structured-block'><div class='rc-structured-label'>默认交付策略</div>" + roleCreationTextBlockHtml(capabilitySpec.default_delivery_policy && capabilitySpec.default_delivery_policy.summary, '当前还没有明确默认交付策略。') + '</div>' +
        roleCreationSummaryGridHtml([
          { label: '优先格式', valueHtml: roleCreationEscapeHtml((capabilitySpec.format_strategy && Array.isArray(capabilitySpec.format_strategy.preferred_formats) ? capabilitySpec.format_strategy.preferred_formats : []).join(' / ') || '待补充') },
          { label: '允许格式', valueHtml: roleCreationEscapeHtml((capabilitySpec.format_strategy && Array.isArray(capabilitySpec.format_strategy.allowed_formats) ? capabilitySpec.format_strategy.allowed_formats : []).join(' / ') || '待补充') },
          { label: '避免格式', valueHtml: roleCreationEscapeHtml((capabilitySpec.format_strategy && Array.isArray(capabilitySpec.format_strategy.avoided_formats) ? capabilitySpec.format_strategy.avoided_formats : []).join(' / ') || '无') },
        ]) +
        "<div class='rc-structured-block'><div class='rc-structured-label'>优先场景</div>" +
        roleCreationEntityCardsHtml(priorityScenarios, (item) => (
          "<article class='rc-entity-card'><div class='rc-entity-title'>" + roleCreationEscapeHtml(safe(item.scenario_text).trim() || '未命名场景') + "</div><div class='rc-entity-meta'>优先级：" + roleCreationEscapeHtml(safe(item.priority).trim() || 'P1') + '</div></article>'
        ), '当前还没有明确首批优先场景。') + '</div>' +
        "<div class='rc-structured-block'><div class='rc-structured-label'>决策规则</div>" +
        roleCreationLayerListHtml(decisionRules.map((item) => safe(item && item.rule_text).trim()).filter((item) => !!item), '当前还没有明确决策规则。', '') + '</div>'
      )
    );
    sections.push(
      roleCreationStructuredSectionHtml(
        '知识沉淀',
        knowledgePlan,
        "<div class='rc-structured-block'><div class='rc-structured-label'>知识资产计划</div>" +
        roleCreationEntityCardsHtml(knowledgeAssets, (item) => (
          "<article class='rc-entity-card' data-rc-knowledge-asset='1'><div class='rc-entity-title'>" + roleCreationEscapeHtml(safe(item.asset_topic).trim() || '未命名资产') + '</div>' +
          "<div class='rc-entity-meta'>类型：" + roleCreationEscapeHtml(safe(item.asset_type).trim() || '待定') + '</div>' +
          "<div class='rc-entity-meta'>建议路径：" + roleCreationEscapeHtml(safe(item.recommended_path).trim() || '待定') + '</div>' +
          "<div class='rc-entity-meta'>优先级：" + roleCreationEscapeHtml(safe(item.priority).trim() || 'P1') + '</div></article>'
        ), '当前还没有形成知识沉淀计划。') + '</div>'
      )
    );
    sections.push(
      roleCreationStructuredSectionHtml(
        '首批任务',
        seedPlan,
        "<div class='rc-structured-block'><div class='rc-structured-label'>首批能力对象</div>" +
        roleCreationEntityCardsHtml(capabilityObjects, (item) => (
          "<article class='rc-entity-card' data-rc-seed-capability='1'><div class='rc-entity-title'>" + roleCreationEscapeHtml(safe(item.capability_name).trim() || '未命名能力对象') + '</div>' +
          "<div class='rc-field-note'>" + roleCreationEscapeHtml(safe(item.capability_goal).trim() || '') + '</div>' +
          "<div class='rc-entity-meta'>来源模块：" + roleCreationEscapeHtml(safe(item.source_module).trim() || '待定') + '</div>' +
          "<div class='rc-entity-meta'>验收提示：" + roleCreationEscapeHtml(safe(item.acceptance_hint).trim() || '待补充') + '</div></article>'
        ), '当前还没有形成首批能力对象。') + '</div>' +
        "<div class='rc-structured-block'><div class='rc-structured-label'>首批任务建议</div>" +
        roleCreationEntityCardsHtml(taskSuggestions, (item) => (
          "<article class='rc-entity-card' data-rc-seed-task='1'><div class='rc-entity-title'>" + roleCreationEscapeHtml(safe(item.task_name).trim() || '未命名任务建议') + '</div>' +
          "<div class='rc-entity-meta'>关联对象：" + roleCreationEscapeHtml(safe(item.linked_target).trim() || '待定') + '</div>' +
          "<div class='rc-entity-meta'>类型：" + roleCreationEscapeHtml(safe(item.task_type).trim() || '待定') + '</div>' +
          "<div class='rc-entity-meta'>阶段：" + roleCreationEscapeHtml(safe(item.stage_key).trim() || '待定') + '</div>' +
          "<div class='rc-entity-meta'>优先级：" + roleCreationEscapeHtml(safe(item.priority).trim() || 'P1') + '</div></article>'
        ), '当前还没有形成首批任务建议。') + '</div>' +
        "<div class='rc-structured-block'><div class='rc-structured-label'>优先顺序</div>" + roleCreationInlineTagsHtml(priorityOrder, '当前还没有明确优先顺序。') + '</div>'
      )
    );
    box.innerHTML = sections.join('');
  }

  function roleCreationTaskCardHtml(task, stageKey) {
    const item = task && typeof task === 'object' ? task : {};
    const tone = roleCreationStatusTone(item.status);
    return (
      "<button class='rc-task-card' type='button' data-kind='task' data-stage-key='" + roleCreationEscapeHtml(stageKey) + "' data-node-id='" + roleCreationEscapeHtml(safe(item.node_id).trim()) + "'>" +
        "<div class='rc-task-card-head'>" +
          "<div class='rc-task-card-title'>" + roleCreationEscapeHtml(safe(item.task_name).trim() || '未命名任务') + '</div>' +
          "<span class='rc-chip " + tone + "'>" + roleCreationEscapeHtml(safe(item.status_text).trim() || safe(item.status).trim() || '待开始') + '</span>' +
        '</div>' +
        "<div class='rc-task-card-ref'>task_id: " + roleCreationEscapeHtml(safe(item.node_id).trim() || '-') + '</div>' +
        (
          safe(item.expected_artifact).trim()
            ? "<div class='rc-task-card-sub'>产物: " + roleCreationEscapeHtml(safe(item.expected_artifact).trim()) + '</div>'
            : ''
        ) +
      '</button>'
    );
  }

  function roleCreationArchivePocketHtml(stage) {
    const item = stage && typeof stage === 'object' ? stage : {};
    const count = Number(item.archive_count || 0);
    if (!count) return '';
    return (
      "<button class='archive-pocket' type='button' data-kind='archive' data-stage-key='" + roleCreationEscapeHtml(safe(item.stage_key).trim()) + "'>" +
        "<div class='task-title'>废案收纳</div>" +
        "<div class='task-ref'>已收口 " + roleCreationEscapeHtml(String(count)) + ' 个任务</div>' +
      '</button>'
    );
  }

  function roleCreationStageCardHtml(stage) {
    const item = stage && typeof stage === 'object' ? stage : {};
    const session = roleCreationCurrentSession();
    const sessionStatus = safe(session.status).trim().toLowerCase();
    const action = item.analyst_action && typeof item.analyst_action === 'object' ? item.analyst_action : {};
    const activeTasks = Array.isArray(item.active_tasks) ? item.active_tasks : [];
    const canSwitch = sessionStatus === 'creating' &&
      safe(item.stage_key).trim() !== 'workspace_init' &&
      safe(item.stage_key).trim() !== 'complete_creation' &&
      safe(item.stage_key).trim() !== safe(session.current_stage_key).trim();
    return (
      "<section class='process-row " + roleCreationEscapeHtml(safe(item.state).trim().toLowerCase()) + "'>" +
        "<div class='rc-stage-gutter'>" +
          "<span class='rc-stage-dot'></span>" +
          "<span class='rc-stage-line'></span>" +
        '</div>' +
        "<div class='rc-stage-main'>" +
          "<div class='rc-stage-head'>" +
            "<div class='rc-stage-title-wrap'>" +
              "<div class='rc-stage-title'>" + roleCreationEscapeHtml(safe(item.title).trim() || '未命名阶段') + '</div>' +
              "<div class='rc-stage-sub'>阶段 " + roleCreationEscapeHtml(String(item.stage_index || '')) + '</div>' +
            '</div>' +
            "<span class='rc-chip " + roleCreationStatusTone(item.state) + "'>" + roleCreationEscapeHtml(roleCreationStageStateText(item.state)) + '</span>' +
          '</div>' +
          "<div class='rc-analyst-card'>" +
            "<div class='rc-analyst-title'>" + roleCreationEscapeHtml(safe(action.title).trim() || '阶段动作') + '</div>' +
            "<div class='rc-analyst-desc'>" + roleCreationEscapeHtml(safe(action.description).trim() || '') + '</div>' +
            (
              safe(item.stage_key).trim() === 'workspace_init'
                ? "<div class='rc-analyst-meta'>初始化结果：" + roleCreationEscapeHtml(safe(item.workspace_init && item.workspace_init.status_text).trim() || '待执行') + (
                  safe(item.workspace_init && item.workspace_init.evidence_ref).trim()
                    ? ' · ' + roleCreationEscapeHtml(safe(item.workspace_init && item.workspace_init.evidence_ref).trim())
                    : ''
                ) + '</div>'
                : ''
            ) +
            (
              safe(action.next_hint).trim()
                ? "<div class='rc-analyst-meta'>" + roleCreationEscapeHtml(safe(action.next_hint).trim()) + '</div>'
                : ''
            ) +
            (
              canSwitch
                ? "<div class='rc-analyst-actions'><button class='alt rc-stage-switch-btn' type='button' data-rc-stage-key='" + roleCreationEscapeHtml(safe(item.stage_key).trim()) + "'>切到此阶段</button></div>"
                : ''
            ) +
          '</div>' +
          (
            activeTasks.length || Number(item.archive_count || 0)
              ? "<div class='rc-task-lane'>" +
                activeTasks.map((task) => roleCreationTaskCardHtml(task, safe(item.stage_key).trim())).join('') +
                roleCreationArchivePocketHtml(item) +
                '</div>'
              : "<div class='rc-stage-empty'>当前阶段还没有挂接真实任务。</div>"
          ) +
        '</div>' +
      '</section>'
      );
    }

  function roleCreationTaskPreviewPayload() {
    const preview = state.tcRoleCreationTaskPreview && typeof state.tcRoleCreationTaskPreview === 'object'
      ? state.tcRoleCreationTaskPreview
      : {};
    const kind = safe(preview.kind).trim();
    if (!kind) return null;
    const detail = roleCreationCurrentDetail();
    const session = roleCreationCurrentSession();
    const taskCenterTicketId = roleCreationMainGraphTicketId(session, detail);
    const stageKey = safe(preview.stage_key).trim();
    const stages = Array.isArray(detail.stages) ? detail.stages : [];
    const stage = stages.find((item) => safe(item && item.stage_key).trim() === stageKey) || {};
    if (kind === 'archive') {
      return {
        kind: 'archive',
        ticket_id: taskCenterTicketId,
        stage_key: stageKey,
        stage_title: safe(stage.title).trim(),
        items: Array.isArray(stage.archived_tasks) ? stage.archived_tasks : [],
      };
    }
    const nodeId = safe(preview.node_id).trim();
    const items = Array.isArray(stage.active_tasks) ? stage.active_tasks : [];
    const task = items.find((item) => safe(item && item.node_id).trim() === nodeId) || {};
    return {
      kind: 'task',
      ticket_id: taskCenterTicketId,
      task: task,
    };
  }

  function roleCreationTaskFloatHtml() {
    const payload = roleCreationTaskPreviewPayload();
    if (!payload) return '';
    if (payload.kind === 'archive') {
      const items = Array.isArray(payload.items) ? payload.items : [];
      return (
        "<div class='rc-float-head'>" +
          "<div class='rc-float-title'>废案收纳 · " + roleCreationEscapeHtml(payload.stage_title || payload.stage_key) + '</div>' +
          "<span class='rc-chip archive'>已归档</span>" +
        '</div>' +
        (
          items.length
            ? "<div class='rc-float-list'>" +
              items.map((item) => (
                "<div class='rc-float-list-item'>" +
                  "<div class='rc-float-list-title'>" + roleCreationEscapeHtml(safe(item && item.task_name).trim() || safe(item && item.node_id).trim()) + '</div>' +
                  "<div class='rc-float-list-sub'>task_id: " + roleCreationEscapeHtml(safe(item && item.node_id).trim() || '-') + '</div>' +
                  (
                    safe(item && item.close_reason).trim()
                      ? "<div class='rc-float-list-sub'>关闭原因: " + roleCreationEscapeHtml(safe(item && item.close_reason).trim()) + '</div>'
                      : ''
                  ) +
                  (
                    safe(payload.ticket_id).trim()
                      ? (
                        "<div class='rc-float-actions'>" +
                          "<button class='alt' type='button' data-rc-open-task-center='1' data-node-id='" + roleCreationEscapeHtml(safe(item && item.node_id).trim()) + "'>去任务中心查看</button>" +
                        '</div>'
                      )
                      : ''
                  ) +
                '</div>'
              )).join('') +
              '</div>'
            : "<div class='rc-float-empty'>当前阶段还没有废案记录。</div>"
        )
      );
    }
    const task = payload.task && typeof payload.task === 'object' ? payload.task : {};
    const canArchive = safe(task.relation_state).trim().toLowerCase() !== 'archived' &&
      safe(task.status).trim().toLowerCase() !== 'running';
    return (
      "<div class='rc-float-head'>" +
        "<div class='rc-float-title'>" + roleCreationEscapeHtml(safe(task.task_name).trim() || '未命名任务') + '</div>' +
        "<span class='rc-chip " + roleCreationStatusTone(task.status) + "'>" + roleCreationEscapeHtml(safe(task.status_text).trim() || safe(task.status).trim() || '待开始') + '</span>' +
      '</div>' +
      "<div class='task-hover-float-meta'>task_id: " + roleCreationEscapeHtml(safe(task.node_id).trim() || '-') + '</div>' +
      (
        safe(task.expected_artifact).trim()
          ? "<div class='rc-float-line'>产物: " + roleCreationEscapeHtml(safe(task.expected_artifact).trim()) + '</div>'
          : ''
      ) +
      (
        safe(task.node_goal).trim()
          ? "<div class='rc-float-line'>目标: " + roleCreationEscapeHtml(safe(task.node_goal).trim()) + '</div>'
          : ''
      ) +
      (
        Array.isArray(task.upstream_labels) && task.upstream_labels.length
          ? "<div class='rc-float-line'>上游: " + roleCreationEscapeHtml(task.upstream_labels.join(' / ')) + '</div>'
          : ''
      ) +
      (
        Array.isArray(task.downstream_labels) && task.downstream_labels.length
          ? "<div class='rc-float-line'>下游: " + roleCreationEscapeHtml(task.downstream_labels.join(' / ')) + '</div>'
          : ''
      ) +
      (
        safe(task.close_reason).trim()
          ? "<div class='rc-float-line'>关闭原因: " + roleCreationEscapeHtml(safe(task.close_reason).trim()) + '</div>'
          : ''
      ) +
      "<div class='rc-float-actions'>" +
        (
          safe(payload.ticket_id).trim()
            ? "<button class='alt' type='button' data-rc-open-task-center='1' data-node-id='" + roleCreationEscapeHtml(safe(task.node_id).trim()) + "'>去任务中心查看</button>"
            : ''
        ) +
        (
          canArchive
            ? "<button class='alt' type='button' data-rc-archive-task='1' data-node-id='" + roleCreationEscapeHtml(safe(task.node_id).trim()) + "'>收口到废案</button>"
            : ''
        ) +
      '</div>'
    );
  }

  function clearRoleCreationTaskPreview() {
    state.tcRoleCreationTaskPreview = {
      kind: '',
      stage_key: '',
      node_id: '',
      pinned: false,
      anchor_rect: null,
    };
    renderRoleCreationTaskPreview();
  }

  function renderRoleCreationTaskPreview() {
    const node = $('rcTaskHoverFloat');
    if (!node) return;
    const preview = state.tcRoleCreationTaskPreview && typeof state.tcRoleCreationTaskPreview === 'object'
      ? state.tcRoleCreationTaskPreview
      : {};
    if (!safe(preview.kind).trim() || safe(state.tcModule).trim() !== 'create-role') {
      node.classList.remove('visible');
      node.setAttribute('aria-hidden', 'true');
      node.style.left = '-9999px';
      node.style.top = '-9999px';
      node.innerHTML = '';
      return;
    }
    node.innerHTML = roleCreationTaskFloatHtml();
    node.classList.add('visible');
    node.setAttribute('aria-hidden', 'false');
    const anchorRect = preview.anchor_rect;
    if (!anchorRect) return;
    window.requestAnimationFrame(() => {
      const rect = node.getBoundingClientRect();
      let left = Number(anchorRect.right || 0) + 12;
      if (left + rect.width > window.innerWidth - 12) {
        left = Math.max(12, Number(anchorRect.left || 0) - rect.width - 12);
      }
      let top = Number(anchorRect.top || 0);
      if (top + rect.height > window.innerHeight - 12) {
        top = Math.max(12, window.innerHeight - rect.height - 12);
      }
      node.style.left = String(Math.round(left)) + 'px';
      node.style.top = String(Math.round(top)) + 'px';
    });
  }

  function showRoleCreationTaskPreviewFromNode(targetNode, options) {
    const node = targetNode instanceof Element ? targetNode : null;
    if (!node) return;
    const rect = node.getBoundingClientRect();
    state.tcRoleCreationTaskPreview = {
      kind: safe(node.getAttribute('data-kind')).trim(),
      stage_key: safe(node.getAttribute('data-stage-key')).trim(),
      node_id: safe(node.getAttribute('data-node-id')).trim(),
      pinned: !!(options && options.pinned),
      anchor_rect: rect,
    };
    renderRoleCreationTaskPreview();
  }

  function bindRoleCreationTaskPreviewTargets() {
    const root = $('rcStageFlow');
    if (!root) return;
    root.querySelectorAll('.rc-task-card, .archive-pocket').forEach((node) => {
      node.onmouseenter = () => {
        if (state.tcRoleCreationTaskPreview && state.tcRoleCreationTaskPreview.pinned) {
          return;
        }
        showRoleCreationTaskPreviewFromNode(node, { pinned: false });
      };
      node.onmouseleave = () => {
        window.setTimeout(() => {
          const floatNode = $('rcTaskHoverFloat');
          if (state.tcRoleCreationTaskPreview && state.tcRoleCreationTaskPreview.pinned) {
            return;
          }
          if (floatNode && floatNode.matches(':hover')) {
            return;
          }
          clearRoleCreationTaskPreview();
        }, 120);
      };
      node.onclick = () => {
        const sameTask = state.tcRoleCreationTaskPreview &&
          safe(state.tcRoleCreationTaskPreview.kind).trim() === safe(node.getAttribute('data-kind')).trim() &&
          safe(state.tcRoleCreationTaskPreview.stage_key).trim() === safe(node.getAttribute('data-stage-key')).trim() &&
          safe(state.tcRoleCreationTaskPreview.node_id).trim() === safe(node.getAttribute('data-node-id')).trim();
        if (sameTask && state.tcRoleCreationTaskPreview.pinned) {
          clearRoleCreationTaskPreview();
          return;
        }
        showRoleCreationTaskPreviewFromNode(node, { pinned: true });
      };
    });
  }

  function renderRoleCreationEvolution() {
    const box = $('rcStageFlow');
    if (!box) return;
    const session = roleCreationCurrentSession();
    const stages = roleCreationCurrentStages();
    if (!safe(session.session_id).trim()) {
      box.innerHTML = "<div class='rc-empty'>选择草稿后，这里会展示统一的阶段与任务演进图。</div>";
      return;
    }
    box.innerHTML = stages.map((stage) => roleCreationStageCardHtml(stage)).join('');
    bindRoleCreationTaskPreviewTargets();
  }

  function renderRoleCreationWorkbench() {
    const workbench = $('rcWorkbench');
    if (!workbench) return;
    workbench.classList.toggle('draft-collapsed', !!state.tcRoleCreationDraftCollapsed);
    const collapseBtn = $('rcDraftCollapseBtn');
    const collapsedBody = $('rcDraftCollapsedBody');
    const searchInput = $('rcSessionSearchInput');
    if (collapseBtn) {
      collapseBtn.setAttribute('aria-expanded', state.tcRoleCreationDraftCollapsed ? 'false' : 'true');
      collapseBtn.innerHTML = state.tcRoleCreationDraftCollapsed ? '<span aria-hidden="true">›</span>' : '<span aria-hidden="true">‹</span>';
    }
    if (collapsedBody) {
      collapsedBody.hidden = !state.tcRoleCreationDraftCollapsed;
    }
    if (searchInput && searchInput.value !== safe(state.tcRoleCreationQuery)) {
      searchInput.value = safe(state.tcRoleCreationQuery);
    }
    Array.from(document.querySelectorAll('[data-rc-session-filter]')).forEach((node) => {
      if (!(node instanceof Element)) return;
      node.classList.toggle(
        'active',
        safe(node.getAttribute('data-rc-session-filter')).trim().toLowerCase()
          === normalizeRoleCreationStatusFilter(state.tcRoleCreationStatusFilter),
      );
    });
    renderRoleCreationSessionList();
    renderRoleCreationDraftAttachments();
    renderRoleCreationMessages();
    renderRoleCreationProfile();
    renderRoleCreationEvolution();
    renderRoleCreationMeta();
    setRoleCreationDetailTab(state.tcRoleCreationDetailTab);
    setRoleCreationError(state.tcRoleCreationError);
    renderRoleCreationTaskPreview();
  }

  function roleCreationOpenTaskCenter(ticketId, nodeId) {
    const ticket = safe(ticketId).trim();
    const taskId = safe(nodeId).trim();
    if (!ticket) return;
    state.assignmentSelectedTicketId = ticket;
    if (taskId) {
      state.assignmentSelectedNodeId = taskId;
    }
    setStatus(taskId ? '已切到任务中心主图并选中对应任务' : '已切到任务中心主图');
    switchTab('task-center');
    refreshAssignmentGraphData({ ticketId: ticket })
      .then(() => {
        if (taskId) {
          return refreshAssignmentDetail(taskId);
        }
        return null;
      })
      .catch((err) => {
        setAssignmentError(err.message || String(err));
      });
  }

  function removeRoleCreationDraftAttachment(attachmentId) {
    const targetId = safe(attachmentId).trim();
    if (!targetId) return;
    state.tcRoleCreationDraftAttachments = (Array.isArray(state.tcRoleCreationDraftAttachments) ? state.tcRoleCreationDraftAttachments : [])
      .filter((item) => safe(item && item.attachment_id).trim() !== targetId);
    renderRoleCreationDraftAttachments();
    renderRoleCreationMeta();
  }

  function roleCreationAttachmentId() {
    return 'rca-' + String(Date.now()) + '-' + String(Math.floor(Math.random() * 100000));
  }

  function readRoleCreationFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(safe(reader.result));
      reader.onerror = () => reject(new Error('图片读取失败'));
      reader.readAsDataURL(file);
    });
  }

  async function normalizeRoleCreationAttachmentFile(file) {
    const item = file || {};
    const contentType = safe(item.type).trim().toLowerCase();
    const fileName = safe(item.name).trim() || 'image';
    const sizeBytes = Number(item.size || 0);
    if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(contentType)) {
      throw new Error('当前仅支持 png/jpg/webp/gif 图片');
    }
    if (sizeBytes > 4 * 1024 * 1024) {
      throw new Error('单张图片不能超过 4MB');
    }
    const dataUrl = await readRoleCreationFileAsDataUrl(item);
    return {
      attachment_id: roleCreationAttachmentId(),
      kind: 'image',
      file_name: fileName,
      content_type: contentType,
      size_bytes: sizeBytes,
      data_url: safe(dataUrl).trim(),
    };
  }

  async function appendRoleCreationDraftFiles(fileList) {
    const files = Array.from(fileList || []).filter((item) => !!item);
    if (!files.length) return [];
    const existing = Array.isArray(state.tcRoleCreationDraftAttachments) ? state.tcRoleCreationDraftAttachments.slice() : [];
    const remaining = Math.max(0, 6 - existing.length);
    if (!remaining) {
      throw new Error('单条消息最多携带 6 张图片');
    }
    const accepted = files.slice(0, remaining);
    const next = [];
    for (const file of accepted) {
      next.push(await normalizeRoleCreationAttachmentFile(file));
    }
    state.tcRoleCreationDraftAttachments = existing.concat(next);
    renderRoleCreationDraftAttachments();
    renderRoleCreationMeta();
    return next;
  }

  function bindRoleCreationEvents() {
    if (bindRoleCreationEvents._bound) return;
    bindRoleCreationEvents._bound = true;
    let dragDepth = 0;
    const draftBox = $('rcDraftFiles');
    const profileView = $('rcProfileView');
    const sessionList = $('rcSessionList');
    const sessionSearchInput = $('rcSessionSearchInput');
    const sessionFilterRow = $('rcSessionFilterRow');
    const composerBox = $('rcComposerBox');
    const dropHint = $('rcDropHint');
    const stageFlow = $('rcStageFlow');
    const taskFloat = $('rcTaskHoverFloat');
    $('rcNewSessionBtn').onclick = async () => {
      try {
        await withButtonLock('rcNewSessionBtn', async () => {
          await createRoleCreationSession();
        });
      } catch (err) {
        setRoleCreationError(err.message || String(err));
      }
    };
    $('rcStartSessionBtn').onclick = async () => {
      try {
        await withButtonLock('rcStartSessionBtn', async () => {
          await startRoleCreationSelectedSession();
        });
      } catch (err) {
        setRoleCreationError(err.message || String(err));
      }
    };
    $('rcCompleteSessionBtn').onclick = async () => {
      try {
        await withButtonLock('rcCompleteSessionBtn', async () => {
          await completeRoleCreationSelectedSession();
        });
      } catch (err) {
        setRoleCreationError(err.message || String(err));
      }
    };
    $('rcSendBtn').onclick = async () => {
      try {
        await postRoleCreationMessage();
      } catch (err) {
        setRoleCreationError(err.message || String(err));
      }
    };
    $('rcPickImageBtn').onclick = () => {
      if ($('rcImageInput')) $('rcImageInput').click();
    };
    $('rcImageInput').addEventListener('change', async (event) => {
      try {
        await appendRoleCreationDraftFiles(event.target && event.target.files ? event.target.files : []);
        setRoleCreationError('');
      } catch (err) {
        setRoleCreationError(err.message || String(err));
      } finally {
        if ($('rcImageInput')) $('rcImageInput').value = '';
      }
    });
    $('rcInput').addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if ($('rcSendBtn') && !$('rcSendBtn').disabled) $('rcSendBtn').click();
      }
    });
    $('rcInput').addEventListener('paste', async (event) => {
      const clipboard = event.clipboardData;
      if (!clipboard || !clipboard.items || !clipboard.items.length) return;
      const files = [];
      Array.from(clipboard.items).forEach((item) => {
        if (item && item.kind === 'file') {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      });
      if (!files.length) return;
      event.preventDefault();
      try {
        await appendRoleCreationDraftFiles(files);
        setRoleCreationError('');
      } catch (err) {
        setRoleCreationError(err.message || String(err));
      }
    });
    ['dragenter', 'dragover'].forEach((type) => {
      composerBox.addEventListener(type, (event) => {
        event.preventDefault();
        dragDepth += 1;
        composerBox.classList.add('dragging');
        if (dropHint) dropHint.hidden = false;
      });
    });
    ['dragleave', 'drop'].forEach((type) => {
      composerBox.addEventListener(type, (event) => {
        event.preventDefault();
        dragDepth = Math.max(0, dragDepth - 1);
        if (!dragDepth || type === 'drop') {
          composerBox.classList.remove('dragging');
          if (dropHint) dropHint.hidden = true;
          dragDepth = 0;
        }
      });
    });
    composerBox.addEventListener('drop', async (event) => {
      const files = event.dataTransfer && event.dataTransfer.files ? event.dataTransfer.files : [];
      try {
        await appendRoleCreationDraftFiles(files);
        setRoleCreationError('');
      } catch (err) {
        setRoleCreationError(err.message || String(err));
      }
    });
    $('rcDraftCollapseBtn').onclick = () => {
      state.tcRoleCreationDraftCollapsed = !state.tcRoleCreationDraftCollapsed;
      renderRoleCreationWorkbench();
    };
    if (sessionSearchInput) {
      sessionSearchInput.addEventListener('input', () => {
        state.tcRoleCreationQuery = safe(sessionSearchInput.value);
        renderRoleCreationWorkbench();
      });
      sessionSearchInput.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && safe(sessionSearchInput.value).trim()) {
          event.preventDefault();
          sessionSearchInput.value = '';
          state.tcRoleCreationQuery = '';
          renderRoleCreationWorkbench();
        }
      });
    }
    if (sessionFilterRow) {
      sessionFilterRow.onclick = (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const filterBtn = target.closest('[data-rc-session-filter]');
        if (!filterBtn) return;
        event.preventDefault();
        state.tcRoleCreationStatusFilter = normalizeRoleCreationStatusFilter(
          filterBtn.getAttribute('data-rc-session-filter'),
        );
        renderRoleCreationWorkbench();
      };
    }
    $('rcDetailTabEvolution').onclick = () => {
      setRoleCreationDetailTab('evolution');
    };
    $('rcDetailTabProfile').onclick = () => {
      setRoleCreationDetailTab('profile');
    };
    if (draftBox) {
      draftBox.onclick = (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const removeBtn = target.closest('.rc-draft-file-remove');
        if (!removeBtn) return;
        event.preventDefault();
        removeRoleCreationDraftAttachment(removeBtn.getAttribute('data-attachment-id'));
      };
    }
    if (profileView) {
      profileView.onclick = (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const openBtn = target.closest('[data-rc-open-summary-task-center]');
        if (!openBtn) return;
        event.preventDefault();
        roleCreationOpenTaskCenter(openBtn.getAttribute('data-rc-open-summary-task-center'), '');
      };
    }
    if (sessionList) {
      sessionList.onclick = (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const deleteBtn = target.closest('[data-rc-delete-session]');
        if (deleteBtn) {
          event.preventDefault();
          event.stopPropagation();
          deleteRoleCreationSession(deleteBtn.getAttribute('data-rc-delete-session')).catch((err) => {
            setRoleCreationError(err.message || String(err));
          });
          return;
        }
        const sessionBtn = target.closest('.rc-session-card-main');
        if (!sessionBtn) return;
        event.preventDefault();
        const sessionId = safe(sessionBtn.getAttribute('data-session-id')).trim();
        if (!sessionId) return;
        selectRoleCreationSession(sessionId).catch((err) => {
          setRoleCreationError(err.message || String(err));
        });
      };
    }
    if (stageFlow) {
      stageFlow.onclick = (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const stageBtn = target.closest('.rc-stage-switch-btn');
        if (!stageBtn) return;
        event.preventDefault();
        const stageKey = safe(stageBtn.getAttribute('data-rc-stage-key')).trim();
        if (!stageKey) return;
        updateRoleCreationStage(stageKey).catch((err) => {
          setRoleCreationError(err.message || String(err));
        });
      };
      stageFlow.addEventListener('scroll', () => {
        if (!state.tcRoleCreationTaskPreview || !state.tcRoleCreationTaskPreview.pinned) {
          clearRoleCreationTaskPreview();
        }
      });
    }
    if (taskFloat) {
      taskFloat.onclick = (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const openBtn = target.closest('[data-rc-open-task-center]');
        if (openBtn) {
          event.preventDefault();
          event.stopPropagation();
          const payload = roleCreationTaskPreviewPayload();
          const ticketId = safe(payload && payload.ticket_id).trim();
          const nodeId = safe(openBtn.getAttribute('data-node-id')).trim();
          roleCreationOpenTaskCenter(ticketId, nodeId);
          return;
        }
        const archiveBtn = target.closest('[data-rc-archive-task]');
        if (archiveBtn) {
          event.preventDefault();
          event.stopPropagation();
          archiveRoleCreationTask(archiveBtn.getAttribute('data-node-id')).catch((err) => {
            setRoleCreationError(err.message || String(err));
          });
        }
      };
      taskFloat.addEventListener('mouseleave', () => {
        window.setTimeout(() => {
          if (state.tcRoleCreationTaskPreview && state.tcRoleCreationTaskPreview.pinned) {
            return;
          }
          if (taskFloat.matches(':hover')) {
            return;
          }
          clearRoleCreationTaskPreview();
        }, 120);
      });
    }
    document.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest('.rc-task-card, .archive-pocket, #rcTaskHoverFloat')) return;
      if (state.tcRoleCreationTaskPreview && state.tcRoleCreationTaskPreview.pinned) {
        clearRoleCreationTaskPreview();
      }
    });
    window.addEventListener('resize', () => {
      if (state.tcRoleCreationTaskPreview && safe(state.tcRoleCreationTaskPreview.kind).trim()) {
        renderRoleCreationTaskPreview();
      }
    });
  }
