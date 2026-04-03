  // Training center agent catalog, portrait, and release list helpers.

  function setTrainingCenterModule(moduleName) {
    const next = normalizeTrainingCenterModule(moduleName);
    state.tcModule = next;
    writeSavedTrainingCenterModule(next);
    const tabAgentsBtn = $('tcTabAgentsBtn');
    const tabCreateRoleBtn = $('tcTabCreateRoleBtn');
    const tabOpsBtn = $('tcTabOpsBtn');
    if (tabAgentsBtn) tabAgentsBtn.classList.toggle('active', next === 'agents');
    if (tabCreateRoleBtn) tabCreateRoleBtn.classList.toggle('active', next === 'create-role');
    if (tabOpsBtn) tabOpsBtn.classList.toggle('active', next === 'ops');
    const moduleAgents = $('tcModuleAgents');
    const moduleCreateRole = $('tcModuleCreateRole');
    const moduleOps = $('tcModuleOps');
    if (moduleAgents) moduleAgents.classList.toggle('active', next === 'agents');
    if (moduleCreateRole) moduleCreateRole.classList.toggle('active', next === 'create-role');
    if (moduleOps) moduleOps.classList.toggle('active', next === 'ops');
    if (next === 'ops') {
      renderTrainingLoop();
    }
    if (next === 'create-role') {
      if (typeof renderRoleCreationWorkbench === 'function') {
        renderRoleCreationWorkbench();
      }
      if (state.agentSearchRootReady && typeof refreshRoleCreationSessions === 'function') {
        refreshRoleCreationSessions({ preserveSelection: true }).catch((err) => {
          if (typeof setRoleCreationError === 'function') {
            setRoleCreationError(err.message || String(err));
          }
        });
      }
    }
  }

  function setTrainingCenterError(text) {
    const node = $('tcOpsErr');
    if (node) node.textContent = safe(text);
  }

  function setTrainingCenterDetailError(text) {
    const node = $('tcAgentDetailErr');
    if (node) node.textContent = safe(text);
  }

  function setTrainingCenterAgentActionResult(value) {
    const node = $('tcAgentActionResult');
    if (!node) return;
    if (typeof value === 'string') {
      node.textContent = value;
      return;
    }
    node.textContent = JSON.stringify(value || {}, null, 2);
  }

  function trainingLifecycleText(value) {
    const key = safe(value).toLowerCase();
    if (key === 'pre_release') return '预发布';
    if (key === 'unknown') return '不可判定';
    return '已发布';
  }

  function trainingGateText(value) {
    const key = safe(value).toLowerCase();
    if (key === 'frozen_switched') return '已切换（禁训）';
    return '可训练';
  }

  function trainingStatusTagText(value) {
    const key = safe(value).toLowerCase();
    if (key === 'published_ready') return '已发布';
    if (key === 'git_unavailable') return 'Git不可用（按预发布处理）';
    if (key === 'pre_release') return '预发布';
    if (key === 'pre_release_unknown') return '预发布不可判定';
    if (key === 'frozen_switched') return '已切换';
    if (key === 'cloned') return '克隆角色';
    if (key === 'normal_commit_present') return '含普通提交';
    return safe(value);
  }

  function visibleTrainingStatusTags(tags) {
    if (!Array.isArray(tags)) return [];
    return tags
      .map((tag) => safe(tag).trim())
      .filter((tag) => !!tag)
      .filter((tag) => {
        const key = tag.toLowerCase();
        return key !== 'git_unavailable' && key !== 'normal_commit_present';
      });
  }

  function trainingCenterVersionText(versionLabel) {
    const value = safe(versionLabel).trim();
    return value || '未发布';
  }

  function renderTrainingCenterVersionPill(versionLabel) {
    const value = safe(versionLabel).trim();
    return (
      "<div class='tc-card-version'>" +
      "<span class='tc-card-version-k'>当前版本</span>" +
      "<span class='tc-card-version-v" +
      (value ? '' : ' empty') +
      "'>" +
      trainingCenterVersionText(value) +
      '</span>' +
      '</div>'
    );
  }

  function trainingCenterAgentDetailById(agentId) {
    const key = safe(agentId).trim();
    if (!key) return {};
    if (safe(state.tcSelectedAgentId).trim() === key && state.tcSelectedAgentDetail) {
      return state.tcSelectedAgentDetail || {};
    }
    const rows = Array.isArray(state.tcAgents) ? state.tcAgents : [];
    return rows.find((item) => safe(item && item.agent_id).trim() === key) || {};
  }

  // Training center release review helpers live in the training_center_release_review_*.js modules.

  function syncTrainingCenterSwitchVersionOptions(agentId) {
    const select = $('tcSwitchVersionSelect');
    const trigger = $('tcSwitchVersionTrigger');
    const triggerText = $('tcSwitchVersionTriggerText');
    const triggerSub = $('tcSwitchVersionTriggerSub');
    const optionsNode = $('tcSwitchVersionOptions');
    if (!select || !trigger || !triggerText || !triggerSub || !optionsNode) return;
    const key = safe(agentId).trim();
    const hasSelectedAgent = !!key;
    const releases = Array.isArray(state.tcReleasesByAgent[key]) ? state.tcReleasesByAgent[key] : [];
    const detail = hasSelectedAgent ? state.tcSelectedAgentDetail || {} : {};
    const currentVersion = currentTrainingCenterDisplayedVersion(detail, releases);
    const currentRelease = releases.find((row) => safe(row && row.version_label).trim() === currentVersion) || releases[0] || null;
    select.innerHTML = '';
    optionsNode.innerHTML = '';
    if (!releases.length) {
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = '无可切换版本';
      select.appendChild(empty);
      select.value = '';
      triggerText.textContent = hasSelectedAgent ? '无可切换版本' : '请选择角色';
      triggerSub.textContent = hasSelectedAgent ? '当前角色暂无已发布版本' : '选择角色后查看已发布版本';
      const emptyNode = document.createElement('div');
      emptyNode.className = 'tc-version-option-empty';
      emptyNode.textContent = hasSelectedAgent ? '暂无符合发布格式的版本' : '请先从左侧选择角色';
      optionsNode.appendChild(emptyNode);
      trigger.disabled = true;
      setTrainingCenterVersionDropdownOpen(false);
      return;
    }
    for (const rel of releases) {
      const version = safe(rel && rel.version_label).trim();
      if (!version) continue;
      const opt = document.createElement('option');
      opt.value = version;
      const releasedAt = safe(rel && rel.released_at).trim();
      opt.textContent = version + (releasedAt ? ' · ' + releasedAt : '');
      select.appendChild(opt);

      const optionBtn = document.createElement('button');
      optionBtn.type = 'button';
      optionBtn.className = 'tc-version-option' + (version === currentVersion ? ' active' : '');
      optionBtn.dataset.version = version;
      optionBtn.setAttribute('role', 'option');
      optionBtn.setAttribute('aria-selected', version === currentVersion ? 'true' : 'false');
      const main = document.createElement('span');
      main.className = 'tc-version-option-main';
      const name = document.createElement('span');
      name.className = 'tc-version-option-name';
      name.textContent = version;
      const sub = document.createElement('span');
      sub.className = 'tc-version-option-sub';
      sub.textContent = releasedAt ? '发布时间：' + releasedAt : '选择后立即切换';
      main.appendChild(name);
      main.appendChild(sub);
      optionBtn.appendChild(main);
      optionsNode.appendChild(optionBtn);
    }
    if (currentVersion) {
      select.value = currentVersion;
    } else if (select.options.length) {
      select.selectedIndex = 0;
    }
    triggerText.textContent = trainingCenterVersionText(currentVersion || safe(select.value).trim());
    triggerSub.textContent =
      currentRelease && safe(currentRelease.released_at).trim()
        ? '发布时间：' + safe(currentRelease.released_at).trim()
        : '选择其他发布版本后立即切换';
    trigger.disabled = false;
  }

  function updateTrainingCenterOpsGateState() {
    const detail = state.tcSelectedAgentDetail || {};
    const frozen = safe(detail.training_gate_state).toLowerCase() === 'frozen_switched';
    ['tcSaveAndStartBtn', 'tcSaveDraftBtn'].forEach((id) => {
      const node = $(id);
      if (node) node.disabled = frozen || !state.agentSearchRootReady;
    });
    const hint = '当前角色已冻结训练，请切回最新发布版本后再训练';
    if (frozen) {
      setTrainingCenterError(hint);
    } else if (safe($('tcOpsErr') ? $('tcOpsErr').textContent : '').includes('冻结训练')) {
      setTrainingCenterError('');
    }
  }

  function updateTrainingCenterSelectedMeta() {
    const node = $('tcSelectedAgentMeta');
    if (!node) return;
    if (!state.tcSelectedAgentId) {
      node.textContent = '未选择角色';
      return;
    }
    const name = safe(state.tcSelectedAgentName).trim() || safe(state.tcSelectedAgentId).trim();
    node.textContent = '当前角色：' + name;
  }

  function renderTrainingCenterAgentStats() {
    const stats = state.tcStats || {};
    const node = $('tcAgentStats');
    if (!node) return;
    node.textContent =
      '角色总数=' +
      safe(stats.agent_total || 0) +
      ' · Git可用=' +
      safe(stats.git_available_count || 0) +
      ' · 最新发布时间=' +
      (safe(stats.latest_release_at) || '-') +
      ' · 队列待处理=' +
      safe(stats.training_queue_pending || 0);
  }

  function filteredTrainingCenterAgents() {
    const keyword = safe($('tcAgentSearchInput') ? $('tcAgentSearchInput').value : '').trim().toLowerCase();
    const rows = Array.isArray(state.tcAgents) ? state.tcAgents : [];
    if (!keyword) return rows;
    return rows.filter((row) => {
      const name = safe(row && row.agent_name).toLowerCase();
      const caps = safe(row && row.core_capabilities).toLowerCase();
      const capability = safe(row && row.capability_summary).toLowerCase();
      const knowledge = safe(row && row.knowledge_scope).toLowerCase();
      const scenarios = safe(row && row.applicable_scenarios).toLowerCase();
      const skills = trainingCenterPortraitSkills(row && row.agent_skills).join(' ').toLowerCase();
      return (
        name.includes(keyword) ||
        caps.includes(keyword) ||
        capability.includes(keyword) ||
        knowledge.includes(keyword) ||
        scenarios.includes(keyword) ||
        skills.includes(keyword)
      );
    });
  }

  function syncTrainingCenterPlanAgentOptions() {
    const select = $('tcPlanTargetAgentSelect');
    if (!select) return;
    const current = safe(select.value).trim();
    const rows = Array.isArray(state.tcAgents) ? state.tcAgents : [];
    select.innerHTML = '';
    const first = document.createElement('option');
    first.value = '';
    first.textContent = '请选择目标角色';
    select.appendChild(first);
    for (const row of rows) {
      const agentId = safe(row && row.agent_id).trim();
      if (!agentId) continue;
      const name = safe(row && row.agent_name).trim();
      const gate = safe(row && row.training_gate_state).trim().toLowerCase();
      const visibleVersion = safe((row && (row.bound_release_version || row.latest_release_version)) || '').trim();
      const opt = document.createElement('option');
      opt.value = agentId;
      const segments = [name || agentId];
      if (visibleVersion) {
        segments.push(visibleVersion);
      }
      if (gate === 'frozen_switched') {
        segments.push('禁训');
      }
      opt.textContent = segments.join(' · ');
      select.appendChild(opt);
    }
    const prefer = safe(state.tcSelectedAgentId).trim() || current;
    if (prefer) select.value = prefer;
  }

  function trainingCenterAvatarSeed(text) {
    const raw = safe(text);
    let hash = 0;
    for (let i = 0; i < raw.length; i += 1) {
      hash = (hash * 131 + raw.charCodeAt(i)) >>> 0;
    }
    return hash >>> 0;
  }

  function trainingCenterAvatarSvg(seedText) {
    const seed = trainingCenterAvatarSeed(seedText);
    const palettes = [
      ['#e6f4ff', '#1677ff', '#073b7a'],
      ['#fff7e6', '#fa8c16', '#7a3c00'],
      ['#f6ffed', '#52c41a', '#245d0c'],
      ['#fff0f6', '#eb2f96', '#7a1450'],
      ['#f9f0ff', '#722ed1', '#3a1572'],
      ['#e6fffb', '#13c2c2', '#0d5959'],
    ];
    const tone = palettes[seed % palettes.length];
    const bg = tone[0];
    const accent = tone[1];
    const deep = tone[2];
    const shoulder = ['#f5d7c0', '#eec39f', '#d9a37e', '#f2c4a4'][seed % 4];
    const hair = ['#2f2a26', '#4b3a2a', '#1e1f26', '#3d2d4f'][seed % 4];
    return (
      "<svg class='tc-avatar-svg' viewBox='0 0 48 48' aria-hidden='true' focusable='false'>" +
      "<rect x='1.5' y='1.5' width='45' height='45' rx='12' fill='" +
      bg +
      "' stroke='" +
      accent +
      "' stroke-width='2'></rect>" +
      "<circle cx='24' cy='18' r='8.3' fill='" +
      shoulder +
      "'></circle>" +
      "<path d='M16 18.3c0-5.4 3.2-9.2 8-9.2s8 3.8 8 9.2c-2.2-1.2-4.6-1.8-8-1.8s-5.8.6-8 1.8z' fill='" +
      hair +
      "'></path>" +
      "<path d='M11 40c0-6.9 5.8-12.4 13-12.4S37 33.1 37 40' fill='" +
      accent +
      "' opacity='0.9'></path>" +
      "<path d='M16 40c0-4.2 3.6-7.6 8-7.6s8 3.4 8 7.6' fill='" +
      deep +
      "' opacity='0.9'></path>" +
      "</svg>"
    );
  }

  function isTrainingCenterSkillPlaceholder(entry) {
    const text = safe(entry).trim();
    if (!text) return true;
    const normalized = text.replace(/[\s\[\]\(\)\{\}'"`,\\]+/g, '').toLowerCase();
    return !normalized || normalized === 'null' || normalized === 'none';
  }

  function trainingCenterPortraitSkills(value) {
    if (Array.isArray(value)) {
      return value.map((item) => safe(item).trim()).filter((item) => !!item && !isTrainingCenterSkillPlaceholder(item));
    }
    const text = safe(value).trim();
    if (!text) return [];
    return text
      .split(/[\r\n,，、;；|/]+/)
      .map((item) => safe(item).trim())
      .filter((item) => !!item && !isTrainingCenterSkillPlaceholder(item));
  }

  function normalizeTrainingCenterSkillKey(value) {
    return safe(value)
      .trim()
      .toLowerCase()
      .replace(/[\s_-]+/g, '');
  }

  function trainingCenterPublishedSkillProfiles(value) {
    if (!Array.isArray(value)) return [];
    const rows = [];
    for (const item of value) {
      if (!item || typeof item !== 'object') continue;
      const name = safe(item.name).trim();
      if (!name || isTrainingCenterSkillPlaceholder(name)) continue;
      rows.push({
        name: name,
        summary: safe(item.summary).trim(),
        details: safe(item.details).trim(),
      });
    }
    return rows;
  }

  function trainingCenterPublishedSkillMap(release, fallbackSkills) {
    const map = Object.create(null);
    const profiles = trainingCenterPublishedSkillProfiles(release && release.skill_profiles);
    for (const profile of profiles) {
      const key = normalizeTrainingCenterSkillKey(profile.name);
      if (!key) continue;
      if (!map[key]) {
        map[key] = profile;
        continue;
      }
      if (!safe(map[key].summary).trim() && safe(profile.summary).trim()) {
        map[key].summary = profile.summary;
      }
      if (!safe(map[key].details).trim() && safe(profile.details).trim()) {
        map[key].details = profile.details;
      }
    }
    const names = trainingCenterPortraitSkills(release && release.skills);
    for (const name of names) {
      const key = normalizeTrainingCenterSkillKey(name);
      if (!key || map[key]) continue;
      map[key] = { name: name, summary: '', details: '' };
    }
    if (!Object.keys(map).length && safe(release && release.version_label).trim()) {
      const fallbackNames = trainingCenterPortraitSkills(fallbackSkills);
      for (const name of fallbackNames) {
        const key = normalizeTrainingCenterSkillKey(name);
        if (!key || map[key]) continue;
        map[key] = {
          name: name,
          summary: '',
          details: '',
          inferred: true,
        };
      }
    }
    return map;
  }

  function trainingCenterSkillSummaryText(profile) {
    const summary = safe(profile && profile.summary).trim();
    if (summary) return summary;
    const details = safe(profile && profile.details).trim();
    if (details) return '已发布，展开查看详情';
    if (profile && profile.inferred) return '已发布，当前版本未单独记录技能详情';
    return '未发布';
  }

  function trainingCenterSkillStateText(isPublished) {
    return isPublished ? '已发布' : '未发布';
  }

  function renderTrainingCenterSkillCards(localSkills, publishedRelease, fallbackPublishedSkills) {
    const skills = trainingCenterPortraitSkills(localSkills);
    if (!skills.length) {
      return '当前工作区未发现本地 Agent Skills';
    }
    const publishedSkillMap = trainingCenterPublishedSkillMap(publishedRelease || {}, fallbackPublishedSkills);
    return (
      "<div class='tc-agent-skill-cards'>" +
      skills
        .map((skillName) => {
          const key = normalizeTrainingCenterSkillKey(skillName);
          const isPublished = !!(key && Object.prototype.hasOwnProperty.call(publishedSkillMap, key));
          const profile = publishedSkillMap[key] || { name: skillName, summary: '', details: '' };
          const summaryText = trainingCenterSkillSummaryText(profile);
          const detailsText = safe(profile && profile.details).trim();
          return (
            "<div class='tc-agent-skill-card'>" +
            "<div class='tc-agent-skill-head'>" +
            "<div class='tc-agent-skill-name'>" +
            safe(skillName) +
            '</div>' +
            "<span class='tc-agent-skill-state " +
            (isPublished ? 'published' : 'unpublished') +
            "'>" +
            trainingCenterSkillStateText(isPublished) +
            '</span>' +
            '</div>' +
            "<div class='tc-agent-skill-summary'>" +
            safe(summaryText) +
            '</div>' +
            (detailsText
              ? "<details class='tc-agent-skill-detail'>" +
                "<summary>查看详情</summary>" +
                "<div class='tc-agent-skill-detail-body'>" +
                safe(detailsText) +
                '</div>' +
                '</details>'
              : '') +
            '</div>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function trainingCenterRolePositionText(value, maxLen) {
    const text = safe(value).trim();
    if (!text) return '未确定';
    const size = Math.max(1, Number(maxLen) || 50);
    if (text.length <= size) return text;
    if (size <= 3) return text.slice(0, size);
    return text.slice(0, size - 3).trimEnd() + '...';
  }

  function trainingCenterProfileTextItems(value, limit) {
    const rows = safe(value)
      .split(/[\r\n,，、;；|/]+/)
      .map((item) => safe(item).trim())
      .filter((item) => !!item);
    return rows.slice(0, Math.max(1, Number(limit) || 6));
  }

  function trainingCenterRoleProfile(detail) {
    const raw = detail && detail.role_profile && typeof detail.role_profile === 'object'
      ? detail.role_profile
      : {};
    const normalizeItems = (value, limit) => {
      if (Array.isArray(value)) {
        return value.map((item) => safe(item).trim()).filter(Boolean).slice(0, Math.max(1, Number(limit) || 6));
      }
      return trainingCenterProfileTextItems(value, limit);
    };
    return {
      profile_source: safe(raw.profile_source).trim(),
      fallback_reason: safe(raw.fallback_reason).trim(),
      source_release_id: safe(raw.source_release_id).trim(),
      source_release_version: safe(raw.source_release_version).trim(),
      source_ref: safe(raw.source_ref).trim(),
      first_person_summary: safe(raw.first_person_summary).trim(),
      what_i_can_do: normalizeItems(raw.what_i_can_do, 5),
      full_capability_inventory: normalizeItems(raw.full_capability_inventory, 12),
      knowledge_scope: safe(raw.knowledge_scope).trim(),
      agent_skills: normalizeItems(raw.agent_skills, 12),
      applicable_scenarios: normalizeItems(raw.applicable_scenarios, 6),
      version_notes: safe(raw.version_notes).trim(),
      public_profile_ref: safe(raw.public_profile_ref).trim(),
      capability_snapshot_ref: safe(raw.capability_snapshot_ref).trim(),
    };
  }

  function trainingCenterRoleProfileSourceText(source) {
    const key = safe(source).trim().toLowerCase();
    if (key === 'latest_release_report') return '最新正式发布报告';
    if (key === 'structured_fields_fallback') return '结构化字段回退';
    return '未绑定';
  }

  function trainingCenterRoleProfileFallbackReasonText(reason) {
    const key = safe(reason).trim().toLowerCase();
    if (key === 'latest_release_report_missing') return '正式发布报告快照缺失';
    if (key === 'latest_release_report_invalid') return '正式发布报告快照解析失败';
    if (key === 'no_released_profile') return '当前还没有可用的正式发布画像';
    return safe(reason).trim();
  }

  function trainingCenterPortraitIntroText(detail, publishedRelease, highlights) {
    const roleProfile = trainingCenterRoleProfile(detail);
    if (roleProfile.first_person_summary) return roleProfile.first_person_summary;
    const intro =
      safe((publishedRelease && (publishedRelease.capability_summary || publishedRelease.change_summary)) || '').trim() ||
      safe(detail && (detail.capability_summary || detail.core_capabilities)).trim();
    if (intro) return intro;
    if (Array.isArray(highlights) && highlights.length) return highlights.join('；');
    return safe((publishedRelease && publishedRelease.knowledge_scope) || detail.knowledge_scope).trim() || '当前暂无已发布角色简介。';
  }

  function trainingCenterWhatICanDoLines(item) {
    const detail = item || {};
    const roleProfile = trainingCenterRoleProfile(detail);
    if (roleProfile.what_i_can_do.length) {
      return roleProfile.what_i_can_do.slice(0, 5);
    }
    const candidateLines = [];
    const pushLines = (text) => {
      const rows = safe(text)
        .split(/[\r\n|；;。!?！？]+/)
        .map((line) => safe(line).replace(/^(能力|知识|技能|场景)\s*[:：]/, '').trim())
        .filter((line) => !!line);
      for (const line of rows) {
        if (!candidateLines.includes(line)) {
          candidateLines.push(line);
        }
      }
    };
    pushLines(detail.capability_summary);
    pushLines(detail.core_capabilities);
    return candidateLines.slice(0, 5);
  }

  function currentTrainingCenterPublishedRelease(item) {
    const detail = item || {};
    const agentId = safe(detail.agent_id).trim();
    if (!agentId) return null;
    const releases = Array.isArray(state.tcReleasesByAgent[agentId]) ? state.tcReleasesByAgent[agentId] : [];
    if (!releases.length) return null;
    const preferredVersion = safe(detail.bound_release_version || detail.latest_release_version).trim();
    if (preferredVersion) {
      const matched = releases.find((row) => safe(row && row.version_label).trim() === preferredVersion);
      if (matched) {
        return matched;
      }
    }
    return releases[0] || null;
  }

  function currentTrainingCenterDisplayedVersion(item, releaseRows) {
    const detail = item || {};
    const agentId = safe(detail.agent_id).trim();
    const releases = Array.isArray(releaseRows)
      ? releaseRows
      : agentId && Array.isArray(state.tcReleasesByAgent[agentId])
        ? state.tcReleasesByAgent[agentId]
        : [];
    const versionSet = new Set(
      releases
        .map((row) => safe(row && row.version_label).trim())
        .filter((value) => !!value)
    );
    const candidates = [
      safe(detail.bound_release_version).trim(),
      safe(detail.current_version).trim(),
      safe(detail.latest_release_version).trim(),
    ];
    for (const value of candidates) {
      if (!value) continue;
      if (!versionSet.size || versionSet.has(value)) {
        return value;
      }
    }
    return releases.length ? safe(releases[0] && releases[0].version_label).trim() : '';
  }

  function setTrainingCenterVersionDropdownOpen(nextOpen) {
    const host = $('tcVersionDropdown');
    const trigger = $('tcSwitchVersionTrigger');
    const panel = $('tcSwitchVersionPanel');
    const options = $('tcSwitchVersionOptions');
    const hasOptions =
      !!options &&
      Array.from(options.children || []).some((node) => node instanceof HTMLElement && node.classList.contains('tc-version-option'));
    const canOpen = !!host && !!trigger && !!panel && !trigger.disabled && hasOptions;
    const open = !!nextOpen && canOpen;
    state.tcVersionDropdownOpen = open;
    if (host) host.classList.toggle('open', open);
    if (trigger) trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function hasTrainingCenterPublishedRelease(item) {
    return !!currentTrainingCenterPublishedRelease(item);
  }

  function renderTrainingCenterAvatarPreview(item, forceDefault) {
    const previewNode = $('tcAvatarPreview');
    if (!previewNode) return;
    if (forceDefault) {
      previewNode.innerHTML = trainingCenterAvatarSvg('default-avatar');
      return;
    }
    const seed = safe((item && item.vector_icon) || (item && item.agent_name) || (item && item.agent_id) || '');
    const avatarUri = safe(item && item.avatar_uri).trim();
    previewNode.innerHTML = '';
    if (!avatarUri) {
      previewNode.innerHTML = trainingCenterAvatarSvg(seed || 'default-avatar');
      return;
    }
    const image = document.createElement('img');
    image.className = 'tc-avatar-image';
    image.alt = '角色头像';
    image.src = avatarUri;
    image.onerror = () => {
      previewNode.innerHTML = trainingCenterAvatarSvg(seed || 'default-avatar');
    };
    previewNode.appendChild(image);
  }

  function renderTrainingCenterPortrait(item) {
    const portraitNode = $('tcPortraitFields');
    if (!portraitNode) return;
    const portraitCard = $('tcPortraitCard');
    if (portraitCard) {
      portraitCard.style.maxHeight = 'none';
      portraitCard.style.overflow = 'visible';
      portraitCard.style.overscrollBehavior = 'auto';
    }
    portraitNode.style.maxHeight = 'none';
    portraitNode.style.overflow = 'visible';
    portraitNode.style.paddingRight = '0';
    const detail = item || {};
    const detailIdentity = safe(detail.agent_id || detail.agent_name).trim();
    if (!detailIdentity) {
      portraitNode.style.display = '';
      portraitNode.innerHTML =
        "<div class='tc-empty-detail'>" +
        "<div class='tc-empty-detail-title'>从左侧选择角色</div>" +
        "<div class='tc-empty-detail-desc'>选择后可查看角色介绍、发布模板信息、本地 Agent Skills 与版本切换入口。</div>" +
        "<div class='tc-empty-detail-pills'>" +
        "<span class='tc-badge'>角色介绍</span>" +
        "<span class='tc-badge'>发布模板</span>" +
        "<span class='tc-badge'>Agent Skills</span>" +
        "<span class='tc-badge'>版本切换</span>" +
        '</div>' +
        '</div>';
      renderTrainingCenterAvatarPreview(null, true);
      return;
    }
    const publishedRelease = currentTrainingCenterPublishedRelease(detail);
    const roleProfile = trainingCenterRoleProfile(detail);
    const localAgentSkills = trainingCenterPortraitSkills(detail.agent_skills);
    const publishedSkillMap = trainingCenterPublishedSkillMap(publishedRelease || {}, localAgentSkills);
    const publishedSkillRows = Object.keys(publishedSkillMap).map((key) => publishedSkillMap[key]).filter((row) => !!row);
    const introText = trainingCenterPortraitIntroText(detail, publishedRelease, roleProfile.what_i_can_do);
    const whatICanDo = roleProfile.what_i_can_do.length ? roleProfile.what_i_can_do : trainingCenterWhatICanDoLines(detail);
    const fullCapabilityInventory = roleProfile.full_capability_inventory.length
      ? roleProfile.full_capability_inventory
      : whatICanDo;
    const knowledgeScope = roleProfile.knowledge_scope || safe(publishedRelease && publishedRelease.knowledge_scope).trim();
    const scenarioItems = roleProfile.applicable_scenarios.length
      ? roleProfile.applicable_scenarios
      : trainingCenterProfileTextItems(safe(publishedRelease && publishedRelease.applicable_scenarios).trim(), 6);
    const skillItems = roleProfile.agent_skills.length
      ? roleProfile.agent_skills
      : (
        publishedSkillRows.length
          ? publishedSkillRows.map((row) => safe(row.name).trim()).filter((row) => !!row)
          : localAgentSkills
      );
    const versionNotes = roleProfile.version_notes || safe(publishedRelease && publishedRelease.version_notes).trim();
    const skillHint = roleProfile.profile_source === 'structured_fields_fallback'
      ? '当前角色详情来自结构化字段回退；正式发布报告补齐后会优先替换。'
      : (
        publishedRelease && !publishedSkillRows.some((skill) => safe(skill.summary || skill.details).trim())
          ? '当前版本仅同步到技能标签，未单独补充技能说明。'
          : ''
      );
    const portraitSections = [];
    const addTextSection = (key, label, value) => {
      const text = safe(value).trim();
      if (!text) return;
      portraitSections.push(
        "<section class='tc-portrait-item' data-portrait-key='" + safe(key) + "' data-portrait-label='" + safe(label) + "'>" +
          "<div class='tc-portrait-k'>" + safe(label) + '</div>' +
          "<div class='tc-portrait-v'>" + safe(text) + '</div>' +
        '</section>'
      );
    };
    const addListSection = (key, label, rows, extraTip) => {
      const list = Array.isArray(rows) ? rows.map((row) => safe(row).trim()).filter((row) => !!row) : [];
      if (!list.length) return;
      portraitSections.push(
        "<section class='tc-portrait-item' data-portrait-key='" + safe(key) + "' data-portrait-label='" + safe(label) + "'>" +
          "<div class='tc-portrait-k'>" + safe(label) + '</div>' +
          "<ul class='tc-portrait-v tc-portrait-list'>" +
            list.map((row) => '<li>' + safe(row) + '</li>').join('') +
          '</ul>' +
          (extraTip ? "<div class='tc-portrait-v'>" + safe(extraTip) + '</div>' : '') +
        '</section>'
      );
    };
    addTextSection('intro', '我是', introText);
    addListSection('what_i_can_do', '我当前能做什么', whatICanDo);
    addListSection('full_capability_inventory', '全量能力清单', fullCapabilityInventory);
    addTextSection('knowledge_scope', '角色知识范围', knowledgeScope);
    addListSection('agent_skills', 'Agent Skills', skillItems, skillHint);
    addListSection('applicable_scenarios', '适用场景', scenarioItems);
    addTextSection('version_notes', '版本说明', versionNotes);
    portraitNode.style.display = '';
    portraitNode.innerHTML = portraitSections.length
      ? portraitSections.join('')
      : (
        "<section class='tc-portrait-item' data-portrait-key='release_status' data-portrait-label='发布状态'>" +
          "<div class='tc-portrait-k'>发布状态</div>" +
          "<div class='tc-portrait-v'>" + safe(publishedRelease ? '当前版本尚未补充角色简介详情。' : '当前还没有可用的发布简介。') + '</div>' +
        '</section>'
      );
    renderTrainingCenterAvatarPreview(detail);
  }

  function renderTrainingCenterCardTags(tags) {
    const visibleTags = visibleTrainingStatusTags(tags);
    if (!visibleTags.length) {
      return "<span class='tc-badge'>已发布</span>";
    }
    return visibleTags.map((tag) => "<span class='tc-badge'>" + trainingStatusTagText(tag) + '</span>').join('');
  }

  function renderTrainingCenterAgentList() {
    const box = $('tcAgentList');
    if (!box) return;
    box.innerHTML = '';
    const rows = filteredTrainingCenterAgents();
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'tc-empty';
      empty.textContent = state.agentSearchRootReady ? '暂无角色资产数据' : '根路径未就绪，功能已锁定';
      box.appendChild(empty);
      return;
    }
    for (const row of rows) {
      const agentId = safe(row && row.agent_id).trim();
      if (!agentId) continue;
      const node = document.createElement('div');
      node.className = 'tc-item tc-agent-card' + (safe(state.tcSelectedAgentId) === agentId ? ' active' : '');
      const tags = visibleTrainingStatusTags(row.status_tags);
      const iconSeed = safe(row.vector_icon || row.agent_name || agentId);
      const cardTitle = safe(row.agent_name || agentId);
      const releaseLine = safe(row.last_release_at).trim();
      const visibleVersion = safe(row.bound_release_version || row.latest_release_version).trim();
      const capabilitySummary = safe(row.capability_summary || row.core_capabilities).trim();
      const knowledgeScope = safe(row.knowledge_scope).trim();
      const rolePosition = visibleVersion
        ? trainingCenterRolePositionText(capabilitySummary || knowledgeScope, 50)
        : '未确定';
      const cardMetaRows = [];
      cardMetaRows.push("<div class='tc-item-sub tc-card-line'>角色定位：" + rolePosition + '</div>');
      if (releaseLine) {
        cardMetaRows.push("<div class='tc-item-sub tc-card-line'>最近发布时间：" + releaseLine + '</div>');
      }
      node.innerHTML =
        "<div class='tc-card-head'>" +
        "<span class='tc-vector-icon'>" +
        trainingCenterAvatarSvg(iconSeed) +
        '</span>' +
        "<div class='tc-card-title-wrap'>" +
        "<div class='tc-item-title'>" +
        cardTitle +
        '</div>' +
        renderTrainingCenterVersionPill(visibleVersion) +
        '</div>' +
        "<span class='tc-card-chip'>工牌</span>" +
        '</div>' +
        cardMetaRows.join('') +
        "<div class='tc-card-tags'>" +
        renderTrainingCenterCardTags(tags) +
        '</div>';
      node.onclick = () => {
        setTrainingCenterVersionDropdownOpen(false);
        state.tcSelectedAgentId = agentId;
        state.tcSelectedAgentName = safe(row.agent_name || '');
        state.tcSelectedAgentDetail = row;
        syncTrainingCenterPlanAgentOptions();
        updateTrainingCenterSelectedMeta();
        renderTrainingCenterAgentList();
        refreshTrainingCenterSelectedAgentContext(agentId).catch((err) => {
          setTrainingCenterDetailError(err.message || String(err));
        });
        applyGateState();
      };
      box.appendChild(node);
    }
  }

  function renderTrainingCenterReleases(agentId) {
    const box = $('tcReleaseList');
    if (!box) return;
    box.innerHTML = '';
    const key = safe(agentId).trim();
    const releases = state.tcReleasesByAgent[key] || [];
    syncTrainingCenterSwitchVersionOptions(key);
    if (!releases.length) {
      const empty = document.createElement('div');
      empty.className = 'tc-empty';
      empty.textContent =
        state.tcSelectedAgentContextLoading && safe(state.tcSelectedAgentId).trim() === key
          ? '正在同步发布版本...'
          : '暂无符合发布格式的版本';
      box.appendChild(empty);
      return;
    }
    for (const row of releases) {
      const node = document.createElement('div');
      node.className = 'tc-item';
      const titleNode = document.createElement('div');
      titleNode.className = 'tc-item-title';
      titleNode.textContent = safe(row.version_label || '-');
      const badgeNode = document.createElement('span');
      badgeNode.className = 'tc-badge ok';
      badgeNode.textContent = '发布版本';
      titleNode.appendChild(document.createTextNode(' '));
      titleNode.appendChild(badgeNode);
      node.appendChild(titleNode);

      const timeNode = document.createElement('div');
      timeNode.className = 'tc-item-sub';
      timeNode.textContent = '发布时间：' + safe(row.released_at || '-');
      node.appendChild(timeNode);

      const summaryNode = document.createElement('div');
      summaryNode.className = 'tc-item-sub';
      summaryNode.textContent = '发布说明：' + safe(row.version_notes || row.change_summary || '-');
      node.appendChild(summaryNode);
      node.dataset.releaseVersion = safe(row.version_label || '').trim();

      const reportRef = safe(row.release_source_ref || row.capability_snapshot_ref).trim();
      if (reportRef) {
        const actionsNode = document.createElement('div');
        actionsNode.className = 'tc-release-row';
        const reportBtn = document.createElement('button');
        reportBtn.type = 'button';
        reportBtn.className = 'alt';
        reportBtn.textContent = '查看发布报告';
        reportBtn.dataset.releaseVersion = safe(row.version_label || '').trim();
        reportBtn.onclick = async () => {
          try {
            reportBtn.disabled = true;
            await openTrainingCenterPublishedReleaseReport(key, row);
          } catch (err) {
            const refs = ensureTrainingCenterPublishedReleaseReportDialog();
            if (refs.errorNode) refs.errorNode.textContent = safe(err && err.message ? err.message : err);
            if (refs.bodyNode) {
              refs.bodyNode.innerHTML = '';
              const empty = document.createElement('div');
              empty.className = 'tc-empty';
              empty.textContent = '当前发布报告暂不可展示。';
              refs.bodyNode.appendChild(empty);
            }
            if (refs.dialog && !refs.dialog.open && typeof refs.dialog.showModal === 'function') {
              refs.dialog.showModal();
            }
          } finally {
            reportBtn.disabled = false;
          }
        };
        actionsNode.appendChild(reportBtn);
        node.appendChild(actionsNode);
      } else {
        const hintNode = document.createElement('div');
        hintNode.className = 'tc-item-sub';
        hintNode.textContent = '发布报告：当前版本未绑定可展示的发布报告文件';
        hintNode.dataset.releaseVersion = safe(row.version_label || '').trim();
        node.appendChild(hintNode);
      }
      box.appendChild(node);
    }
  }

  function renderTrainingCenterNormalCommits(agentId) {
    const box = $('tcNormalCommitList');
    const detailsNode = $('tcNormalCommitDetails');
    const summaryTextNode = $('tcNormalCommitSummaryText');
    const countNode = $('tcNormalCommitCount');
    if (!box) return;
    box.innerHTML = '';
    const key = safe(agentId).trim();
    const rows = state.tcNormalCommitsByAgent && state.tcNormalCommitsByAgent[key]
      ? state.tcNormalCommitsByAgent[key]
      : [];
    if (summaryTextNode) {
      summaryTextNode.textContent = rows.length ? '查看 Git 提交记录详情' : '暂无 Git 提交记录';
    }
    if (countNode) {
      countNode.textContent = rows.length ? String(rows.length) : '';
    }
    if (detailsNode) {
      detailsNode.hidden = !rows.length;
      if (!rows.length) detailsNode.open = false;
    }
    if (!rows.length) {
      return;
    }
    for (const row of rows) {
      const reasons = Array.isArray(row.invalid_reasons) ? row.invalid_reasons.filter((v) => !!safe(v).trim()) : [];
      const node = document.createElement('div');
      node.className = 'tc-item';
      node.innerHTML =
        "<div class='tc-item-title'>" +
        safe(row.version_label || '-') +
        " <span class='tc-badge warn'>普通提交</span>" +
        '</div>' +
        "<div class='tc-item-sub'>发布时间：" +
        safe(row.released_at || '-') +
        '</div>' +
        "<div class='tc-item-sub'>说明：" +
        safe(row.version_notes || row.change_summary || '-') +
        '</div>' +
        "<div class='tc-item-sub'>未通过原因：" +
        (reasons.length ? reasons.join(', ') : '发布字段不完整') +
        '</div>';
      box.appendChild(node);
    }
  }
