import { useState } from "react";
import { formatDate, QUOTE_STATUS_LABELS } from "./presentation";
import type { OpportunityDetail } from "./types";

interface Props {
  opportunity: OpportunityDetail;
  busy: boolean;
  canManage: boolean;
  canRegisterAuthority: boolean;
  onRequest: (input: {
    requirements: Record<string, unknown>;
    status: "unavailable" | "review_required";
    failure_code: string;
  }) => void;
  onRegisterVersion: (
    requestId: string,
    input: {
      expected_version: number;
      authority_name: string;
      authority_version: string;
      external_reference: string;
      content_hash: string;
      issued_at: string;
    },
  ) => void;
}

export function QuotesPanel({
  opportunity,
  busy,
  canManage,
  canRegisterAuthority,
  onRequest,
  onRegisterVersion,
}: Props) {
  const [requirements, setRequirements] = useState("");
  const [needsReview, setNeedsReview] = useState(false);

  return (
    <section
      aria-labelledby="quotes-title"
      className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
    >
      <h3 id="quotes-title" className="font-semibold">
        Presupuestos
      </h3>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        Registrar una solicitud no calcula, emite ni entrega un presupuesto.
      </p>
      {canManage && (
        <form
          className="mt-4 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!requirements.trim()) return;
            onRequest({
              requirements: { scope: requirements.trim() },
              status: needsReview ? "review_required" : "unavailable",
              failure_code: needsReview ? "manual_review_required" : "quote_provider_unavailable",
            });
          }}
        >
          <label className="block text-xs text-[var(--text-muted)]">
            Alcance solicitado
            <textarea
              required
              rows={3}
              value={requirements}
              onChange={(event) => setRequirements(event.target.value)}
              className="mt-1 w-full resize-y rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-2 text-sm"
            />
          </label>
          <label className="mt-2 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={needsReview}
              onChange={(event) => setNeedsReview(event.target.checked)}
            />
            Requiere revisión manual antes de consultar una fuente autoritativa
          </label>
          <button
            type="submit"
            disabled={busy || !requirements.trim()}
            className="mt-3 w-full rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Registrar solicitud
          </button>
        </form>
      )}

      <div className="mt-4 space-y-3">
        {opportunity.quote_requests.map((request) => (
          <article key={request.id} className="rounded border border-[var(--border-color)] p-3">
            <div className="flex flex-wrap items-start gap-2">
              <strong className="min-w-0 flex-1 text-sm">
                Solicitud {formatDate(request.created_at)}
              </strong>
              <span className="rounded bg-[var(--bg-hover)] px-2 py-1 text-[10px]">
                {QUOTE_STATUS_LABELS[request.status]}
              </span>
            </div>
            {request.failure_code && (
              <p className="mt-2 text-xs text-[var(--warning)]">Bloqueo: {request.failure_code}</p>
            )}
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded bg-[var(--bg-secondary)] p-2 text-xs text-[var(--text-secondary)]">
              {JSON.stringify(request.requirements, null, 2)}
            </pre>
            {request.versions.map((version) => (
              <div
                key={version.id}
                className="mt-2 rounded border border-green-500/30 bg-green-500/5 p-2 text-xs"
              >
                <p className="font-medium text-green-400">
                  Versión {version.version} · evidencia autoritativa
                </p>
                <p className="mt-1 text-[var(--text-secondary)]">
                  {version.authority_name} {version.authority_version} ·{" "}
                  {version.external_reference}
                </p>
                <p className="mt-1 break-all font-mono text-[10px] text-[var(--text-muted)]">
                  SHA-256 {version.content_hash}
                </p>
                <p className="mt-1 text-[var(--text-muted)]">
                  Emitida {formatDate(version.issued_at)}
                </p>
              </div>
            ))}
            {canRegisterAuthority && request.status !== "cancelled" && (
              <AuthorityEvidenceForm
                request={request}
                busy={busy}
                onSubmit={(input) => onRegisterVersion(request.id, input)}
              />
            )}
          </article>
        ))}
        {opportunity.quote_requests.length === 0 && (
          <p className="text-sm text-[var(--text-muted)]">
            Todavía no hay solicitudes de presupuesto.
          </p>
        )}
      </div>
      <p className="mt-4 rounded border border-[var(--warning)]/30 bg-[var(--warning)]/5 p-3 text-xs text-[var(--warning)]">
        La entrega por WhatsApp o email no está habilitada desde este workspace. Cuando se
        implemente deberá revalidar contacto y consentimiento de entrega.
      </p>
    </section>
  );
}

function AuthorityEvidenceForm({
  request,
  busy,
  onSubmit,
}: {
  request: OpportunityDetail["quote_requests"][number];
  busy: boolean;
  onSubmit: (input: {
    expected_version: number;
    authority_name: string;
    authority_version: string;
    external_reference: string;
    content_hash: string;
    issued_at: string;
  }) => void;
}) {
  const [authorityName, setAuthorityName] = useState("");
  const [authorityVersion, setAuthorityVersion] = useState("");
  const [externalReference, setExternalReference] = useState("");
  const [contentHash, setContentHash] = useState("");
  const [issuedAt, setIssuedAt] = useState("");
  return (
    <form
      className="mt-3 grid gap-2 rounded border border-[var(--accent)]/30 p-3 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          expected_version: request.state_version,
          authority_name: authorityName,
          authority_version: authorityVersion,
          external_reference: externalReference,
          content_hash: contentHash,
          issued_at: new Date(issuedAt).toISOString(),
        });
      }}
    >
      <p className="text-xs font-semibold text-[var(--accent-hover)] sm:col-span-2">
        Registrar evidencia autoritativa
      </p>
      <EvidenceInput label="Autoridad" value={authorityName} onChange={setAuthorityName} />
      <EvidenceInput
        label="Versión de autoridad"
        value={authorityVersion}
        onChange={setAuthorityVersion}
      />
      <EvidenceInput
        label="Referencia externa"
        value={externalReference}
        onChange={setExternalReference}
      />
      <EvidenceInput
        label="SHA-256 en minúsculas"
        value={contentHash}
        onChange={setContentHash}
        pattern="[0-9a-f]{64}"
      />
      <label className="text-xs text-[var(--text-muted)] sm:col-span-2">
        Fecha de emisión
        <input
          required
          type="datetime-local"
          value={issuedAt}
          onChange={(event) => setIssuedAt(event.target.value)}
          className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 py-2 text-sm"
        />
      </label>
      <button
        type="submit"
        disabled={
          busy ||
          !authorityName ||
          !authorityVersion ||
          !externalReference ||
          !contentHash ||
          !issuedAt
        }
        className="rounded border border-[var(--accent)] px-3 py-2 text-sm text-[var(--accent-hover)] disabled:opacity-50 sm:col-span-2"
      >
        Registrar versión emitida
      </button>
    </form>
  );
}

function EvidenceInput({
  label,
  value,
  pattern,
  onChange,
}: {
  label: string;
  value: string;
  pattern?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="text-xs text-[var(--text-muted)]">
      {label}
      <input
        required
        value={value}
        pattern={pattern}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] px-2 py-2 text-sm"
      />
    </label>
  );
}
