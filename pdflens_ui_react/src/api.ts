import type { ConfigResponse, ExtractionOptions, JobRecord } from './types';

async function errorMessage(response: Response): Promise<string> {
  try {
    const data: unknown = await response.json();
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === 'string') return detail;
      if (typeof detail === 'object' && detail !== null && 'message' in detail) {
        const message = (detail as { message?: unknown }).message;
        if (typeof message === 'string') return message;
      }
    }
  } catch {
    // Use the generic message below when the backend response is not JSON.
  }
  return `Request failed (HTTP ${response.status}). Check the PDFLens service and try again.`;
}

export async function getConfigurations(): Promise<ConfigResponse> {
  const response = await fetch('/ui-api/configurations', { cache: 'no-store' });
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json() as Promise<ConfigResponse>;
}

export async function getHealth(): Promise<boolean> {
  const response = await fetch('/ui-api/health', { cache: 'no-store' });
  if (!response.ok) return false;
  const data = (await response.json()) as { available?: boolean };
  return data.available === true;
}

export async function submitPdf(
  file: File,
  configId: string,
  options: ExtractionOptions,
): Promise<JobRecord> {
  const body = new FormData();
  body.append('file', file, file.name);
  body.append('config_id', configId);
  Object.entries(options).forEach(([key, value]) => body.append(key, String(value)));
  const response = await fetch('/ui-api/jobs', { method: 'POST', body });
  if (!response.ok) throw new Error(await errorMessage(response));
  const data = (await response.json()) as {
    request_id: string;
    status: string | number;
    filename: string;
    submitted_at: string;
    config_label: string;
  };
  return {
    request_id: data.request_id,
    status: String(data.status),
    filename: data.filename || file.name,
    submitted_at: data.submitted_at || new Date().toISOString(),
    config: data.config_label || configId,
    size: file.size,
    options,
  };
}

export async function retrieveZip(requestId: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch('/ui-api/results', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/zip, application/json' },
    body: JSON.stringify({ request_id: requestId }),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: await response.blob(),
    filename: match?.[1] || 'pdflens-result.zip',
  };
}
