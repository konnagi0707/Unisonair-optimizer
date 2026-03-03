const state = {
  cards: [],
  cardsByCode: new Map(),
  songs: [],
  defaults: null,
  slots: [null, null, null, null, null],
  activeSlot: 0,
  memberPoints: {},
  baseMemberPoints: {},
  memberPointOverrides: new Set(),
  memberCatalog: [],
  memberNameAliasMap: new Map(),
  selectedMembers: new Set(),
  selectedColors: new Set(),
  selectedGroups: new Set(),
  selectedSortKeys: new Set(),
  selectedSeries: new Set(),
  selectedSkillBuckets: new Set(),
  ownedCodes: new Set(),
  excludedCodes: new Set(),
  centerCandidateCodes: new Set(),
  mustIncludeCodes: new Set(),
  optimizeProgressTimer: null,
  optimizePollTimer: null,
  currentOptimizeJobId: "",
  optimizeJobStatus: "",
  optimizeStarting: false,
  optimizeCancelBusy: false,
  lastOptimizeData: null,
  lastOptimizePayload: null,
  profileBackups: [],
  profileBackupsName: "",
  profiles: {},
  activeProfile: "",
  profileAutoSaveEnabled: true,
  defaultMemberPoint: 15000,
  excludedFilterText: "",
  excludedFilterColors: new Set(),
  excludedFilterGroups: new Set(),
  excludedFilterSeries: new Set(),
  teamReplace: null,
};

const $ = (id) => document.getElementById(id);
let workspaceSyncTimer = null;
let profileAutoSaveTimer = null;
let profileAutoSaveInFlight = false;
let profileAutoSavePending = false;
let profileAutoSaveTarget = "";
let teamReplaceCalcToken = 0;

function colorClass(color) {
  return ["R", "B", "G", "Y", "P"].includes(color) ? color : "P";
}

const COLOR_LONG = {
  R: "RED",
  B: "BLUE",
  G: "GREEN",
  Y: "YELLOW",
  P: "PURPLE",
};

const COLOR_FULL_LABEL = {
  R: "Red",
  B: "Blue",
  G: "Green",
  Y: "Yellow",
  P: "Purple",
  ALL: "All",
};

const COLOR_FILTER_OPTIONS = [
  { key: "R", label: COLOR_FULL_LABEL.R },
  { key: "B", label: COLOR_FULL_LABEL.B },
  { key: "G", label: COLOR_FULL_LABEL.G },
  { key: "Y", label: COLOR_FULL_LABEL.Y },
  { key: "P", label: COLOR_FULL_LABEL.P },
];

const GROUP_FILTER_OPTIONS = [
  { key: "sakura", label: "櫻坂46" },
  { key: "hinata", label: "日向坂46" },
];

const SORT_FILTER_OPTIONS = [
  { key: "vo_desc", label: "Vo 高→低" },
  { key: "da_desc", label: "Da 高→低" },
  { key: "pe_desc", label: "Pe 高→低" },
  { key: "power_desc", label: "总和 高→低" },
];
const MAX_MUST_INCLUDE = 5;
const DEFAULT_MEMBER_POINT = 15000;
const FAIR_BASELINE_LABEL = "公平配置（成员均值15000）";
const UNGROUPED_GENERATION_LABEL = "毕业成员";
const PRECIOUS_PAIR_SERIES_TAG = "Precious -pair-";
const PRECIOUS_PAIR_23_SERIES_TAG = "Precious -pair-'23";
const DEFAULT_PROFILE_NAME = "琴原美名";
const UI_STATE_STORAGE_KEY = "uoa_scoring_ui_state_v2";
const OPTIMIZE_JOB_STORAGE_KEY = "uoa_scoring_optimize_job_id_v1";
const RESULT_STATE_STORAGE_KEY = "uoa_scoring_result_state_v2";
const UI_STATE_VERSION = 1;
const RESULT_STATE_VERSION = 2;
let persistUiStateTimer = null;
let isApplyingPersistedUiState = false;
let renderCardListRaf = null;

function toUniqueStringArray(input) {
  if (!Array.isArray(input)) return [];
  return [...new Set(input.map((x) => String(x || "").trim()).filter(Boolean))];
}

function normalizeMemberNameKey(text) {
  return String(text || "")
    .trim()
    .normalize("NFKC")
    .replace(/\s+/g, "")
    .replaceAll("髙", "高")
    .replaceAll("﨑", "崎")
    .replaceAll("神", "神");
}

function canonicalMemberName(text) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  const aliases = state.memberNameAliasMap;
  if (aliases && aliases.has(raw)) return String(aliases.get(raw) || raw);
  const key = normalizeMemberNameKey(raw);
  if (aliases && aliases.has(key)) return String(aliases.get(key) || raw);
  return raw;
}

function rebuildMemberNameAliasMap() {
  const aliases = new Map();
  const addAlias = (aliasKey, canonicalName) => {
    const a = String(aliasKey || "").trim();
    const c = String(canonicalName || "").trim();
    if (!a || !c || aliases.has(a)) return;
    aliases.set(a, c);
  };
  state.cards.forEach((card) => {
    const memberName = String(card?.member_name || "").trim();
    if (!memberName) return;
    const memberNameNorm = String(card?.member_name_norm || memberName).trim();
    addAlias(memberName, memberName);
    addAlias(memberNameNorm, memberName);
    addAlias(normalizeMemberNameKey(memberName), memberName);
    addAlias(normalizeMemberNameKey(memberNameNorm), memberName);
  });
  state.memberNameAliasMap = aliases;
}

function sanitizeMemberPointsMap(raw, memberNameSet = null) {
  const out = {};
  if (!raw || typeof raw !== "object") return out;
  Object.entries(raw).forEach(([k, v]) => {
    const key = canonicalMemberName(k);
    if (!key) return;
    if (memberNameSet && !memberNameSet.has(key)) return;
    const iv = Math.max(0, parseInt(String(v), 10) || 0);
    out[key] = iv;
  });
  return out;
}

function buildUiStateSnapshot() {
  return {
    version: UI_STATE_VERSION,
    saved_at: new Date().toISOString(),
    activeProfile: String(state.activeProfile || ""),
    profileAutoSaveEnabled: Boolean(state.profileAutoSaveEnabled),
    profileSelectValue: $("profileSelect")?.value || "",
    mode: $("mode")?.value || "single",
    songKey: $("songKey")?.value || "",
    songColor: $("songColor")?.value || "ALL",
    groupPower: $("groupPower")?.value || "",
    trials: $("trials")?.value || "",
    sortBy: $("sortBy")?.value || "",
    optTopN: $("optTopN")?.value || "",
    optPoolScope: $("optPoolScope")?.value || "owned",
    cardListScope: $("cardListScope")?.value || "all",
    qSearch: $("qSearch")?.value || "",
    selectedMembers: [...state.selectedMembers],
    selectedColors: [...state.selectedColors],
    selectedGroups: [...state.selectedGroups],
    selectedSortKeys: [...state.selectedSortKeys],
    selectedSeries: [...state.selectedSeries],
    selectedSkillBuckets: [...state.selectedSkillBuckets],
    ownedCodes: [...state.ownedCodes],
    excludedCodes: [...state.excludedCodes],
    centerCandidateCodes: [...state.centerCandidateCodes],
    mustIncludeCodes: [...state.mustIncludeCodes],
    slots: [...state.slots],
    activeSlot: Number(state.activeSlot || 0),
    defaultMemberPoint: getDefaultMemberPoint(),
    memberPoints: getMemberPointsPayload(),
    baseMemberPoints: sanitizeMemberPointsMap(state.baseMemberPoints || {}),
    memberPointOverrides: [...state.memberPointOverrides],
    filterFoldOpenStates: [...document.querySelectorAll(".workspace-left .filter-fold")].map((fold) => Boolean(fold.open)),
  };
}

function persistUiStateNow() {
  if (isApplyingPersistedUiState) return;
  try {
    localStorage.setItem(UI_STATE_STORAGE_KEY, JSON.stringify(buildUiStateSnapshot()));
  } catch (_) {}
}

function schedulePersistUiState() {
  if (isApplyingPersistedUiState) return;
  if (persistUiStateTimer) window.clearTimeout(persistUiStateTimer);
  persistUiStateTimer = window.setTimeout(() => {
    persistUiStateTimer = null;
    persistUiStateNow();
  }, 180);
}

function loadPersistedUiState() {
  try {
    const raw = localStorage.getItem(UI_STATE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch (_) {
    return null;
  }
}

function persistResultState(snapshot) {
  try {
    localStorage.setItem(
      RESULT_STATE_STORAGE_KEY,
      JSON.stringify({
        version: RESULT_STATE_VERSION,
        saved_at: new Date().toISOString(),
        ...snapshot,
      })
    );
  } catch (_) {}
}

function loadPersistedResultState() {
  try {
    const raw = localStorage.getItem(RESULT_STATE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch (_) {
    return null;
  }
}

function restorePersistedResultState() {
  const snapshot = loadPersistedResultState();
  if (!snapshot || typeof snapshot !== "object") return false;
  const kind = String(snapshot.kind || "").trim();
  if (kind === "optimize") {
    const data = snapshot.data;
    if (!data || typeof data !== "object" || !Array.isArray(data.teams) || !data.teams.length) return false;
    state.lastOptimizePayload = snapshot.payload && typeof snapshot.payload === "object" ? snapshot.payload : null;
    applyOptimizeResult(data);
    return true;
  }
  if (kind === "evaluate") {
    const data = snapshot.data;
    if (!data || typeof data !== "object") return false;
    const results = Array.isArray(data.results) ? data.results : [];
    if (!results.length) return false;
    const mode = data.meta?.mode || "single";
    $("resultHint").textContent = "";
    $("resultArea").innerHTML = mode === "single" ? renderSingle(results[0], data.meta) : renderMulti(results, data.meta);
    return true;
  }
  return false;
}

function applyPersistedUiState(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return false;
  const cardCodeSet = new Set(state.cards.map((c) => String(c.code || "").trim()).filter(Boolean));
  const memberNormSet = new Set(
    state.cards.map((c) => String(c.member_name_norm || c.member_name || "").trim()).filter(Boolean)
  );
  const memberNameSet = new Set(state.cards.map((c) => String(c.member_name || "").trim()).filter(Boolean));
  const seriesSet = new Set();
  state.cards.forEach((c) => getCardSeriesTags(c).forEach((x) => seriesSet.add(x)));
  const skillBucketSet = new Set(state.cards.map((c) => String(c.skill_bucket || "").trim()).filter(Boolean));
  const colorSet = new Set(COLOR_FILTER_OPTIONS.map((x) => x.key));
  const groupSet = new Set(GROUP_FILTER_OPTIONS.map((x) => x.key));
  const sortSet = new Set(SORT_FILTER_OPTIONS.map((x) => x.key));

  isApplyingPersistedUiState = true;
  try {
    if (typeof snapshot.profileAutoSaveEnabled === "boolean") {
      state.profileAutoSaveEnabled = Boolean(snapshot.profileAutoSaveEnabled);
    }
    let loadedProfileName = "";
    const profileName = String(snapshot.activeProfile || "").trim();
    if (profileName && state.profiles[profileName]) {
      const ok = applyProfile(profileName, false);
      const profileSelect = $("profileSelect");
      if (ok) loadedProfileName = profileName;
      if (profileSelect) profileSelect.value = ok ? profileName : "";
    }
    if (!loadedProfileName) {
      const profileSelect = $("profileSelect");
      const selectedValue = String(snapshot.profileSelectValue || "").trim();
      if (profileSelect && selectedValue && state.profiles[selectedValue]) {
        const ok = applyProfile(selectedValue, false);
        if (ok) {
          loadedProfileName = selectedValue;
          profileSelect.value = selectedValue;
        }
      }
    }
    if (!loadedProfileName) {
      const fallbackLoaded = String(state.activeProfile || "").trim();
      if (fallbackLoaded && state.profiles[fallbackLoaded]) {
        loadedProfileName = fallbackLoaded;
      }
    }
    const hasProfileLoaded = Boolean(loadedProfileName);

    const modeEl = $("mode");
    if (modeEl) {
      const mode = String(snapshot.mode || "").trim();
      if (["single", "color", "all"].includes(mode)) modeEl.value = mode;
    }
    onModeChange(true);

    const songKey = String(snapshot.songKey || "").trim();
    if (songKey && state.songs.some((s) => s.key === songKey)) {
      const songKeyEl = $("songKey");
      if (songKeyEl) songKeyEl.value = songKey;
    }
    const songColor = String(snapshot.songColor || "").toUpperCase();
    if (["ALL", "R", "B", "G", "Y", "P"].includes(songColor)) {
      const songColorEl = $("songColor");
      if (songColorEl) songColorEl.value = songColor;
    }
    const sortBy = String(snapshot.sortBy || "").trim();
    if (["+2sigma", "median", "+1sigma", "+3sigma"].includes(sortBy)) {
      const sortByEl = $("sortBy");
      if (sortByEl) sortByEl.value = sortBy;
    }
    const poolScope = String(snapshot.optPoolScope || "").trim();
    if (["all", "owned"].includes(poolScope)) {
      const poolScopeEl = $("optPoolScope");
      if (poolScopeEl) poolScopeEl.value = poolScope;
    }
    const cardListScope = String(snapshot.cardListScope || "").trim();
    if (["all", "owned"].includes(cardListScope)) {
      const cardListScopeEl = $("cardListScope");
      if (cardListScopeEl) cardListScopeEl.value = cardListScope;
    }

    if (!hasProfileLoaded) {
      const groupPower = parseInt(String(snapshot.groupPower || ""), 10);
      if (Number.isFinite(groupPower) && groupPower > 0) {
        const groupPowerEl = $("groupPower");
        if (groupPowerEl) groupPowerEl.value = String(groupPower);
      }
    }
    const trials = parseInt(String(snapshot.trials || ""), 10);
    if (Number.isFinite(trials) && trials >= 100) {
      const trialsEl = $("trials");
      if (trialsEl) trialsEl.value = String(Math.min(50000, trials));
    }
    const optTopN = parseInt(String(snapshot.optTopN || ""), 10);
    if (Number.isFinite(optTopN) && optTopN >= 1) {
      const optTopNEl = $("optTopN");
      if (optTopNEl) optTopNEl.value = String(Math.min(30, optTopN));
    }
    const qSearchEl = $("qSearch");
    if (qSearchEl) qSearchEl.value = String(snapshot.qSearch || "");

    state.selectedMembers = new Set(toUniqueStringArray(snapshot.selectedMembers).filter((x) => memberNormSet.has(x)));
    state.selectedColors = new Set(toUniqueStringArray(snapshot.selectedColors).filter((x) => colorSet.has(x)));
    state.selectedGroups = new Set(toUniqueStringArray(snapshot.selectedGroups).filter((x) => groupSet.has(x)));
    state.selectedSortKeys = new Set(toUniqueStringArray(snapshot.selectedSortKeys).filter((x) => sortSet.has(x)));
    state.selectedSeries = new Set(toUniqueStringArray(snapshot.selectedSeries).filter((x) => seriesSet.has(x)));
    state.selectedSkillBuckets = new Set(
      toUniqueStringArray(snapshot.selectedSkillBuckets).filter((x) => skillBucketSet.has(x))
    );

    // Exclude pool is paused for now; ignore persisted exclude state.
    state.excludedCodes = new Set();
    if (!hasProfileLoaded) {
      state.ownedCodes = new Set(toUniqueStringArray(snapshot.ownedCodes).filter((x) => cardCodeSet.has(x)));
    }
    state.centerCandidateCodes = new Set(
      toUniqueStringArray(snapshot.centerCandidateCodes).filter((x) => cardCodeSet.has(x) && isVsCenterCode(x))
    );
    state.mustIncludeCodes = new Set(
      toUniqueStringArray(snapshot.mustIncludeCodes)
        .filter((x) => cardCodeSet.has(x))
        .slice(0, MAX_MUST_INCLUDE)
    );

    if (Array.isArray(snapshot.slots) && snapshot.slots.length === state.slots.length) {
      const used = new Set();
      state.slots = snapshot.slots.map((code) => {
        const key = String(code || "").trim();
        if (!key || !cardCodeSet.has(key) || used.has(key)) return null;
        used.add(key);
        return key;
      });
      const firstEmpty = state.slots.findIndex((x) => x === null);
      state.activeSlot = firstEmpty >= 0 ? firstEmpty : 0;
    }

    const hasMemberPoints = snapshot.memberPoints && typeof snapshot.memberPoints === "object";
    if (hasMemberPoints && !hasProfileLoaded) {
      state.memberPoints = sanitizeMemberPointsMap(snapshot.memberPoints, memberNameSet);
    }
    if (snapshot.baseMemberPoints && typeof snapshot.baseMemberPoints === "object" && !hasProfileLoaded) {
      state.baseMemberPoints = sanitizeMemberPointsMap(snapshot.baseMemberPoints, memberNameSet);
    }
    if (Array.isArray(snapshot.memberPointOverrides) && !hasProfileLoaded) {
      state.memberPointOverrides = new Set(
        toUniqueStringArray(snapshot.memberPointOverrides)
          .map((name) => canonicalMemberName(name))
          .filter((name) => memberNameSet.has(name))
      );
    }
    const defaultMemberPoint = parseInt(String(snapshot.defaultMemberPoint || ""), 10);
    if (Number.isFinite(defaultMemberPoint) && defaultMemberPoint >= 0) {
      state.defaultMemberPoint = defaultMemberPoint;
    }

    const foldStates = Array.isArray(snapshot.filterFoldOpenStates) ? snapshot.filterFoldOpenStates : [];
    if (foldStates.length > 0) {
      const folds = [...document.querySelectorAll(".workspace-left .filter-fold")];
      folds.forEach((fold, idx) => {
        if (typeof foldStates[idx] === "boolean") fold.open = foldStates[idx];
      });
    }
  } finally {
    isApplyingPersistedUiState = false;
  }
  return true;
}

function normalizeSeriesToken(s) {
  return String(s || "")
    .trim()
    .toLowerCase()
    .replace(/é/g, "e")
    .replace(/\s+/g, "");
}

function isVsCenterCard(card) {
  if (!card) return false;
  if (Boolean(card.is_vs_base)) return true;
  const tags = Array.isArray(card.tags) ? card.tags.map((x) => normalizeSeriesToken(x)) : [];
  if (tags.includes("v/s") || tags.includes("veaut") || tags.includes("s.teller")) return true;
  const titleKey = normalizeSeriesToken(card.title || "");
  return titleKey.includes("veaut") || titleKey.includes("s.teller");
}

function isVsCenterCode(code) {
  if (!code) return false;
  const card = getCardByCode(code);
  return isVsCenterCard(card);
}

function nfmt(num) {
  return Number(num || 0).toLocaleString("en-US");
}

function pickStatValue(primary, fallback) {
  const p = Number(primary);
  if (Number.isFinite(p) && p > 0) return p;
  const f = Number(fallback);
  return Number.isFinite(f) ? f : 0;
}

function getDefaultMemberPoint() {
  return Math.max(
    0,
    parseInt(String(state.defaultMemberPoint ?? DEFAULT_MEMBER_POINT), 10) || DEFAULT_MEMBER_POINT
  );
}

function getActiveProfileMemberPoints() {
  const profile = state.activeProfile ? state.profiles[state.activeProfile] : null;
  const points = profile?.member_points;
  if (!points || typeof points !== "object") return null;
  return points;
}

function hasBaseMemberPoint(memberName) {
  const key = canonicalMemberName(memberName);
  if (!key) return false;
  if (Object.prototype.hasOwnProperty.call(state.baseMemberPoints || {}, key)) return true;
  const activeProfilePoints = getActiveProfileMemberPoints();
  return Boolean(activeProfilePoints && Object.prototype.hasOwnProperty.call(activeProfilePoints, key));
}

function getBaseMemberPoint(memberName) {
  const key = canonicalMemberName(memberName);
  if (!key) return getDefaultMemberPoint();
  if (Object.prototype.hasOwnProperty.call(state.baseMemberPoints || {}, key)) {
    return Math.max(0, parseInt(String(state.baseMemberPoints[key]), 10) || 0);
  }
  const activeProfilePoints = getActiveProfileMemberPoints();
  if (activeProfilePoints && Object.prototype.hasOwnProperty.call(activeProfilePoints, key)) {
    return Math.max(0, parseInt(String(activeProfilePoints[key]), 10) || 0);
  }
  return getDefaultMemberPoint();
}

function getCurrentMemberPoint(memberName) {
  const key = canonicalMemberName(memberName);
  if (!key) return getDefaultMemberPoint();
  if (Object.prototype.hasOwnProperty.call(state.memberPoints || {}, key)) {
    return Math.max(0, parseInt(String(state.memberPoints[key]), 10) || 0);
  }
  return getBaseMemberPoint(key);
}

function applyDefaultBaseline(refreshUI = true) {
  state.activeProfile = "";
  state.defaultMemberPoint = DEFAULT_MEMBER_POINT;
  state.memberPoints = {};
  state.baseMemberPoints = {};
  state.memberPointOverrides.clear();
  state.ownedCodes.clear();
  state.excludedCodes.clear();
  state.centerCandidateCodes.clear();
  state.mustIncludeCodes.clear();
  const groupPowerEl = $("groupPower");
  if (groupPowerEl) {
    const fallbackGroup = parseInt(String(state.defaults?.group_power || 1800000), 10) || 1800000;
    groupPowerEl.value = String(fallbackGroup);
  }
  const poolScopeEl = $("optPoolScope");
  if (poolScopeEl) poolScopeEl.value = "owned";
  if (refreshUI) {
    renderSlots();
    renderCardList();
    refreshPoolSummary();
    refreshResultExcludeBadges();
  }
  setProfileHint("公平配置：未使用账号。候选卡池=仅持有（初始0张），请先勾选自己的持有卡或在下拉菜单选择账号。");
  schedulePersistUiState();
}

function confirmMemberPointToggle(memberName, toCustomValue) {
  if (toCustomValue) {
    return window.confirm(`确认要修改「${memberName}」成员分吗？\n建议修改后及时保存账号，避免误操作丢失。`);
  }
  const hasAccountValue = hasBaseMemberPoint(memberName);
  if (hasAccountValue) {
    const accountValue = getBaseMemberPoint(memberName);
    return window.confirm(`确认要恢复「${memberName}」账号值吗？\n将回退为账号成员分：${nfmt(accountValue)}。`);
  }
  return window.confirm(
    `确认要恢复「${memberName}」账号值吗？\n当前未读取账号，回退后将使用默认成员分：${nfmt(getDefaultMemberPoint())}。`
  );
}

function confirmMemberPointZero(memberName, prevValue, nextValue) {
  if (nextValue !== 0) return true;
  if (prevValue === 0) return true;
  return window.confirm(`确认将「${memberName}」成员分设为 0 吗？`);
}

function getSceneCardTotal(card) {
  const basePower =
    Number(card?.power || 0) > 0
      ? Number(card.power || 0)
      : Number(card?.vo || 0) + Number(card?.da || 0) + Number(card?.pe || 0);
  const sceneSkill = Number(state.defaults?.scene_skill_per_card ?? 430) || 0;
  return Math.max(0, Math.round(basePower + sceneSkill));
}

function buildProfileSnapshot() {
  const currentGroupRaw = parseInt(String($("groupPower")?.value || ""), 10);
  const activeProfileGroup = state.activeProfile && state.profiles[state.activeProfile]
    ? parseInt(String(state.profiles[state.activeProfile].group_power || 0), 10) || 0
    : 0;
  const defaultGroup = parseInt(String(state.defaults?.group_power || 1800000), 10) || 1800000;
  const groupPower = Number.isFinite(currentGroupRaw) && currentGroupRaw > 0
    ? currentGroupRaw
    : (activeProfileGroup > 0 ? activeProfileGroup : defaultGroup);
  return {
    group_power: groupPower,
    member_points: getMemberPointsPayload(),
    owned_codes: [...state.ownedCodes],
    exclude_codes: [],
    saved_at: new Date().toISOString(),
  };
}

function normalizeProfileForDiff(profile) {
  const groupPower = Math.max(0, parseInt(String(profile?.group_power || 0), 10) || 0);
  const memberPoints = sanitizeMemberPointsMap(profile?.member_points || {});
  const ownedCodes = toUniqueStringArray(profile?.owned_codes || []).sort((a, b) => a.localeCompare(b, "ja"));
  return {
    group_power: groupPower,
    member_points: memberPoints,
    owned_codes: ownedCodes,
  };
}

function diffMemberPoints(beforeMap, afterMap) {
  const before = beforeMap && typeof beforeMap === "object" ? beforeMap : {};
  const after = afterMap && typeof afterMap === "object" ? afterMap : {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  let addedCount = 0;
  let removedCount = 0;
  let modifiedCount = 0;
  const sample = [];

  keys.forEach((name) => {
    const hasBefore = Object.prototype.hasOwnProperty.call(before, name);
    const hasAfter = Object.prototype.hasOwnProperty.call(after, name);
    const beforeVal = hasBefore ? Math.max(0, parseInt(String(before[name]), 10) || 0) : 0;
    const afterVal = hasAfter ? Math.max(0, parseInt(String(after[name]), 10) || 0) : 0;
    if (!hasBefore && hasAfter) {
      addedCount += 1;
      if (sample.length < 3) sample.push(`${name} +${nfmt(afterVal)}`);
      return;
    }
    if (hasBefore && !hasAfter) {
      removedCount += 1;
      if (sample.length < 3) sample.push(`${name} ${nfmt(beforeVal)}→删除`);
      return;
    }
    if (beforeVal !== afterVal) {
      modifiedCount += 1;
      if (sample.length < 3) sample.push(`${name} ${nfmt(beforeVal)}→${nfmt(afterVal)}`);
    }
  });

  return {
    changedCount: addedCount + removedCount + modifiedCount,
    addedCount,
    removedCount,
    modifiedCount,
    sample,
  };
}

function diffStringList(beforeList, afterList) {
  const beforeSet = new Set(toUniqueStringArray(beforeList));
  const afterSet = new Set(toUniqueStringArray(afterList));
  const added = [...afterSet].filter((x) => !beforeSet.has(x));
  const removed = [...beforeSet].filter((x) => !afterSet.has(x));
  return { added, removed };
}

function buildProfileSaveSummary(name, beforeProfile, afterProfile) {
  const before = normalizeProfileForDiff(beforeProfile || {});
  const after = normalizeProfileForDiff(afterProfile || {});
  const parts = [];

  if (before.group_power !== after.group_power) {
    parts.push(`group ${nfmt(before.group_power)}→${nfmt(after.group_power)}`);
  } else {
    parts.push(`group ${nfmt(after.group_power)}（未变）`);
  }

  const mpDiff = diffMemberPoints(before.member_points, after.member_points);
  const afterMemberCount = Object.keys(after.member_points).length;
  if (mpDiff.changedCount > 0) {
    let memberText = `成员分 ${afterMemberCount} 人（变更 ${mpDiff.changedCount}：新增${mpDiff.addedCount}/修改${mpDiff.modifiedCount}/删除${mpDiff.removedCount}）`;
    if (mpDiff.sample.length) {
      memberText += `，例如 ${mpDiff.sample.join("，")}`;
    }
    parts.push(memberText);
  } else {
    parts.push(`成员分 ${afterMemberCount} 人（未变）`);
  }

  const ownedDiff = diffStringList(before.owned_codes, after.owned_codes);
  if (ownedDiff.added.length || ownedDiff.removed.length) {
    parts.push(
      `持有卡 ${before.owned_codes.length}→${after.owned_codes.length}（新增${ownedDiff.added.length}/移除${ownedDiff.removed.length}）`
    );
  } else {
    parts.push(`持有卡 ${after.owned_codes.length} 张（未变）`);
  }

  return `已保存账号「${name}」：${parts.join("；")}。`;
}

async function fetchProfilesFromServer() {
  const resp = await fetch("/api/profiles");
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data?.detail || "读取账号失败");
  }
  const profiles = data?.profiles || {};
  if (!profiles || typeof profiles !== "object") return {};
  return profiles;
}

async function saveProfileToServer(name, snapshot) {
  const resp = await fetch("/api/profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      group_power: parseInt(String(snapshot?.group_power || 0), 10) || 0,
      member_points: snapshot?.member_points || {},
      owned_codes: Array.isArray(snapshot?.owned_codes) ? snapshot.owned_codes : [],
      exclude_codes: [],
    }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "保存账号失败");
  return data?.profile || {
    group_power: parseInt(String(snapshot?.group_power || 0), 10) || 0,
    member_points: snapshot?.member_points || {},
    owned_codes: Array.isArray(snapshot?.owned_codes) ? snapshot.owned_codes : [],
    exclude_codes: [],
  };
}

async function fetchProfileBackupsFromServer(name, limit = 30) {
  const key = String(name || "").trim();
  if (!key) throw new Error("账号名不能为空");
  const resp = await fetch(`/api/profiles/${encodeURIComponent(key)}/backups?limit=${Math.max(1, Math.min(80, limit))}`);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "读取备份失败");
  return Array.isArray(data?.backups) ? data.backups : [];
}

async function deleteProfileBackupFromServer(name, backupFile) {
  const key = String(name || "").trim();
  const file = String(backupFile || "").trim();
  if (!key) throw new Error("账号名不能为空");
  if (!file) throw new Error("备份文件不能为空");
  const resp = await fetch(
    `/api/profiles/${encodeURIComponent(key)}/backups/${encodeURIComponent(file)}`,
    { method: "DELETE" }
  );
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "删除备份失败");
  return data;
}

async function undoProfileFromServer(name, backupFile = "") {
  const key = String(name || "").trim();
  if (!key) throw new Error("账号名不能为空");
  const payload = {};
  const file = String(backupFile || "").trim();
  if (file) payload.backup_file = file;
  const resp = await fetch(`/api/profiles/${encodeURIComponent(key)}/undo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "撤回失败");
  return data;
}

async function exportProfilesFromServer(name = "") {
  const key = String(name || "").trim();
  const query = key ? `?name=${encodeURIComponent(key)}` : "";
  const resp = await fetch(`/api/profiles/export${query}`);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "导出失败");
  return data;
}

async function importProfilesToServer(payload) {
  const resp = await fetch("/api/profiles/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "导入失败");
  return data;
}

function normalizeDownloadFilePart(input, fallback = "profiles") {
  const text = String(input || "")
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  return text || fallback;
}

function makeTimestampTag() {
  const now = new Date();
  const pad = (v) => String(v).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function downloadJsonAsFile(fileName, data) {
  const content = `${JSON.stringify(data, null, 2)}\n`;
  const blob = new Blob([content], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function isExcludedModalOpen() {
  const modal = $("excludedModal");
  return Boolean(modal && !modal.classList.contains("hidden"));
}

function canonicalizeProfileSnapshot(profile) {
  const normalized = normalizeProfileForDiff(profile || {});
  const memberPoints = {};
  Object.keys(normalized.member_points)
    .sort((a, b) => a.localeCompare(b, "zh-Hans-CN"))
    .forEach((k) => {
      memberPoints[k] = Math.max(0, parseInt(String(normalized.member_points[k]), 10) || 0);
    });
  return {
    group_power: Math.max(0, parseInt(String(normalized.group_power || 0), 10) || 0),
    member_points: memberPoints,
    owned_codes: toUniqueStringArray(normalized.owned_codes || []).sort((a, b) => a.localeCompare(b, "ja")),
  };
}

function isProfileSnapshotSame(a, b) {
  const left = canonicalizeProfileSnapshot(a);
  const right = canonicalizeProfileSnapshot(b);
  return JSON.stringify(left) === JSON.stringify(right);
}

function buildAutoSaveSnapshotForProfile(name) {
  const profile = state.profiles[name];
  if (!profile) return null;
  const cardCodeSet = new Set(state.cards.map((c) => String(c.code || "").trim()).filter(Boolean));
  const source = buildProfileSnapshot();
  return {
    group_power: parseInt(String(source.group_power || profile.group_power || 1800000), 10) || 1800000,
    member_points: sanitizeMemberPointsMap(source.member_points || {}),
    owned_codes: toUniqueStringArray(source.owned_codes || []).filter((code) => cardCodeSet.has(code)),
    exclude_codes: [],
  };
}

function updateProfileAutoSaveButton() {
  const btn = $("toggleProfileAutoSaveBtn");
  if (!btn) return;
  const on = Boolean(state.profileAutoSaveEnabled);
  btn.textContent = on ? "自动保存：开" : "自动保存：关";
  btn.classList.toggle("off", !on);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
}

function setProfileActionDrawerOpen(open) {
  const drawer = $("profileActionDrawer");
  const toggle = $("profileActionDrawerToggle");
  const menu = $("profileActionDrawerMenu");
  if (!drawer || !toggle || !menu) return;
  const on = Boolean(open);
  drawer.classList.toggle("open", on);
  toggle.setAttribute("aria-expanded", on ? "true" : "false");
  menu.classList.toggle("hidden", !on);
}

function closeProfileActionDrawer() {
  setProfileActionDrawerOpen(false);
}

function clearActiveProfileAutoSaveTimer() {
  if (!profileAutoSaveTimer) return;
  window.clearTimeout(profileAutoSaveTimer);
  profileAutoSaveTimer = null;
}

async function flushActiveProfileAutoSave() {
  const name = String(profileAutoSaveTarget || state.activeProfile || "").trim();
  if (!name || !state.profiles[name] || !state.profileAutoSaveEnabled) return;
  if (profileAutoSaveInFlight) {
    profileAutoSavePending = true;
    return;
  }
  const snapshot = buildAutoSaveSnapshotForProfile(name);
  if (!snapshot) return;
  if (isProfileSnapshotSame(snapshot, state.profiles[name])) {
    if (profileAutoSaveTarget === name) profileAutoSaveTarget = "";
    return;
  }
  profileAutoSaveInFlight = true;
  try {
    const saved = await saveProfileToServer(name, snapshot);
    state.profiles[name] = saved;
    if (state.activeProfile === name) {
      setProfileHint(`账号「${name}」已自动保存。`);
    }
    schedulePersistUiState();
  } catch (err) {
    if (state.activeProfile === name) {
      setProfileHint(`账号「${name}」自动保存失败：${err?.message || err}`);
    }
  } finally {
    profileAutoSaveInFlight = false;
    if (profileAutoSavePending) {
      profileAutoSavePending = false;
      void flushActiveProfileAutoSave();
    } else if (profileAutoSaveTarget === name) {
      profileAutoSaveTarget = "";
    }
  }
}

function scheduleActiveProfileAutoSave(reason = "") {
  const profileName = String(state.activeProfile || "").trim();
  if (!profileName || !state.profiles[profileName]) return;
  if (!state.profileAutoSaveEnabled) {
    if (reason) {
      setProfileHint(`账号「${profileName}」${reason}，自动保存已关闭，请点击“保存账号”。`);
    }
    return;
  }
  profileAutoSaveTarget = profileName;
  clearActiveProfileAutoSaveTimer();
  profileAutoSaveTimer = window.setTimeout(() => {
    profileAutoSaveTimer = null;
    void flushActiveProfileAutoSave();
  }, 420);
}

function setProfileAutoSaveEnabled(on) {
  const next = Boolean(on);
  state.profileAutoSaveEnabled = next;
  updateProfileAutoSaveButton();
  if (!next) {
    clearActiveProfileAutoSaveTimer();
    const profileName = String(state.activeProfile || "").trim();
    if (profileName) {
      setProfileHint(`账号「${profileName}」已关闭自动保存，请记得点击“保存账号”。`);
    }
  } else {
    const profileName = String(state.activeProfile || "").trim();
    if (profileName) {
      setProfileHint(`账号「${profileName}」已开启自动保存。`);
      scheduleActiveProfileAutoSave("当前修改");
    }
  }
  schedulePersistUiState();
}

async function deleteProfileFromServer(name) {
  const resp = await fetch(`/api/profiles/${encodeURIComponent(name)}`, { method: "DELETE" });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "删除账号失败");
  return Boolean(data?.ok);
}

function renderProfileOptions() {
  const sel = $("profileSelect");
  if (!sel) return;
  const names = Object.keys(state.profiles).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  sel.innerHTML = `<option value="">${FAIR_BASELINE_LABEL}</option>` + names.map((n) => `<option value="${escHtml(n)}">${escHtml(n)}</option>`).join("");
  if (state.activeProfile && state.profiles[state.activeProfile]) {
    sel.value = state.activeProfile;
  } else {
    sel.value = "";
    state.activeProfile = "";
  }
}

function setProfileHint(text) {
  const el = $("profileHint");
  if (el) el.textContent = text;
}

function getSelectedProfileName() {
  return String($("profileSelect")?.value || state.activeProfile || "").trim();
}

function cloneProfileSnapshot(profile) {
  if (!profile || typeof profile !== "object") return null;
  return {
    group_power: parseInt(String(profile.group_power || 0), 10) || 0,
    member_points: sanitizeMemberPointsMap(profile.member_points || {}),
    owned_codes: toUniqueStringArray(profile.owned_codes || []),
    exclude_codes: toUniqueStringArray(profile.exclude_codes || []),
  };
}

function applyProfile(name, refreshUI = true) {
  const profile = state.profiles[name];
  if (!profile) return false;
  const cardSet = new Set(state.cards.map((c) => String(c.code || "").trim()).filter(Boolean));
  const profileOwned = toUniqueStringArray(profile.owned_codes).filter((code) => cardSet.has(code));
  const profilePoints = sanitizeMemberPointsMap(profile.member_points || {});
  const profilePointCount = Object.keys(profilePoints).length;
  const fallbackDefaults = sanitizeMemberPointsMap(state.defaults?.member_points || {});
  const useFallbackDefaults = profilePointCount === 0 && Object.keys(fallbackDefaults).length > 0;
  const effectivePoints = useFallbackDefaults ? { ...fallbackDefaults } : { ...profilePoints };

  state.activeProfile = name;
  $("groupPower").value = String(profile.group_power || 1800000);
  const poolScopeEl = $("optPoolScope");
  if (poolScopeEl) poolScopeEl.value = "owned";
  state.defaultMemberPoint = DEFAULT_MEMBER_POINT;
  state.memberPoints = { ...effectivePoints };
  state.baseMemberPoints = { ...effectivePoints };
  state.memberPointOverrides.clear();
  state.ownedCodes = new Set(profileOwned);
  state.excludedCodes.clear();
  state.centerCandidateCodes = new Set([...state.centerCandidateCodes]);
  state.mustIncludeCodes = new Set([...state.mustIncludeCodes]);
  if (useFallbackDefaults) {
    // Keep profile in-memory baseline non-empty to avoid accidental overwrite
    // from follow-up auto-sync flows (owned pool updates).
    profile.member_points = { ...effectivePoints };
  }
  if (refreshUI) {
    renderSlots();
    renderCardList();
    refreshPoolSummary();
    refreshResultExcludeBadges();
  }
  setProfileHint(
    useFallbackDefaults
      ? `已加载账号「${name}」：group=${nfmt(profile.group_power || 0)}，成员分为空，已自动套用默认成员分 ${Object.keys(effectivePoints).length} 人。`
      : `已加载账号「${name}」：group=${nfmt(profile.group_power || 0)}，成员分 ${Object.keys(effectivePoints).length} 人，持有 ${profileOwned.length} 张。`
  );
  schedulePersistUiState();
  return true;
}

function saveProfile(name) {
  const key = String(name || "").trim();
  if (!key) throw new Error("账号名不能为空");
  return key;
}

async function saveCurrentToExistingProfile(name) {
  const key = saveProfile(name);
  const beforeProfile = cloneProfileSnapshot(state.profiles[key]);
  const saved = await saveProfileToServer(key, buildProfileSnapshot());
  state.profiles[key] = saved;
  renderProfileOptions();
  applyProfile(key);
  $("profileSelect").value = key;
  scheduleWorkspacePanelHeightSync();
  setProfileHint(buildProfileSaveSummary(key, beforeProfile, saved));
  schedulePersistUiState();
}

async function deleteProfile(name) {
  const key = String(name || "").trim();
  if (!key || !state.profiles[key]) return;
  await deleteProfileFromServer(key);
  delete state.profiles[key];
  if (state.activeProfile === key) state.activeProfile = "";
  renderProfileOptions();
  setProfileHint(`已删除账号「${key}」。`);
  schedulePersistUiState();
}

async function reloadProfilesFromServer(preferredName = "") {
  const targetName = String(preferredName || "").trim();
  const previousActive = String(state.activeProfile || "").trim();
  state.profiles = await fetchProfilesFromServer();
  renderProfileOptions();

  if (targetName && state.profiles[targetName]) {
    applyProfile(targetName);
    $("profileSelect").value = targetName;
    return targetName;
  }
  if (previousActive && state.profiles[previousActive]) {
    applyProfile(previousActive);
    $("profileSelect").value = previousActive;
    return previousActive;
  }
  const names = Object.keys(state.profiles).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  if (names.length > 0) {
    const first = names[0];
    applyProfile(first);
    $("profileSelect").value = first;
    return first;
  }
  applyDefaultBaseline();
  $("profileSelect").value = "";
  return "";
}

function formatBackupTimeLabel(raw) {
  const text = String(raw || "").trim();
  if (!text) return "-";
  const compact = text.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/);
  if (compact) {
    const [, y, m, d, hh, mm, ss] = compact;
    return `${y}/${Number(m)}/${Number(d)} ${hh}:${mm}:${ss}`;
  }
  const dt = new Date(text);
  if (!Number.isFinite(dt.getTime())) return text;
  return dt.toLocaleString("zh-CN", { hour12: false });
}

function closeProfileBackupsModal() {
  const modal = $("profileBackupsModal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
}

function renderProfileBackupsModal(name, backups) {
  const hint = $("profileBackupsHint");
  const list = $("profileBackupsList");
  if (!hint || !list) return;
  const rows = Array.isArray(backups) ? backups : [];
  state.profileBackups = rows;
  state.profileBackupsName = String(name || "").trim();
  if (!rows.length) {
    hint.textContent = `账号「${name}」暂无可用备份。`;
    list.innerHTML = `<div class="card-meta">当前没有备份记录。</div>`;
    return;
  }
  hint.textContent = `账号「${name}」共有 ${rows.length} 条备份记录。`;
  list.innerHTML = rows
    .map((row) => {
      const file = String(row?.backup_file || "").trim();
      const backupCreated = formatBackupTimeLabel(row?.backup_created_at || "");
      const profileSavedAt = formatBackupTimeLabel(row?.profile_saved_at || "");
      const groupPower = nfmt(Number(row?.group_power || 0));
      const memberCount = Number(row?.member_point_count || 0);
      const ownedCount = Number(row?.owned_count || 0);
      return `
        <article class="profile-backup-item">
          <div class="profile-backup-main">
            <div class="profile-backup-title">备份时间: ${escHtml(backupCreated)}</div>
            <div class="profile-backup-meta">账号快照时间: ${escHtml(profileSavedAt)}</div>
            <div class="profile-backup-meta">group ${groupPower} | 成员分 ${memberCount} 人 | 持有 ${ownedCount} 张</div>
          </div>
          <div class="profile-backup-actions">
            <button type="button" class="btn-sub tiny" data-restore-profile-backup="${escHtml(file)}">恢复到此备份</button>
            <button type="button" class="btn-sub tiny danger" data-delete-profile-backup="${escHtml(file)}">删除备份</button>
          </div>
        </article>
      `;
    })
    .join("");
}

async function openProfileBackupsModal() {
  const key = getSelectedProfileName();
  if (!key || !state.profiles[key]) {
    setProfileHint("请先选择账号。");
    return;
  }
  const modal = $("profileBackupsModal");
  if (!modal) return;
  const hint = $("profileBackupsHint");
  const list = $("profileBackupsList");
  if (hint) hint.textContent = "读取中...";
  if (list) list.innerHTML = "";
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  try {
    const backups = await fetchProfileBackupsFromServer(key, 40);
    renderProfileBackupsModal(key, backups);
  } catch (err) {
    if (hint) hint.textContent = `读取失败：${err?.message || err}`;
    if (list) list.innerHTML = "";
  }
}

async function restoreProfileByBackup(name, backupFile = "") {
  const key = String(name || "").trim();
  if (!key || !state.profiles[key]) throw new Error("账号不存在");
  const data = await undoProfileFromServer(key, backupFile);
  const restored = data?.profile || null;
  if (!restored || typeof restored !== "object") throw new Error("恢复结果无效");
  state.profiles[key] = restored;
  renderProfileOptions();
  applyProfile(key);
  $("profileSelect").value = key;
  scheduleWorkspacePanelHeightSync();
  setProfileHint(`已恢复账号「${key}」到备份。`);
  schedulePersistUiState();
}

function makeSongLabel(song) {
  const colorCode = String(song?.color || "").toUpperCase();
  const colorLabel = COLOR_FULL_LABEL[colorCode] || colorCode || "All";
  return `[${colorLabel}] ${song.name} (Lv.${song.level})`;
}

function parseAxes(raw) {
  return String(raw || "")
    .split(",")
    .map((x) => x.trim().toLowerCase())
    .filter(Boolean);
}

function getCardByCode(code) {
  const key = String(code || "").trim();
  if (!key) return null;
  return state.cardsByCode.get(key) || null;
}

function buildCardSearchBlob(card) {
  return [
    card?.code,
    card?.member_name,
    card?.member_name_roman || "",
    card?.member_name_kana || "",
    card?.title,
    card?.color,
  ]
    .join(" ")
    .toLowerCase();
}

function computeCardSeriesTags(card) {
  const tags = Array.isArray(card?.tags) ? card.tags : [];
  const list = tags.filter((t) => t && t !== "V/S");
  const titleRaw = String(card?.title || "");
  const isPreciousPair = /precious\s*-\s*pair/i.test(titleRaw);
  const isPreciousPair23 = /precious\s*-\s*pair\s*-\s*'?23/i.test(titleRaw);
  if (isPreciousPair) {
    list.push(PRECIOUS_PAIR_SERIES_TAG);
  }
  if (isPreciousPair23) {
    list.push(PRECIOUS_PAIR_23_SERIES_TAG);
  }
  return [...new Set(list)];
}

function prepareCardForUi(cardLike) {
  if (!cardLike || typeof cardLike !== "object") return cardLike;
  cardLike._search_blob = buildCardSearchBlob(cardLike);
  cardLike._series_tags_cached = computeCardSeriesTags(cardLike);
  return cardLike;
}

function scheduleRenderCardList() {
  if (renderCardListRaf) window.cancelAnimationFrame(renderCardListRaf);
  renderCardListRaf = window.requestAnimationFrame(() => {
    renderCardListRaf = null;
    renderCardList();
  });
}

function escHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function stripGameTags(text) {
  return String(text || "")
    .replace(/\r?\n/g, " ")
    .replace(/<br\s*\/?>/gi, " / ")
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function syncWorkspacePanelHeight() {
  const leftPanel = document.querySelector(".workspace-shell .workspace-left");
  const rightPanel = document.querySelector(".workspace-shell .workspace-right-panel");
  if (!leftPanel || !rightPanel) return;

  // In stacked layout, keep natural flow and avoid forcing fixed heights.
  if (window.matchMedia("(max-width: 1180px)").matches) {
    rightPanel.style.height = "";
    return;
  }

  const leftHeight = Math.ceil(leftPanel.getBoundingClientRect().height);
  if (!Number.isFinite(leftHeight) || leftHeight <= 0) return;
  rightPanel.style.height = `${leftHeight}px`;
}

function scheduleWorkspacePanelHeightSync() {
  if (workspaceSyncTimer) window.cancelAnimationFrame(workspaceSyncTimer);
  workspaceSyncTimer = window.requestAnimationFrame(() => {
    syncWorkspacePanelHeight();
    workspaceSyncTimer = null;
  });
}

function syncTopbarOffset() {
  const topbar = document.querySelector(".app-topbar");
  if (!topbar) return;
  const pos = window.getComputedStyle(topbar).position;
  if (pos !== "fixed" && pos !== "sticky") {
    document.documentElement.style.setProperty("--topbar-offset", "0px");
    return;
  }
  const rect = topbar.getBoundingClientRect();
  if (!Number.isFinite(rect.height) || rect.height <= 0) return;
  const topInset = Math.max(0, rect.top);
  const offset = Math.ceil(rect.height + topInset + 12);
  document.documentElement.style.setProperty("--topbar-offset", `${offset}px`);
}

function shortText(text, max = 82) {
  const raw = stripGameTags(text);
  if (!raw) return "-";
  return raw.length > max ? `${raw.slice(0, max - 1)}…` : raw;
}

function formatGameText(text) {
  const raw = String(text || "").replace(/\r?\n/g, " ").replace(/<br\s*\/?>/gi, " / ");
  if (!raw.trim()) return "-";
  const colorRe = /<color=(#[0-9a-fA-F]{6})>([\s\S]*?)<\/color>/gi;
  let out = "";
  let last = 0;
  let match;
  while ((match = colorRe.exec(raw)) !== null) {
    const prefix = raw.slice(last, match.index).replace(/<[^>]+>/g, "");
    out += escHtml(prefix);
    const coloredWord = String(match[2] || "").replace(/<[^>]+>/g, "");
    out += `<span class="color-word" style="color:${match[1]}">${escHtml(coloredWord)}</span>`;
    last = colorRe.lastIndex;
  }
  out += escHtml(raw.slice(last).replace(/<[^>]+>/g, ""));
  out = out.replace(/\s+/g, " ").trim();
  return out || "-";
}

function numOrDash(v, digits = 2) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : "-";
}

function parseSkillBucketSValue(bucketLike) {
  const bucket = String(bucketLike || "").trim();
  if (!bucket) return null;
  const sMatch = bucket.match(/^(\d+(?:\.\d+)?)s$/i);
  if (sMatch) return Number(sMatch[1]);
  const parenMatch = bucket.match(/^(\d+(?:\.\d+)?)%?\(s\)$/i);
  if (parenMatch) return Number(parenMatch[1]);
  return null;
}

function formatSkillBucketChipLabel(bucketLike) {
  const sValue = parseSkillBucketSValue(bucketLike);
  if (Number.isFinite(sValue)) return `${sValue.toFixed(2)}%(S)`;
  const n = Number(bucketLike);
  return Number.isFinite(n) ? n.toFixed(2) : String(bucketLike || "");
}

function getSkillExpectedLabel(cardLike) {
  const card = cardLike || {};
  const bucket = String(card.skill_bucket || "").trim();
  if (bucket) {
    const sValue = parseSkillBucketSValue(bucket);
    if (Number.isFinite(sValue)) return `${sValue.toFixed(2)}%(S)`;
    const n = Number(bucket);
    return Number.isFinite(n) ? `${n.toFixed(2)}%` : bucket;
  }
  const tuple = String(card.skill_front_tuple || card.front_tuple_base || card.front_tuple || "").trim();
  const numeric = numOrDash(card.skill_expected, 2);
  if (numeric === "-") return "-";
  if (tuple === "8-16.0-7-30.0-0.0") return `${numeric}%(S)`;
  return `${numeric}%`;
}

function memberPointSummaryHTML(rows, limit = 5) {
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) return "-";
  const head = list.slice(0, limit);
  const text = head
    .map((r) => {
      const name = `${r.member_name || "-"}[${r.title || "-"}]`;
      const cardPoint = Number(r.scene_card_total ?? r.scene_raw_total ?? 0);
      return `${name} ${nfmt(cardPoint)} + ${nfmt(r.member_point || 0)} = ${nfmt(r.scene_plus_member || 0)}`;
    })
    .join(" / ");
  if (list.length > limit) {
    return `${escHtml(text)} / …(${list.length}人)`;
  }
  return escHtml(text);
}

function getLeaderTypeWords(card) {
  const text = String(card?.leader_desc || "").toUpperCase();
  const found = [];
  ["RED", "BLUE", "GREEN", "YELLOW", "PURPLE"].forEach((w) => {
    if (text.includes(w)) found.push(w);
  });
  return found.slice(0, 3);
}

function colorByWord(word) {
  if (word === "RED") return "R";
  if (word === "BLUE") return "B";
  if (word === "GREEN") return "G";
  if (word === "YELLOW") return "Y";
  return "P";
}

function typePillsHTML(card) {
  const words = getLeaderTypeWords(card);
  if (!words.length) {
    return `<span class="type-pill ${colorClass(card.color)}">${COLOR_LONG[colorClass(card.color)] || card.color}</span>`;
  }
  return words
    .map((w) => `<span class="type-pill ${colorByWord(w)}">${w}</span>`)
    .join("");
}

function cardAvatarHTML(card, size = "md") {
  if (!card) return `<span class="card-avatar ${size} fallback"><span class="fallback-label">?</span></span>`;
  const color = colorClass(card.color);
  const alt = escHtml(`${card.member_name}[${card.title}]`);
  const fallbackText = "无图";
  const iconApi = String(card.icon_url || "").trim();
  const iconCatalog = String(card.icon_catalog_url || "").trim();
  const iconFallback = String(card.icon_fallback_url || "").trim();
  // `icon_catalog_url` may point to bundle bytes; prefer browser-displayable fallback URL first.
  const iconCandidates = [iconFallback, iconApi, iconCatalog].filter(Boolean).filter((x, i, arr) => arr.indexOf(x) === i);
  const iconSrc = iconCandidates[0] || "";
  const iconBackup = iconCandidates[1] || "";
  const loadingMode = size === "lg" ? "auto" : "eager";
  const fetchPriority = size === "sm" ? "high" : "auto";
  if (!iconSrc) {
    return `<span class="card-avatar ${size} fallback ${color}" title="icon unavailable"><span class="fallback-label">${fallbackText}</span></span>`;
  }
  return `
    <span class="card-avatar ${size} ${color}">
      <img src="${escHtml(iconSrc)}" alt="${alt}" loading="${loadingMode}" decoding="async" fetchpriority="${fetchPriority}" referrerpolicy="no-referrer" data-fallback-src="${escHtml(iconBackup)}"
        onerror="if(!this.dataset.fallbackTried&&this.dataset.fallbackSrc){this.dataset.fallbackTried='1';this.src=this.dataset.fallbackSrc;return;} this.parentElement.classList.add('fallback'); this.remove();" />
      <span class="fallback-label">${fallbackText}</span>
    </span>
  `;
}

function isCenterEligible(code) {
  const c = getCardByCode(code);
  return isVsCenterCard(c);
}

function setOwned(code, on) {
  if (!code) return;
  const prevOwned = state.ownedCodes.has(code);
  if (on) {
    state.ownedCodes.add(code);
  } else {
    state.ownedCodes.delete(code);
    state.centerCandidateCodes.delete(code);
    state.mustIncludeCodes.delete(code);
  }
  const changed = prevOwned !== state.ownedCodes.has(code);
  if (changed && state.activeProfile) {
    scheduleActiveProfileAutoSave("持有卡池已修改");
  }
  schedulePersistUiState();
}

function refreshPoolSummary() {
  const scope = $("optPoolScope")?.value || "all";
  const scopeLabel = scope === "owned" ? "仅持有" : "全卡池";
  const listScope = $("cardListScope")?.value || "all";
  const listScopeLabel = listScope === "owned" ? "仅持有" : "全卡池";
  const ownedNode = $("ownedSummary");
  if (ownedNode) {
    ownedNode.textContent = `持有卡池: ${state.ownedCodes.size} 张 | ${listScopeLabel}`;
  }
  const centerText = state.centerCandidateCodes.size
    ? `队长候选: ${state.centerCandidateCodes.size}`
    : "队长候选: 自动";
  const mustCount = state.mustIncludeCodes.size;
  const mustHint = mustCount === 5 ? "必带=5(固定5卡自动枚举队长)" : `必带: ${mustCount}`;
  const profileText = state.activeProfile ? `账号: ${state.activeProfile}` : "账号: 默认";
  const profileGroup = state.activeProfile && state.profiles[state.activeProfile]
    ? Math.max(0, parseInt(String(state.profiles[state.activeProfile].group_power || 0), 10) || 0)
    : Math.max(0, parseInt(String($("groupPower")?.value || 0), 10) || 0);
  const groupText = `group: ${nfmt(profileGroup)}`;
  $("optSummary").textContent = `${centerText} | ${mustHint} | ${profileText} | ${groupText} | 卡池: ${scopeLabel}`;
}

function syncOwnedPoolVisibility() {
  // Owned pool visibility is now fully represented by optPoolScope/cardListScope controls.
  // Keep this as a no-op to avoid breaking older call sites.
  return;
}

function getCardSeriesTags(card) {
  if (!card || typeof card !== "object") return [];
  if (Array.isArray(card._series_tags_cached)) return card._series_tags_cached;
  const tags = computeCardSeriesTags(card);
  card._series_tags_cached = tags;
  return tags;
}

function renderSeriesTags() {
  const root = $("qSeriesTags");
  if (!root) return;
  const set = new Set();
  state.cards.forEach((c) => getCardSeriesTags(c).forEach((x) => set.add(x)));
  const order = ["S.teller", "Véaut", PRECIOUS_PAIR_SERIES_TAG, PRECIOUS_PAIR_23_SERIES_TAG];
  const series = [...set].sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    if (ia >= 0 || ib >= 0) {
      if (ia < 0) return 1;
      if (ib < 0) return -1;
      return ia - ib;
    }
    return String(a).localeCompare(String(b), "ja");
  });
  const allActive = state.selectedSeries.size === 0;
  root.innerHTML =
    `<button type="button" class="skill-chip ${allActive ? "active" : ""}" data-series="__all__">全部系列</button>` +
    series
      .map((x) => `<button type="button" class="skill-chip ${state.selectedSeries.has(x) ? "active" : ""}" data-series="${escHtml(x)}">${escHtml(x)}</button>`)
      .join("");
  root.querySelectorAll("button[data-series]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-series") || "";
      if (!key || key === "__all__") {
        state.selectedSeries.clear();
      } else if (state.selectedSeries.has(key)) {
        state.selectedSeries.delete(key);
      } else {
        state.selectedSeries.add(key);
      }
      renderSeriesTags();
      renderCardList();
    });
  });
}

function renderColorTags() {
  const root = $("qColorTags");
  if (!root) return;
  const allActive = state.selectedColors.size === 0;
  root.innerHTML =
    `<button type="button" class="skill-chip ${allActive ? "active" : ""}" data-color="__all__">全部颜色</button>` +
    COLOR_FILTER_OPTIONS.map((x) => {
      const active = state.selectedColors.has(x.key);
      return `<button type="button" class="skill-chip ${active ? "active" : ""}" data-color="${x.key}">${x.label}</button>`;
    }).join("");
  root.querySelectorAll("button[data-color]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-color") || "";
      if (!key || key === "__all__") {
        state.selectedColors.clear();
      } else if (state.selectedColors.has(key)) {
        state.selectedColors.delete(key);
      } else {
        state.selectedColors.add(key);
      }
      renderColorTags();
      renderCardList();
    });
  });
}

function renderGroupTags() {
  const root = $("qGroupTags");
  if (!root) return;
  const allActive = state.selectedGroups.size === 0;
  root.innerHTML =
    `<button type="button" class="skill-chip ${allActive ? "active" : ""}" data-group="__all__">全部团体</button>` +
    GROUP_FILTER_OPTIONS.map((x) => {
      const active = state.selectedGroups.has(x.key);
      return `<button type="button" class="skill-chip ${active ? "active" : ""}" data-group="${x.key}">${x.label}</button>`;
    }).join("");
  root.querySelectorAll("button[data-group]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-group") || "";
      if (!key || key === "__all__") {
        state.selectedGroups.clear();
      } else if (state.selectedGroups.has(key)) {
        state.selectedGroups.delete(key);
      } else {
        state.selectedGroups.add(key);
      }
      renderGroupTags();
      renderMemberPicker();
      renderCardList();
    });
  });
}

function renderSortTags() {
  const root = $("qSortTags");
  if (!root) return;
  const allActive = state.selectedSortKeys.size === 0;
  root.innerHTML =
    `<button type="button" class="skill-chip ${allActive ? "active" : ""}" data-sort="__all__">默认排序</button>` +
    SORT_FILTER_OPTIONS.map((x) => {
      const active = state.selectedSortKeys.has(x.key);
      return `<button type="button" class="skill-chip ${active ? "active" : ""}" data-sort="${x.key}">${x.label}</button>`;
    }).join("");
  root.querySelectorAll("button[data-sort]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-sort") || "";
      if (!key || key === "__all__") {
        state.selectedSortKeys.clear();
      } else if (state.selectedSortKeys.has(key)) {
        state.selectedSortKeys.delete(key);
      } else {
        state.selectedSortKeys.add(key);
      }
      renderSortTags();
      renderCardList();
    });
  });
}

function initMembersFilter() {
  const byMember = new Map();
  state.cards.forEach((c) => {
    const memberKey = String(c.member_name_norm || c.member_name || "").trim();
    if (!memberKey) return;
    const prev = byMember.get(memberKey);
    const next = {
      name: c.member_name,
      name_norm: memberKey,
      roman: c.member_name_roman || "",
      kana: c.member_name_kana || "",
      group_key: c.member_group_key || null,
      group_label: c.member_group_label || null,
      generation_no: Number(c.member_generation_no || 0) || null,
      generation_label: c.member_generation_label || null,
      generation_member_order: Number(c.member_generation_member_order || 0) || 0,
      group_generation_key: c.member_group_generation_key || null,
    };
    if (!prev) {
      byMember.set(memberKey, next);
      return;
    }
    if (!prev.roman && next.roman) prev.roman = next.roman;
    if (!prev.kana && next.kana) prev.kana = next.kana;
    if (!prev.group_key && next.group_key) prev.group_key = next.group_key;
    if (!prev.group_label && next.group_label) prev.group_label = next.group_label;
    if (!prev.generation_no && next.generation_no) prev.generation_no = next.generation_no;
    if (!prev.generation_label && next.generation_label) prev.generation_label = next.generation_label;
    if (!prev.generation_member_order && next.generation_member_order) {
      prev.generation_member_order = next.generation_member_order;
    }
  });
  const groupOrder = { sakura: 1, hinata: 2 };
  const members = [...byMember.values()].sort((a, b) => {
    const ga = groupOrder[a.group_key] || 9;
    const gb = groupOrder[b.group_key] || 9;
    if (ga !== gb) return ga - gb;
    const gna = Number(a.generation_no || 0) || 99;
    const gnb = Number(b.generation_no || 0) || 99;
    if (gna !== gnb) return gna - gnb;
    const oa = Number(a.generation_member_order || 0) || 999;
    const ob = Number(b.generation_member_order || 0) || 999;
    if (oa !== ob) return oa - ob;
    return String(a.name || "").localeCompare(String(b.name || ""));
  });

  state.memberCatalog = members;
  renderMemberPicker();
}

function renderMemberPicker() {
  const root = $("memberPicker");
  if (!root) return;
  const list = state.memberCatalog.filter((m) =>
    state.selectedGroups.size > 0 ? state.selectedGroups.has(m.group_key) : true
  );
  if (!list.length) {
    root.innerHTML = `<div class="card-meta">当前筛选下无成员</div>`;
    return;
  }

  const groups = [];
  const byGroup = new Map();
  list.forEach((m) => {
    const gk = m.group_key || "other";
    if (!byGroup.has(gk)) {
      const fallbackGroup = gk === "sakura" ? "櫻坂46成员" : gk === "hinata" ? "日向坂46成员" : "其他成员";
      byGroup.set(gk, {
        key: gk,
        label: m.group_label ? `${m.group_label}成员` : fallbackGroup,
        gens: new Map(),
      });
      groups.push(gk);
    }
    const g = byGroup.get(gk);
    const genNo = Number(m.generation_no || 0) || 0;
    const genKey = m.group_generation_key || `${gk}|0`;
    if (!g.gens.has(genKey)) {
      const genLabel = genNo > 0 ? `${genNo}期生` : UNGROUPED_GENERATION_LABEL;
      g.gens.set(genKey, {
        key: genKey,
        no: genNo || 99,
        label: m.generation_label || genLabel,
        members: [],
      });
    }
    g.gens.get(genKey).members.push(m);
  });

  const groupOrder = { sakura: 1, hinata: 2, other: 9 };
  groups.sort((a, b) => (groupOrder[a] || 9) - (groupOrder[b] || 9));

  root.innerHTML = groups
    .map((gk) => {
      const g = byGroup.get(gk);
      const genList = [...g.gens.values()].sort((a, b) => Number(a.no) - Number(b.no));
      return `
        <section class="member-group-block">
          <h4>${escHtml(g.label)}</h4>
          ${genList
            .map((gen) => {
              const chips = gen.members
                .sort((a, b) => {
                  const oa = Number(a.generation_member_order || 0) || 999;
                  const ob = Number(b.generation_member_order || 0) || 999;
                  if (oa !== ob) return oa - ob;
                  return String(a.name || "").localeCompare(String(b.name || ""));
                })
                .map((m) => {
                  const active = state.selectedMembers.has(m.name_norm);
                  const title = [m.roman, m.kana].filter(Boolean).join(" / ");
                  return `<button type="button" class="member-chip ${active ? "active" : ""}" data-member="${escHtml(m.name_norm)}" title="${escHtml(title)}">${escHtml(m.name)}</button>`;
                })
                .join("");
              return `
                <div class="member-gen-block">
                  <div class="member-gen-title">${escHtml(gen.label)}</div>
                  <div class="member-chip-grid">${chips}</div>
                </div>
              `;
            })
            .join("")}
        </section>
      `;
    })
    .join("");

  root.querySelectorAll("button[data-member]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const member = btn.getAttribute("data-member") || "";
      if (!member) return;
      if (state.selectedMembers.has(member)) state.selectedMembers.delete(member);
      else state.selectedMembers.add(member);
      renderMemberPicker();
      renderCardList();
    });
  });

  scheduleWorkspacePanelHeightSync();
}

function renderProfileBuilderInputs() {
  const root = $("builderMemberPoints");
  if (!root) return;
  const catalog = [...(state.memberCatalog || [])];
  if (!catalog.length) {
    root.innerHTML = `<div class="card-meta">成员数据未加载</div>`;
    return;
  }
  const groupOrder = { sakura: 1, hinata: 2, other: 9 };
  const grouped = new Map();
  catalog.forEach((m) => {
    const gk = m.group_key || "other";
    if (!grouped.has(gk)) {
      grouped.set(gk, {
        label: m.group_label ? `${m.group_label}成员` : gk === "sakura" ? "櫻坂46成员" : gk === "hinata" ? "日向坂46成员" : "其他成员",
        gens: new Map(),
      });
    }
    const grp = grouped.get(gk);
    const genNo = Number(m.generation_no || 0) || 99;
    const genKey = `${genNo}|${m.generation_label || ""}`;
    if (!grp.gens.has(genKey)) {
      grp.gens.set(genKey, {
        no: genNo,
        label: m.generation_label || (genNo < 90 ? `${genNo}期生` : UNGROUPED_GENERATION_LABEL),
        members: [],
      });
    }
    grp.gens.get(genKey).members.push(m);
  });

  const html = [...grouped.entries()]
    .sort((a, b) => (groupOrder[a[0]] || 9) - (groupOrder[b[0]] || 9))
    .map(([_, g]) => {
      const genHtml = [...g.gens.values()]
        .sort((a, b) => a.no - b.no)
        .map((gen) => {
          const rows = gen.members
            .sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), "ja"))
            .map((m) => {
              return `
                <label class="builder-point-row">
                  <span>${escHtml(m.name)}</span>
                  <input type="number" min="0" step="1" placeholder="0" data-builder-member="${escHtml(m.name)}" value="" />
                </label>
              `;
            })
            .join("");
          return `<section class="builder-gen"><h5>${escHtml(gen.label)}</h5><div class="builder-point-grid">${rows}</div></section>`;
        })
        .join("");
      return `<section class="builder-group"><h4>${escHtml(g.label)}</h4>${genHtml}</section>`;
    })
    .join("");

  root.innerHTML = html;
}

function openProfileBuilderModal() {
  const modal = $("profileBuilderModal");
  if (!modal) return;
  const nameInput = $("builderProfileName");
  const groupInput = $("builderGroupPower");
  nameInput.value = "";
  groupInput.value = "";
  groupInput.placeholder = "0";
  renderProfileBuilderInputs();
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  nameInput.focus();
}

function closeProfileBuilderModal() {
  const modal = $("profileBuilderModal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
}

async function saveProfileFromBuilder() {
  const name = String($("builderProfileName").value || "").trim();
  if (!name) {
    setProfileHint("新建账号失败：账号名不能为空");
    return;
  }
  const groupPower = Math.max(0, parseInt(String($("builderGroupPower").value || "0"), 10) || 0);
  const points = {};
  document.querySelectorAll("input[data-builder-member]").forEach((inp) => {
    const member = String(inp.getAttribute("data-builder-member") || "").trim();
    if (!member) return;
    const raw = String(inp.value || "").trim();
    const value = raw ? Math.max(0, parseInt(raw, 10) || 0) : 0;
    points[member] = value;
  });
  const saved = await saveProfileToServer(name, {
    group_power: groupPower,
    member_points: points,
    owned_codes: [],
    exclude_codes: [],
  });
  state.profiles[name] = saved;
  renderProfileOptions();
  applyProfile(name);
  closeProfileBuilderModal();
  setProfileHint(`已新建账号「${name}」。`);
  schedulePersistUiState();
}

function getExcludedCardRows() {
  return [...state.excludedCodes]
    .map((code) => {
      const card = getCardByCode(code);
      const groupKey = String(card?.member_group_key || "other");
      const groupLabel = card?.member_group_label || (groupKey === "sakura" ? "櫻坂46" : groupKey === "hinata" ? "日向坂46" : "其他");
      return {
        code,
        card,
        member_name: card?.member_name || "未知成员",
        member_name_norm: card?.member_name_norm || card?.member_name || "",
        title: card?.title || "(未知卡名)",
        color: colorClass(card?.color || "P"),
        group_key: groupKey,
        group_label: groupLabel,
        generation_label: card?.member_generation_label || "",
        series_tags: card ? getCardSeriesTags(card) : [],
      };
    })
    .sort((a, b) => {
      const byName = String(a.member_name).localeCompare(String(b.member_name), "ja");
      if (byName !== 0) return byName;
      return String(a.title).localeCompare(String(b.title), "ja");
    });
}

function resetExcludedModalFilters() {
  state.excludedFilterText = "";
  state.excludedFilterColors.clear();
  state.excludedFilterGroups.clear();
  state.excludedFilterSeries.clear();
}

function toggleFilterSetValue(setObj, value) {
  if (!value || value === "__all__") {
    setObj.clear();
    return;
  }
  if (setObj.has(value)) setObj.delete(value);
  else setObj.add(value);
}

function buildExcludedFilterOptions(rows) {
  const colorSet = new Set(rows.map((r) => r.color).filter(Boolean));
  const groupSet = new Set(rows.map((r) => r.group_key).filter(Boolean));
  const seriesSet = new Set();
  rows.forEach((r) => (Array.isArray(r.series_tags) ? r.series_tags : []).forEach((tag) => seriesSet.add(tag)));
  const colorOptions = COLOR_FILTER_OPTIONS.filter((opt) => colorSet.has(opt.key));
  const groupOptions = GROUP_FILTER_OPTIONS.filter((opt) => groupSet.has(opt.key));
  if (groupSet.has("other")) groupOptions.push({ key: "other", label: "其他" });
  const seriesOrder = ["S.teller", "Véaut", PRECIOUS_PAIR_SERIES_TAG, PRECIOUS_PAIR_23_SERIES_TAG];
  const seriesOptions = [...seriesSet].sort((a, b) => {
    const ia = seriesOrder.indexOf(a);
    const ib = seriesOrder.indexOf(b);
    if (ia >= 0 || ib >= 0) {
      if (ia < 0) return 1;
      if (ib < 0) return -1;
      return ia - ib;
    }
    return String(a).localeCompare(String(b), "ja");
  });
  return { colorOptions, groupOptions, seriesOptions };
}

function renderExcludedFilterChips(rootId, options, selectedSet, attrName, allLabel, onChange = null) {
  const root = $(rootId);
  if (!root) return;
  const allActive = selectedSet.size === 0;
  root.innerHTML =
    `<button type="button" class="excluded-chip ${allActive ? "active" : ""}" ${attrName}="__all__">${allLabel}</button>` +
    options
      .map((opt) => {
        const key = typeof opt === "string" ? opt : opt.key;
        const label = typeof opt === "string" ? opt : opt.label;
        const active = selectedSet.has(key);
        return `<button type="button" class="excluded-chip ${active ? "active" : ""}" ${attrName}="${escHtml(key)}">${escHtml(label)}</button>`;
      })
      .join("");
  root.querySelectorAll(`button[${attrName}]`).forEach((btn) => {
    btn.addEventListener("click", () => {
      const value = String(btn.getAttribute(attrName) || "").trim();
      toggleFilterSetValue(selectedSet, value);
      if (typeof onChange === "function") onChange();
      else renderExcludedModal();
    });
  });
}

function rowMatchesExcludedFilters(row) {
  const q = String(state.excludedFilterText || "").trim().toLowerCase();
  if (q) {
    const hit = [
      row.code,
      row.member_name,
      row.member_name_norm,
      row.title,
      row.group_label,
      row.color,
      ...(Array.isArray(row.series_tags) ? row.series_tags : []),
    ]
      .join(" ")
      .toLowerCase();
    if (!hit.includes(q)) return false;
  }
  if (state.excludedFilterColors.size > 0 && !state.excludedFilterColors.has(row.color)) return false;
  if (state.excludedFilterGroups.size > 0 && !state.excludedFilterGroups.has(row.group_key)) return false;
  if (state.excludedFilterSeries.size > 0) {
    const series = new Set(Array.isArray(row.series_tags) ? row.series_tags : []);
    if (![...state.excludedFilterSeries].some((s) => series.has(s))) return false;
  }
  return true;
}

function applyExcludedPoolChange(stateText = "") {
  refreshPoolSummary();
  refreshResultExcludeBadges();
  renderCardList();
  if (isExcludedModalOpen()) renderExcludedModal();
  if (stateText) $("optState").textContent = stateText;
  schedulePersistUiState();
}

function renderExcludedModal() {
  const list = $("excludedList");
  const hint = $("excludedHint");
  const search = $("excludedSearch");
  if (!list || !hint) return;
  const rowsAll = getExcludedCardRows();
  const { colorOptions, groupOptions, seriesOptions } = buildExcludedFilterOptions(rowsAll);
  const colorKeys = new Set(colorOptions.map((x) => x.key));
  const groupKeys = new Set(groupOptions.map((x) => x.key));
  const seriesKeys = new Set(seriesOptions);
  state.excludedFilterColors = new Set([...state.excludedFilterColors].filter((x) => colorKeys.has(x)));
  state.excludedFilterGroups = new Set([...state.excludedFilterGroups].filter((x) => groupKeys.has(x)));
  state.excludedFilterSeries = new Set([...state.excludedFilterSeries].filter((x) => seriesKeys.has(x)));
  if (search && search.value !== state.excludedFilterText) search.value = state.excludedFilterText;
  renderExcludedFilterChips("excludedColorFilters", colorOptions, state.excludedFilterColors, "data-excluded-color", "全部颜色");
  renderExcludedFilterChips("excludedGroupFilters", groupOptions, state.excludedFilterGroups, "data-excluded-group", "全部团体");
  renderExcludedFilterChips("excludedSeriesFilters", seriesOptions, state.excludedFilterSeries, "data-excluded-series", "全部系列");
  const rows = rowsAll.filter(rowMatchesExcludedFilters);
  hint.textContent = rowsAll.length
    ? `当前排除 ${rowsAll.length} 张卡，筛中 ${rows.length} 张。可逐张恢复或全部恢复。`
    : "排除池为空。";
  if (!rowsAll.length) {
    list.innerHTML = `<div class="card-meta">暂无排除卡</div>`;
    return;
  }
  if (!rows.length) {
    list.innerHTML = `<div class="card-meta">当前筛选条件下无结果。</div>`;
    return;
  }
  list.innerHTML = rows
    .map(
      (r) => `
        <div class="excluded-row">
          <div class="excluded-main">
            <div class="excluded-avatar">
              ${cardAvatarHTML(r.card || { member_name: r.member_name, title: r.title, color: r.color, icon_url: "" }, "sm")}
            </div>
            <div class="excluded-text">
              <div class="excluded-name">${escHtml(r.member_name)}</div>
              <div class="excluded-title">${escHtml(r.title)}</div>
              <div class="meta-chip-row">
                ${r.card ? typePillsHTML(r.card) : `<span class="type-pill ${r.color}">${COLOR_LONG[r.color] || r.color}</span>`}
                <span class="meta-chip soft">${escHtml(r.group_label)}</span>
                ${r.generation_label ? `<span class="meta-chip soft">${escHtml(r.generation_label)}</span>` : ""}
                ${(r.series_tags || []).map((tag) => `<span class="meta-chip">${escHtml(tag)}</span>`).join("")}
              </div>
            </div>
          </div>
          <button class="btn-sub tiny" type="button" data-restore-excluded="${escHtml(r.code)}">恢复</button>
        </div>
      `
    )
    .join("");
  list.querySelectorAll("button[data-restore-excluded]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const code = String(btn.getAttribute("data-restore-excluded") || "").trim();
      if (!code) return;
      state.excludedCodes.delete(code);
      applyExcludedPoolChange();
    });
  });
}

function openExcludedModal() {
  const modal = $("excludedModal");
  if (!modal) return;
  resetExcludedModalFilters();
  renderExcludedModal();
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  $("excludedSearch")?.focus();
}

function closeExcludedModal() {
  const modal = $("excludedModal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
}

function initSongSelect() {
  const sel = $("songKey");
  const songs = [...state.songs].sort((a, b) => {
    const ia = Number(a.zawa_index);
    const ib = Number(b.zawa_index);
    const hasIa = Number.isFinite(ia) && ia >= 0;
    const hasIb = Number.isFinite(ib) && ib >= 0;
    if (hasIa && hasIb && ia !== ib) return ia - ib;
    if (hasIa !== hasIb) return hasIa ? -1 : 1;
    const na = Number(a.no || 0);
    const nb = Number(b.no || 0);
    if (na && nb && na !== nb) return na - nb;
    return `${a.color || ""}${a.name || ""}${a.level || 0}`.localeCompare(
      `${b.color || ""}${b.name || ""}${b.level || 0}`,
      "ja"
    );
  });
  sel.innerHTML = songs.map((s) => `<option value="${s.key}">${makeSongLabel(s)}</option>`).join("");
}

function initSkillTagFilter() {
  const root = $("qSkillTags");
  const buckets = [...new Set(state.cards.map((c) => c.skill_bucket).filter(Boolean))];
  buckets.sort((a, b) => {
    const aSpecial = Number.isFinite(parseSkillBucketSValue(a));
    const bSpecial = Number.isFinite(parseSkillBucketSValue(b));
    if (aSpecial && !bSpecial) return -1;
    if (!aSpecial && bSpecial) return 1;
    const na = parseFloat(a);
    const nb = parseFloat(b);
    if (Number.isFinite(na) && Number.isFinite(nb)) return nb - na;
    return String(a).localeCompare(String(b));
  });

  root.innerHTML =
    `<button type="button" class="skill-chip active" data-bucket="__all__">全部</button>` +
    buckets
      .map(
        (b) =>
          `<button type="button" class="skill-chip" data-bucket="${escHtml(String(b))}">${escHtml(formatSkillBucketChipLabel(b))}</button>`
      )
      .join("");

  root.querySelectorAll(".skill-chip").forEach((el) => {
    el.addEventListener("click", () => {
      const bucket = el.getAttribute("data-bucket") || "";
      if (bucket === "__all__") {
        state.selectedSkillBuckets.clear();
      } else if (state.selectedSkillBuckets.has(bucket)) {
        state.selectedSkillBuckets.delete(bucket);
      } else {
        state.selectedSkillBuckets.add(bucket);
      }
      syncSkillTagButtons();
      renderCardList();
    });
  });
  syncSkillTagButtons();
}

function syncSkillTagButtons() {
  const allBtn = $("qSkillTags").querySelector('.skill-chip[data-bucket="__all__"]');
  const chips = $("qSkillTags").querySelectorAll(".skill-chip");
  chips.forEach((chip) => {
    const bucket = chip.getAttribute("data-bucket") || "";
    if (bucket === "__all__") {
      chip.classList.toggle("active", state.selectedSkillBuckets.size === 0);
      return;
    }
    chip.classList.toggle("active", state.selectedSkillBuckets.has(bucket));
  });
  if (allBtn) allBtn.classList.toggle("active", state.selectedSkillBuckets.size === 0);
}

function renderSlots() {
  const root = $("teamSlots");
  if (!root) return;
  root.innerHTML = state.slots
    .map((cardCode, idx) => {
      const card = cardCode ? getCardByCode(cardCode) : null;
      const active = idx === state.activeSlot ? "active" : "";
      const slotBadge =
        idx === 0
          ? `<span class="slot-index-chip center" title="Center">C</span>`
          : `<span class="slot-index-chip">${idx + 1}</span>`;
      if (!card) {
        return `
          <div class="slot slot-detailed ${active}" data-slot="${idx}">
            <div class="slot-top">${slotBadge}</div>
            <div class="empty">点这里激活槽位，再在左侧卡池点「上队」</div>
          </div>
        `;
      }
      const centerText = formatGameText(card.leader_desc || card.leader_name || "-");
      const skillText = formatGameText(card.skill_desc || "-");
      return `
        <div class="slot slot-detailed ${active}" data-slot="${idx}">
          <div class="slot-top">
            ${slotBadge}
            <div class="slot-tools">
              <label class="slot-point-inline">
                <span>成员分</span>
                <input
                  type="number"
                  min="0"
                  step="1"
                  data-member-point="${escHtml(card.member_name)}"
                  value="${getCurrentMemberPoint(card.member_name)}"
                  placeholder="0"
                />
              </label>
              <button class="slot-remove" type="button" data-remove-slot="${idx}">移除</button>
            </div>
          </div>
          <div class="team-card-row">
            <div class="team-card-leading">${cardAvatarHTML(card, "md")}</div>
            <div class="team-card-main">
              <div class="type-pill-row">${typePillsHTML(card)}</div>
              <div class="team-card-title tone-${colorClass(card.color)}">${card.member_name}</div>
              <div class="team-card-sub">${card.title}</div>
              <div class="meta-chip-row">
                <span class="meta-chip">Vo ${card.vo}</span>
                <span class="meta-chip">Da ${card.da}</span>
                <span class="meta-chip">Pe ${card.pe}</span>
                <span class="meta-chip">期望 ${getSkillExpectedLabel(card)}</span>
              </div>
              <div class="team-card-grid">
                <div class="kosa-cell">
                  <div class="kosa-key">队长技能</div>
                  <div class="kosa-val">${centerText}</div>
                </div>
                <div class="kosa-cell">
                  <div class="kosa-key">技能</div>
                  <div class="kosa-val">${skillText}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll(".slot[data-slot]").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest("button") || e.target.closest("input")) return;
      const idx = Number(el.getAttribute("data-slot") || 0);
      state.activeSlot = idx;
      renderSlots();
    });
  });

  root.querySelectorAll("button[data-remove-slot]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const idx = Number(btn.getAttribute("data-remove-slot") || 0);
      state.slots[idx] = null;
      renderSlots();
    });
  });

  root.querySelectorAll("input[data-member-point]").forEach((inp) => {
    inp.addEventListener("change", (e) => {
      const key = String(inp.getAttribute("data-member-point") || "").trim();
      if (!key) return;
      const raw = String(e.target.value || "").trim();
      const prev = getCurrentMemberPoint(key);
      const next = raw ? Math.max(0, parseInt(raw, 10) || 0) : 0;
      if (!confirmMemberPointZero(key, prev, next)) {
        inp.value = String(prev);
        return;
      }
      state.memberPoints[key] = next;
      state.memberPointOverrides.add(key);
      if (state.activeProfile) {
        scheduleActiveProfileAutoSave("成员分已修改");
      }
    });
  });
}

function cardMatchesFilter(card) {
  const q = $("qSearch").value.trim().toLowerCase();
  const listScope = $("cardListScope")?.value || "all";
  if (listScope === "owned" && !state.ownedCodes.has(card.code)) return false;

  if (q) {
    const hit = String(card._search_blob || buildCardSearchBlob(card));
    if (!hit.includes(q)) return false;
  }
  if (state.selectedColors.size > 0 && !state.selectedColors.has(card.color)) return false;
  if (state.selectedGroups.size > 0 && !state.selectedGroups.has(card.member_group_key)) return false;
  if (state.selectedMembers.size > 0) {
    const key = String(card.member_name_norm || card.member_name || "").trim();
    if (!key || !state.selectedMembers.has(key)) return false;
  }
  if (state.selectedSeries.size > 0) {
    const tags = getCardSeriesTags(card);
    if (!tags.some((x) => state.selectedSeries.has(x))) return false;
  }
  if (state.selectedSkillBuckets.size > 0 && !state.selectedSkillBuckets.has(card.skill_bucket)) return false;
  return true;
}

function renderCardList() {
  const root = $("cardList");
  const filtered = state.cards.filter(cardMatchesFilter);
  const sortKeys = [...state.selectedSortKeys];
  const sorted = [...filtered];
  if (sortKeys.length > 0) {
    const cmp = (a, b, key) => {
      if (key === "vo_desc") return Number(b.vo || 0) - Number(a.vo || 0);
      if (key === "da_desc") return Number(b.da || 0) - Number(a.da || 0);
      if (key === "pe_desc") return Number(b.pe || 0) - Number(a.pe || 0);
      if (key === "power_desc") return Number(b.power || 0) - Number(a.power || 0);
      return 0;
    };
    sorted.sort((a, b) => {
      for (const key of sortKeys) {
        const d = cmp(a, b, key);
        if (d !== 0) return d;
      }
      return Number(b.skill_expected || 0) - Number(a.skill_expected || 0) || String(a.code).localeCompare(String(b.code));
    });
  }
  const cards = sorted.slice(0, 500);
  const countNode = $("filterCount");
  if (countNode) {
    countNode.textContent = `（候选卡: ${filtered.length}）`;
  }
  root.innerHTML = cards
    .map((c) => {
      const owned = state.ownedCodes.has(c.code);
      const center = state.centerCandidateCodes.has(c.code);
      const must = state.mustIncludeCodes.has(c.code);
      const evalValue = Number(c.kosa_evaluation_value);
      const evalText = Number.isFinite(evalValue) && evalValue > 0 ? nfmt(Math.round(evalValue)) : "-";
      const centerText = formatGameText(c.leader_desc || c.leader_name || "-");
      const skillText = formatGameText(c.skill_desc || "-");
      const tierChip = c.kosa_tier_rank ? `<span class="meta-chip tier">${escHtml(c.kosa_tier_rank)}</span>` : "";
      const sceneCard = getSceneCardTotal(c);
      const memberPoint = getCurrentMemberPoint(c.member_name);
      const totalPower = sceneCard + memberPoint;
      const isOverridden =
        state.memberPointOverrides.has(c.member_name) ||
        (Object.prototype.hasOwnProperty.call(state.memberPoints || {}, c.member_name) &&
          getCurrentMemberPoint(c.member_name) !== getBaseMemberPoint(c.member_name));
      return `
      <div class="card-row">
        <div class="card-leading">
          ${cardAvatarHTML(c, "lg")}
          <div class="card-actions">
            <button class="use-btn" data-act="slot" data-code="${c.code}">上队</button>
            <button class="pool-btn ${owned ? "active" : ""}" data-act="owned" data-code="${c.code}">${
        owned ? "已持有" : "持有"
      }</button>
            <button class="pool-btn ${center ? "active" : ""}" data-act="center" data-code="${c.code}" ${
        isVsCenterCard(c) ? "" : "disabled"
      }>候选</button>
            <button class="pool-btn ${must ? "active" : ""}" data-act="must" data-code="${c.code}">必带</button>
          </div>
        </div>
        <div class="card-main">
          <div class="filter-head-row">
            <div>
              <div class="card-title tone-${colorClass(c.color)}">${c.member_name}</div>
              <div class="card-meta">${c.title}</div>
              <div class="type-pill-row">${typePillsHTML(c)}</div>
            </div>
            <div class="expect-box">
              <span>期望值</span>
              <b class="mono">${getSkillExpectedLabel(c)}</b>
            </div>
          </div>
          <div class="meta-chip-row filter-meta-row">
            <span class="meta-chip">Vo ${c.vo}</span>
            <span class="meta-chip">Da ${c.da}</span>
            <span class="meta-chip">Pe ${c.pe}</span>
            <span class="meta-chip soft mono" title="skill tuple">${c.skill_front_tuple}</span>
            ${tierChip}
            ${c.member_group_label ? `<span class="meta-chip soft">${escHtml(c.member_group_label)}</span>` : ""}
            ${c.member_generation_label ? `<span class="meta-chip soft">${escHtml(c.member_generation_label)}</span>` : ""}
            ${c.icon_url ? "" : `<span class="meta-chip warn">无图标</span>`}
          </div>
          <div class="member-score-box">
            <div class="member-score-line mono">${nfmt(sceneCard)} + ${nfmt(memberPoint)} = <b>${nfmt(totalPower)}</b></div>
            <div class="member-score-tools">
              <button class="member-point-toggle ${isOverridden ? "active" : ""}" type="button" data-member-toggle="${escHtml(c.member_name)}">${
        isOverridden ? "使用账号值" : "修改成员分"
      }</button>
              <input
                type="number"
                min="0"
                step="1"
                data-member-point-card="${escHtml(c.member_name)}"
                value="${memberPoint}"
                ${isOverridden ? "" : "disabled"}
              />
            </div>
          </div>
          <div class="filter-detail-grid">
            <div class="kosa-cell filter-left-cell">
              <div class="kosa-key">队长技能</div>
              <div class="kosa-val">${centerText}</div>
            </div>
            <div class="kosa-cell filter-right-cell">
              <div class="kosa-key">技能</div>
              <div class="kosa-val">${skillText}</div>
              <div class="card-meta inline-meta">评价值(kosa3): <b class="mono">${evalText}</b></div>
            </div>
          </div>
        </div>
      </div>
    `;
    })
    .join("");

  root.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.onclick = () => {
      const act = btn.getAttribute("data-act");
      const code = btn.getAttribute("data-code");
      if (!act || !code) return;
      if (act === "slot") {
        if (state.slots.includes(code)) return;
        state.slots[state.activeSlot] = code;
        const nextEmpty = state.slots.findIndex((x) => x === null);
        if (nextEmpty >= 0) state.activeSlot = nextEmpty;
        renderSlots();
        return;
      }
      if (act === "owned") {
        setOwned(code, !state.ownedCodes.has(code));
      } else if (act === "center") {
        if (!isCenterEligible(code)) return;
        if (($("optPoolScope")?.value || "all") === "owned") setOwned(code, true);
        if (state.centerCandidateCodes.has(code)) state.centerCandidateCodes.delete(code);
        else state.centerCandidateCodes.add(code);
      } else if (act === "must") {
        if (($("optPoolScope")?.value || "all") === "owned") setOwned(code, true);
        if (state.mustIncludeCodes.has(code)) {
          state.mustIncludeCodes.delete(code);
        } else {
          if (state.mustIncludeCodes.size >= MAX_MUST_INCLUDE) {
            $("optState").textContent = `必带卡最多 ${MAX_MUST_INCLUDE} 张，请先取消一张必带。`;
            return;
          }
          state.mustIncludeCodes.add(code);
        }
      }
      refreshPoolSummary();
      renderCardList();
    };
  });

  root.querySelectorAll("button[data-member-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const member = String(btn.getAttribute("data-member-toggle") || "").trim();
      if (!member) return;
      const on = !state.memberPointOverrides.has(member);
      if (!confirmMemberPointToggle(member, on)) return;
      if (on) {
        state.memberPointOverrides.add(member);
        if (!Object.prototype.hasOwnProperty.call(state.memberPoints, member)) {
          state.memberPoints[member] = getCurrentMemberPoint(member);
        }
      } else {
        state.memberPointOverrides.delete(member);
        if (hasBaseMemberPoint(member)) {
          state.memberPoints[member] = getBaseMemberPoint(member);
        } else {
          delete state.memberPoints[member];
        }
      }
      if (state.activeProfile) {
        scheduleActiveProfileAutoSave("成员分已修改");
      }
      renderCardList();
    });
  });

  root.querySelectorAll("input[data-member-point-card]").forEach((inp) => {
    inp.addEventListener("change", (e) => {
      const member = String(inp.getAttribute("data-member-point-card") || "").trim();
      if (!member) return;
      const prev = getCurrentMemberPoint(member);
      const next = Math.max(0, parseInt(String(e.target.value || "0"), 10) || 0);
      if (!confirmMemberPointZero(member, prev, next)) {
        inp.value = String(prev);
        return;
      }
      state.memberPoints[member] = next;
      state.memberPointOverrides.add(member);
      if (state.activeProfile) {
        scheduleActiveProfileAutoSave("成员分已修改");
      }
      renderCardList();
    });
  });
}

function onModeChange(preserveTrials = false) {
  const mode = $("mode").value;
  $("songSelectWrap").classList.toggle("hidden", mode !== "single");
  $("songColorWrap").classList.toggle("hidden", mode !== "color");
  if (!preserveTrials) $("trials").value = mode === "single" ? "10000" : "2000";
}

function resetFilters() {
  $("qSearch").value = "";
  const cardListScopeEl = $("cardListScope");
  if (cardListScopeEl) cardListScopeEl.value = "all";
  state.selectedMembers.clear();
  state.selectedColors.clear();
  state.selectedGroups.clear();
  state.selectedSortKeys.clear();
  state.selectedSeries.clear();
  state.selectedSkillBuckets.clear();
  renderSeriesTags();
  syncSkillTagButtons();
  renderColorTags();
  renderGroupTags();
  renderSortTags();
  renderMemberPicker();
  renderCardList();
  scheduleWorkspacePanelHeightSync();
  schedulePersistUiState();
}

function resetFiltersQuick() {
  resetFilters();
  state.centerCandidateCodes.clear();
  state.mustIncludeCodes.clear();
  refreshPoolSummary();
  renderCardList();
  $("optState").textContent = "已重置筛选与队长/必带约束。";
  schedulePersistUiState();
}

function getMemberPointsPayload() {
  const memberPoints = {};
  Object.entries(state.memberPoints).forEach(([k, v]) => {
    const key = canonicalMemberName(k);
    if (!key) return;
    const iv = parseInt(String(v), 10);
    if (Number.isFinite(iv) && iv >= 0) memberPoints[key] = iv;
  });
  return memberPoints;
}

function getCommonOptionPayload() {
  const readChecked = (id, fallback) => {
    const el = $(id);
    return el ? Boolean(el.checked) : Boolean(fallback);
  };
  const readInt = (id, fallback) => {
    const el = $(id);
    return el ? parseInt(String(el.value || fallback), 10) || fallback : fallback;
  };
  const readFloat = (id, fallback) => {
    const el = $(id);
    return el ? parseFloat(String(el.value || fallback)) || fallback : fallback;
  };
  const readStr = (id, fallback) => {
    const el = $(id);
    return el ? String(el.value || fallback) : String(fallback);
  };

  return {
    mode: $("mode").value,
    song_key: $("songKey").value,
    song_color: $("songColor").value,
    trials: parseInt($("trials").value, 10) || 10000,
    seed: 20260227,
    group_power: parseInt($("groupPower").value, 10) || 1800000,
    default_member_point: getDefaultMemberPoint(),
    member_points: getMemberPointsPayload(),
    sort_by: $("sortBy").value,

    enable_costume: readChecked("enableCostume", true),
    costume_vo: readInt("costumeVo", 125),
    costume_da: readInt("costumeDa", 125),
    costume_pe: readInt("costumePe", 125),
    costume_skill_per_card: 10,
    scene_skill_per_card: 430,

    enable_office: readChecked("enableOffice", true),
    office_vo: readFloat("officeVo", 0.17),
    office_da: readFloat("officeDa", 0.17),
    office_pe: readFloat("officePe", 0.17),

    enable_skin: readChecked("enableSkin", true),
    front_skin_rate: readFloat("skinRate", 0.08),
    front_skin_axes: parseAxes(readStr("skinAxes", "auto")),
    front_skin_target_color: readStr("skinTarget", "song"),

    enable_type_bonus: readChecked("enableTypeBonus", true),
    type_bonus_rate: readFloat("typeBonusRate", 0.30),
  };
}

function getEvaluatePayload() {
  const cardCodes = state.slots.filter(Boolean);
  if (cardCodes.length !== 5) throw new Error("请先填满5张卡（第一张必须是队长）");
  if (new Set(cardCodes).size !== 5) throw new Error("5张卡不能重复");
  const payload = {
    ...getCommonOptionPayload(),
    card_codes: cardCodes,
    include_histogram: true,
    histogram_bins: 120,
  };
  if (payload.mode === "single" && !payload.song_key) throw new Error("单曲模式需要选择歌曲");
  return payload;
}

function getOptimizePayload() {
  const scope = $("optPoolScope").value;
  const ownedCodes = [...state.ownedCodes];
  if (scope === "owned" && ownedCodes.length < 5) {
    throw new Error("候选卡池=仅持有 时，持有卡池至少需要5张卡");
  }
  const centerCodes = scope === "owned"
    ? [...state.centerCandidateCodes].filter((c) => state.ownedCodes.has(c))
    : [...state.centerCandidateCodes];
  const mustCodesRaw = scope === "owned"
    ? [...state.mustIncludeCodes].filter((c) => state.ownedCodes.has(c))
    : [...state.mustIncludeCodes];
  const mustCodes = [...new Set(mustCodesRaw)];
  if (mustCodes.length > MAX_MUST_INCLUDE) {
    throw new Error(`必带卡最多只能选择 ${MAX_MUST_INCLUDE} 张`);
  }
  if (scope === "owned" && centerCodes.length === 0) {
    const hasOwnedVsCenter = ownedCodes.some((code) => isVsCenterCode(code));
    if (!hasOwnedVsCenter) {
      throw new Error("仅持有卡池中没有V/S队长卡（Véaut / S.teller），无法优化。请先加入至少1张V/S卡或切回全卡池。");
    }
  }
  if (mustCodes.length === MAX_MUST_INCLUDE) {
    const mustHasVsCenter = mustCodes.some((code) => isVsCenterCode(code));
    if (!mustHasVsCenter) {
      throw new Error("必带已选5张，但其中没有V/S队长卡（Véaut / S.teller），无法组成可行队伍。");
    }
    if (centerCodes.length > 0 && !centerCodes.some((code) => mustCodes.includes(code))) {
      throw new Error("必带=5时，队长候选里至少要包含1张必带卡，否则无法组成5人队伍。");
    }
  }
  if ($("mode").value !== "single") throw new Error("精确配队目前仅支持单曲模式，请先把模式切到“单曲”");
  if (!$("songKey").value) throw new Error("精确配队需要先选择歌曲");
  const topN = parseInt($("optTopN").value, 10) || 5;
  const defaultPreEvalTrials = Number(state.defaults?.optimize?.pre_eval_trials ?? 100);
  const defaultFinalEvalCount = Number(state.defaults?.optimize?.final_eval_count ?? topN);
  const ownedPoolCount = scope === "owned" ? ownedCodes.length : 0;
  const ownedFastTrack =
    scope === "owned" &&
    ownedPoolCount >= 60 &&
    centerCodes.length === 0 &&
    mustCodes.length === 0;
  const centerCandidatesPerCenter = ownedFastTrack ? (ownedPoolCount >= 120 ? 10 : 12) : 16;
  const shortlistSize = ownedFastTrack ? (ownedPoolCount >= 120 ? 30 : 36) : 48;
  const searchPoolSize = ownedFastTrack ? (ownedPoolCount >= 120 ? 30 : 36) : 48;
  const preselectAll = !ownedFastTrack;
  const preselectTopM = preselectAll ? 999999 : Math.max(topN * 20, ownedPoolCount >= 120 ? 140 : 120);
  const preEvalTrials = ownedFastTrack
    ? Math.min(defaultPreEvalTrials, ownedPoolCount >= 120 ? 50 : 60)
    : defaultPreEvalTrials;
  return {
    ...getCommonOptionPayload(),
    mode: "single",
    pool_scope: scope,
    owned_card_codes: scope === "owned" ? ownedCodes : [],
    exclude_card_codes: [],
    center_card_codes: centerCodes,
    must_include_codes: mustCodes,
    top_n: topN,
    center_candidates_per_center: centerCandidatesPerCenter,
    shortlist_size: shortlistSize,
    search_pool_size: searchPoolSize,
    // strict_no_miss=true (default): disable fast-all pruning to avoid miss.
    disable_fast_all: Boolean(state.defaults?.optimize?.strict_no_miss ?? true),
    preselect_all: preselectAll,
    preselect_top_m: preselectTopM,
    pre_eval_trials: preEvalTrials,
    final_eval_count: Number.isFinite(defaultFinalEvalCount) ? Math.max(topN, defaultFinalEvalCount) : topN,
    candidate_strategy: state.defaults?.optimize?.candidate_strategy || "axis_t1",
    opt_min_skill_expected: Number(state.defaults?.optimize?.opt_min_skill_expected ?? 3.0),
    include_histogram: false,
    histogram_bins: 120,
  };
}

function formatOptimizeErrorMessage(raw) {
  const msg = String(raw || "").trim();
  if (!msg) return "优化失败，请检查当前设置。";
  if (msg.includes("must_include_codes cannot exceed 5")) {
    return "必带卡最多只能选5张。请先取消多余必带后再试。";
  }
  if (msg.includes("no center candidates found")) {
    return "当前卡池没有可用的V/S队长卡（Véaut / S.teller），无法优化。";
  }
  if (msg.includes("current pool has fewer than 5 cards after exclusions")) {
    return "当前卡池不足5张，无法优化。";
  }
  if (msg.includes("center_card_codes not in current pool")) {
    return "队长候选里有卡不在当前卡池，请检查候选设置。";
  }
  if (msg.includes("must_include code not in current pool")) {
    return "必带里有卡不在当前卡池，请检查必带设置。";
  }
  if (msg.includes("owned_card_codes must contain at least 5 unique cards")) {
    return "仅持有卡池至少需要5张不重复卡片，才能进行优化。";
  }
  if (msg.includes("no candidate teams matched current constraints")) {
    return "当前约束下找不到可行队伍。常见原因：必带太多，或必带=5但没有V/S队长卡。";
  }
  return msg;
}

function startOptimizeProgress() {
  const wrap = $("optProgressWrap");
  const bar = $("optProgressBar");
  const text = $("optProgressText");
  if (!wrap || !bar || !text) return;
  wrap.classList.remove("hidden");
  let p = 4;
  bar.style.width = `${p}%`;
  text.textContent = "准备候选队伍…";
  if (state.optimizeProgressTimer) clearInterval(state.optimizeProgressTimer);
  state.optimizeProgressTimer = setInterval(() => {
    p = Math.min(92, p + (p < 40 ? 3 : p < 70 ? 2 : 1));
    bar.style.width = `${p}%`;
    if (p >= 72) {
      text.textContent = "严格 zawa MonteCarlo 重排中…";
    } else if (p >= 38) {
      text.textContent = "构建队伍候选中…";
    } else {
      text.textContent = "准备候选队伍…";
    }
  }, 260);
}

function stopOptimizeProgress(success) {
  const wrap = $("optProgressWrap");
  const bar = $("optProgressBar");
  const text = $("optProgressText");
  if (state.optimizeProgressTimer) {
    clearInterval(state.optimizeProgressTimer);
    state.optimizeProgressTimer = null;
  }
  if (!wrap || !bar || !text) return;
  bar.style.width = success ? "100%" : "0%";
  text.textContent = success ? "完成" : "中断";
  setTimeout(() => {
    wrap.classList.add("hidden");
    bar.style.width = "0%";
    text.textContent = "准备中…";
  }, success ? 650 : 300);
}

function renderSingle(result, meta) {
  const song = result.song;
  const dist = result.distribution;
  const order = meta.distribution_order;
  const bonuses = result.bonuses;
  const scene = result.scene_power;
  const skills = result.skill_profiles || [];
  const memberRows = result.member_point_breakdown || [];
  const histogram = result.histogram || [];
  const histMax = histogram.reduce((m, x) => Math.max(m, Number(x.count || 0)), 0) || 1;
  const histBars = histogram
    .map((h) => {
      const hp = Math.max(2, Math.round((Number(h.count || 0) / histMax) * 170));
      return `<div class="hist-bin" style="height:${hp}px" title="${nfmt(h.x0)} ~ ${nfmt(h.x1)} | count ${nfmt(
        h.count
      )}"></div>`;
    })
    .join("");

  return `
    <div class="result-card">
      <div class="result-head">
        <div>
          <h3>${makeSongLabel(song)}</h3>
          <div class="card-meta">mode=${meta.mode}</div>
        </div>
        <div class="mono">mean = ${nfmt(result.mean || dist.median)} | σ = ${nfmt(result.sigma)}</div>
      </div>
      <div class="dist-grid">
        ${order.map((k) => `<div class="dist-cell"><div>${k}</div><b class="mono">${nfmt(dist[k])}</b></div>`).join("")}
      </div>
    </div>
    <div class="result-card">
      <h3>分布图（直方图）</h3>
      <div class="hist-wrap">
        ${histBars || '<div class="card-meta">无直方图数据</div>'}
      </div>
      <div class="card-meta">同一批模拟样本生成，形状应与 zawa 网页分布图一致。</div>
    </div>
    <div class="result-card">
      <h3>综合力拆分</h3>
      <table>
        <tr><th>进歌前综合力(含office)</th><td class="mono">${nfmt(result.front_pre)}</td></tr>
        <tr><th>进歌后综合力(含类型加成)</th><td class="mono">${nfmt(result.front_post)}</td></tr>
        <tr><th>Scene raw (Vo/Da/Pe)</th><td class="mono">${nfmt(scene.raw.vo)} / ${nfmt(scene.raw.da)} / ${nfmt(scene.raw.pe)}</td></tr>
        <tr><th>Scene effective (Vo/Da/Pe)</th><td class="mono">${nfmt(scene.effective.vo)} / ${nfmt(scene.effective.da)} / ${nfmt(scene.effective.pe)}</td></tr>
        <tr><th>Center delta (Vo/Da/Pe)</th><td class="mono">${nfmt(scene.delta.vo)} / ${nfmt(scene.delta.da)} / ${nfmt(scene.delta.pe)}</td></tr>
        <tr><th>成员分合计</th><td class="mono">${nfmt(bonuses.member_point_total)}</td></tr>
        <tr><th>衣服合计</th><td class="mono">${nfmt(bonuses.costume_total)}</td></tr>
        <tr><th>家具合计</th><td class="mono">${nfmt(bonuses.office_total)}</td></tr>
        <tr><th>Skin 合计</th><td class="mono">${nfmt(bonuses.skin_total)}</td></tr>
        <tr><th>同色类型加成</th><td class="mono">${nfmt(bonuses.type_bonus_total)}</td></tr>
        <tr><th>成员分明细(卡分+成员分)</th><td>${memberPointSummaryHTML(memberRows)}</td></tr>
      </table>
    </div>
    <div class="result-card">
      <h3>发动效果摘要</h3>
      <p>${formatGameText(result.effect_summary || "-")}</p>
      <p class="card-meta">Center Skill: ${escHtml(result.center_skill?.name || "-")}</p>
      <p class="card-meta">${formatGameText(result.center_skill?.desc || "")}</p>
    </div>
    <div class="result-card">
      <h3>队员技能明细</h3>
      <table>
        <thead>
          <tr><th>成员</th><th>卡</th><th>颜色</th><th>front(生效tuple)</th><th>scope</th><th>base期望%</th><th>降级后期望%</th><th>倍率</th><th>乘后期望%</th></tr>
        </thead>
        <tbody>
          ${skills
            .map(
              (s) => `
            <tr>
              <td>${s.member_name}</td>
              <td>${s.title}</td>
              <td>${s.color}</td>
              <td class="mono">${s.front_tuple_base || s.front_tuple}</td>
              <td>${s.tuple_scope || "-"}</td>
              <td class="mono">${Number(s.skill_expected_base || 0).toFixed(2)}</td>
              <td class="mono">${Number(s.skill_expected_effective_base ?? s.skill_expected_base ?? 0).toFixed(2)}</td>
              <td class="mono">${Number(s.proc_multiplier || 1).toFixed(2)}x</td>
              <td class="mono">${Number(s.skill_expected_effective ?? (Number(s.skill_expected_effective_base ?? s.skill_expected_base ?? 0) * Number(s.proc_multiplier || 1))).toFixed(2)}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderMulti(results, meta) {
  const rows = results.slice(0, 60);
  return `
    <div class="result-card">
      <h3>Top Songs (${rows.length}/${results.length})</h3>
      <table>
        <thead>
          <tr><th>#</th><th>歌曲</th><th>median</th><th>+2σ</th><th>-2σ</th><th>front pre</th><th>front post</th><th>σ</th></tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (r, idx) => `
            <tr>
              <td>${idx + 1}</td>
              <td>[${r.song.color}] ${r.song.name} (Lv.${r.song.level})</td>
              <td class="mono">${nfmt(r.distribution.median)}</td>
              <td class="mono">${nfmt(r.distribution["+2sigma"])}</td>
              <td class="mono">${nfmt(r.distribution["-2sigma"])}</td>
              <td class="mono">${nfmt(r.front_pre)}</td>
              <td class="mono">${nfmt(r.front_post)}</td>
              <td class="mono">${nfmt(r.sigma)}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
      <p class="card-meta">多曲模式不输出技能明细，建议切单曲查看完整拆分。</p>
    </div>
  `;
}

function renderOptimize(data) {
  const teams = data.teams || [];
  const meta = data.meta || {};
  if (!teams.length) return `<div class="result-card">没有可用优化结果</div>`;
  const pickSongLabel = () => {
    const direct = String(meta.song_label || "").trim();
    if (direct) return direct;
    const keyFromMeta = String(meta.song_key || "").trim();
    const keyFromPayload = String(state.lastOptimizePayload?.song_key || "").trim();
    const currentSongKey = String($("songKey")?.value || "").trim();
    const songKey = keyFromMeta || keyFromPayload || currentSongKey;
    if (songKey) {
      const song = state.songs.find((s) => String(s.key || "").trim() === songKey);
      if (song) return makeSongLabel(song);
    }
    const name = String(meta.song_name || "").trim();
    if (name) {
      const color = String(meta.song_color || "").trim();
      const level = Number(meta.song_level || 0);
      const lvText = level > 0 ? ` (Lv.${level})` : "";
      return color ? `[${color}] ${name}${lvText}` : `${name}${lvText}`;
    }
    return "-";
  };
  const selectedSongLabel = pickSongLabel();
  const distOrder = ["min", "-3sigma", "-2sigma", "-1sigma", "median", "+1sigma", "+2sigma", "+3sigma", "max"];
  const distLabel = {
    min: "MIN",
    "-3sigma": "-3σ",
    "-2sigma": "-2σ",
    "-1sigma": "-σ",
    median: "0",
    "+1sigma": "σ",
    "+2sigma": "2σ",
    "+3sigma": "3σ",
    max: "MAX",
  };
  const distPct = {
    min: "-",
    "-3sigma": "0.13%",
    "-2sigma": "2.28%",
    "-1sigma": "15.87%",
    median: "50.00%",
    "+1sigma": "84.13%",
    "+2sigma": "97.72%",
    "+3sigma": "99.87%",
    max: "-",
  };

  return teams
    .map((t, idx) => {
      const cards = t.team?.cards || [];
      const result = t.result || {};
      const dist = result.distribution || {};
      const order = meta.distribution_order || distOrder;
      const center = t.team?.center || cards[0] || {};
      const skills = result.skill_profiles || [];
      const memberBreakdown = result.member_point_breakdown || [];
      const memberBreakdownByCode = new Map(
        memberBreakdown.map((r) => [String(r.code || ""), r]).filter((x) => x[0])
      );
      const cardsByCode = new Map(cards.map((c) => [String(c.code || ""), c]).filter((x) => x[0]));
      const cardStrip = cards
        .map(
          (c, slotIdx) => {
            const row = memberBreakdownByCode.get(String(c.code || "")) || {};
            const displayCard = getCardByCode(c.code) || c;
            const cardPointRaw = Number(row.scene_card_total ?? row.scene_raw_total);
            const cardPointByCard = Number(getSceneCardTotal(displayCard) || 0);
            const cardPoint = cardPointByCard > 0 ? cardPointByCard : Number.isFinite(cardPointRaw) ? cardPointRaw : 0;
            const memberPointRaw = Number(row.member_point);
            const memberPoint = Number.isFinite(memberPointRaw)
              ? memberPointRaw
              : Number(getCurrentMemberPoint(displayCard.member_name || c.member_name || "") || 0);
            const totalPoint = Number(cardPoint + memberPoint);
            const voVal = pickStatValue(displayCard.vo, row.vo ?? c.vo);
            const daVal = pickStatValue(displayCard.da, row.da ?? c.da);
            const peVal = pickStatValue(displayCard.pe, row.pe ?? c.pe);
            const owned = Boolean(state.ownedCodes.has(c.code));
            return `
          <article class="mini-card replace-slot-card ${state.ownedCodes.has(c.code) ? "" : "not-owned"}">
            <button
              class="mini-avatar-btn"
              type="button"
              data-open-team-replace="${idx}"
              data-replace-slot="${slotIdx}"
              title="点击替换此位卡并对比结果"
            >${cardAvatarHTML(c, "sm")}</button>
            <div class="replace-slot-body">
              <div class="replace-slot-head">
                <span class="replace-slot-name mini-name">${escHtml(c.member_name || "-")}</span>
              <button
                class="replace-owned-btn mini-owned-btn ${state.ownedCodes.has(c.code) ? "active" : ""}"
                type="button"
                data-owned-card="${escHtml(c.code)}"
                title="${state.ownedCodes.has(c.code) ? "已在持有池，点击移出" : "未在持有池，点击加入"}"
              >${owned ? "已持有" : "未持有"}</button>
              </div>
              <div class="replace-slot-title mini-title">${escHtml(displayCard.title || c.title || "-")}</div>
              <div class="mini-meta-row meta-chip-row">
                ${typePillsHTML(displayCard)}
                <span class="meta-chip">期望 ${getSkillExpectedLabel(displayCard || c)}</span>
              </div>
              <div class="replace-slot-stat mini-stat mono">Vo ${nfmt(voVal)} / Da ${nfmt(daVal)} / Pe ${nfmt(peVal)}</div>
              <div class="replace-slot-stat mini-stat mono">卡分 ${nfmt(cardPoint)} + 成员分 ${nfmt(memberPoint)} = ${nfmt(totalPoint)}</div>
            </div>
          </article>`
          }
        )
        .join("");
      const memberRows = memberBreakdown.length
        ? memberBreakdown
            .map((r, i) => {
              const code = String(r.code || "");
              const rowCardRef = cardsByCode.get(code) || cards[i] || null;
              const cardRef = (code ? getCardByCode(code) : null) || rowCardRef;
              const memberName = String(r.member_name || cardRef?.member_name || "-");
              const title = String(r.title || cardRef?.title || "-");
              const voVal = pickStatValue(cardRef?.vo, r.vo);
              const daVal = pickStatValue(cardRef?.da, r.da);
              const peVal = pickStatValue(cardRef?.pe, r.pe);
              const cardPointRaw = Number(r.scene_card_total ?? r.scene_raw_total);
              const cardPointByCard = Number(getSceneCardTotal(cardRef) || 0);
              const cardPoint = cardPointByCard > 0 ? cardPointByCard : Number.isFinite(cardPointRaw) ? cardPointRaw : 0;
              const memberPointRaw = Number(r.member_point);
              const memberPoint = Number.isFinite(memberPointRaw) ? memberPointRaw : Number(getCurrentMemberPoint(memberName) || 0);
              const totalPoint = Number(cardPoint + memberPoint);
              return `<tr>
                <td>${i + 1}</td>
                <td>${escHtml(memberName)}[${escHtml(title)}]</td>
                <td class="mono">${nfmt(voVal)}</td>
                <td class="mono">${nfmt(daVal)}</td>
                <td class="mono">${nfmt(peVal)}</td>
                <td class="mono">${nfmt(cardPoint)}</td>
                <td class="mono">${nfmt(memberPoint)}</td>
                <td class="mono">${nfmt(totalPoint)}</td>
              </tr>`;
            })
            .join("")
        : `<tr><td colspan="8" class="card-meta">无成员分明细</td></tr>`;
      const frontLines = skills.length
        ? skills
            .map((s) => {
              const evBase = Number(s.skill_expected_base || 0);
              const evEffBase = Number(s.skill_expected_effective_base ?? evBase);
              const evWithMul = Number(s.skill_expected_effective ?? (evEffBase * Number(s.proc_multiplier || 1)));
              const mul = Number(s.proc_multiplier || 1).toFixed(2);
              const tupleBase = s.front_tuple_base || s.front_tuple || "-";
              const scope = String(s.tuple_scope || "").trim();
              const scopeText = scope ? `(${scope})` : "";
              const evText =
                Math.abs(evEffBase - evBase) > 0.009
                  ? `${evEffBase.toFixed(2)}%(base ${evBase.toFixed(2)}%)`
                  : `${evEffBase.toFixed(2)}%`;
              return `<div class="front-line mono">${evText} (${tupleBase})${scopeText} / ${mul}x => ${evWithMul.toFixed(
                2
              )}% · ${escHtml(s.member_name)}[${escHtml(
                s.title
              )}]</div>`;
            })
            .join("")
        : `<div class="front-line card-meta">无技能明细</div>`;
      const scene = result.scene_power || {};
      const bonuses = result.bonuses || {};
      return `
      <div class="result-card">
        <h3>Top${idx + 1}: ${center.member_name || "-"}[${center.title || "-"}]</h3>
        <p class="card-meta">队伍: ${(cards || []).map((c) => `${c.member_name}[${c.title}]`).join(" / ")}</p>
        <div class="mini-strip">${cardStrip}</div>
        <div class="opt-zawa-wrap">
          <div class="opt-front-block">
            <table class="opt-front-table">
              <tr><th>选择歌曲</th><td>${escHtml(selectedSongLabel)}</td></tr>
              <tr><th>进歌前综合力</th><td class="mono">${nfmt(result.front_pre)}</td></tr>
              <tr><th>进歌后综合力</th><td class="mono">${nfmt(result.front_post)}</td></tr>
              <tr><th>σ</th><td class="mono">${nfmt(result.sigma)}</td></tr>
              <tr><th>发动效果</th><td>${formatGameText(result.effect_summary || "-")}</td></tr>
              <tr><th>Front 编成</th><td><div class="front-lines">${frontLines}</div></td></tr>
            </table>
          </div>
          <div class="opt-dist-block">
            <table class="opt-dist-table">
              <thead>
                <tr><th>累积分布</th><th>概率</th><th>预测分数</th></tr>
              </thead>
              <tbody>
                ${order
                  .map(
                    (k) => `<tr><td>${distLabel[k] || k}</td><td>${distPct[k] || "-"}</td><td class="mono">${nfmt(dist[k])}</td></tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        </div>
        <details class="opt-detail-box">
          <summary>展开算分细则（Center / 技能 / 成员分 / VoDaPe拆分）</summary>
          <div class="opt-detail-body">
            <table class="opt-front-table">
              <tr><th>Center Skill</th><td>${formatGameText(result.center_skill?.name || "-")}</td></tr>
              <tr><th>Center Skill Desc</th><td>${formatGameText(result.center_skill?.desc || "-")}</td></tr>
              <tr><th>Scene raw</th><td class="mono">Vo ${nfmt(scene.raw?.vo || 0)} / Da ${nfmt(scene.raw?.da || 0)} / Pe ${nfmt(
                scene.raw?.pe || 0
              )}</td></tr>
              <tr><th>Scene effective</th><td class="mono">Vo ${nfmt(scene.effective?.vo || 0)} / Da ${nfmt(
                scene.effective?.da || 0
              )} / Pe ${nfmt(scene.effective?.pe || 0)}</td></tr>
              <tr><th>Scene delta</th><td class="mono">Vo ${nfmt(scene.delta?.vo || 0)} / Da ${nfmt(
                scene.delta?.da || 0
              )} / Pe ${nfmt(scene.delta?.pe || 0)}</td></tr>
              <tr><th>加成合计</th><td class="mono">成员分 ${nfmt(bonuses.member_point_total || 0)} / 衣服 ${nfmt(
                bonuses.costume_total || 0
              )} / 家具 ${nfmt(bonuses.office_total || 0)} / Skin ${nfmt(bonuses.skin_total || 0)} / 同色 ${nfmt(
                bonuses.type_bonus_total || 0
              )}</td></tr>
            </table>
            <div class="opt-member-wrap">
              <h4>成员分明细（卡面分 + 成员分）</h4>
              <table class="opt-member-table">
                <thead>
                  <tr><th>#</th><th>成员卡</th><th>Vo</th><th>Da</th><th>Pe</th><th>卡面分</th><th>成员分</th><th>合计</th></tr>
                </thead>
                <tbody>
                  ${memberRows}
                </tbody>
              </table>
            </div>
          </div>
        </details>
      </div>
      `;
    })
    .join("");
}

async function runEvaluate() {
  const btn = $("runOptimizeBtn");
  const stateText = $("runState");
  try {
    const payload = getEvaluatePayload();
    if (btn) btn.disabled = true;
    stateText.textContent = "计算中...";
    const resp = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data?.detail || "计算失败");
    const results = data.results || [];
    if (!results.length) {
      $("resultArea").innerHTML = `<div class="result-card">没有可用结果</div>`;
      $("resultHint").textContent = "无结果";
      return;
    }
    const mode = data.meta?.mode || "single";
    persistResultState({
      kind: "evaluate",
      data,
    });
    $("resultHint").textContent = "";
    $("resultArea").innerHTML = mode === "single" ? renderSingle(results[0], data.meta) : renderMulti(results, data.meta);
  } catch (err) {
    $("resultArea").innerHTML = `<div class="result-card">错误: ${err.message || err}</div>`;
    $("resultHint").textContent = "计算失败";
  } finally {
    if (btn) btn.disabled = false;
    stateText.textContent = "";
  }
}

function setOptimizeButtonsDisabled(disabled) {
  const on = Boolean(disabled);
  const runOptimizeBtn = $("runOptimizeBtn");
  const runOptimizeQuickBtn = $("runOptimizeQuickBtn");
  if (runOptimizeBtn) runOptimizeBtn.disabled = on;
  if (runOptimizeQuickBtn) runOptimizeQuickBtn.disabled = on;
  updateOptimizeCancelButton();
}

function setOptimizeJobStatus(status) {
  state.optimizeJobStatus = String(status || "").trim().toLowerCase();
  updateOptimizeCancelButton();
}

function updateOptimizeCancelButton() {
  const btn = $("optCancelBtn");
  if (!btn) return;
  const hasJob = Boolean(state.currentOptimizeJobId);
  btn.classList.remove("hidden");
  const status = state.optimizeJobStatus;
  const canCancel = hasJob && (status === "queued" || status === "running");
  btn.textContent = "取消优化";
  btn.disabled = Boolean(state.optimizeCancelBusy || !canCancel);
}

function setPendingOptimizeJobId(jobId) {
  const key = String(jobId || "").trim();
  state.currentOptimizeJobId = key;
  state.optimizeStarting = false;
  if (!key) {
    state.optimizeJobStatus = "";
    state.optimizeCancelBusy = false;
  }
  updateOptimizeCancelButton();
  try {
    if (key) localStorage.setItem(OPTIMIZE_JOB_STORAGE_KEY, key);
    else localStorage.removeItem(OPTIMIZE_JOB_STORAGE_KEY);
  } catch (_) {}
}

function getPendingOptimizeJobId() {
  try {
    return String(localStorage.getItem(OPTIMIZE_JOB_STORAGE_KEY) || "").trim();
  } catch (_) {
    return "";
  }
}

function clearOptimizePollTimer() {
  if (state.optimizePollTimer) {
    clearTimeout(state.optimizePollTimer);
    state.optimizePollTimer = null;
  }
}

function finishOptimizeJobTracking() {
  clearOptimizePollTimer();
  state.optimizeStarting = false;
  state.optimizeCancelBusy = false;
  setOptimizeJobStatus("");
  setPendingOptimizeJobId("");
  setOptimizeButtonsDisabled(false);
}

function refreshResultExcludeBadges() {
  const root = $("resultArea");
  if (!root) return;
  root.querySelectorAll("button[data-owned-card]").forEach((btn) => {
    const code = String(btn.getAttribute("data-owned-card") || "").trim();
    const owned = Boolean(code && state.ownedCodes.has(code));
    btn.textContent = owned ? "已持有" : "未持有";
    btn.classList.toggle("active", owned);
    const holder = btn.closest(".mini-card");
    if (holder) holder.classList.toggle("not-owned", !owned);
    btn.setAttribute("title", owned ? "已在持有池，点击移出" : "未在持有池，点击加入");
  });
}

function toggleOwnedByCode(code) {
  const key = String(code || "").trim();
  if (!key) return;
  const card = getCardByCode(key);
  const label = card ? `${card.member_name}[${card.title}]` : key;
  if (state.ownedCodes.has(key)) {
    setOwned(key, false);
    $("optState").textContent = `已移出持有池：${label}。`;
  } else {
    setOwned(key, true);
    $("optState").textContent = `已加入持有池：${label}。`;
  }
  refreshPoolSummary();
  renderCardList();
  refreshResultExcludeBadges();
}

function bindOptimizeResultExcludeActions() {
  const root = $("resultArea");
  if (!root) return;
  root.querySelectorAll("button[data-owned-card]").forEach((btn) => {
    btn.onclick = () => {
      const code = String(btn.getAttribute("data-owned-card") || "").trim();
      if (!code) return;
      toggleOwnedByCode(code);
    };
  });
}

function getTeamByIndex(teamIndex) {
  const idx = Number(teamIndex);
  if (!Number.isFinite(idx) || idx < 0) return null;
  const teams = state.lastOptimizeData?.teams || [];
  return teams[idx] || null;
}

function buildTeamReplaceBasePayload(team) {
  const payload = getCommonOptionPayload();
  const src = state.lastOptimizePayload || {};
  const syncKeys = [
    "mode",
    "song_key",
    "song_color",
    "trials",
    "group_power",
    "default_member_point",
    "member_points",
    "sort_by",
    "enable_costume",
    "costume_vo",
    "costume_da",
    "costume_pe",
    "costume_skill_per_card",
    "scene_skill_per_card",
    "enable_office",
    "office_vo",
    "office_da",
    "office_pe",
    "enable_skin",
    "front_skin_rate",
    "front_skin_axes",
    "front_skin_target_color",
    "enable_type_bonus",
    "type_bonus_rate",
  ];
  syncKeys.forEach((k) => {
    if (Object.prototype.hasOwnProperty.call(src, k)) payload[k] = src[k];
  });
  payload.mode = "single";
  const teamSongKey = String(team?.result?.song?.key || "").trim();
  if (teamSongKey) payload.song_key = teamSongKey;
  return payload;
}

function openTeamReplaceModal(teamIndex, slotIndex) {
  const team = getTeamByIndex(teamIndex);
  const modal = $("teamReplaceModal");
  if (!team || !modal) return;
  const cards = Array.isArray(team?.team?.cards) ? team.team.cards : [];
  const codes = cards.map((c) => String(c?.code || "").trim()).filter(Boolean);
  if (codes.length !== 5 || new Set(codes).size !== 5) {
    $("optState").textContent = "当前队伍数据不完整，无法进入换卡对比。";
    return;
  }
  const slot = Math.max(0, Math.min(4, parseInt(String(slotIndex || 0), 10) || 0));
  state.teamReplace = {
    teamIndex: Number(teamIndex),
    team,
    baseCodes: [...codes],
    currentCodes: [...codes],
    slotIndex: slot,
    filterText: String($("qSearch")?.value || "").trim(),
    filterColors: new Set([...state.selectedColors]),
    filterGroups: new Set([...state.selectedGroups]),
    filterSeries: new Set([...state.selectedSeries]),
    filterMembers: new Set([...state.selectedMembers]),
    poolScope: "all",
    ownFilter: "all",
    compareLoading: false,
    compareError: "",
    compareResult: null,
    basePayload: buildTeamReplaceBasePayload(team),
  };
  renderTeamReplaceModal();
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
}

function closeTeamReplaceModal() {
  const modal = $("teamReplaceModal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  state.teamReplace = null;
}

function getTeamReplaceFilterOptions(ctx) {
  const sourceCards = state.cards.filter((card) => (ctx.poolScope === "owned" ? state.ownedCodes.has(card.code) : true));
  const colorSet = new Set(sourceCards.map((c) => colorClass(c.color)).filter(Boolean));
  const groupSet = new Set(sourceCards.map((c) => String(c.member_group_key || "other")));
  const seriesSet = new Set();
  sourceCards.forEach((c) => getCardSeriesTags(c).forEach((tag) => seriesSet.add(tag)));
  const colorOptions = COLOR_FILTER_OPTIONS.filter((opt) => colorSet.has(opt.key));
  const groupOptions = GROUP_FILTER_OPTIONS.filter((opt) => groupSet.has(opt.key));
  if (groupSet.has("other")) groupOptions.push({ key: "other", label: "其他" });
  const seriesOrder = ["S.teller", "Véaut", PRECIOUS_PAIR_SERIES_TAG, PRECIOUS_PAIR_23_SERIES_TAG];
  const seriesOptions = [...seriesSet].sort((a, b) => {
    const ia = seriesOrder.indexOf(a);
    const ib = seriesOrder.indexOf(b);
    if (ia >= 0 || ib >= 0) {
      if (ia < 0) return 1;
      if (ib < 0) return -1;
      return ia - ib;
    }
    return String(a).localeCompare(String(b), "ja");
  });
  return { colorOptions, groupOptions, seriesOptions };
}

function cardMatchesTeamReplaceFilters(card, ctx) {
  if (!card) return false;
  if (ctx.poolScope === "owned" && !state.ownedCodes.has(card.code)) return false;
  if (ctx.ownFilter === "owned" && !state.ownedCodes.has(card.code)) return false;
  if (ctx.ownFilter === "unowned" && state.ownedCodes.has(card.code)) return false;
  const q = String(ctx.filterText || "").trim().toLowerCase();
  if (q) {
    const hit = [
      card.code,
      card.member_name,
      card.member_name_norm || "",
      card.member_name_roman || "",
      card.member_name_kana || "",
      card.title,
      card.member_group_label || "",
      card.member_generation_label || "",
      ...(getCardSeriesTags(card) || []),
    ]
      .join(" ")
      .toLowerCase();
    if (!hit.includes(q)) return false;
  }
  if (ctx.filterColors.size > 0 && !ctx.filterColors.has(colorClass(card.color))) return false;
  if (ctx.filterGroups.size > 0 && !ctx.filterGroups.has(String(card.member_group_key || "other"))) return false;
  if (ctx.filterSeries.size > 0) {
    const tags = getCardSeriesTags(card);
    if (!tags.some((x) => ctx.filterSeries.has(x))) return false;
  }
  if (ctx.filterMembers && ctx.filterMembers.size > 0) {
    const memberKey = String(card.member_name_norm || card.member_name || "").trim();
    if (!memberKey || !ctx.filterMembers.has(memberKey)) return false;
  }
  return true;
}

function renderTeamReplaceMemberPicker(ctx) {
  const root = $("teamReplaceMemberPicker");
  const selectedCountNode = $("teamReplaceMemberSelected");
  if (!root) return;
  const baseCards = state.cards.filter((card) => {
    if (ctx.poolScope === "owned" && !state.ownedCodes.has(card.code)) return false;
    if (ctx.filterColors.size > 0 && !ctx.filterColors.has(colorClass(card.color))) return false;
    if (ctx.filterGroups.size > 0 && !ctx.filterGroups.has(String(card.member_group_key || "other"))) return false;
    if (ctx.filterSeries.size > 0) {
      const tags = getCardSeriesTags(card);
      if (!tags.some((x) => ctx.filterSeries.has(x))) return false;
    }
    return true;
  });
  const memberKeySet = new Set(
    baseCards.map((card) => String(card.member_name_norm || card.member_name || "").trim()).filter(Boolean)
  );
  const list = state.memberCatalog.filter((m) => {
    if (!memberKeySet.has(m.name_norm)) return false;
    if (ctx.filterGroups.size > 0 && !ctx.filterGroups.has(m.group_key || "other")) return false;
    return true;
  });
  ctx.filterMembers = new Set([...ctx.filterMembers].filter((x) => memberKeySet.has(x)));
  if (selectedCountNode) {
    selectedCountNode.textContent = ctx.filterMembers.size ? `已选成员 ${ctx.filterMembers.size} 人` : "全部成员";
  }
  if (!list.length) {
    root.innerHTML = `<div class="card-meta">当前筛选下无成员</div>`;
    return;
  }
  const groups = [];
  const byGroup = new Map();
  list.forEach((m) => {
    const gk = m.group_key || "other";
    if (!byGroup.has(gk)) {
      const fallbackGroup = gk === "sakura" ? "櫻坂46成员" : gk === "hinata" ? "日向坂46成员" : "其他成员";
      byGroup.set(gk, {
        key: gk,
        label: m.group_label ? `${m.group_label}成员` : fallbackGroup,
        gens: new Map(),
      });
      groups.push(gk);
    }
    const g = byGroup.get(gk);
    const genNo = Number(m.generation_no || 0) || 0;
    const genKey = m.group_generation_key || `${gk}|0`;
    if (!g.gens.has(genKey)) {
      const genLabel = genNo > 0 ? `${genNo}期生` : UNGROUPED_GENERATION_LABEL;
      g.gens.set(genKey, {
        key: genKey,
        no: genNo || 99,
        label: m.generation_label || genLabel,
        members: [],
      });
    }
    g.gens.get(genKey).members.push(m);
  });
  const groupOrder = { sakura: 1, hinata: 2, other: 9 };
  groups.sort((a, b) => (groupOrder[a] || 9) - (groupOrder[b] || 9));
  root.innerHTML = groups
    .map((gk) => {
      const g = byGroup.get(gk);
      const genList = [...g.gens.values()].sort((a, b) => Number(a.no) - Number(b.no));
      return `
        <section class="member-group-block">
          <h4>${escHtml(g.label)}</h4>
          ${genList
            .map((gen) => {
              const chips = gen.members
                .sort((a, b) => {
                  const oa = Number(a.generation_member_order || 0) || 999;
                  const ob = Number(b.generation_member_order || 0) || 999;
                  if (oa !== ob) return oa - ob;
                  return String(a.name || "").localeCompare(String(b.name || ""), "ja");
                })
                .map((m) => {
                  const active = ctx.filterMembers.has(m.name_norm);
                  const title = [m.name, m.roman, m.kana].filter(Boolean).join(" / ");
                  return `<button type="button" class="member-chip ${active ? "active" : ""}" data-team-replace-member="${escHtml(m.name_norm)}" title="${escHtml(title)}">${escHtml(m.name)}</button>`;
                })
                .join("");
              return `
                <div class="member-gen-block">
                  <div class="member-gen-title">${escHtml(gen.label)}</div>
                  <div class="member-chip-grid">${chips}</div>
                </div>
              `;
            })
            .join("")}
        </section>
      `;
    })
    .join("");
  root.querySelectorAll("button[data-team-replace-member]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const member = String(btn.getAttribute("data-team-replace-member") || "").trim();
      if (!member) return;
      if (ctx.filterMembers.has(member)) ctx.filterMembers.delete(member);
      else ctx.filterMembers.add(member);
      renderTeamReplaceModal();
    });
  });
}

function buildTeamReplaceCandidates(ctx) {
  const currentSlotCode = ctx.currentCodes[ctx.slotIndex];
  const filtered = state.cards.filter((card) => cardMatchesTeamReplaceFilters(card, ctx));
  const sorted = [...filtered].sort((a, b) => {
    const ea = Number(a.skill_expected || 0);
    const eb = Number(b.skill_expected || 0);
    if (eb !== ea) return eb - ea;
    const pa = Number(a.power || 0);
    const pb = Number(b.power || 0);
    if (pb !== pa) return pb - pa;
    return String(a.code).localeCompare(String(b.code));
  });
  const rows = sorted.map((card) => {
    const code = String(card.code || "").trim();
    const existingSlotIndex = ctx.currentCodes.findIndex((x) => x === code);
    const inTeamElsewhere = existingSlotIndex >= 0 && existingSlotIndex !== ctx.slotIndex;
    return {
      code,
      card,
      selected: code === currentSlotCode,
      inTeamElsewhere,
      existingSlotIndex,
    };
  });
  return {
    total: filtered.length,
    rows: rows.slice(0, 260),
  };
}

function applyTeamReplaceChoice(ctx, code) {
  const chosen = String(code || "").trim();
  if (!ctx || !chosen) return;
  const otherIdx = ctx.currentCodes.findIndex((x, i) => i !== ctx.slotIndex && x === chosen);
  if (otherIdx >= 0) {
    const cur = ctx.currentCodes[ctx.slotIndex];
    ctx.currentCodes[ctx.slotIndex] = chosen;
    ctx.currentCodes[otherIdx] = cur;
  } else {
    ctx.currentCodes[ctx.slotIndex] = chosen;
  }
  ctx.compareResult = null;
  ctx.compareError = "";
  renderTeamReplaceModal();
}

function renderTeamCompareValue(v) {
  return nfmt(Number(v || 0));
}

function renderTeamReplaceComparison(ctx) {
  const root = $("teamReplaceCompare");
  if (!root) return;
  const baseResult = ctx.team?.result || {};
  const compared = ctx.compareResult || null;
  const baseDist = baseResult.distribution || {};
  if (ctx.compareLoading) {
    root.innerHTML = `<div class="result-card">替换算分中...</div>`;
    return;
  }
  if (ctx.compareError) {
    root.innerHTML = `<div class="result-card">错误: ${escHtml(ctx.compareError)}</div>`;
    return;
  }
  if (!compared) {
    root.innerHTML = `<div class="card-meta">选择替换卡后点击“计算替换对比”。</div>`;
    return;
  }
  const nextResult = compared.result || {};
  const nextDist = nextResult.distribution || {};
  const rows = [
    { label: "进歌前综合力", base: Number(baseResult.front_pre || 0), next: Number(nextResult.front_pre || 0) },
    { label: "进歌后综合力", base: Number(baseResult.front_post || 0), next: Number(nextResult.front_post || 0) },
    { label: "σ", base: Number(baseResult.sigma || 0), next: Number(nextResult.sigma || 0) },
    { label: "0 (median)", base: Number(baseDist.median || 0), next: Number(nextDist.median || 0) },
    { label: "2σ", base: Number(baseDist["+2sigma"] || 0), next: Number(nextDist["+2sigma"] || 0) },
    { label: "3σ", base: Number(baseDist["+3sigma"] || 0), next: Number(nextDist["+3sigma"] || 0) },
  ];
  const tableRows = rows
    .map((r) => {
      const delta = r.next - r.base;
      const deltaClass = delta > 0 ? "up" : delta < 0 ? "down" : "";
      const deltaPrefix = delta > 0 ? "+" : "";
      return `<tr>
        <th>${escHtml(r.label)}</th>
        <td class="mono">${renderTeamCompareValue(r.base)}</td>
        <td class="mono">${renderTeamCompareValue(r.next)}</td>
        <td class="mono delta-cell ${deltaClass}">${deltaPrefix}${renderTeamCompareValue(delta)}</td>
      </tr>`;
    })
    .join("");
  root.innerHTML = `
    <div class="replace-compare-grid">
      <div class="replace-compare-card">
        <h4>原始结果（Top${ctx.teamIndex + 1}）</h4>
        <p class="card-meta">${formatGameText(baseResult.effect_summary || "-")}</p>
      </div>
      <div class="replace-compare-card">
        <h4>替换后结果</h4>
        <p class="card-meta">${formatGameText(nextResult.effect_summary || "-")}</p>
      </div>
    </div>
    <table class="replace-compare-table">
      <thead><tr><th>指标</th><th>原始</th><th>替换后</th><th>变化</th></tr></thead>
      <tbody>${tableRows}</tbody>
    </table>
  `;
}

async function runTeamReplaceCompare() {
  const ctx = state.teamReplace;
  if (!ctx) return;
  const uniq = new Set(ctx.currentCodes.filter(Boolean));
  if (ctx.currentCodes.length !== 5 || uniq.size !== 5) {
    ctx.compareError = "替换后队伍必须是5张不重复卡。";
    ctx.compareResult = null;
    renderTeamReplaceComparison(ctx);
    return;
  }
  const songKey = String(ctx.basePayload?.song_key || "").trim();
  if (!songKey) {
    ctx.compareError = "缺少歌曲信息，无法计算替换对比。";
    ctx.compareResult = null;
    renderTeamReplaceComparison(ctx);
    return;
  }
  const payload = {
    ...ctx.basePayload,
    mode: "single",
    song_key: songKey,
    card_codes: [...ctx.currentCodes],
    include_histogram: false,
    histogram_bins: 80,
  };
  ctx.compareLoading = true;
  ctx.compareError = "";
  renderTeamReplaceComparison(ctx);
  const token = ++teamReplaceCalcToken;
  try {
    const resp = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (token !== teamReplaceCalcToken) return;
    if (!resp.ok) throw new Error(data?.detail || "替换对比计算失败");
    const result = Array.isArray(data?.results) ? data.results[0] : null;
    if (!result) throw new Error("替换对比无结果");
    ctx.compareResult = { result, meta: data?.meta || {} };
    ctx.compareError = "";
  } catch (err) {
    if (token !== teamReplaceCalcToken) return;
    ctx.compareResult = null;
    ctx.compareError = String(err?.message || err || "替换对比失败");
  } finally {
    if (token === teamReplaceCalcToken) {
      ctx.compareLoading = false;
      renderTeamReplaceModal();
    }
  }
}

function renderTeamReplaceModal() {
  const ctx = state.teamReplace;
  if (!ctx) return;
  const team = ctx.team;
  const teamCardsWrap = $("teamReplaceCurrent");
  const hint = $("teamReplaceHint");
  const searchInput = $("teamReplaceSearch");
  const scopeSel = $("teamReplacePoolScope");
  const ownFilterSel = $("teamReplaceOwnFilter");
  const clearMembersBtn = $("teamReplaceClearMembersBtn");
  const listWrap = $("teamReplaceCandidates");
  const countNode = $("teamReplaceCount");
  const calcBtn = $("teamReplaceCalcBtn");
  if (!teamCardsWrap || !hint || !searchInput || !scopeSel || !ownFilterSel || !listWrap || !countNode) return;

  const baseCards = ctx.currentCodes.map((code) => getCardByCode(code) || (team?.team?.cards || []).find((x) => x.code === code));
  const replaceBreakdown = Array.isArray(team?.result?.member_point_breakdown) ? team.result.member_point_breakdown : [];
  const replaceBreakdownByCode = new Map(
    replaceBreakdown.map((r) => [String(r?.code || ""), r]).filter((x) => x[0])
  );
  teamCardsWrap.innerHTML = baseCards
    .map((card, idx) => {
      const code = String(card?.code || "");
      const active = idx === ctx.slotIndex ? "active" : "";
      const detail = replaceBreakdownByCode.get(code) || {};
      const displayCard = (code ? getCardByCode(code) : null) || card || {};
      const cardPointRaw = Number(detail.scene_card_total ?? detail.scene_raw_total);
      const cardPointByCard = Number(getSceneCardTotal(displayCard) || 0);
      const cardPoint = cardPointByCard > 0 ? cardPointByCard : Number.isFinite(cardPointRaw) ? cardPointRaw : 0;
      const memberPointRaw = Number(detail.member_point);
      const memberPoint = Number.isFinite(memberPointRaw)
        ? memberPointRaw
        : Number(getCurrentMemberPoint(displayCard?.member_name || card?.member_name || "") || 0);
      const totalPoint = Number(cardPoint + memberPoint);
      const voVal = pickStatValue(displayCard?.vo, detail.vo ?? card?.vo);
      const daVal = pickStatValue(displayCard?.da, detail.da ?? card?.da);
      const peVal = pickStatValue(displayCard?.pe, detail.pe ?? card?.pe);
      const owned = Boolean(code && state.ownedCodes.has(code));
      const typeRow = displayCard ? typePillsHTML(displayCard) : `<span class="type-pill P">PURPLE</span>`;
      return `
        <article class="replace-slot-card ${active}" data-replace-pick-slot="${idx}" role="button" tabindex="0" aria-label="选择第${
          idx + 1
        }位替换卡槽">
          ${cardAvatarHTML(displayCard, "sm")}
          <div class="replace-slot-body">
            <div class="replace-slot-head">
              <div class="replace-slot-name">${escHtml(displayCard?.member_name || card?.member_name || code || `#${idx + 1}`)}</div>
              <button
                type="button"
                class="replace-owned-btn ${owned ? "active" : ""}"
                data-replace-owned="${escHtml(code)}"
                title="${owned ? "已在持有池，点击移出" : "未在持有池，点击加入"}"
              >${owned ? "已持有" : "未持有"}</button>
            </div>
            <div class="replace-slot-title">${escHtml(displayCard?.title || card?.title || "-")}</div>
            <div class="meta-chip-row">
              ${typeRow}
              <span class="meta-chip">期望 ${getSkillExpectedLabel(displayCard || card)}</span>
            </div>
            <div class="replace-slot-stat mono">Vo ${nfmt(voVal)} / Da ${nfmt(daVal)} / Pe ${nfmt(peVal)}</div>
            <div class="replace-slot-stat mono">卡分 ${nfmt(cardPoint)} + 成员分 ${nfmt(memberPoint)} = ${nfmt(totalPoint)}</div>
          </div>
        </article>
      `;
    })
    .join("");
  teamCardsWrap.onclick = (ev) => {
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    const ownBtn = target.closest("button[data-replace-owned]");
    if (ownBtn) {
      const code = String(ownBtn.getAttribute("data-replace-owned") || "").trim();
      if (code) {
        toggleOwnedByCode(code);
        if (state.teamReplace) renderTeamReplaceModal();
      }
      return;
    }
    const slotCard = target.closest("[data-replace-pick-slot]");
    if (!slotCard) return;
    const idx = parseInt(String(slotCard.getAttribute("data-replace-pick-slot") || "0"), 10) || 0;
    ctx.slotIndex = Math.max(0, Math.min(4, idx));
    renderTeamReplaceModal();
  };
  teamCardsWrap.onkeydown = (ev) => {
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.tagName === "BUTTON") return;
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const slotCard = target.closest("[data-replace-pick-slot]");
    if (!(slotCard instanceof HTMLElement)) return;
    ev.preventDefault();
    const idx = parseInt(String(slotCard.getAttribute("data-replace-pick-slot") || "0"), 10) || 0;
    ctx.slotIndex = Math.max(0, Math.min(4, idx));
    renderTeamReplaceModal();
  };

  const options = getTeamReplaceFilterOptions(ctx);
  const ownFilterValue = String(ctx.ownFilter || "all");
  ctx.ownFilter = ["all", "owned", "unowned"].includes(ownFilterValue) ? ownFilterValue : "all";
  const colorKeys = new Set(options.colorOptions.map((x) => x.key));
  const groupKeys = new Set(options.groupOptions.map((x) => x.key));
  const seriesKeys = new Set(options.seriesOptions);
  ctx.filterColors = new Set([...ctx.filterColors].filter((x) => colorKeys.has(x)));
  ctx.filterGroups = new Set([...ctx.filterGroups].filter((x) => groupKeys.has(x)));
  ctx.filterSeries = new Set([...ctx.filterSeries].filter((x) => seriesKeys.has(x)));
  searchInput.value = ctx.filterText;
  scopeSel.value = ctx.poolScope;
  ownFilterSel.value = ctx.ownFilter;
  if (clearMembersBtn) {
    clearMembersBtn.disabled = ctx.filterMembers.size === 0;
    clearMembersBtn.onclick = () => {
      ctx.filterMembers.clear();
      renderTeamReplaceModal();
    };
  }
  renderExcludedFilterChips(
    "teamReplaceColorFilters",
    options.colorOptions,
    ctx.filterColors,
    "data-team-replace-color",
    "全部颜色",
    renderTeamReplaceModal
  );
  renderExcludedFilterChips(
    "teamReplaceGroupFilters",
    options.groupOptions,
    ctx.filterGroups,
    "data-team-replace-group",
    "全部团体",
    renderTeamReplaceModal
  );
  renderExcludedFilterChips(
    "teamReplaceSeriesFilters",
    options.seriesOptions,
    ctx.filterSeries,
    "data-team-replace-series",
    "全部系列",
    renderTeamReplaceModal
  );
  renderTeamReplaceMemberPicker(ctx);

  const pickedCard = baseCards[ctx.slotIndex];
  hint.textContent = `正在替换第 ${ctx.slotIndex + 1} 位：${pickedCard ? `${pickedCard.member_name}[${pickedCard.title}]` : "-"}`;

  const { total, rows } = buildTeamReplaceCandidates(ctx);
  countNode.textContent = `候选卡: ${total}（最多显示260）`;
  listWrap.innerHTML = rows.length
    ? rows
        .map((r) => {
          const c = r.card;
          const sceneCard = getSceneCardTotal(c);
          const memberPoint = getCurrentMemberPoint(c.member_name);
          const totalPower = sceneCard + memberPoint;
          return `
            <div class="replace-candidate ${r.selected ? "selected" : ""}" data-replace-choose-row="${escHtml(c.code)}">
              <div class="replace-candidate-main">
                ${cardAvatarHTML(c, "sm")}
                <div class="replace-candidate-text">
                  <div class="replace-candidate-name-row">
                    <div class="replace-candidate-name">${escHtml(c.member_name)}</div>
                  </div>
                  <div class="replace-candidate-title">${escHtml(c.title)}</div>
                  <div class="meta-chip-row">
                    ${typePillsHTML(c)}
                    <span class="meta-chip">期望 ${getSkillExpectedLabel(c)}</span>
                  </div>
                  <div class="replace-candidate-stat mono">Vo ${nfmt(c.vo)} / Da ${nfmt(c.da)} / Pe ${nfmt(c.pe)}</div>
                  <div class="replace-candidate-stat mono">卡分 ${nfmt(sceneCard)} + 成员分 ${nfmt(memberPoint)} = ${nfmt(totalPower)}</div>
                </div>
              </div>
              <div class="replace-candidate-actions">
                <button
                  type="button"
                  class="replace-owned-btn ${state.ownedCodes.has(c.code) ? "active" : ""}"
                  data-replace-owned="${escHtml(c.code)}"
                  title="${state.ownedCodes.has(c.code) ? "已在持有池，点击移出" : "未在持有池，点击加入"}"
                >${state.ownedCodes.has(c.code) ? "已持有" : "未持有"}</button>
                <button
                  type="button"
                  class="btn-sub tiny"
                  data-replace-choose="${escHtml(c.code)}"
                >${r.selected ? "已选择" : r.inTeamElsewhere ? `与第${r.existingSlotIndex + 1}位互换` : "替换为此卡"}</button>
              </div>
            </div>
          `;
        })
        .join("")
    : `<div class="card-meta">当前筛选下无候选卡。</div>`;
  listWrap.onclick = (ev) => {
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    const ownBtn = target.closest("button[data-replace-owned]");
    if (ownBtn) {
      const code = String(ownBtn.getAttribute("data-replace-owned") || "").trim();
      if (code) {
        toggleOwnedByCode(code);
        if (state.teamReplace) renderTeamReplaceModal();
      }
      return;
    }
    const chooseBtn = target.closest("button[data-replace-choose]");
    if (chooseBtn) {
      const code = String(chooseBtn.getAttribute("data-replace-choose") || "").trim();
      if (code) applyTeamReplaceChoice(ctx, code);
      return;
    }
    const row = target.closest("[data-replace-choose-row]");
    if (!row) return;
    const ignore = target.closest("a, input, select, textarea, button, label");
    if (ignore) return;
    const code = String(row.getAttribute("data-replace-choose-row") || "").trim();
    if (code) applyTeamReplaceChoice(ctx, code);
  };
  if (calcBtn) {
    calcBtn.disabled = Boolean(ctx.compareLoading);
    calcBtn.textContent = ctx.compareLoading ? "计算中..." : "计算替换对比";
  }
  renderTeamReplaceComparison(ctx);
}

function bindOptimizeResultReplaceActions() {
  const root = $("resultArea");
  if (!root) return;
  root.querySelectorAll("button[data-open-team-replace]").forEach((btn) => {
    btn.onclick = () => {
      const teamIndex = parseInt(String(btn.getAttribute("data-open-team-replace") || "-1"), 10);
      const slotIndex = parseInt(String(btn.getAttribute("data-replace-slot") || "0"), 10);
      openTeamReplaceModal(teamIndex, slotIndex);
    };
  });
}

function applyOptimizeResult(data) {
  state.lastOptimizeData = data;
  persistResultState({
    kind: "optimize",
    data,
    payload: state.lastOptimizePayload || null,
  });
  $("resultHint").textContent = "";
  $("resultArea").innerHTML = renderOptimize(data);
  refreshResultExcludeBadges();
  bindOptimizeResultExcludeActions();
  bindOptimizeResultReplaceActions();
}

async function pollOptimizeJob(jobId) {
  const stateText = $("optState");
  let resp;
  let data;
  try {
    resp = await fetch(`/api/optimize/jobs/${encodeURIComponent(jobId)}`);
    data = await resp.json();
  } catch (_) {
    stateText.textContent = "优化状态查询失败，正在重试...";
    state.optimizePollTimer = setTimeout(() => {
      pollOptimizeJob(jobId);
    }, 1200);
    return;
  }
  if (!resp.ok) {
    const raw = data?.detail || "优化任务状态查询失败";
    $("resultArea").innerHTML = `<div class="result-card">错误: ${formatOptimizeErrorMessage(raw)}</div>`;
    $("resultHint").textContent = "优化失败";
    stateText.textContent = "";
    stopOptimizeProgress(false);
    finishOptimizeJobTracking();
    return;
  }

  const status = String(data?.status || "").toLowerCase();
  setOptimizeJobStatus(status);
  if (status === "queued" || status === "running") {
    stateText.textContent = status === "queued" ? "优化任务排队中..." : "优化中...";
    if (!state.optimizeProgressTimer) startOptimizeProgress();
    state.optimizePollTimer = setTimeout(() => {
      pollOptimizeJob(jobId);
    }, 900);
    return;
  }

  if (status === "success") {
    applyOptimizeResult(data.result || {});
    setOptimizeJobStatus("success");
    stateText.textContent = "";
    stopOptimizeProgress(true);
    finishOptimizeJobTracking();
    return;
  }

  if (status === "canceled") {
    setOptimizeJobStatus("canceled");
    $("resultHint").textContent = "已取消";
    stateText.textContent = "优化已取消。";
    stopOptimizeProgress(false);
    finishOptimizeJobTracking();
    return;
  }

  setOptimizeJobStatus(status || "error");
  const hint = formatOptimizeErrorMessage(data?.error || "优化失败");
  $("resultArea").innerHTML = `<div class="result-card">错误: ${hint}</div>`;
  $("resultHint").textContent = "优化失败";
  stateText.textContent = "";
  stopOptimizeProgress(false);
  finishOptimizeJobTracking();
}

async function startOptimizeJobAndPoll(payload, slowHint = "") {
  const stateText = $("optState");
  state.optimizeStarting = true;
  setOptimizeJobStatus("queued");
  setOptimizeButtonsDisabled(true);
  stateText.textContent = `优化中...${slowHint}`;
  startOptimizeProgress();
  const resp = await fetch("/api/optimize/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "优化失败");
  const jobId = String(data?.job_id || "").trim();
  if (!jobId) throw new Error("优化任务创建失败：缺少 job_id");
  setPendingOptimizeJobId(jobId);
  setOptimizeJobStatus(String(data?.status || "queued"));
  updateOptimizeCancelButton();
  schedulePersistUiState();
  pollOptimizeJob(jobId);
}

function resumePendingOptimizeJobIfAny() {
  const jobId = getPendingOptimizeJobId();
  if (!jobId) return false;
  state.optimizeStarting = false;
  setPendingOptimizeJobId(jobId);
  setOptimizeJobStatus("queued");
  setOptimizeButtonsDisabled(true);
  $("optState").textContent = "检测到未完成优化任务，正在恢复...";
  startOptimizeProgress();
  pollOptimizeJob(jobId);
  return true;
}

async function cancelOptimizeJob() {
  const jobId = String(state.currentOptimizeJobId || "").trim();
  if (!jobId || state.optimizeCancelBusy) return;
  state.optimizeCancelBusy = true;
  updateOptimizeCancelButton();
  try {
    const resp = await fetch(`/api/optimize/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data?.detail || "取消失败");
    const status = String(data?.status || "").toLowerCase() || "canceled";
    setOptimizeJobStatus(status);
    $("resultHint").textContent = "已取消";
    $("optState").textContent = "优化已取消。";
    stopOptimizeProgress(false);
    finishOptimizeJobTracking();
  } catch (err) {
    $("optState").textContent = String(err?.message || err || "取消失败");
  } finally {
    state.optimizeCancelBusy = false;
    updateOptimizeCancelButton();
  }
}

async function runOptimize() {
  try {
    if (state.currentOptimizeJobId) {
      throw new Error("已有优化任务在运行，请等待完成。");
    }
    const payload = getOptimizePayload();
    state.lastOptimizePayload = { ...payload };
    const slowHint = payload.owned_card_codes?.length ? "" : (payload.trials > 5000 ? "（全卡池+高试行，较慢）" : "");
    await startOptimizeJobAndPoll(payload, slowHint);
  } catch (err) {
    const raw = String(err?.message || err || "");
    if (raw.includes("已有优化任务在运行")) {
      $("optState").textContent = "已有优化任务在运行，请等待当前任务完成。";
      return;
    }
    const hint = formatOptimizeErrorMessage(raw);
    $("resultArea").innerHTML = `<div class="result-card">错误: ${hint}</div>`;
    $("resultHint").textContent = "优化失败";
    $("optState").textContent = "";
    stopOptimizeProgress(false);
    finishOptimizeJobTracking();
  }
}

async function bootstrap() {
  $("runState").textContent = "加载数据中...";
  const resp = await fetch("/api/bootstrap", { cache: "no-store" });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data?.detail || "bootstrap failed");

  state.cards = (data.cards || []).map((card) => prepareCardForUi(card));
  state.cardsByCode = new Map(state.cards.map((c) => [String(c.code || ""), c]).filter((x) => x[0]));
  rebuildMemberNameAliasMap();
  state.songs = (data.songs || []).filter((s) => s.zawa_available);
  state.defaults = data.defaults || {};
  state.memberPoints = { ...(state.defaults.member_points || {}) };
  state.baseMemberPoints = { ...(state.defaults.member_points || {}) };
  state.memberPointOverrides.clear();
  state.defaultMemberPoint = DEFAULT_MEMBER_POINT;

  state.profiles = await fetchProfilesFromServer();
  if (!state.profiles[DEFAULT_PROFILE_NAME] && Object.keys(state.profiles).length === 0) {
    const bootProfile = {
      group_power: state.defaults.group_power || 1800000,
      member_points: { ...(state.defaults.member_points || {}) },
      owned_codes: [],
      exclude_codes: [],
    };
    const saved = await saveProfileToServer(DEFAULT_PROFILE_NAME, bootProfile);
    state.profiles[DEFAULT_PROFILE_NAME] = saved;
  }

  $("groupPower").value = state.defaults.group_power || 1800000;
  $("trials").value = state.defaults.trials_single || 10000;
  $("optTopN").value = state.defaults.optimize?.top_n || 5;
  $("optPoolScope").value = state.defaults.optimize?.pool_scope || "owned";
  renderProfileOptions();
  updateProfileAutoSaveButton();
  const persisted = loadPersistedUiState();
  const profileNames = Object.keys(state.profiles).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  const preferredProfile =
    (state.profiles[DEFAULT_PROFILE_NAME] ? DEFAULT_PROFILE_NAME : profileNames[0] || "").trim();
  if (preferredProfile && state.profiles[preferredProfile]) {
    applyProfile(preferredProfile, false);
    $("profileSelect").value = preferredProfile;
  } else {
    applyDefaultBaseline(false);
    $("profileSelect").value = "";
  }
  renderColorTags();
  renderGroupTags();
  renderSortTags();
  renderSeriesTags();
  initMembersFilter();
  initSkillTagFilter();
  initSongSelect();
  if (persisted) {
    applyPersistedUiState(persisted);
    updateProfileAutoSaveButton();
    renderColorTags();
    renderGroupTags();
    renderSortTags();
    renderSeriesTags();
    renderMemberPicker();
    syncSkillTagButtons();
  }
  onModeChange(true);
  syncOwnedPoolVisibility();
  renderSlots();
  renderCardList();
  refreshPoolSummary();
  const resumed = resumePendingOptimizeJobIfAny();
  const restoredResult = resumed ? false : restorePersistedResultState();
  if (!resumed && !restoredResult) {
    $("resultHint").textContent = "";
  }
  $("runState").textContent = "";
  schedulePersistUiState();
}

function bindEvents() {
  const backToTopBtn = $("backToTopBtn");
  if (backToTopBtn) {
    const updateBackToTopVisibility = () => {
      backToTopBtn.classList.toggle("is-hidden", window.scrollY < 220);
    };
    updateBackToTopVisibility();
    backToTopBtn.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    window.addEventListener("scroll", updateBackToTopVisibility, { passive: true });
  }
  syncTopbarOffset();

  const profileSelect = $("profileSelect");
  if (profileSelect) profileSelect.addEventListener("change", (e) => {
    const name = String(e.target.value || "").trim();
    if (!name) {
      applyDefaultBaseline();
      return;
    }
    if (!state.profiles[name]) {
      setProfileHint(`读取失败：账号「${name}」不存在。`);
      return;
    }
    applyProfile(name);
    profileSelect.value = name;
  });
  const profileActionDrawerToggle = $("profileActionDrawerToggle");
  if (profileActionDrawerToggle) profileActionDrawerToggle.addEventListener("click", (e) => {
    e.stopPropagation();
    const expanded = profileActionDrawerToggle.getAttribute("aria-expanded") === "true";
    setProfileActionDrawerOpen(!expanded);
  });
  const profileActionDrawerMenu = $("profileActionDrawerMenu");
  if (profileActionDrawerMenu) {
    profileActionDrawerMenu.addEventListener("click", (e) => {
      e.stopPropagation();
    });
  }
  document.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof Element)) return;
    if (target.closest("#profileActionDrawer")) return;
    closeProfileActionDrawer();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeProfileActionDrawer();
  });
  const saveProfileBtn = $("saveProfileBtn");
  if (saveProfileBtn) saveProfileBtn.addEventListener("click", async () => {
    closeProfileActionDrawer();
    try {
      const name = String($("profileSelect").value || state.activeProfile || "").trim();
      if (!name) throw new Error("请先选择一个账号再保存");
      await saveCurrentToExistingProfile(name);
    } catch (err) {
      setProfileHint(`保存失败：${err.message || err}`);
    }
  });
  const exportProfilesBtn = $("exportProfilesBtn");
  if (exportProfilesBtn) exportProfilesBtn.addEventListener("click", async () => {
    closeProfileActionDrawer();
    try {
      const selectedName = getSelectedProfileName();
      const exportName = selectedName && state.profiles[selectedName] ? selectedName : "";
      const payload = await exportProfilesFromServer(exportName);
      const stamp = makeTimestampTag();
      const scope = exportName ? normalizeDownloadFilePart(exportName, "profile") : "profiles";
      const fileName = `uoa_${scope}_${stamp}.json`;
      downloadJsonAsFile(fileName, payload);
      setProfileHint(exportName ? `已导出账号「${exportName}」。` : "已导出全部账号资料。");
    } catch (err) {
      setProfileHint(`导出失败：${err.message || err}`);
    }
  });
  const importProfilesBtn = $("importProfilesBtn");
  if (importProfilesBtn) importProfilesBtn.addEventListener("click", () => {
    closeProfileActionDrawer();
    const input = $("importProfilesFileInput");
    if (!input) return;
    input.value = "";
    input.click();
  });
  const importProfilesFileInput = $("importProfilesFileInput");
  if (importProfilesFileInput) importProfilesFileInput.addEventListener("change", async (ev) => {
    const input = ev.target;
    if (!(input instanceof HTMLInputElement)) return;
    const file = input.files && input.files[0] ? input.files[0] : null;
    if (!file) return;
    try {
      const rawText = await file.text();
      const payload = JSON.parse(String(rawText || "").replace(/^\uFEFF/, ""));
      const data = await importProfilesToServer(payload);
      const loadedName = await reloadProfilesFromServer(String(data?.active_profile || "").trim());
      scheduleWorkspacePanelHeightSync();
      schedulePersistUiState();
      const importedCount = Number(data?.imported_count || 0);
      const createdCount = Array.isArray(data?.created) ? data.created.length : 0;
      const updatedCount = Array.isArray(data?.updated) ? data.updated.length : 0;
      const skippedCount = Array.isArray(data?.skipped) ? data.skipped.length : 0;
      const loadedText = loadedName ? `，已读取「${loadedName}」` : "";
      setProfileHint(`导入完成：新增 ${createdCount}，覆盖 ${updatedCount}，跳过 ${skippedCount}（共 ${importedCount}）${loadedText}。`);
    } catch (err) {
      setProfileHint(`导入失败：${err.message || err}`);
    } finally {
      input.value = "";
    }
  });
  const toggleProfileAutoSaveBtn = $("toggleProfileAutoSaveBtn");
  if (toggleProfileAutoSaveBtn) toggleProfileAutoSaveBtn.addEventListener("click", () => {
    setProfileAutoSaveEnabled(!state.profileAutoSaveEnabled);
  });
  const showProfileBackupsBtn = $("showProfileBackupsBtn");
  if (showProfileBackupsBtn) showProfileBackupsBtn.addEventListener("click", async () => {
    closeProfileActionDrawer();
    try {
      await openProfileBackupsModal();
    } catch (err) {
      setProfileHint(`读取备份失败：${err.message || err}`);
    }
  });
  const closeProfileBackupsBtn = $("closeProfileBackupsBtn");
  if (closeProfileBackupsBtn) closeProfileBackupsBtn.addEventListener("click", closeProfileBackupsModal);
  document.querySelectorAll("[data-close-profile-backups-modal]").forEach((el) => {
    el.addEventListener("click", closeProfileBackupsModal);
  });
  const profileBackupsList = $("profileBackupsList");
  if (profileBackupsList) profileBackupsList.addEventListener("click", async (ev) => {
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    const restoreBtn = target.closest("button[data-restore-profile-backup]");
    const deleteBtn = target.closest("button[data-delete-profile-backup]");
    if (!restoreBtn && !deleteBtn) return;
    const actionBtn = restoreBtn || deleteBtn;
    const backupFile = String(
      actionBtn?.getAttribute("data-restore-profile-backup") || actionBtn?.getAttribute("data-delete-profile-backup") || ""
    ).trim();
    const profileName = String(state.profileBackupsName || getSelectedProfileName()).trim();
    if (!profileName || !backupFile) return;
    actionBtn.disabled = true;
    try {
      if (restoreBtn) {
        await restoreProfileByBackup(profileName, backupFile);
      } else if (deleteBtn) {
        const ok = window.confirm("确认删除这条备份吗？\n此操作不可撤销。");
        if (!ok) return;
        await deleteProfileBackupFromServer(profileName, backupFile);
        setProfileHint(`已删除账号「${profileName}」的一条备份。`);
      }
      const backups = await fetchProfileBackupsFromServer(profileName, 40);
      renderProfileBackupsModal(profileName, backups);
    } catch (err) {
      setProfileHint(`${restoreBtn ? "恢复" : "删除"}失败：${err?.message || err}`);
    } finally {
      actionBtn.disabled = false;
    }
  });
  const deleteProfileBtn = $("deleteProfileBtn");
  if (deleteProfileBtn) deleteProfileBtn.addEventListener("click", async () => {
    closeProfileActionDrawer();
    const name = String($("profileSelect").value || state.activeProfile || "").trim();
    if (!name) return;
    try {
      await deleteProfile(name);
    } catch (err) {
      setProfileHint(`删除失败：${err.message || err}`);
    }
  });
  const openProfileBuilderBtn = $("openProfileBuilderBtn");
  if (openProfileBuilderBtn) openProfileBuilderBtn.addEventListener("click", () => {
    closeProfileActionDrawer();
    openProfileBuilderModal();
  });
  const closeProfileBuilderBtn = $("closeProfileBuilderBtn");
  if (closeProfileBuilderBtn) closeProfileBuilderBtn.addEventListener("click", closeProfileBuilderModal);
  document.querySelectorAll("[data-close-profile-modal]").forEach((el) => {
    el.addEventListener("click", closeProfileBuilderModal);
  });
  const saveProfileBuilderBtn = $("saveProfileBuilderBtn");
  if (saveProfileBuilderBtn) saveProfileBuilderBtn.addEventListener("click", async () => {
    try {
      await saveProfileFromBuilder();
    } catch (err) {
      setProfileHint(`新建账号失败：${err.message || err}`);
    }
  });
  const closeExcludedModalBtn = $("closeExcludedModalBtn");
  if (closeExcludedModalBtn) closeExcludedModalBtn.addEventListener("click", closeExcludedModal);
  document.querySelectorAll("[data-close-excluded-modal]").forEach((el) => {
    el.addEventListener("click", closeExcludedModal);
  });
  const restoreAllExcludedBtn = $("restoreAllExcludedBtn");
  if (restoreAllExcludedBtn) restoreAllExcludedBtn.addEventListener("click", () => {
    state.excludedCodes.clear();
    applyExcludedPoolChange("已全部恢复排除池。");
  });
  const excludedSearch = $("excludedSearch");
  if (excludedSearch) excludedSearch.addEventListener("input", (e) => {
    state.excludedFilterText = String(e.target.value || "").trim();
    renderExcludedModal();
  });
  const closeTeamReplaceModalBtn = $("closeTeamReplaceModalBtn");
  if (closeTeamReplaceModalBtn) closeTeamReplaceModalBtn.addEventListener("click", closeTeamReplaceModal);
  document.querySelectorAll("[data-close-team-replace-modal]").forEach((el) => {
    el.addEventListener("click", closeTeamReplaceModal);
  });
  const teamReplaceSearch = $("teamReplaceSearch");
  if (teamReplaceSearch) teamReplaceSearch.addEventListener("input", (e) => {
    if (!state.teamReplace) return;
    state.teamReplace.filterText = String(e.target.value || "").trim();
    renderTeamReplaceModal();
  });
  const teamReplacePoolScope = $("teamReplacePoolScope");
  if (teamReplacePoolScope) teamReplacePoolScope.addEventListener("change", (e) => {
    if (!state.teamReplace) return;
    state.teamReplace.poolScope = String(e.target.value || "all") === "owned" ? "owned" : "all";
    renderTeamReplaceModal();
  });
  const teamReplaceOwnFilter = $("teamReplaceOwnFilter");
  if (teamReplaceOwnFilter) teamReplaceOwnFilter.addEventListener("change", (e) => {
    if (!state.teamReplace) return;
    const val = String(e.target.value || "all");
    state.teamReplace.ownFilter = ["all", "owned", "unowned"].includes(val) ? val : "all";
    renderTeamReplaceModal();
  });
  const teamReplaceCalcBtn = $("teamReplaceCalcBtn");
  if (teamReplaceCalcBtn) teamReplaceCalcBtn.addEventListener("click", runTeamReplaceCompare);
  const teamReplaceResetBtn = $("teamReplaceResetBtn");
  if (teamReplaceResetBtn) teamReplaceResetBtn.addEventListener("click", () => {
    if (!state.teamReplace) return;
    state.teamReplace.currentCodes = [...state.teamReplace.baseCodes];
    state.teamReplace.compareResult = null;
    state.teamReplace.compareError = "";
    renderTeamReplaceModal();
  });

  ["qSearch"].forEach((id) => {
    $(id).addEventListener("input", scheduleRenderCardList);
    $(id).addEventListener("change", scheduleRenderCardList);
  });
  const cardListScopeEl = $("cardListScope");
  if (cardListScopeEl) {
    cardListScopeEl.addEventListener("change", () => {
      renderCardList();
      refreshPoolSummary();
      schedulePersistUiState();
    });
  }
  const mode = $("mode");
  if (mode) mode.addEventListener("change", onModeChange);
  const groupPower = $("groupPower");
  if (groupPower) groupPower.addEventListener("change", () => {
    if (state.activeProfile) scheduleActiveProfileAutoSave("group 总综合力已修改");
  });
  const optPoolScope = $("optPoolScope");
  if (optPoolScope) optPoolScope.addEventListener("change", () => {
    syncOwnedPoolVisibility();
    refreshPoolSummary();
  });
  const resetFiltersQuickBtn = $("resetFiltersQuick");
  if (resetFiltersQuickBtn) resetFiltersQuickBtn.addEventListener("click", resetFiltersQuick);
  const runOptimizeBtn = $("runOptimizeBtn");
  if (runOptimizeBtn) runOptimizeBtn.addEventListener("click", runOptimize);
  const optCancelBtn = $("optCancelBtn");
  if (optCancelBtn) optCancelBtn.addEventListener("click", cancelOptimizeJob);
  const runOptimizeQuickBtn = $("runOptimizeQuickBtn");
  if (runOptimizeQuickBtn) runOptimizeQuickBtn.addEventListener("click", () => {
    $("mode").value = "single";
    onModeChange();
    $("optPoolScope").value = "all";
    $("optTopN").value = "5";
    $("trials").value = String(state.defaults?.optimize?.trials_recommended_all || 3000);
    state.centerCandidateCodes.clear();
    state.mustIncludeCodes.clear();
    syncOwnedPoolVisibility();
    refreshPoolSummary();
    renderCardList();
    runOptimize();
  });
  document.querySelectorAll(".workspace-left .filter-fold").forEach((fold) => {
    fold.addEventListener("toggle", () => {
      scheduleWorkspacePanelHeightSync();
      window.setTimeout(scheduleWorkspacePanelHeightSync, 60);
      schedulePersistUiState();
    });
  });

  const persistFromWorkspaceEvent = (e) => {
    const target = e.target;
    if (!(target instanceof Element)) return;
    if (!target.closest(".workspace-shell")) return;
    schedulePersistUiState();
  };
  document.addEventListener("change", persistFromWorkspaceEvent);
  document.addEventListener("input", persistFromWorkspaceEvent);
  document.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof Element)) return;
    if (!target.closest(".workspace-shell")) return;
    if (!target.closest("button, .member-chip, .skill-chip, .slot, summary")) return;
    schedulePersistUiState();
  });

  window.addEventListener("resize", () => {
    scheduleWorkspacePanelHeightSync();
    syncTopbarOffset();
  });
  window.addEventListener("load", () => {
    scheduleWorkspacePanelHeightSync();
    syncTopbarOffset();
  });
  window.addEventListener("beforeunload", persistUiStateNow);
  if (document.fonts?.ready) {
    document.fonts.ready
      .then(() => {
        scheduleWorkspacePanelHeightSync();
        syncTopbarOffset();
      })
      .catch(() => {});
  }
}

async function main() {
  bindEvents();
  onModeChange();
  try {
    await bootstrap();
    scheduleWorkspacePanelHeightSync();
    syncTopbarOffset();
  } catch (err) {
    $("resultArea").innerHTML = `<div class="result-card">初始化失败: ${err.message || err}</div>`;
    $("runState").textContent = "";
  }
}

main();
