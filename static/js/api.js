// Thin fetch wrapper for the CLI Scheduler JSON API.
// Every call returns parsed JSON or throws an Error with the server's message.

async function request(method, path, body) {
    const opts = {
        method,
        headers: { 'Accept': 'application/json' },
    };
    if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }

    const response = await fetch(path, opts);
    const isJson = (response.headers.get('Content-Type') || '').includes('application/json');
    const payload = isJson ? await response.json().catch(() => ({})) : null;

    if (!response.ok) {
        const message = (payload && payload.error) || `${response.status} ${response.statusText}`;
        const error = new Error(message);
        error.status = response.status;
        error.payload = payload;
        throw error;
    }
    return payload;
}

export const api = {
    listJobs({ page = 1, perPage = 20, status } = {}) {
        const params = new URLSearchParams({ page, per_page: perPage });
        if (status) params.set('status', status);
        return request('GET', `/api/jobs?${params.toString()}`);
    },
    getJob(id) {
        return request('GET', `/api/jobs/${encodeURIComponent(id)}`);
    },
    cancelJob(id) {
        return request('POST', `/api/jobs/${encodeURIComponent(id)}/cancel`);
    },
    rerunJob(id) {
        return request('POST', `/api/jobs/${encodeURIComponent(id)}/rerun`);
    },
    getJobLog(id) {
        return request('GET', `/api/jobs/${encodeURIComponent(id)}/log`);
    },
    submitJobs(payload) {
        return request('POST', '/api/jobs', payload);
    },
    listPresets() {
        return request('GET', '/api/presets');
    },
};
