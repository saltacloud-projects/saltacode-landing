import { Send } from "lucide-react";
import type { FormEvent } from "react";

interface MessageComposerProps {
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}

export function MessageComposer({ value, busy, onChange, onSubmit }: MessageComposerProps) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <form
      onSubmit={submit}
      className="shrink-0 border-t border-[var(--border-color)] bg-[var(--bg-card)] p-3"
    >
      <label htmlFor="operator-message" className="sr-only">
        Respuesta del operador
      </label>
      <div className="flex items-end gap-2">
        <textarea
          id="operator-message"
          rows={1}
          maxLength={16_000}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Escribí una respuesta…"
          className="min-h-12 max-h-32 min-w-0 flex-1 resize-none rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
        />
        <button
          type="submit"
          aria-label="Enviar respuesta"
          disabled={busy || !value.trim()}
          className="inline-flex min-h-12 items-center gap-2 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-white disabled:opacity-50"
        >
          <Send size={16} /> <span className="hidden sm:inline">Enviar</span>
        </button>
      </div>
    </form>
  );
}
