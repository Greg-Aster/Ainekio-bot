/* Optional experimental panel. Ordinary motion buttons keep their owners. */
(function () {
  "use strict";
  const panel = document.createElement("section");
  panel.className = "control-section freestyle-panel";
  panel.dataset.workspacePanel = "poses";
  panel.hidden = true;
  panel.innerHTML = `<h2>Freestyle motions (experimental)</h2>
    <label>Generator address <input data-field="endpoint" value="http://127.0.0.1:8794"></label>
    <label class="freestyle-recovery"><input data-field="recovery" type="checkbox"> Let Freestyle respond to body events</label>
    <button data-action="configure" type="button">Apply Freestyle settings</button>
    <label>Requested movement <textarea data-field="request" placeholder="Wave hello, then stretch both front legs"></textarea></label>
    <button data-action="generate" type="button">Generate only</button>
    <button data-action="execute" type="button">Generate and perform</button>
    <button data-action="refresh" type="button">Refresh result</button>
    <button data-action="save" type="button">Save trial data</button>
    <button data-action="corrections" type="button">Load saved corrections</button>
    <label>Corrected motion <select data-field="correction"></select></label>
    <button data-action="test-correction" type="button">Test selected correction</button>
    <p>Test the saved program, then record how it looked before adding it to training data.</p>
    <p data-field="recording" aria-live="polite"></p>
    <label>What happened? <select data-field="outcome">
      <option value="success">Performed correctly</option>
      <option value="partial">Partly correct</option>
      <option value="incorrect">Incorrect movement</option>
    </select></label>
    <label>Observed result or correction <textarea data-field="note" placeholder="Describe what moved incorrectly and what you expected"></textarea></label>
    <button data-action="review" type="button">Save motion review</button>
    <p data-field="review" aria-live="polite"></p>
    <pre data-field="result" aria-live="polite"></pre>`;
  document.querySelector('[data-workspace-panel="poses"]').after(panel);
  const field = name => panel.querySelector(`[data-field="${name}"]`);
  const jobs = new Map();
  let displayedRobot = null;
  let settingsEdited = false;
  let displayedSettings = null;
  panel.addEventListener("input", event => {
    if (["endpoint", "recovery"].includes(event.target.dataset.field)) settingsEdited = true;
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
      field("result").textContent = JSON.stringify(latest,null,2);
    } else if (displayedRobot !== robot) {
      field("result").textContent = "";
    }
    if (displayedRobot !== robot) field("review").textContent = "";
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
  panel.addEventListener("click", async event => {
    const action = event.target.dataset.action;
    if (!action) return;
    const robot = document.getElementById("robot-select").value;
    try {
      let result;
      if (action === "refresh") {
        const status = await fetch("/api/status").then(r => r.json());
        result = status.freestyle?.jobs?.[jobs.get(robot)] || status.freestyle;
      } else if (action === "configure") {
        result = await post({operation:"configure",robot_id:robot,endpoint:field("endpoint").value,
          recover_events:field("recovery").checked});
        settingsEdited = false;
        displayedSettings = null;
      } else if (action === "corrections") {
        result = await post({operation:"corrections",robot_id:robot});
        field("correction").replaceChildren();
        for (const correction of result.corrections) {
          const option = document.createElement("option");
          option.value = correction.review_id;
          option.textContent = correction.request;
          field("correction").append(option);
        }
        field("correction").dataset.robot = robot;
      } else if (action === "test-correction") {
        if (field("correction").dataset.robot !== robot || !field("correction").value) {
          throw new Error("Load and select a saved correction for this robot first.");
        }
        result = await post({operation:"test-correction",robot_id:robot,review_id:field("correction").value});
        jobs.set(robot,result.job_id);
      } else if (action === "review") {
        result = await post({operation:"review",robot_id:robot,job_id:jobs.get(robot),
          outcome:field("outcome").value,note:field("note").value});
        field("review").textContent = result.saved ? "Review saved with this motion's evidence." : "Review was not saved; check recording status.";
      } else if (action === "save") {
        result = await post({operation:"trial",robot_id:robot,job_id:jobs.get(robot)});
        const url = URL.createObjectURL(new Blob([JSON.stringify(result,null,2)], {type:"application/json"}));
        const link = document.createElement("a");
        link.href=url;link.download=`freestyle-${result.job.id}.json`;link.click();
        URL.revokeObjectURL(url);
      } else {
        if (settingsEdited) {
          await post({operation:"configure",robot_id:robot,endpoint:field("endpoint").value,
            recover_events:field("recovery").checked});
          settingsEdited = false;
          displayedSettings = null;
        }
        result = await post({robot_id:robot,request:field("request").value,execute:action === "execute"});
        jobs.set(robot,result.job_id);
      }
      field("result").textContent = JSON.stringify(result,null,2);
    } catch (error) { field("result").textContent = error.message; }
  });
}());
