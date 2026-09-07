import { GitBranch, Hand } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import type { CrmAgent } from "../../crm/operations";
import { ProgressionPolicyEditor } from "./ProgressionPolicyEditor";

const STAGES = [
  {
    title: "Canal y gateway",
    owner: "Conexiones y rutas",
    description:
      "El canal recibe el mensaje. Un adaptador implementado lo normaliza y una ruta resuelve el agente de ingreso; las credenciales se configuran en Canales.",
  },
  {
    title: "Identidad y consentimiento",
    owner: "Reglas del dominio",
    description:
      "El sistema persiste la conversación e identifica el contacto. Vincular canales requiere evidencia; aportar un teléfono no autoriza cualquier mensaje ni fusiona identidades automáticamente.",
  },
  {
    title: "Atención del agente",
    owner: "Configuración por agente",
    description:
      "Nombre, instrucciones, modelo y recursos determinan la especialización. Las herramientas disponibles dependen de sus vinculaciones, no de un nombre comercial fijado en código.",
  },
  {
    title: "Datos y solicitud",
    owner: "Herramienta más formulario validado",
    description:
      "El agente puede proponer capturar datos mediante una herramienta habilitada. El visitante confirma contacto, canal y consentimiento; el servidor valida y registra la solicitud.",
  },
  {
    title: "Oportunidad",
    owner: "Política persistente y transacción",
    description:
      "La captura válida crea la oportunidad. La política de abajo permite continuar con el mismo agente o exige una derivación explícita. El historial de ingreso no se reasigna.",
  },
  {
    title: "Presupuesto y entrega",
    owner: "Integración externa y comandos auditados",
    description:
      "El sistema de presupuestos debe aportar el documento y valores autoritativos. Capturar una solicitud no emite presupuestos. La entrega requiere contacto, consentimiento y canal habilitado; un resultado incierto se revisa sin repetirlo automáticamente.",
  },
  {
    title: "Seguimiento, reunión y cierre",
    owner: "Operación y políticas comerciales",
    description:
      "El CRM registra tareas, reuniones y estados de oportunidad. Los seguimientos se programan con una fecha y condiciones concretas; existen controles de horario y consentimiento, no un planificador autónomo completo ni agenda externa conectada.",
  },
];

export default function PipelinePage() {
  const { user } = useAuth();
  const [profiles, setProfiles] = useState<CrmAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    api<CrmAgent[]>("/crm/automation/agents")
      .then((agents) => {
        if (current) setProfiles(agents);
      })
      .catch(() => {
        if (current) setError("No se pudo consultar el acceso a la configuración de agentes.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, []);
  const [agentId, setAgentId] = useState("");
  const canReadPolicy = hasPermission(user, PERMISSIONS.RUNTIME_READ);
  const canManage = hasPermission(user, PERMISSIONS.RUNTIME_MANAGE);
  const selected = profiles.find((agent) => agent.id === agentId);
  const configLinks = [
    { path: "identity", label: "Identidad y prompts", permission: PERMISSIONS.PROFILES_READ },
    { path: "tools", label: "Herramientas habilitadas", permission: PERMISSIONS.TOOLS_READ },
    {
      path: "handoffs",
      label: "Reglas de derivación",
      permission: PERMISSIONS.OPPORTUNITIES_MANAGE,
    },
    {
      path: "automation-policy",
      label: "Límites de seguimiento",
      permission: PERMISSIONS.OPPORTUNITIES_READ,
    },
  ];
  return (
    <div className="max-w-6xl space-y-6">
      <header className="flex items-start gap-3">
        <GitBranch className="mt-1 text-[var(--accent)]" size={24} />
        <div>
          <h2 className="text-xl font-semibold">Pipeline comercial</h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Un recorrido guiado con políticas configurables y controles del sistema. No es un editor
            de flujos arbitrarios ni una automatización externa ya conectada.
          </p>
        </div>
      </header>
      <section
        aria-labelledby="human-control-title"
        className="rounded-lg border border-[var(--accent)]/40 bg-[var(--bg-card)] p-4"
      >
        <h3 id="human-control-title" className="flex items-center gap-2 font-semibold">
          <Hand size={18} /> Intervención humana en cualquier etapa
        </h3>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Desde Inbox podés pausar, tomar control, responder, reasignar y reanudar explícitamente.
          Se detiene la automatización de esa conversación, no de todos los agentes. Un cambio de
          política no devuelve el control a la IA.
        </p>
        {hasPermission(user, PERMISSIONS.CONVERSATIONS_READ) && (
          <Link
            to="/inbox"
            className="mt-3 inline-flex min-h-11 items-center rounded border border-[var(--border-color)] px-3 py-2 text-sm"
          >
            Abrir Inbox
          </Link>
        )}
      </section>
      <ol aria-label="Etapas del pipeline" className="grid gap-3 md:grid-cols-2">
        {STAGES.map((stage, index) => (
          <li
            key={stage.title}
            className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4"
          >
            <p className="text-xs text-[var(--text-muted)]">
              {index + 1} · {stage.owner}
            </p>
            <h3 className="mt-1 font-semibold">{stage.title}</h3>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">{stage.description}</p>
          </li>
        ))}
      </ol>
      <section aria-labelledby="pipeline-agent-title" className="space-y-4">
        <div>
          <h3 id="pipeline-agent-title" className="font-semibold">
            Configuración del recorrido por agente
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Esta selección configura al agente elegido; no filtra el CRM ni cambia quién atiende una
            conversación.
          </p>
        </div>
        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}
        <label className="block max-w-lg text-sm">
          Agente cuya política vas a configurar
          <select
            disabled={loading}
            value={selected?.id ?? ""}
            onChange={(event) => setAgentId(event.target.value)}
            className="mt-1 min-h-11 w-full rounded border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2"
          >
            <option value="">Seleccionar agente…</option>
            {profiles.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </label>
        {!loading && profiles.length === 0 && (
          <p className="text-sm text-[var(--text-muted)]">
            No hay agentes accesibles con tus permisos. Solicita acceso o creá un agente desde su
            sección.
          </p>
        )}
        {selected && (
          <>
            <nav aria-label="Configuración comercial del agente" className="flex flex-wrap gap-2">
              {configLinks
                .filter((link) => hasPermission(user, link.permission))
                .map((link) => (
                  <Link
                    key={link.path}
                    to={`/agents/${selected.id}/${link.path}`}
                    className="inline-flex min-h-11 items-center rounded border border-[var(--border-color)] px-3 py-2 text-sm"
                  >
                    {link.label}
                  </Link>
                ))}
            </nav>
            {canReadPolicy ? (
              <ProgressionPolicyEditor
                key={selected.id}
                agentId={selected.id}
                canManage={canManage && selected.capabilities.includes(PERMISSIONS.RUNTIME_MANAGE)}
              />
            ) : (
              <p className="text-sm text-[var(--text-muted)]">
                No tenés permiso para consultar la política de ejecución de este agente.
              </p>
            )}
          </>
        )}
      </section>
      <section
        aria-labelledby="pipeline-external-title"
        className="rounded-lg border border-amber-500/30 p-5"
      >
        <h3 id="pipeline-external-title" className="font-semibold">
          Qué requiere integración externa
        </h3>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Web y WhatsApp cuentan con adaptadores implementados; la conexión y el tráfico deben
          verificarse. Instagram DM, Facebook Messenger y email todavía requieren implementación y
          habilitación del proveedor. El sistema autoritativo de presupuestos y una agenda externa
          no quedan conectados por guardar esta política.
        </p>
        {hasPermission(user, PERMISSIONS.CONNECTIONS_READ) && (
          <Link
            to="/channels"
            className="mt-3 inline-flex min-h-11 items-center rounded border border-[var(--border-color)] px-3 py-2 text-sm"
          >
            Revisar canales y conexiones
          </Link>
        )}
      </section>
    </div>
  );
}
