export type RequestOpts = {
  baseUrl: string;
  timeout?: number;
  headers?: Record<string, string>;
};

export class ApiClient {
  private baseUrl: string;
  private timeout: number;
  private headers: Record<string, string>;

  constructor(opts: RequestOpts) {
    this.baseUrl = opts.baseUrl;
    this.timeout = opts.timeout ?? 120000;
    this.headers = { 'Content-Type': 'application/json', Accept: 'application/json', ...(opts.headers || {}) };
  }

  private async request(endpoint: string, init: RequestInit = {}) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), this.timeout);
    const res = await fetch(`${this.baseUrl}${endpoint}`, { ...init, headers: { ...this.headers, ...(init.headers || {}) }, signal: controller.signal });
    clearTimeout(id);
    if (!res.ok) {
      let data: any = {};
      try { data = await res.json(); } catch {}
      throw { status: res.status, data };
    }
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text();
  }

  get(path: string) { return this.request(path, { method: 'GET' }); }
  post(path: string, body?: any) { return this.request(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }); }
  put(path: string, body?: any) { return this.request(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }); }
  delete(path: string) { return this.request(path, { method: 'DELETE' }); }
}

