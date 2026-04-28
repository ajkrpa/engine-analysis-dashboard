function bindEvents() {
  $("upload-data").addEventListener("change", async (e) => {
    const pre = getDashboardConfigObject();
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    const datasets = [];
    for (const file of files) {
      const text = await file.text();
      const parsed = Papa.parse(text, { header: true, dynamicTyping: false, skipEmptyLines: true });
      const raw = (parsed.data || []).map(stripBomFromRowKeys);
      const rows = parseTimeSeconds(raw);
      datasets.push(rows);
    }
    const merged = mergeDatasets(datasets);
    state.dataset = merged;
    state.perf = null;
    state.perfMeta = null;
    if (getAnalysisHintEl()) getAnalysisHintEl().textContent = "";
    updateMdotDisplays(null);
    const { tMin, tMax } = merged;
    const tPair = mergeSavedTimeOnUpload(pre, "time-start", "time-end", tMin, tMax);
    const aPair = mergeSavedTimeOnUpload(pre, "analysis-time-start", "analysis-time-end", tMin, tMax);
    $("time-start").value = tPair.lo;
    $("time-end").value = tPair.hi;
    $("analysis-time-start").value = aPair.lo;
    $("analysis-time-end").value = aPair.hi;
    initTimeseriesNoui(merged);
    initAnalysisNoui(merged);
    const cols = numericColumns(merged.rows);
    const preData = (pre.dataChannels || []).filter((c) => cols.includes(c));
    state.selectedChannels = preData.length ? preData.slice() : [];
    makeCheckboxList($("data-checklist"), cols, state.selectedChannels, () => {
      state.selectedChannels = Array.from(document.querySelectorAll("#data-checklist input:checked")).map((i) => i.value);
      drawTimeseries();
      scheduleConfigSave();
    });
    initThrustChannelPicker(cols, pre.thrust);
    const selectIds = [
      "chamber-pressure-select", "fuel-weight-select", "ox-weight-select",
      "venturi-fuel-inlet-select", "venturi-fuel-throat-select", "venturi-ox-inlet-select", "venturi-ox-throat-select",
    ];
    selectIds.forEach((id) => {
      setSelectOptions($(id), cols);
      if (pre?.e?.[id] && optionListContains($(id), pre.e[id])) $(id).value = String(pre.e[id]);
    });
    makeCheckboxList($("analysis-metrics-checklist"), METRICS, getMetricsInitialSelected(pre), () => {
      drawAnalysisGraph();
      scheduleConfigSave();
    });
    $("upload-filenames").textContent = `Loaded: ${files.map((f) => f.name).join(", ")}`;
    drawTimeseries();
    drawAnalysisGraph();
    scheduleConfigSave();
  });

  $("clear-channels-button").addEventListener("click", () => {
    state.selectedChannels = [];
    document.querySelectorAll("#data-checklist input").forEach((i) => { i.checked = false; });
    drawTimeseries();
    scheduleConfigSave();
  });
  $("reset-button").addEventListener("click", () => {
    if (!state.dataset) return;
    const { tMin, tMax } = state.dataset;
    const el = $("time-range-noui");
    if (el?.noUiSlider) {
      const { startLo, startHi } = nudgeTimeRange(tMin, tMax);
      el.noUiSlider.set([startLo, startHi]);
    } else {
      $("time-start").value = tMin;
      $("time-end").value = tMax;
    }
    drawTimeseries();
    scheduleConfigSave();
  });
  $("analysis-reset-button").addEventListener("click", () => {
    if (!state.dataset) return;
    const { tMin, tMax } = state.dataset;
    const el = $("analysis-time-range-noui");
    if (el?.noUiSlider) {
      const { startLo, startHi } = nudgeTimeRange(tMin, tMax);
      el.noUiSlider.set([startLo, startHi]);
    } else {
      $("analysis-time-start").value = tMin;
      $("analysis-time-end").value = tMax;
    }
    drawAnalysisGraph();
    scheduleConfigSave();
  });
  ["time-start", "time-end"].forEach((id) => $(id).addEventListener("input", () => {
    drawTimeseries();
    syncTimeseriesNouiFromInputs();
    scheduleConfigSave();
  }));
  ["analysis-regression", "analysis-show-burn"].forEach((id) => $(id).addEventListener("input", () => {
    drawTimeseries();
    scheduleConfigSave();
  }));
  ["analysis-time-start", "analysis-time-end"].forEach((id) => $(id).addEventListener("input", () => {
    drawAnalysisGraph();
    syncAnalysisNouiFromInputs();
    scheduleConfigSave();
  }));
  $("analysis-calculate-button").addEventListener("click", computePerformance);
  $("clear-plot-metrics-button").addEventListener("click", () => {
    document.querySelectorAll("#analysis-metrics-checklist input").forEach((i) => { i.checked = false; });
    drawAnalysisGraph();
    scheduleConfigSave();
  });
  $("save-data-graph-btn").addEventListener("click", () => {
    openSavePlotImageModal("data-graph", "timeseries", "Save timeseries image");
  });
  $("save-analysis-graph-btn").addEventListener("click", () => {
    openSavePlotImageModal("analysis-graph", "performance_analysis", "Save analysis image");
  });
  $("save-plot-confirm-btn").addEventListener("click", () => { runSavePlotImageDownload(); });

  [
    "input-throat-area",
    "chamber-pressure-select",
    "analysis-mass-flow-source",
    "fuel-weight-select",
    "ox-weight-select",
    "venturi-fuel-rho-constant",
    "venturi-ox-rho-constant",
    "venturi-fuel-cda",
    "venturi-fuel-beta",
    "venturi-ox-cda",
    "venturi-ox-beta",
  ].forEach((id) => { $(id).addEventListener("change", () => { maybeRecomputeAnalysis(); scheduleConfigSave(); }); });
  [
    "venturi-fuel-inlet-select", "venturi-fuel-throat-select",
    "venturi-ox-inlet-select", "venturi-ox-throat-select",
  ].forEach((id) => $(id).addEventListener("change", () => { maybeRecomputeAnalysis(); scheduleConfigSave(); }));
  const _cfg0 = loadSavedDashboardConfig();
  if (_cfg0) {
    state.pendingDashConfig = _cfg0;
    applyDashboardConfigFields(_cfg0);
    if (Array.isArray(_cfg0.dataChannels)) state.selectedChannels = _cfg0.dataChannels.slice();
    if (Array.isArray(_cfg0.thrust)) state.selectedThrustChannels = _cfg0.thrust.slice();
  }
  makeCheckboxList($("analysis-metrics-checklist"), METRICS, getMetricsInitialSelected(_cfg0), () => {
    drawAnalysisGraph();
    scheduleConfigSave();
  });
}

bindEvents();
initializeEmptyPlots();
