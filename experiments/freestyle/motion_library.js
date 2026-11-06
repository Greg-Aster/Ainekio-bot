/* Editable examples share the normal Body Control executor and status stream. */
(function () {
  "use strict";
  const host = document.querySelector("[data-freestyle-training]");
  const panel = document.createElement("section");
  panel.className = "motion-training-library";
  panel.dataset.motionSystem = "freestyle";
  panel.hidden = !document.getElementById("motion-system").checked;
  const pagination = `<div class="motion-library-pages" aria-label="Training data pages">
    <button type="button" data-action="first">First</button>
    <button type="button" data-action="previous">Previous</button>
    <span data-field="page" aria-live="polite"></span>
    <button type="button" data-action="next">Next</button>
    <button type="button" data-action="last">Last</button>
  </div>`;
  panel.innerHTML = `<details data-field="browser" open><summary>Training data</summary>
      <p class="field-help">Editable examples for future training exports. Saving does not update the loaded model.</p>
      <form data-field="search-form" class="motion-library-search">
        <label>Find a motion <input type="search" data-field="search" placeholder="Title, request or motion family"></label>
        <button type="submit">Search</button>
        <a href="/api/motion-library/export" download="motion-training-library.zip">Export training data</a>
      </form>
      <label>Sort by <select data-field="sort">
        <option value="name_asc">Name — A to Z</option>
        <option value="name_desc">Name — Z to A</option>
        <option value="added_desc" selected>Date added — newest first</option>
        <option value="added_asc">Date added — oldest first</option>
        <option value="edited_desc">Last edited — newest first</option>
        <option value="edited_asc">Last edited — oldest first</option>
      </select></label>
      <p data-field="list-status" role="status"></p>
      ${pagination}
      <ul data-field="list" class="motion-library-list" aria-label="Training examples"></ul>
      ${pagination}
      <fieldset data-field="editor" hidden>
        <legend>Edit training example</legend>
        <div class="motion-library-actions">
          <button type="button" data-action="run">Perform example</button>
          <button type="button" data-action="pause">Pause</button>
          <button type="button" data-action="release">Release servos</button>
          <button type="button" data-action="run-step">Perform from selected operation</button>
          <button type="button" data-action="save">Replace example</button>
        </div>
        <p data-field="edit-status" role="status"></p>
        <p data-field="play-status" role="status"></p>
        <div class="motion-edit-workspace">
          <section><h4>Playback</h4>
            <label class="motion-system-toggle motion-code-toggle"><span>Readable</span>
              <input data-field="raw-training" type="checkbox" role="switch" aria-label="Show actual training data" checked>
              <span class="motion-system-track" aria-hidden="true"></span><span>Actual training data</span>
            </label>
            <p data-field="format-status" role="status"></p>
            <ol data-field="operations" class="motion-operation-list"></ol>
            <pre data-field="raw-code" class="motion-raw-target" hidden></pre>
            <label>Draft operation <select data-field="step"></select></label>
            <textarea data-field="step-code" rows="10" spellcheck="false" aria-label="Selected operation code"></textarea>
            <button type="button" data-action="capture">Capture measured pose into operation</button>
            <p class="field-help">Capture changes the draft. Replace example saves it. Perform uses the draft.</p>
          </section>
          <section><h4>Servo positions</h4><p data-field="feedback-status" role="status"></p>
            <div class="motion-feedback-table"><table><thead><tr><th>Joint</th><th>ADC</th><th>Signal mV</th><th>Measured °</th><th>Commanded °</th><th>Sample age ms</th></tr></thead>
              <tbody data-field="feedback"></tbody></table></div>
          </section>
        </div>
        <label>Title <input data-field="title"></label>
        <details><summary>Training input</summary>
          <label>Exact input <textarea data-field="query" rows="8" spellcheck="false"></textarea></label>
        </details>
        <details><summary>Complete motion program</summary>
          <label>Named program JSON <textarea data-field="answers" rows="12" spellcheck="false"></textarea></label>
        </details>
        <p data-field="qualification"></p>
        <p class="field-help">Perform uses the edited program, including unsaved changes.</p>
      </fieldset>
    </details>`;
  host.append(panel);
  const field = name => panel.querySelector(`[data-field="${name}"]`);
  const button = name => panel.querySelector(`[data-action="${name}"]`);
  let page = 1, pages = 1, search = "", sort = "added_desc", selected = null, dirty = false;
  let listVersion = 0, selectionVersion = 0, displayedRobot = null;
  const jobs = new Map();
  const editor = field("editor");
  let editingIndex = 0, editingSource = "program", observedFeedback = null, watchJob = null;
  const pretty = value => formatTrainingOperation(JSON.stringify(value),0);
  let playbackProgram = [], trainingTarget = null, formatVersion = 0, highlightedIndex = null;
  function highlightPlayback() {
    for (const row of [...field("operations").children,...field("raw-code").children]) {
      if (row.dataset.index == null) continue;
      row.className=highlightedIndex===Number(row.dataset.index)?"motion-operation-current":"";
      row.setAttribute("aria-current",highlightedIndex===Number(row.dataset.index)?"step":"false");
    }
  }
  function formatTrainingOperation(source, depth=1) {
    // Tokenize strings intact so display whitespace never changes their contents
    // or rounds the numeric literals in the saved training target.
    const tokens=source.match(/"(?:\\.|[^"\\])*"|[\[\]{},:]|[^\s\[\]{},:]+/g) || [];
    let result="  ".repeat(depth);
    const indent=()=>"  ".repeat(depth);
    for (let index=0;index<tokens.length;index++) {
      const token=tokens[index];
      if (token==="[") {
        let end=index+1;
        while (end<tokens.length && !["[", "{", "]"].includes(tokens[end])) end++;
        if (tokens[end]==="]") {
          result+=tokens.slice(index,end+1).map(value=>value===","?", ":value).join("");
          index=end; continue;
        }
      }
      if (token==="[" || token==="{") {
        result+=token;
        if (tokens[index+1]===(token==="["?"]":"}")) result+=tokens[++index];
        else { depth++;result+="\n"+indent(); }
      } else if (token==="]" || token==="}") {
        depth--;result+="\n"+indent()+token;
      } else if (token===",") result+=",\n"+indent();
      else if (token===":") result+=": ";
      else result+=token;
    }
    return result;
  }
  async function renderPlaybackFormat() {
    const version=++formatVersion, raw=field("raw-training").checked;
    field("operations").hidden=raw; field("raw-code").hidden=!raw;
    field("format-status").textContent="";
    if (!raw || !selected) return;
    const identifier=selected.id;
    try {
      if (!trainingTarget) {
        field("format-status").textContent="Encoding training target…";
        const result=await api("/api/motion-library",{operation:"preview",id:identifier,
          ...(!watchJob && !dirty ? {} : {program:playbackProgram})});
        if (version!==formatVersion || selected?.id!==identifier) return;
        trainingTarget=result;
      }
      field("raw-code").replaceChildren();
      const text=value=>{const span=document.createElement("span");span.textContent=value;field("raw-code").append(span);};
      text("[\n");
      trainingTarget.operations.forEach((operation,index)=>{
        if (index) text(",\n");
        const span=document.createElement("span");span.dataset.index=String(index);span.textContent=formatTrainingOperation(operation);field("raw-code").append(span);
      });
      text("\n]"); highlightPlayback();
      field("format-status").textContent=watchJob?"Playback snapshot":dirty?"Draft":"";
    } catch (error) {
      if (version===formatVersion) { field("raw-code").replaceChildren();field("format-status").textContent=error.message; }
    }
  }
  field("raw-training").addEventListener("change",renderPlaybackFormat);
  function readProgram() {
    const program = JSON.parse(field("answers").value);
    if (editingSource === "step" && program[editingIndex]) {
      program[editingIndex] = JSON.parse(field("step-code").value);
      field("answers").value = pretty(program);
    }
    return program;
  }
  function showStep(program) {
    field("step-code").value = pretty(program[editingIndex] || {});
    editingSource = "program";
  }
  function showPlayback(program) {
    playbackProgram=program; trainingTarget=null;
    field("raw-code").replaceChildren();
    field("operations").replaceChildren();
    program.forEach((operation,index) => {
      const row=document.createElement("li"), code=document.createElement("pre");
      row.dataset.index=String(index); code.textContent=pretty(operation); row.append(code); field("operations").append(row);
    });
    highlightPlayback(); void renderPlaybackFormat();
  }
  function showOperations(program, updateStep=true) {
    if (!watchJob) showPlayback(program);
    field("step").replaceChildren();
    program.forEach((operation,index) => {
      const option=document.createElement("option");option.value=String(index);option.textContent=`${index+1}. ${operation.name}`;field("step").append(option);
    });
    editingIndex = Math.min(editingIndex,Math.max(0,program.length-1)); field("step").value = String(editingIndex);
    if (updateStep) showStep(program);
  }
  field("step").addEventListener("change", () => {
    try { const program=readProgram(); editingIndex=Number(field("step").value); showStep(program); }
    catch (error) { field("step").value=String(editingIndex); field("edit-status").textContent=error.message; }
  });
  function capturePose() {
    const program = readProgram(), operation = program[editingIndex];
    if (!operation) throw new Error("Select an operation first.");
    const names=selected.joint_names, feedback=observedFeedback;
    const measured = new Map();
    names.forEach((name,index) => {
      const value=feedback?.filtered_model_deg?.[index];
      if (Number.isFinite(value)) measured.set(name,value);
    });
    if (!measured.size) throw new Error("No measured servo positions are available.");
    program[editingIndex]={name:"pose",arguments:{joints:[...measured.keys()],angles_deg:[...measured.values()],
      reference:"absolute",speed_pct:operation.arguments.speed_pct ?? 100,taper_deg:operation.arguments.taper_deg ?? 0}};
    field("answers").value=pretty(program); editingSource="program"; dirty=true; showOperations(program);
    field("edit-status").textContent="Measured pose captured into draft. Replace example to save.";
  }

  async function api(url, payload) {
    let options;
    if (payload) {
      const sessionResponse = await fetch("/api/session");
      if (!sessionResponse.ok) throw new Error("Sign in to Body Control to save or play a motion.");
      const session = await sessionResponse.json();
      options = {method: "POST", headers: {"Content-Type": "application/json", "X-Ainekio-CSRF": session.csrf},
        body: JSON.stringify(payload)};
    }
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || response.statusText);
    return result;
  }

  async function loadPage(target) {
    const version = ++listVersion;
    ++selectionVersion;
    editor.disabled = false;
    field("list-status").textContent = "Loading training examples…";
    try {
      const result = await api(`/api/motion-library?page=${target}&search=${encodeURIComponent(search)}&sort=${encodeURIComponent(sort)}`);
      if (version !== listVersion) return;
      page = result.page; pages = result.pages;
      field("browser").append(editor);
      field("list").replaceChildren();
      for (const item of result.items) {
        const li = document.createElement("li");
        const branch = document.createElement("details");
        const choose = document.createElement("summary");
        branch.dataset.exampleId = item.id;
        choose.textContent = item.title;
        branch.append(choose);
        branch.addEventListener("toggle", () => openExample(branch, item.id));
        const family = document.createElement("small");
        const date = value => new Date(value).toLocaleString();
        family.textContent = `${item.family.replaceAll("_", " ")} · Added ${item.added_at ? date(item.added_at) : "date unavailable"} · ${item.edited_at ? "Edited " + date(item.edited_at) : "Not edited"}`;
        const play = document.createElement("button");
        play.type = "button"; play.className = "motion-library-play";
        play.dataset.action = "play"; play.dataset.id = item.id; play.dataset.title = item.title;
        play.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="M8 5v14l11-7z"></path></svg>';
        play.title = `Play ${item.title}`;
        play.setAttribute("aria-label", `Play ${item.title}`);
        play.disabled = !document.getElementById("robot-select").value;
        branch.append(family); li.append(play, branch); field("list").append(li);
        if (selected?.id === item.id) { branch.append(editor); branch.open = true; }
      }
      for (const label of panel.querySelectorAll('[data-field="page"]')) label.textContent = `Page ${page} of ${pages}`;
      for (const action of ["first", "previous", "next", "last"]) {
        for (const control of panel.querySelectorAll(`[data-action="${action}"]`)) {
          control.disabled = ["first", "previous"].includes(action) ? page <= 1 : page >= pages;
        }
      }
      field("list-status").textContent = `${result.total} ${result.total === 1 ? "example" : "examples"} · ${result.page_size} per page`;
    } catch (error) {
      if (version === listVersion) field("list-status").textContent = error.message;
    }
  }

  function showExample(example) {
    if (selected?.id!==example.id) watchJob=null;
    selected = example; dirty = false;
    field("editor").hidden = false;
    field("title").value = example.title;
    field("query").value = example.query;
    field("answers").value = pretty(example.program);
    editingIndex = 0; editingSource = "program"; showOperations(example.program);
    field("qualification").textContent = example.physical_qualification
      ? "This saved version has an operator-approved physical trial."
      : "This saved version has no operator-approved physical trial.";
    field("edit-status").textContent = `Saved version ${example.revision}`;
  }

  async function openExample(branch, identifier) {
    if (!branch.open) return;
    if (selected?.id === identifier) { branch.append(editor); return; }
    if (dirty && !window.confirm("Discard unsaved edits and open this example?")) { branch.open = false; return; }
    const version = ++selectionVersion;
    editor.disabled = true;
    field("list-status").textContent = "Loading example…";
    try {
      const result = await api(`/api/motion-library?id=${encodeURIComponent(identifier)}`);
      if (version === selectionVersion) {
        showExample(result); branch.append(editor);
        for (const other of field("list").querySelectorAll("details[data-example-id]")) if (other !== branch) other.open = false;
        field("list-status").textContent = result.title;
      }
    } catch (error) { field("list-status").textContent = error.message; }
    finally { if (version === selectionVersion) editor.disabled = false; }
  }

  async function playExample(target, exampleId, title, options = {}) {
    const robot = document.getElementById("robot-select").value;
    if (!robot) throw new Error("Select a robot for playback.");
    target.disabled = true;
    try {
      const result = await api("/api/motion-library", {operation: "run", id: exampleId,
        robot_id: robot, ...options});
      jobs.set(robot, {id: result.job_id, title, exampleId});
      const message = `${title} submitted to ${robot}.`;
      field("list-status").textContent = message;
      if (robot === displayedRobot && selected?.id === exampleId) {
        watchJob = options.program ? result.job_id : null;
        if (options.program) showPlayback(options.program);
        field("play-status").textContent = message;
      }
    } finally { target.disabled = !document.getElementById("robot-select").value; }
  }

  panel.addEventListener("input", event => {
    if (["title", "query", "answers", "step-code"].includes(event.target.dataset.field)) {
      dirty = true;
      field("edit-status").textContent = "Unsaved changes";
      try {
        if (event.target.dataset.field === "answers") { editingSource="program"; showOperations(readProgram()); }
        if (event.target.dataset.field === "step-code") { editingSource="step"; showOperations(readProgram(),false); }
      } catch (error) { field("edit-status").textContent = "Draft JSON: " + error.message; }
    }
  });
  window.addEventListener("beforeunload", event => {
    if (dirty) { event.preventDefault(); event.returnValue = ""; }
  });
  field("search-form").addEventListener("submit", event => {
    event.preventDefault(); search = field("search").value.trim(); void loadPage(1);
  });
  field("sort").addEventListener("change", () => {
    sort = field("sort").value;
    return loadPage(1);
  });
  window.renderMotionLibraryStatus = (status, robot, entry) => {
    displayedRobot = robot;
    const imu=entry?.status?.imu; observedFeedback=imu?.joint_feedback || null;
    field("feedback").replaceChildren();
    const names=selected?.joint_names || [];
    const feedback=observedFeedback;
    names.forEach((name,index) => {
      const row=document.createElement("tr");
      const measured=feedback?.filtered_model_deg?.[index], commanded=feedback?.commanded_model_deg?.[index];
      const age=feedback?.sampled_us?.[index] != null ? (feedback.device_us-feedback.sampled_us[index])/1000 : null;
      const values=[name.replaceAll("_"," "),
        Number.isFinite(feedback?.raw_adc?.[index])?String(feedback.raw_adc[index]):"—",
        Number.isFinite(feedback?.signal_millivolts?.[index])?String(feedback.signal_millivolts[index]):"—",
        Number.isFinite(measured)?measured.toFixed(2):"—",
        feedback && !(feedback.commanded_mask & (1<<index))?"released":Number.isFinite(commanded)?commanded.toFixed(2):"—",
        age!=null?age.toFixed(0):"—"];
      values.forEach(value=>{const cell=document.createElement("td");cell.textContent=value;row.append(cell);});field("feedback").append(row);
    });
    field("feedback-status").textContent=imu ? `${entry.connected && entry.connection_state!=="stale" && imu.fresh?"Live feedback":"Last reported feedback"}${imu.received_at?" · "+imu.received_at:""}` : "No servo feedback received.";
    for (const action of ["run","run-step"]) button(action).disabled=!robot;
    for (const control of panel.querySelectorAll('[data-action="play"]')) control.disabled=!robot;
    if (selected && jobs.get(robot)?.exampleId !== selected.id) {
      const previous=Object.values(status?.jobs || {}).filter(job=>job.robot_id===robot &&
        (job.source || job.latest_generation?.source)?.example_id===selected.id).at(-1);
      if (previous) jobs.set(robot,{id:previous.id,title:selected.title,exampleId:selected.id});
    }
    const trial=jobs.get(robot), matches=Boolean(trial && selected && trial.exampleId===selected.id);
    const job=matches && status?.jobs?.[trial.id];
    if (job?.latest_generation?.program && watchJob!==job.id) { watchJob=job.id;showPlayback(job.latest_generation.program); }
    for (const action of ["pause","release"]) button(action).disabled=!matches || job?.owns_motion===false;
    field("play-status").textContent=job
      ? `${job.pause_state ? job.pause_state === "released" ? "Release acknowledged" : "Paused" : job.state}${job.operation_index!=null?" · operation "+(job.operation_index+1):""}${job.error?" — "+job.error:""} · ${job.completed_commands || 0} receipts`
      : matches?`${trial.title} submitted to ${robot}.`:robot?`Selected robot: ${robot}`:"Select a robot for playback.";
    if (dirty && job) field("play-status").textContent += " · draft edits apply on next Perform";
    highlightedIndex=job?.operation_index ?? null;
    highlightPlayback();
  };

  panel.addEventListener("click", async event => {
    const target = event.target.closest("[data-action]");
    if (!target || target.disabled) return;
    const action = target.dataset.action;
    try {
      if (["first", "previous", "next", "last"].includes(action)) {
        await loadPage(action === "first" ? 1 : action === "last" ? pages : page + (action === "next" ? 1 : -1));
      } else if (action === "play") {
        await playExample(target, target.dataset.id, target.dataset.title);
      } else if (action === "capture") {
        capturePose();
      } else if (action === "pause" || action === "release") {
        const robot=document.getElementById("robot-select").value, trial=jobs.get(robot);
        if (!selected || trial?.exampleId!==selected.id) return;
        const exampleId=selected.id, version=selectionVersion;
        target.disabled=true;
        try {
          const result=await api("/api/motion-library",{operation:action,id:exampleId,robot_id:robot,job_id:trial.id});
          if (selected?.id!==exampleId || version!==selectionVersion || robot!==document.getElementById("robot-select").value) return;
          const program=readProgram();
          editingIndex=result.operation_index ?? Math.min(result.completed_operation_index ?? 0,program.length-1);
          field("step").value=String(editingIndex); showStep(program);
          field("play-status").textContent=result.pause_state==="released"?"Release acknowledged. Hand-pose the robot and capture its measured angles.":"Paused. Edit this operation or release the servos to hand-pose it.";
        } finally { target.disabled=false; }
      } else if (action === "save" || action === "run" || action === "run-step") {
        if (!selected) return;
        const program = readProgram();
        const query = field("query").value;
        if (action === "save") {
          const version = ++selectionVersion;
          // Keep the submitted edit stable while the atomic save is in flight.
          field("editor").disabled = true;
          try {
            const result = await api("/api/motion-library", {operation: "save", id: selected.id,
              revision: selected.revision, title: field("title").value, query, program});
            if (version === selectionVersion) {
              const previousIndex=editingIndex;
              showExample(result); editingIndex=Math.min(previousIndex,result.program.length-1); field("step").value=String(editingIndex); showStep(result.program);
              field("edit-status").textContent = "Saved to training data.";
              await loadPage(page);
            }
          } finally {
            if (version === selectionVersion) field("editor").disabled = false;
          }
        } else {
          await playExample(target, selected.id, field("title").value,
            {query, program, ...(action === "run-step" ? {start_index: editingIndex} : {})});
        }
      }
    } catch (error) {
      field(action === "play" || !selected ? "list-status" : "edit-status").textContent = error.message;
    }
  });
  void loadPage(1);
}());
