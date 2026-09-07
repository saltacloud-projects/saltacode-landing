import { Plus, RefreshCw, Target } from "lucide-react";
import { useState } from "react";
import { useAgentWorkspace } from "../../agents/AgentWorkspaceContext";
import { useAuth } from "../../auth/AuthContext";
import { hasPermission, PERMISSIONS } from "../../auth/permissions";
import { CrmPagination, CrmScopeFilter, canOperateItem, useCrmScope } from "../../crm/operations";
import { CreateOpportunityForm } from "./CreateOpportunityForm";
import { OpportunityDetail } from "./OpportunityDetail";
import { OpportunityFiltersForm } from "./OpportunityFilters";
import { OpportunityList } from "./OpportunityList";
import { useOpportunities } from "./useOpportunities";

export default function OpportunitiesPage() {
  const scope = useCrmScope("opportunities");
  const { selectedAgent } = scope;
  const { profiles } = useAgentWorkspace();
  const { user } = useAuth();
  const [creating, setCreating] = useState(false);
  const canManage = hasPermission(user, PERMISSIONS.OPPORTUNITIES_MANAGE);
  const canRegisterAuthority = hasPermission(user, PERMISSIONS.QUOTES_APPROVE);
  const workspace = useOpportunities({
    agentId: scope.agentId,
    global: scope.global,
    offset: scope.offset,
    adminId: user?.id ?? "",
    canManage,
  });
  const canOperate = Boolean(
    canManage &&
      workspace.detail &&
      canOperateItem(scope.global, workspace.detail, user, PERMISSIONS.OPPORTUNITIES_MANAGE) &&
      (!workspace.detail.assigned_operator || workspace.detail.assigned_operator.id === user?.id),
  );

  return (
    <div className="mx-auto max-w-[1600px]">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <Target size={23} className="text-[var(--accent)]" />
        <div>
          <h2 className="text-xl font-semibold">
            Oportunidades{selectedAgent ? ` de ${selectedAgent.name}` : ""}
          </h2>
          <p className="text-sm text-[var(--text-muted)]">
            Expedientes comerciales, handoffs, seguimientos y evidencia de presupuestos.
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => void workspace.refresh()}
            className="inline-flex items-center gap-2 rounded border border-[var(--border-color)] px-3 py-2 text-sm"
          >
            <RefreshCw size={16} /> <span className="hidden sm:inline">Actualizar</span>
          </button>
          {canManage &&
            Boolean(scope.agentId) &&
            (!scope.global ||
              Boolean(
                scope.agents
                  .find((agent) => agent.id === scope.agentId)
                  ?.capabilities.includes(PERMISSIONS.OPPORTUNITIES_MANAGE),
              )) && (
              <button
                type="button"
                onClick={() => setCreating((value) => !value)}
                className="inline-flex items-center gap-2 rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white"
              >
                <Plus size={16} /> Nueva
              </button>
            )}
        </div>
      </header>
      <CrmScopeFilter scope={scope} label="Responsable comercial" />
      {scope.global && !scope.agentId && canManage && (
        <p className="mb-3 text-sm text-[var(--text-muted)]">
          Para crear una oportunidad, seleccioná su responsable comercial.
        </p>
      )}

      {creating && user && (
        <CreateOpportunityForm
          candidates={workspace.candidates}
          currentAdminId={user.id}
          busy={workspace.busy}
          onCancel={() => setCreating(false)}
          onSubmit={(input) => {
            void workspace.create(input).then((created) => {
              if (created) setCreating(false);
            });
          }}
        />
      )}

      <CrmPagination
        offset={scope.offset}
        total={workspace.total}
        loading={workspace.loadingList}
        onChange={scope.setOffset}
      />
      <OpportunityFiltersForm
        filters={workspace.filters}
        operators={workspace.operators}
        onChange={(filters) => {
          scope.setOffset(0);
          workspace.setFilters(filters);
        }}
      />

      {workspace.error && (
        <p
          role="alert"
          className="mb-4 rounded border border-[var(--error)]/35 bg-[var(--error)]/5 p-3 text-sm text-[var(--error)]"
        >
          {workspace.error}
        </p>
      )}

      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(17rem,0.75fr)_minmax(0,2fr)]">
        <OpportunityList
          items={workspace.items}
          selectedId={workspace.detail?.id}
          loading={workspace.loadingList}
          hiddenOnMobile={Boolean(workspace.detail)}
          onSelect={workspace.open}
        />
        <OpportunityDetail
          opportunity={workspace.detail}
          agents={
            scope.global
              ? scope.agents.filter((agent) =>
                  agent.capabilities.includes(PERMISSIONS.OPPORTUNITIES_MANAGE),
                )
              : profiles
          }
          operators={workspace.operators}
          loading={workspace.loadingDetail}
          busy={workspace.busy}
          canManage={canOperate}
          canRegisterAuthority={
            canOperate &&
            canRegisterAuthority &&
            canOperateItem(scope.global, workspace.detail, user, PERMISSIONS.QUOTES_APPROVE)
          }
          onBack={workspace.close}
          onStage={(stage, reason) => void workspace.transitionStage(stage, reason)}
          onReassign={(agentId, operatorId, reason) =>
            void workspace.reassign(agentId, operatorId, reason)
          }
          onLinkConversation={(conversationId) => void workspace.linkConversation(conversationId)}
          onCreateFollowUp={(input) => void workspace.createFollowUp(input)}
          onTransitionFollowUp={(taskId, status, version) =>
            void workspace.transitionFollowUp(taskId, status, version)
          }
          onRequestQuote={(input) => void workspace.requestQuote(input)}
          onRegisterQuoteVersion={(requestId, input) =>
            void workspace.registerQuoteVersion(requestId, input)
          }
        />
      </div>
    </div>
  );
}
