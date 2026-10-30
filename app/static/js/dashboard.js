const form = document.querySelector('#automation-form');
const runButton = document.querySelector('#run-button');
const statusBadge = document.querySelector('#status-badge');
const statusText = document.querySelector('#status-text');
const livePreview = document.querySelector('#live-preview');
const previewImage = document.querySelector('#preview-image');
const previewPlaceholder = document.querySelector('#preview-placeholder');
const newRunButton = document.querySelector('#new-run-button');
const fields = ['username', 'password', 'first_name', 'last_name', 'employee_id'];
let activeJob = null;
let lastPreviewVersion = 0;

previewImage.addEventListener('load', () => {
  previewImage.hidden = false;
  previewPlaceholder.hidden = true;
});
previewImage.addEventListener('error', () => {
  previewImage.hidden = true;
  previewPlaceholder.hidden = false;
  previewPlaceholder.textContent = 'The page view is temporarily unavailable. Progress continues on the right.';
});

function renderPreview(job) {
  const current = job.steps.find(step => step.state === 'running');
  const latest = [...job.steps].reverse().find(step => step.state === 'success' || step.state === 'failed');
  document.getElementById('preview-step').textContent = current ? current.label : latest?.label || 'Preparing the browser…';
  if (job.preview_version > lastPreviewVersion) {
    lastPreviewVersion = job.preview_version;
    previewImage.src = `/api/automation/${encodeURIComponent(job.job_id)}/preview?v=${lastPreviewVersion}`;
  }
}

function setStatus(status, text) {
  statusBadge.className = 'status-badge ' + status;
  statusText.textContent = text;
}

function validate() {
  let valid = true;
  for (const name of fields) {
    const input = document.getElementById(name);
    const error = document.getElementById(name + '-error');
    if (name !== 'password') input.value = input.value.trim();
    const empty = !input.value || (name === 'password' && !input.value.trim());
    const tooLong = input.value.length > Number(input.maxLength);
    error.textContent = empty ? 'This field is required.' : tooLong ? 'Value is too long.' : '';
    input.classList.toggle('invalid', Boolean(error.textContent));
    input.setAttribute('aria-invalid', error.textContent ? 'true' : 'false');
    if (error.textContent) valid = false;
  }
  if (!valid) form.querySelector('input.invalid').focus();
  return valid;
}

function renderSteps(steps) {
  let done = 0;
  for (const step of steps) {
    const row = document.querySelector(`#progress-list [data-key="${step.key}"]`);
    if (!row) continue;
    row.className = step.state;
    row.querySelector('small').textContent = step.state === 'failed' ? 'See reason below' :
      step.message || step.state.charAt(0).toUpperCase() + step.state.slice(1);
    row.querySelector('small').title = step.message || '';
    if (step.state === 'success') done += 1;
  }
  document.getElementById('progress-count').textContent = `${done} of 8`;
}

function renderIssues(issues) {
  const panel = document.getElementById('failure-details');
  const list = document.getElementById('failure-list');
  list.replaceChildren();
  panel.hidden = issues.length === 0;
  for (const issue of issues) {
    const item = document.createElement('li');
    const step = document.createElement('strong');
    step.textContent = issue.label;
    const reason = document.createElement('p');
    reason.textContent = issue.message;
    item.append(step, reason);
    if (issue.next_action) {
      const action = document.createElement('small');
      action.textContent = `Next: ${issue.next_action}`;
      item.append(action);
    }
    list.append(item);
  }
}

function renderResult(job) {
  document.getElementById('result-empty').hidden = true;
  document.getElementById('result-content').hidden = false;
  const banner = document.getElementById('result-banner');
  const failures = job.steps.filter(step => step.state === 'failed' && step.key !== 'completed');
  banner.className = 'result-banner ' + job.status;
  banner.textContent = job.status === 'running' && failures.length ? 'A step failed; finishing the run…' :
    job.status === 'running' ? 'Automation is running…' :
    job.status === 'success' ? 'Automation completed successfully' :
    job.status === 'partial' ? 'Employee verified; a later step needs attention' :
    'Automation failed';
  const employee = job.verified_employee;
  document.getElementById('result-first').textContent = employee?.first_name || '—';
  document.getElementById('result-last').textContent = employee?.last_name || '—';
  document.getElementById('result-id').textContent = employee?.employee_id || '—';
  if (!failures.length) {
    const completion = job.steps.find(step => step.key === 'completed' && step.state === 'failed');
    if (completion) failures.push({...completion, message: job.error || completion.message});
  }
  renderIssues(failures);
  document.getElementById('result-note').textContent = employee ?
    'Employee details were read from the saved OrangeHRM record.' :
    job.status === 'running' ? 'Waiting for saved-record verification.' :
    failures.length ? 'No employee was verified in this run.' : 'No employee data is available.';
}

function renderEmployees(job) {
  const body = document.getElementById('employee-rows');
  body.replaceChildren();
  const link = document.getElementById('download-link');
  link.hidden = !job.export_ready;
  if (job.export_ready) link.href = `/api/automation/${encodeURIComponent(job.job_id)}/export`;
  document.getElementById('data-summary').textContent = job.export_ready ?
    `${job.extracted_count} real employee records extracted from OrangeHRM.` :
    job.status === 'running' ? 'Waiting for employee list extraction…' : 'No employee data was extracted.';
  if (!job.employees.length) {
    const row = body.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 3;
    cell.className = 'table-empty';
    cell.textContent = 'No data extracted yet';
    return;
  }
  for (const employee of job.employees) {
    const row = body.insertRow();
    for (const value of [employee.employee_id, employee.first_name, employee.last_name]) {
      row.insertCell().textContent = value;
    }
  }
}

function renderJob(job) {
  renderPreview(job);
  renderSteps(job.steps);
  renderResult(job);
  renderEmployees(job);
  const current = job.steps.find(step => step.state === 'running');
  setStatus(job.status, {
    running: current ? `Running · ${current.label}` : 'Automation running', success: 'Completed successfully',
    partial: 'Partially completed', failed: 'Automation failed',
  }[job.status]);
}

function resetRunView() {
  newRunButton.hidden = true;
  lastPreviewVersion = 0;
  previewImage.hidden = true;
  previewImage.removeAttribute('src');
  previewPlaceholder.hidden = false;
  previewPlaceholder.textContent = 'Opening OrangeHRM…';
  document.getElementById('preview-step').textContent = 'Preparing the browser…';
  livePreview.hidden = false;
  form.hidden = true;
  document.getElementById('config-heading').textContent = 'OrangeHRM live view';
  document.getElementById('config-eyebrow').textContent = '01 / WATCH';
  for (const row of document.querySelectorAll('#progress-list [data-key]')) {
    row.className = '';
    row.querySelector('small').textContent = 'Pending';
  }
  document.getElementById('progress-count').textContent = '0 of 8';
  document.getElementById('result-empty').hidden = false;
  document.getElementById('result-content').hidden = true;
  for (const id of ['result-first', 'result-last', 'result-id']) document.getElementById(id).textContent = '—';
  renderIssues([]);
  renderEmployees({employees: [], export_ready: false, extracted_count: 0, status: 'running'});
}

async function poll(jobId) {
  while (activeJob === jobId) {
    try {
      const response = await fetch(`/api/automation/${encodeURIComponent(jobId)}/status`, {cache: 'no-store'});
      if (!response.ok) throw new Error('Could not read the automation status.');
      const job = await response.json();
      renderJob(job);
      if (job.status !== 'running') break;
    } catch (error) {
      setStatus('failed', 'Status connection lost');
      document.getElementById('result-banner').className = 'result-banner failed';
      document.getElementById('result-banner').textContent = 'Cannot confirm the current run';
      renderIssues([{label: 'Status connection', message: error.message,
        next_action: 'Refresh the page and check OrangeHRM before starting another run; employee creation may have completed.'}]);
      break;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  activeJob = null;
  newRunButton.hidden = false;
  runButton.disabled = false;
  document.getElementById('button-label').textContent = 'Run automation';
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (activeJob || !validate()) return;
  resetRunView();
  runButton.disabled = true;
  document.getElementById('button-label').textContent = 'Starting…';
  setStatus('running', 'Starting automation');
  const payload = Object.fromEntries(fields.map(name => [name, document.getElementById(name).value]));
  try {
    const response = await fetch('/api/automation/run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload), cache: 'no-store',
    });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 422 && Array.isArray(result.detail)) {
        for (const issue of result.detail) {
          const name = issue.loc?.at(-1);
          if (!fields.includes(name)) continue;
          const input = document.getElementById(name);
          document.getElementById(name + '-error').textContent = issue.msg || 'Invalid value.';
          input.classList.add('invalid');
          input.setAttribute('aria-invalid', 'true');
        }
        throw new Error('Some inputs failed validation. Correct the highlighted fields and try again.');
      }
      throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not start automation.');
    }
    document.getElementById('password').value = '';
    activeJob = result.job_id;
    renderJob(result);
    document.getElementById('button-label').textContent = 'Automation running…';
    await poll(result.job_id);
  } catch (error) {
    setStatus('failed', 'Could not start');
    document.getElementById('result-empty').hidden = true;
    document.getElementById('result-content').hidden = false;
    document.getElementById('result-banner').className = 'result-banner failed';
    document.getElementById('result-banner').textContent = 'Could not start automation';
    document.getElementById('result-note').textContent = 'No employee was verified in this run.';
    renderIssues([{label: 'Starting the run', message: error.message,
      next_action: 'Correct the problem shown here, then try again.'}]);
    runButton.disabled = false;
    form.hidden = false;
    livePreview.hidden = true;
    document.getElementById('config-heading').textContent = 'Run details';
    document.getElementById('config-eyebrow').textContent = '01 / CONFIGURE';
    document.getElementById('button-label').textContent = 'Run automation';
  }
});

newRunButton.addEventListener('click', () => {
  form.hidden = false;
  livePreview.hidden = true;
  document.getElementById('config-heading').textContent = 'Run details';
  document.getElementById('config-eyebrow').textContent = '01 / CONFIGURE';
  document.getElementById('username').focus();
});
