/* Read-only learning history. This view never issues robot commands. */
(() => {
  const numeric = value => typeof value === "number" && Number.isFinite(value);
  const number = value => numeric(value) ? Number(value.toPrecision(5)).toString() : "Unknown";
  const when = value => numeric(value) ? new Date(value * 1000).toLocaleString() : "Time not recorded";
  const short = id => id ? id.slice(0, 12) : "Unknown model";
  const el = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
  const conditionLabel = condition => {
    try {
      const [command, rate] = JSON.parse(condition);
      return `Forward ${number(command[0])}, turn ${number(command[1])}, lateral ${number(command[2])}, stride ${number(command[3])} · rate ${number(rate)}`;
    } catch { return condition || "Command settings not recorded"; }
  };
  const modelChanges = (model, reference) => {
    if (!reference) return ["Reference model unavailable; changes cannot be calculated."];
    const changes = [];
    const labels = {0:"Stance fraction", 1:"Sweep (mm)", 6:"Rear-left lift (mm)",
      7:"Rear-right lift (mm)", 8:"Front-left lift (mm)", 9:"Front-right lift (mm)",
      10:"Rear-left landing X (mm)", 12:"Rear-right landing X (mm)",
      14:"Front-left landing X (mm)", 16:"Front-right landing X (mm)", 28:"Body Z constant (mm)"};
    (model.gait_profile || []).forEach((v, i) => {
      const before = reference.gait_profile?.[i];
      if (numeric(before) && Math.abs(v-before) > 1e-7)
        changes.push(`${labels[i] || `Gait profile [${i}]`}: ${number(before)} → ${number(v)} (change ${number(v-before)})`);
    });
    for (const [key, label] of [["feedback_coefficients", "Sensor-response coefficients"],
      ["coefficients", "Phase correction coefficients"], ["command_coefficients", "Command correction coefficients"]]) {
      const differences = (model[key] || []).map((v,i) => numeric(reference[key]?.[i]) ? v-reference[key][i] : 0).filter(v => Math.abs(v)>1e-7);
      if (differences.length) changes.push(`${label}: ${differences.length} changed; largest absolute change ${number(Math.max(...differences.map(Math.abs)))}`);
    }
    return changes.length ? changes : ["No numerical profile or correction changes from this reference."];
  };

  window.createGaitHistory = ({request, getRobot}) => {
    const node = name => document.getElementById(`gait-history-${name}`);
    const panel = node("panel");
    let data = null, robot = null, status = null, revision = "", loadedRevision = null, serial = 0, busy = false;
    let page = 0;
    const current = () => data?.contexts?.[Number(node("context").value)];
    const state = text => { node("state").textContent = text; };
    const option = (value, label) => { const o=el("option",label); o.value=value; return o; };
    function clear() {
      for (const key of ["context","condition","chart","models","observations"]) node(key).replaceChildren();
      node("summary").textContent = ""; node("point").textContent = "";
      node("export").disabled = true;
    }
    function summary() {
      const context = current(); if (!context) return;
      const b = context.bank;
      node("summary").textContent = `${context.gait === "run" ? "Run" : "Walk"} · ${context.current ? "current" : "archived"} context · generation ${b.generation ?? 0} · ${(b.observations || []).length} scored observations · ${b.converged ? "plateau in tested contexts" : "collecting / evaluating"} · best model ${short(b.incumbent?.id)}.`;
      if (context.reason) node("summary").textContent += ` Archived: ${context.reason}.`;
    }
    function models() {
      const context = current(), root = node("models"); root.replaceChildren();
      if (!context) return;
      const b = context.bank, known = new Map();
      const entries = [];
      if (b.initial) { known.set(b.initial.id,b.initial); entries.push({model:b.initial, label:"Starting model"}); }
      let reference = b.initial;
      for (const h of b.history || []) {
        entries.push({...h, reference:known.get(h.reference_model_id) || reference,
          label:h.promoted ? "Accepted improvement" : "Improvement not demonstrated"});
        known.set(h.model.id,h.model);
        if (h.promoted) reference=h.model;
      }
      if (b.centre) known.set(b.centre.id,b.centre);
      for (const [key,label] of [["candidate","Current candidate"],["proposal","Analyzed proposal — not installed"]]) {
        if (b[key] && !entries.some(e=>e.model.id===b[key].id)) entries.push({model:b[key],reference:b.centre,label});
      }
      for (const entry of entries) {
        const detail = el("details"); detail.className="gait-history-model";
        detail.append(el("summary",`${entry.label} · ${short(entry.model.id)}${entry.model.id===b.incumbent?.id ? " · current best" : ""}`));
        detail.append(el("p",`${when(entry.recorded_at)}${entry.generation!==undefined ? ` · generation ${entry.generation}` : ""}`));
        detail.append(el("p",`Model: ${entry.model.id}`));
        if (entry.reference) detail.append(el("p",`Compared with ${short(entry.reference.id)}`));
        if (entry.label!=="Starting model") {
          const list=el("ul"); for(const change of modelChanges(entry.model,entry.reference)) list.append(el("li",change)); detail.append(list);
        }
        for (const [condition, comparison] of Object.entries(entry.comparisons || {})) {
          detail.append(el("p",`${conditionLabel(condition)}: ${comparison.decision === "improved" ? "improved" : "improvement not demonstrated"}. Score change ${number(comparison.gain)}; standard error ${number(comparison.standard_error)}; ${comparison.reference_windows ?? "?"} reference / ${comparison.challenger_windows ?? "?"} candidate observations.`));
        }
        root.append(detail);
      }
    }
    function inspect(row, index) {
      const metrics = Object.entries(row.metrics || {}).map(([k,v])=>`${k}: ${number(v)}`).join(" · ");
      node("point").textContent = `Observation ${index+1} · ${when(row.recorded_at)} · model ${short(row.model_id)} · score ${number(row.score)}. ${metrics}`;
    }
    function observations() {
      const context=current(), chart=node("chart"), table=node("observations");
      chart.replaceChildren(); table.replaceChildren(); node("point").textContent="";
      if (!context) return;
      const metric=node("metric").value, condition=node("condition").value;
      const rows=(context.bank.observations || []).map((row,index)=>({row,index,value:metric==="score" ? row.score : row.metrics?.[metric]}))
        .filter(p=>(p.row.condition || "")===condition);
      const valid=rows.filter(p=>numeric(p.value));
      const title=node("metric").selectedOptions[0].textContent;
      if (!valid.length) chart.append(el("p","No measured values for this selection yet."));
      else {
        const ns="http://www.w3.org/2000/svg";
        const svg=(tag,attrs={},text)=>{const n=document.createElementNS(ns,tag); for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};
        const plot=svg("svg",{viewBox:"0 0 780 260",role:"img","aria-label":`${title} by observation order. Values are also listed in the table below.`});
        let low=Math.min(...valid.map(p=>p.value)), high=Math.max(...valid.map(p=>p.value));
        const padding=(high-low || Math.max(Math.abs(high)*.1,.01))*.12; low-=padding;high+=padding;
        const first=rows[0].index, last=rows[rows.length-1].index;
        const x=p=>78+(p.index-first)/Math.max(1,last-first)*672;
        const y=p=>208-(p.value-low)/(high-low)*182;
        for(let i=0;i<4;i++){
          const yy=26+i*182/3, v=high-i*(high-low)/3;
          plot.append(svg("line",{x1:78,x2:750,y1:yy,y2:yy,stroke:"currentColor",opacity:".16"}),svg("text",{x:70,y:yy+4,"text-anchor":"end",fill:"currentColor","font-size":12},number(v)));
        }
        plot.append(svg("text",{x:78,y:236,fill:"currentColor","font-size":12},`#${first+1}`),svg("text",{x:750,y:236,"text-anchor":"end",fill:"currentColor","font-size":12},`#${last+1}`));
        // Keep unknown measurements as gaps, not interpolated zeroes.
        let segment=[];
        const flush=()=>{if(segment.length>1)plot.append(svg("polyline",{points:segment.join(" "),fill:"none",stroke:"#38bdf8","stroke-width":2}));segment=[];};
        for(const p of rows){if(numeric(p.value))segment.push(`${x(p)},${y(p)}`);else flush();}flush();
        for(const p of valid){
          const point=svg("circle",{cx:x(p),cy:y(p),r:5,fill:p.row.model_id===context.bank.incumbent?.id ? "#34d399":"#38bdf8",tabindex:0,role:"button","aria-label":`Observation ${p.index+1}: ${number(p.value)}, model ${short(p.row.model_id)}`});
          point.append(svg("title",{},`#${p.index+1} · ${when(p.row.recorded_at)} · ${number(p.value)} · ${short(p.row.model_id)}`));
          point.addEventListener("click",()=>inspect(p.row,p.index));
          point.addEventListener("keydown",e=>{if(e.key==="Enter" || e.key===" "){e.preventDefault();e.stopPropagation();inspect(p.row,p.index);}});
          plot.append(point);
        }
        chart.append(plot,el("p","Green: current best model. Blue: other evaluated models. These colours identify models, not whether an individual observation succeeded."));
      }
      const size=25; page=Math.min(page,Math.max(0,Math.ceil(rows.length/size)-1));
      for(const p of rows.slice(page*size,(page+1)*size)){
        const tr=el("tr"), cell=el("td"), button=el("button",`#${p.index+1}`);
        button.type="button";button.addEventListener("click",()=>inspect(p.row,p.index));cell.append(button);tr.append(cell);
        for(const v of [when(p.row.recorded_at),short(p.row.model_id),number(p.value)])tr.append(el("td",v));table.append(tr);
      }
      if(rows.length>size){
        const tr=el("tr"), td=el("td");td.colSpan=4;
        for(const [label,delta]of [["Previous",-1],["Next",1]]){const b=el("button",label);b.type="button";b.disabled=delta<0?page===0:(page+1)*size>=rows.length;b.addEventListener("click",()=>{page+=delta;observations();});td.append(b);}
        td.append(document.createTextNode(` Page ${page+1} of ${Math.ceil(rows.length/size)}`));tr.append(td);table.append(tr);
      }
    }
    function selectContext() {
      const previous=node("condition").value;node("condition").replaceChildren();
      const rows=current()?.bank.observations || [];
      for(const condition of new Set(rows.map(o=>o.condition || "")))node("condition").append(option(condition,conditionLabel(condition)));
      if([...node("condition").options].some(o=>o.value===previous))node("condition").value=previous;
      page=0;summary();models();observations();
    }
    async function refresh() {
      const selected=getRobot(); if(!selected || busy)return;
      if(robot!==selected){robot=selected;data=null;clear();}
      const mine=++serial, requestedRevision=revision;busy=true;state("Reading saved learning history…");
      try {
        const result=await request("/api/gait-learning/service",{method:"POST",body:JSON.stringify({robot_id:selected,op:"history"})});
        if(mine!==serial || getRobot()!==selected)return;
        const old=current();data=result;loadedRevision=requestedRevision;
        node("context").replaceChildren();
        data.contexts.forEach((c,i)=>node("context").append(option(String(i),`${c.gait === "run" ? "Run":"Walk"} · ${c.current ? "current":"archived"} context ${i+1}`)));
        const chosen=data.contexts.findIndex(c=>old && c.gait===old.gait && c.current===old.current && JSON.stringify(c.bank.camera_context)===JSON.stringify(old.bank.camera_context));
        node("context").value=String(chosen>=0?chosen:Math.max(0,data.contexts.findIndex(c=>c.current)));
        node("export").disabled=false;selectContext();
        state(data.contexts.length ? `History updated ${new Date().toLocaleTimeString()} · ${status?.state || "saved data"}${status?.error ? ` · ${status.error}`:""}` : "No scored learning history yet. Normal walking will populate this view when usable observations arrive.");
      }catch(error){if(mine===serial)state(`History unavailable: ${error.message}${data ? " · Previously loaded history remains below.":""}`);}
      finally{if(mine===serial)busy=false;}
    }
    node("refresh").addEventListener("click",refresh);
    node("context").addEventListener("change",selectContext);
    for(const key of ["condition","metric"])node(key).addEventListener("change",()=>{page=0;observations();});
    node("export").addEventListener("click",()=>{
      if(!data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));
      const link=el("a");link.href=url;link.download=`gait-history-${data.robot_id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),0);
    });
    // Do not let chart/filter keyboard navigation trigger driving shortcuts.
    for(const type of ["keydown","keyup"])panel.addEventListener(type,e=>e.stopPropagation());
    return {refresh,update(selected,live){
      if(robot!==selected){serial++;busy=false;robot=selected;data=null;loadedRevision=null;clear();state(selected ? "Open or refresh history to read saved observations." : "Select a robot to view its learning history.");}
      status=live;revision=JSON.stringify([selected,live?.windows,live?.banks,live?.state,live?.error]);
      if(selected && !panel.hidden && revision!==loadedRevision && !busy)void refresh();
    }};
  };
})();
