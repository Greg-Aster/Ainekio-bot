/* Optional experimental panel. Ordinary motion buttons keep their owners. */
(function () {
  "use strict";
  const panel = document.createElement("section");
  panel.className = "control-section freestyle-panel";
  panel.dataset.motionSystem = "freestyle";
  panel.hidden = !document.getElementById("motion-system").checked;
  panel.innerHTML = `<section class="freestyle-request">
    <label>Requested movement <textarea data-field="request" placeholder="Wave hello, then stretch both front legs"></textarea></label>
    <button data-action="generate" type="button">Generate only</button>
    <button data-action="execute" type="button">Generate and perform</button>
    </section>
    <div data-freestyle-training></div>
    <details class="freestyle-folder"><summary>Latest result</summary>
      <button data-action="refresh" type="button">Refresh result</button>
      <button data-action="edit-training" type="button">Edit in training library</button>
      <button data-action="save" type="button">Save trial data</button>
      <pre data-field="result" aria-live="polite"></pre>
    </details>
    <details class="freestyle-folder" data-field="trials"><summary>Saved motion trials</summary>
      <button data-action="corrections" type="button">Refresh saved trials</button>
      <label>Proposed motion <select data-field="correction"></select></label>
      <button data-action="test-correction" type="button">Perform selected correction</button>
      <p data-field="recording" aria-live="polite"></p>
      <label>What happened? <select data-field="outcome">
        <option value="success">Performed correctly</option>
        <option value="partial">Partly correct</option>
        <option value="incorrect">Incorrect movement</option>
      </select></label>
      <label>Observed result or correction <textarea data-field="note" placeholder="Describe what moved incorrectly and what you expected"></textarea></label>
      <details><summary>Attach corrected program JSON (optional)</summary>
        <label>Corrected program <textarea data-field="corrected-program" rows="6" spellcheck="false" placeholder='[{"name":"stand","arguments":{}}]'></textarea></label>
      </details>
      <button data-action="review" type="button">Save motion review</button>
      <p data-field="review" aria-live="polite"></p>
    </details>
    <details class="freestyle-folder"><summary>Freestyle settings</summary>
      <label>Generator address <input data-field="endpoint" value="http://127.0.0.1:8794"></label>
      <label class="freestyle-recovery"><input data-field="recovery" type="checkbox"> Respond to body events</label>
      <p data-field="settings-status" role="status"></p>
    </details>`;
  document.querySelector('[data-workspace-panel="poses"]').append(panel);
  const field = name => panel.querySelector(`[data-field="${name}"]`);
  const jobs = new Map();
  const latestJobs = new Map();
  let displayedRobot = null;
  let settingsEdited = false;
  let displayedSettings = null;
  panel.addEventListener("input", event => {
    if (["endpoint", "recovery"].includes(event.target.dataset.field)) settingsEdited = true;
  });
  panel.addEventListener("change", async event => {
    if (!["endpoint", "recovery"].includes(event.target.dataset.field)) return;
    settingsEdited = true;
    const robot = document.getElementById("robot-select").value;
    try { await saveSettings(robot); }
    catch (error) {
      if (robot === document.getElementById("robot-select").value) field("settings-status").textContent = "Not saved: " + error.message;
    }
  });
  window.renderFreestyleStatus = (status, robot) => {
    const recording = status?.recording;
    field("recording").textContent = recording?.error
      ? `Recording error: ${recording.error}`
      : recording?.enabled ? `Recording commands, generated motions and received feedback automatically (${recording.written} records saved).`
      : "Motion recording is not active.";
    const settings = status?.settings?.[robot] || {};
    const serialized = JSON.stringify(settings);
    if (displayedRobot !== robot || (!settingsEdited && displayedSettings !== serialized)) {
      field("endpoint").value = settings.endpoint || "http://127.0.0.1:8794";
      field("recovery").checked = settings.recover_events === true;
      settingsEdited = false;
      displayedSettings = serialized;
    }
    const latest = Object.values(status?.jobs || {}).filter(job => job.robot_id === robot).at(-1);
    if (latest) {
      jobs.set(robot, latest.id);
      latestJobs.set(robot, latest);
      field("result").textContent = JSON.stringify(latest,null,2);
    } else if (displayedRobot !== robot) {
      field("result").textContent = "";
    }
    if (displayedRobot !== robot) {
      field("review").textContent = "";
      field("settings-status").textContent = "";
    }
    displayedRobot = robot;
  };
  async function post(payload) {
    const session = await fetch("/api/session").then(r => r.json());
    const response = await fetch("/api/freestyle", {method:"POST", headers:{
      "Content-Type":"application/json", "X-Ainekio-CSRF":session.csrf}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || response.statusText);
    return result;
  }
  async function saveSettings(robot) {
    const endpoint = field("endpoint").value, recovery = field("recovery").checked;
    field("settings-status").textContent = "Saving settings…";
    const result = await post({operation:"configure",robot_id:robot,endpoint,recover_events:recovery});
    if (robot === document.getElementById("robot-select").value &&
        endpoint === field("endpoint").value && recovery === field("recovery").checked) {
      settingsEdited = false;
      displayedSettings = null;
      field("settings-status").textContent = "Settings saved.";
    }
    return result;
  }
  async function loadCorrections(robot) {
    const result = await post({operation:"corrections",robot_id:robot});
    field("correction").replaceChildren();
    for (const correction of result.corrections) {
      const option = document.createElement("option");
      option.value = correction.review_id;
      option.textContent = correction.title || correction.request;
      field("correction").append(option);
    }
    field("correction").dataset.robot = robot;
    return result;
  }
  field("trials").addEventListener("toggle", async () => {
    if (!field("trials").open) return;
    try { await loadCorrections(document.getElementById("robot-select").value); }
    catch (error) { field("review").textContent = error.message; }
  });
  panel.addEventListener("click", async event => {
    const action = event.target.dataset.action;
    if (!action) return;
    const robot = document.getElementById("robot-select").value;
    try {
      let result;
      if (action === "refresh") {
        const status = await fetch("/api/status").then(r => r.json());
        result = status.freestyle?.jobs?.[jobs.get(robot)] || status.freestyle;

      } else if (action === "corrections") {
        result = await loadCorrections(robot);
      } else if (action === "test-correction") {
        if (field("correction").dataset.robot !== robot || !field("correction").value) {
          throw new Error("Load and select a saved correction for this robot first.");
        }
        result = await post({operation:"test-correction",robot_id:robot,review_id:field("correction").value});
        jobs.set(robot,result.job_id);
      } else if (action === "edit-training") {
        if (typeof window.openFreestyleDraftInLibrary !== "function") {
          throw new Error("Training library editor is not loaded.");
        }
        const jobId = jobs.get(robot);
        if (!jobId) throw new Error("Generate a motion first.");
        const summary = latestJobs.get(robot);
        let fullJob = null;
        if (!summary?.latest_generation?.program) {
          const trial = await post({operation:"trial",robot_id:robot,job_id:jobId});
          fullJob = trial.job;
        }
        const sourceJob = fullJob || summary;
        const program = fullJob?.programs?.at(-1)?.program || summary?.latest_generation?.program;
        if (!Array.isArray(program) || !program.length) {
          throw new Error("No generated motion program is available for this job yet.");
        }
        const title = sourceJob?.request || field("request").value.trim() || "Generated motion";
        let queryObject = {request: title};
        if (fullJob?.event) {
          const ev = fullJob.event.data ? {type: fullJob.event.data.kind, ...fullJob.event.data} : fullJob.event;
          queryObject = {
            request: title,
            event: ev,
            observation: fullJob.initial_observation || fullJob.observation || null,
            history: fullJob.history || [],
            ...(fullJob.motion_goal ? {motion_goal: fullJob.motion_goal} : {})
          };
        }
        window.openFreestyleDraftInLibrary({title, query: JSON.stringify(queryObject), program});
        result = {opened_in_training_library: true, job_id: jobId, operations: program.length};
      } else if (action === "review") {
        const correctedRaw = field("corrected-program").value.trim();
        const extra = correctedRaw ? {corrected_program: JSON.parse(correctedRaw)} : {};
        result = await post({operation:"review",robot_id:robot,job_id:jobs.get(robot),
          outcome:field("outcome").value,note:field("note").value,...extra});
        field("review").textContent = result.saved ? "Review saved. Successfully reviewed trials are included in Export training data; recording a trial does not train the model." : "Review was not saved; check recording status.";
      } else if (action === "save") {
        result = await post({operation:"trial",robot_id:robot,job_id:jobs.get(robot)});
        const url = URL.createObjectURL(new Blob([JSON.stringify(result,null,2)], {type:"application/json"}));
        const link = document.createElement("a");
        link.href=url;link.download=`freestyle-${result.job.id}.json`;link.click();
        URL.revokeObjectURL(url);
      } else {
        if (settingsEdited) await saveSettings(robot);
        result = await post({robot_id:robot,request:field("request").value,execute:action === "execute"});
        jobs.set(robot,result.job_id);
      }
      field("result").textContent = JSON.stringify(result,null,2);
    } catch (error) { field("result").textContent = error.message; }
  });
}());
