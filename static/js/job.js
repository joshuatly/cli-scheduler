// Job detail view: poll status and logs via API and update in place.

import { api } from './api.js';
import { duration, escapeHtml, timeAgo } from './format.js';
import { toast } from './toast.js';

const ACTIVE = new Set(['queued', 'running']);
const POLL_INTERVAL_MS = 2000;

const root = document.querySelector('[data-job-root]');
if (!root) {
    throw new Error('Job root element missing');
}

const jobId = root.dataset.jobId;
let lastLogLength = 0;
let currentStatus = root.dataset.initialStatus;
let timer = null;

const elements = {
    status: document.querySelector('[data-field="status"]'),
    startTime: document.querySelector('[data-field="start-time"]'),
    endTime: document.querySelector('[data-field="end-time"]'),
    ran: document.querySelector('[data-field="ran"]'),
    queued: document.querySelector('[data-field="queued"]'),
    exitCode: document.querySelector('[data-field="exit-code"]'),
    log: document.querySelector('#log-container'),
    actions: document.querySelector('[data-field="actions"]'),
};

function renderStatus(status) {
    elements.status.innerHTML = `<span class="status ${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function renderTimestamps(job) {
    if (job.start_time) {
        elements.startTime.innerHTML = `Started: ${escapeHtml(timeAgo(job.start_time))} <small class="text-secondary">(${escapeHtml(job.start_time)})</small>`;
    } else {
        elements.startTime.innerHTML = '<span class="text-secondary">-</span>';
    }

    if (job.end_time) {
        elements.endTime.innerHTML = `Completed: ${escapeHtml(timeAgo(job.end_time))} <small class="text-secondary">(${escapeHtml(job.end_time)})</small>`;
        elements.endTime.hidden = false;
    } else {
        elements.endTime.hidden = true;
    }
}

function renderDurations(job) {
    if (job.end_time && job.start_time) {
        elements.ran.textContent = `Ran: ${duration(job.start_time, job.end_time)}`;
    } else if (job.start_time && job.status === 'running') {
        elements.ran.textContent = `Running: ${duration(job.start_time)}`;
    } else {
        elements.ran.textContent = '-';
    }

    if (job.start_time) {
        elements.queued.textContent = `Queued: ${duration(job.created_at, job.start_time)}`;
        elements.queued.hidden = false;
    } else {
        elements.queued.hidden = true;
    }
}

function renderExitCode(job) {
    if (job.exit_code === undefined || job.exit_code === null) {
        elements.exitCode.textContent = '-';
        elements.exitCode.className = 'text-secondary';
    } else {
        elements.exitCode.textContent = job.exit_code;
        elements.exitCode.className = job.exit_code === 0 ? 'text-success' : 'text-error';
    }
}

function renderActions(job) {
    const active = ACTIVE.has(job.status);
    const cancelBtn = elements.actions.querySelector('[data-action="cancel"]');
    if (cancelBtn) cancelBtn.hidden = !active;
}

async function refreshJob() {
    try {
        const job = await api.getJob(jobId);
        currentStatus = job.status;
        renderStatus(job.status);
        renderTimestamps(job);
        renderDurations(job);
        renderExitCode(job);
        renderActions(job);

        // Logs: only fetch if content might have grown or during active states.
        const logData = await api.getJobLog(jobId);
        if (logData.content.length !== lastLogLength) {
            const atBottom = isScrolledToBottom(elements.log);
            elements.log.textContent = logData.content;
            lastLogLength = logData.content.length;
            if (atBottom) elements.log.scrollTop = elements.log.scrollHeight;
        }
    } catch (err) {
        console.error('Failed to refresh job:', err);
    }
}

function isScrolledToBottom(el) {
    return el.scrollHeight - el.clientHeight - el.scrollTop < 40;
}

function schedulePoll() {
    clearTimeout(timer);
    if (!ACTIVE.has(currentStatus) || document.hidden) return;
    timer = setTimeout(async () => {
        await refreshJob();
        schedulePoll();
    }, POLL_INTERVAL_MS);
}

document.addEventListener('visibilitychange', () => {
    if (!document.hidden && ACTIVE.has(currentStatus)) {
        refreshJob().then(schedulePoll);
    }
});

elements.actions.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    event.preventDefault();

    try {
        if (button.dataset.action === 'cancel') {
            if (!confirm('Cancel this job?')) return;
            await api.cancelJob(jobId);
            toast('Job cancelled', { type: 'success' });
            await refreshJob();
            schedulePoll();
        } else if (button.dataset.action === 'rerun') {
            const res = await api.rerunJob(jobId);
            toast('Job rerun queued', { type: 'success' });
            if (res && res.id) {
                window.location.href = `/job/${encodeURIComponent(res.id)}`;
            }
        }
    } catch (err) {
        toast(err.message || 'Action failed', { type: 'error' });
    }
});

// Initial scroll + polling
lastLogLength = elements.log.textContent.length;
elements.log.scrollTop = elements.log.scrollHeight;
schedulePoll();
