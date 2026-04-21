// Dashboard view: polls the /api/jobs endpoint and updates the table in place.
// Replaces the old <meta http-equiv="refresh"> full-page reload.

import { api } from './api.js';
import { duration, escapeHtml, timeAgo } from './format.js';
import { toast } from './toast.js';

const POLL_INTERVAL_MS = 3000;
const ACTIVE_STATUSES = new Set(['queued', 'running']);

const state = {
    page: 1,
    perPage: 20,
    status: '',
    totalPages: 1,
    totalJobs: 0,
    hasActive: false,
    timer: null,
    abort: null,
    visible: !document.hidden,
};

function $(selector) {
    return document.querySelector(selector);
}

function readStateFromUrl() {
    const params = new URLSearchParams(window.location.search);
    state.page = Math.max(1, parseInt(params.get('page') || '1', 10) || 1);
    state.perPage = Math.max(1, parseInt(params.get('per_page') || '20', 10) || 20);
    state.status = params.get('status') || '';
}

function writeStateToUrl({ replace = false } = {}) {
    const params = new URLSearchParams();
    if (state.page !== 1) params.set('page', state.page);
    if (state.perPage !== 20) params.set('per_page', state.perPage);
    if (state.status) params.set('status', state.status);

    const query = params.toString();
    const url = `${window.location.pathname}${query ? '?' + query : ''}`;
    const method = replace ? 'replaceState' : 'pushState';
    window.history[method]({ page: state.page, status: state.status }, '', url);
}

function renderRows(jobs) {
    const tbody = $('#jobs-tbody');
    if (!jobs.length) {
        tbody.innerHTML = '';
        $('#empty-state').hidden = false;
        return;
    }
    $('#empty-state').hidden = true;

    tbody.innerHTML = jobs.map(renderRow).join('');
}

function renderRow(job) {
    const inputArg = job.input_arg || '';
    const timeline = renderTimeline(job);
    const durations = renderDurations(job);
    const jobUrl = `/job/${encodeURIComponent(job.id)}`;

    return `
        <tr data-job-id="${escapeHtml(job.id)}">
            <td><span class="status ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span></td>
            <td>${escapeHtml(job.preset || '')}</td>
            <td title="${escapeHtml(job.command || '')}" style="max-width: 400px;">
                <div class="cell-primary">${escapeHtml(inputArg)}</div>
                <small class="cell-secondary">${escapeHtml(job.command || '')}</small>
            </td>
            <td>${timeline}</td>
            <td>${durations}</td>
            <td><a href="${jobUrl}">View</a></td>
        </tr>
    `;
}

function renderTimeline(job) {
    const parts = [`<div title="${escapeHtml(job.created_at || '')}">Created: ${escapeHtml(timeAgo(job.created_at))}</div>`];
    if (job.start_time) {
        parts.push(`<small class="text-secondary" title="${escapeHtml(job.start_time)}">Started: ${escapeHtml(timeAgo(job.start_time))}</small>`);
    }
    if (job.end_time) {
        parts.push(`<small class="text-secondary" title="${escapeHtml(job.end_time)}">Completed: ${escapeHtml(timeAgo(job.end_time))}</small>`);
    }
    return `<div class="timeline-cell">${parts.join('')}</div>`;
}

function renderDurations(job) {
    const parts = [];
    if (job.end_time && job.start_time) {
        parts.push(`<div title="Execution time">Ran: ${escapeHtml(duration(job.start_time, job.end_time))}</div>`);
    } else if (job.start_time && job.status === 'running') {
        parts.push(`<div title="Current runtime">Running: ${escapeHtml(duration(job.start_time))}</div>`);
    } else {
        parts.push('<span class="text-secondary">-</span>');
    }
    if (job.start_time) {
        parts.push(`<small class="text-secondary" title="Time in queue">Queued: ${escapeHtml(duration(job.created_at, job.start_time))}</small>`);
    }
    return `<div class="timeline-cell">${parts.join('')}</div>`;
}

function renderPagination() {
    const container = $('#pagination');
    if (state.totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    const buttons = [];
    buttons.push(pageButton(state.page - 1, '&laquo; Prev', state.page === 1));

    for (const p of pageNumbers(state.page, state.totalPages)) {
        if (p === null) {
            buttons.push('<span class="ellipsis">…</span>');
        } else if (p === state.page) {
            buttons.push(`<span class="btn active">${p}</span>`);
        } else {
            buttons.push(`<button type="button" class="btn" data-page="${p}">${p}</button>`);
        }
    }

    buttons.push(pageButton(state.page + 1, 'Next &raquo;', state.page === state.totalPages));
    container.innerHTML = buttons.join('');
}

function pageButton(targetPage, label, disabled) {
    if (disabled) {
        return `<span class="btn" aria-disabled="true">${label}</span>`;
    }
    return `<button type="button" class="btn" data-page="${targetPage}">${label}</button>`;
}

function pageNumbers(current, total) {
    const pages = [];
    const start = Math.max(1, current - 2);
    const end = Math.min(total, current + 2);
    if (start > 1) {
        pages.push(1);
        if (start > 2) pages.push(null);
    }
    for (let p = start; p <= end; p += 1) pages.push(p);
    if (end < total) {
        if (end < total - 1) pages.push(null);
        pages.push(total);
    }
    return pages;
}

function updateMeta() {
    const meta = $('#jobs-meta');
    if (!meta) return;
    if (state.totalJobs === 0) {
        meta.textContent = '';
        return;
    }
    const start = (state.page - 1) * state.perPage + 1;
    const end = Math.min(state.page * state.perPage, state.totalJobs);
    meta.textContent = `${start}-${end} of ${state.totalJobs}`;
}

function setLive(active) {
    const el = $('#live-indicator');
    if (!el) return;
    el.classList.toggle('paused', !active);
    el.querySelector('.label').textContent = active ? 'Live' : 'Paused';
}

async function fetchAndRender() {
    if (state.abort) state.abort.abort();
    state.abort = new AbortController();
    try {
        const data = await api.listJobs({
            page: state.page,
            perPage: state.perPage,
            status: state.status,
        });
        state.totalPages = data.total_pages;
        state.totalJobs = data.total;
        state.hasActive = data.jobs.some((j) => ACTIVE_STATUSES.has(j.status));

        if (state.page > state.totalPages && state.totalPages > 0) {
            state.page = state.totalPages;
            writeStateToUrl({ replace: true });
            return fetchAndRender();
        }

        renderRows(data.jobs);
        renderPagination();
        updateMeta();
    } catch (err) {
        if (err.name !== 'AbortError') {
            console.error('Failed to load jobs:', err);
            toast(`Failed to load jobs: ${err.message}`, { type: 'error' });
        }
    }
}

function schedule() {
    clearTimeout(state.timer);
    if (!state.visible) {
        setLive(false);
        return;
    }
    setLive(true);
    // Poll more frequently when there are active jobs so status feels real-time.
    const delay = state.hasActive ? POLL_INTERVAL_MS : POLL_INTERVAL_MS * 2;
    state.timer = setTimeout(async () => {
        await fetchAndRender();
        schedule();
    }, delay);
}

function bindEvents() {
    $('#status-filter').addEventListener('change', (event) => {
        state.status = event.target.value;
        state.page = 1;
        writeStateToUrl();
        fetchAndRender().then(schedule);
    });

    $('#pagination').addEventListener('click', (event) => {
        const button = event.target.closest('[data-page]');
        if (!button) return;
        const targetPage = parseInt(button.dataset.page, 10);
        if (!Number.isFinite(targetPage) || targetPage < 1) return;
        state.page = targetPage;
        writeStateToUrl();
        fetchAndRender().then(schedule);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    $('#refresh-now').addEventListener('click', () => {
        fetchAndRender().then(schedule);
    });

    window.addEventListener('popstate', () => {
        readStateFromUrl();
        syncFilterUi();
        fetchAndRender().then(schedule);
    });

    document.addEventListener('visibilitychange', () => {
        state.visible = !document.hidden;
        if (state.visible) {
            fetchAndRender().then(schedule);
        } else {
            clearTimeout(state.timer);
            setLive(false);
        }
    });
}

function syncFilterUi() {
    const filter = $('#status-filter');
    if (filter) filter.value = state.status;
}

async function init() {
    readStateFromUrl();
    syncFilterUi();
    bindEvents();
    await fetchAndRender();
    schedule();
}

init();
