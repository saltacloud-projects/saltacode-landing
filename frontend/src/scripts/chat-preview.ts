import { createClientMessageId } from "./client-message-id";

const CHAT_STYLES = `.chat-preview{position:fixed;inset:1rem 1rem 1rem auto;width:min(460px,calc(100% - 2rem));height:calc(100dvh - 2rem);margin:0;padding:0;overflow:hidden;border:1px solid var(--line);border-radius:24px;color:var(--ink);background:var(--surface-raised);box-shadow:0 24px 80px rgb(0 0 0/.24);opacity:0;transform:translateX(28px) scale(.975)}
.chat-preview[open]{animation:chat-enter .44s cubic-bezier(.16,1,.3,1) forwards}
.chat-preview::backdrop{background:rgb(8 6 14/.46);backdrop-filter:blur(3px)}
body:has(.chat-preview[open]){overflow:hidden}
.chat-layout{position:relative;display:grid;height:100%;grid-template-rows:auto minmax(0,1fr) auto;background:var(--surface-raised)}
.chat-layout::before{position:absolute;z-index:2;inset:0;border:1px solid rgb(103 65 245/.3);border-radius:inherit;box-shadow:inset 0 0 30px rgb(103 65 245/.05);opacity:0;content:"";pointer-events:none;animation:chat-frame 1s .12s ease-out forwards}
.chat-head{position:relative;display:flex;align-items:center;gap:.8rem;overflow:hidden;padding:1rem 1.1rem;border-bottom:1px solid var(--line);background:linear-gradient(110deg,var(--surface-raised),var(--purple-soft),var(--surface-raised))}
.chat-head::after{position:absolute;inset:0;background:linear-gradient(105deg,transparent 30%,rgb(255 255 255/.24) 48%,transparent 66%);content:"";pointer-events:none;transform:translateX(-120%);animation:chat-sheen .9s .22s cubic-bezier(.16,1,.3,1) both}
.chat-tech{position:relative;display:grid;width:52px;height:44px;flex:0 0 auto;color:var(--purple);place-items:center}
.chat-tech::before{position:absolute;width:44px;height:44px;border-radius:50%;background:radial-gradient(circle,rgb(103 65 245/.22),transparent 68%);opacity:0;content:"";animation:chat-aura 1.4s .18s ease-out both}
.chat-tech svg{position:relative;width:52px;height:44px;overflow:visible;fill:none;stroke:currentColor;stroke-linecap:round;stroke-linejoin:round}
.chat-tech .chat-circuit{stroke-width:1.25;stroke-dasharray:28;stroke-dashoffset:28;opacity:.5;animation:chat-circuit .7s .16s ease-out forwards}
.chat-tech .chat-mountain{stroke:var(--ink);stroke-width:3.6;stroke-dasharray:54;stroke-dashoffset:54}
.chat-tech .chat-mountain-left{animation:chat-mountain .55s .34s cubic-bezier(.2,.8,.2,1) forwards}
.chat-tech .chat-mountain-right{animation:chat-mountain .58s .5s cubic-bezier(.2,.8,.2,1) forwards}
.chat-tech circle{fill:currentColor;stroke:none;transform-box:fill-box;transform-origin:center;opacity:0;animation:chat-node .4s .76s cubic-bezier(.2,1.8,.4,1) forwards}
.chat-head>div{position:relative;z-index:1;display:grid;line-height:1.25}
.chat-head small{color:var(--muted);font-size:.72rem}
.chat-close{position:relative;z-index:1;display:grid;width:42px;height:42px;margin-left:auto;padding:0;border:1px solid var(--line);border-radius:50%;color:var(--ink);background:var(--surface);font-size:1.4rem;cursor:pointer;place-items:center}
.chat-log{display:flex;overflow-y:auto;flex-direction:column;gap:.75rem;padding:1.15rem}
.chat-message{max-width:86%;padding:.75rem .9rem;border-radius:16px;background:var(--surface-soft);line-height:1.45}
.chat-preview[open] .chat-log>.chat-message:first-child{animation:chat-content .42s .38s ease-out both}
.chat-message[data-role=user]{align-self:flex-end;color:var(--on-accent);background:var(--button-accent);border-bottom-right-radius:5px}
.chat-message[data-role=agent]{align-self:flex-start;border:1px solid var(--line);border-bottom-left-radius:5px}
.chat-message[data-state=error]{border-color:var(--rose)}
.chat-message p{margin:0;white-space:pre-wrap}
.chat-retry{margin-top:.65rem;padding:.4rem .65rem;border:1px solid var(--line);border-radius:999px;color:var(--ink);background:var(--surface);font-weight:700}
.chat-suggestions{display:flex;flex-wrap:wrap;gap:.45rem}
.chat-suggestions button{min-height:38px;padding:.45rem .7rem;border:1px solid var(--line);border-radius:999px;color:var(--ink);background:var(--surface);font-size:.78rem}
.chat-preview[open] .chat-suggestions button{animation:chat-content .38s .52s ease-out both}
.chat-compose{padding:.9rem 1rem max(.9rem,env(safe-area-inset-bottom));border-top:1px solid var(--line);background:var(--surface)}
.chat-compose>label{display:block;margin-bottom:.45rem;color:var(--muted);font-size:.75rem}
.chat-row{display:flex;align-items:flex-end;gap:.55rem}
.chat-row textarea{width:100%;min-height:48px;max-height:120px;padding:.7rem .8rem;border:1px solid var(--line);border-radius:14px;color:var(--ink);background:var(--surface-raised);font:inherit;line-height:1.35;resize:vertical}
.chat-send{min-height:48px;padding:.6rem 1rem;border:0;border-radius:999px;color:var(--on-accent);background:var(--button-accent);font:inherit;font-weight:800;cursor:pointer}
.chat-send:disabled{opacity:.58}
.chat-actions{margin-top:.55rem}
.chat-actions a{color:var(--purple-dark);font-size:.78rem}
.chat-consent-gate{position:absolute;z-index:3;inset:72px 0 0;display:grid;align-content:center;padding:clamp(1.25rem,5vw,2.5rem);background:var(--surface-raised)}
.chat-consent-gate[hidden]{display:none}
.chat-consent-gate::before{position:absolute;inset:0;background:linear-gradient(135deg,transparent 0 35%,rgb(103 65 245/.08) 35.2% 35.6%,transparent 35.8% 64%,rgb(103 65 245/.08) 64.2% 64.6%,transparent 64.8%);content:"";pointer-events:none}
.chat-consent-card{position:relative;padding:1.4rem;border:1px solid var(--line);border-radius:20px;background:var(--surface);box-shadow:var(--shadow)}
.chat-consent-card h2{margin-bottom:.75rem;font-size:1.35rem}
.chat-consent-card p{color:var(--muted);font-size:.88rem}
.chat-consent-card a{color:var(--purple-dark)}
.chat-consent-question{padding:.75rem;border-left:3px solid var(--purple);background:var(--purple-soft);color:var(--ink)!important}
.chat-sensitive{font-size:.78rem!important}
.chat-consent-actions{display:flex;flex-wrap:wrap;gap:.6rem;margin-top:1rem}
.chat-consent-accept,.chat-consent-cancel{min-height:44px;padding:.65rem 1rem;border-radius:999px;font:inherit;font-weight:750;cursor:pointer}
.chat-consent-accept{border:1px solid var(--button-accent);color:var(--on-accent);background:var(--button-accent)}
.chat-consent-cancel{border:1px solid var(--line);color:var(--ink);background:var(--surface-raised)}
@keyframes chat-enter{to{opacity:1;transform:none}}
@keyframes chat-frame{to{opacity:1}}
@keyframes chat-sheen{to{transform:translateX(120%)}}
@keyframes chat-circuit{to{stroke-dashoffset:0}}
@keyframes chat-mountain{to{stroke-dashoffset:0}}
@keyframes chat-node{to{opacity:1;transform:scale(1)}}
@keyframes chat-aura{0%{opacity:0;transform:scale(.55)}35%{opacity:1}to{opacity:.35;transform:scale(1.25)}}
@keyframes chat-content{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media(max-width:620px){.chat-preview{inset:0;width:100%;height:100dvh;border:0;border-radius:0;transform:translateY(22px) scale(.99)}.chat-head{padding-top:max(1rem,env(safe-area-inset-top))}.chat-consent-gate{inset:max(72px,calc(56px + env(safe-area-inset-top))) 0 0}.chat-message{max-width:92%}.chat-row{align-items:stretch}.chat-send{min-width:84px}}
@media(prefers-reduced-motion:reduce){.chat-preview[open],.chat-layout::before,.chat-head::after,.chat-tech::before,.chat-tech .chat-circuit,.chat-tech .chat-mountain,.chat-tech circle,.chat-preview[open] .chat-log>.chat-message:first-child,.chat-preview[open] .chat-suggestions button{animation:none}.chat-preview[open]{opacity:1;transform:none}.chat-layout::before,.chat-tech circle{opacity:1}.chat-tech .chat-circuit,.chat-tech .chat-mountain{stroke-dashoffset:0}}`;

const PRIVACY_VERSION = "saltacode-chat-privacy-2026-08-28";
const CONSENT_STORAGE_KEY = "saltacode-chat-consent";
const INITIAL_MESSAGE = "Hola, soy el asistente de SaltaCode. Contame qué necesitás resolver.";

interface StreamEvent {
  type: string;
  correlation_id?: string;
  response_id?: string;
  sequence?: number;
  delta?: string;
  retryable?: boolean;
  outcome?: string;
}

interface PendingMessage {
  text: string;
  clientMessageId: string;
}

interface PendingLaunch extends PendingMessage {
  input: HTMLInputElement | null;
}

interface StreamState {
  started: boolean;
  done: boolean;
  correlationId: string;
  responseId: string;
  lastSequence: number;
}

let dialog: HTMLDialogElement | undefined;
let composer: HTMLTextAreaElement;
let sendButton: HTMLButtonElement;
let log: HTMLElement;
let status: HTMLElement;
let gate: HTMLElement;
let gateAccept: HTMLButtonElement;
let gateQuestion: HTMLElement;
let interactiveBody: HTMLElement[];
let returnFocus: HTMLElement | null;
let pendingLaunch: PendingLaunch | undefined;
let currentController: AbortController | undefined;
let stylesApplied = false;
let sending = false;
let generation = 0;
let acceptedForPage = false;

function applyStyles(): void {
  if (stylesApplied) return;
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(CHAT_STYLES);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  stylesApplied = true;
}

function hasCurrentConsent(): boolean {
  if (acceptedForPage) return true;
  try {
    const value = JSON.parse(localStorage.getItem(CONSENT_STORAGE_KEY) ?? "null") as unknown;
    if (!value || typeof value !== "object") return false;
    const record = value as { version?: unknown; acceptedAt?: unknown };
    return record.version === PRIVACY_VERSION &&
      typeof record.acceptedAt === "string" &&
      Number.isFinite(Date.parse(record.acceptedAt));
  } catch {
    return false;
  }
}

function rememberConsent(): void {
  acceptedForPage = true;
  try {
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify({
      version: PRIVACY_VERSION,
      acceptedAt: new Date().toISOString(),
    }));
  } catch {
    // Consent remains valid for this page when local storage is unavailable.
  }
}

function addMessage(role: "agent" | "user", text: string): HTMLElement {
  const message = document.createElement("article");
  const paragraph = document.createElement("p");
  message.className = "chat-message";
  message.dataset.role = role;
  paragraph.textContent = text;
  message.append(paragraph);
  log.append(message);
  log.scrollTop = log.scrollHeight;
  return message;
}

function setBusy(value: boolean): void {
  sending = value;
  composer.disabled = value;
  sendButton.disabled = value;
  sendButton.textContent = value ? "Enviando…" : "Enviar";
}

function assertStreamIdentity(event: StreamEvent, state: StreamState): void {
  if (event.correlation_id !== state.correlationId || event.response_id !== state.responseId) {
    throw new Error("stream_identity_changed");
  }
}

function applyStreamEvent(event: StreamEvent, response: HTMLElement, state: StreamState): void {
  if (!dialog?.open || state.done) throw new Error("unexpected_stream_event");
  const paragraph = response.querySelector("p")!;

  if (event.type === "chat.started") {
    if (state.started || !event.correlation_id || !event.response_id) throw new Error("invalid_started");
    state.started = true;
    state.correlationId = event.correlation_id;
    state.responseId = event.response_id;
    return;
  }

  if (!state.started) throw new Error("stream_not_started");
  assertStreamIdentity(event, state);

  if (event.type === "chat.delta") {
    if (!event.delta || !Number.isInteger(event.sequence) || event.sequence! <= state.lastSequence) {
      throw new Error("invalid_sequence");
    }
    state.lastSequence = event.sequence!;
    if (response.dataset.empty === "true") paragraph.textContent = "";
    response.dataset.empty = "false";
    paragraph.textContent += event.delta;
    status.textContent = "El asistente está respondiendo.";
  } else if (event.type === "chat.error") {
    response.dataset.state = "error";
    paragraph.textContent = event.retryable
      ? "No pude responder ahora. Podés reintentar o contactarnos."
      : "No pude procesar la consulta. Revisala e intentá otra vez.";
    status.textContent = "No fue posible completar la respuesta.";
  } else if (event.type === "chat.done") {
    state.done = true;
    if (event.outcome === "completed") status.textContent = "Respuesta recibida.";
    else if (response.dataset.state !== "error") throw new Error("stream_failed");
  } else {
    throw new Error("unknown_stream_event");
  }
  log.scrollTop = log.scrollHeight;
}

async function consumeSse(
  stream: ReadableStream<Uint8Array>,
  response: HTMLElement,
  requestGeneration: number,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const state: StreamState = {
    started: false,
    done: false,
    correlationId: "",
    responseId: "",
    lastSequence: -1,
  };
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (requestGeneration !== generation || !dialog?.open) {
      await reader.cancel();
      throw new DOMException("Chat closed", "AbortError");
    }
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const data = frame.split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (!data) continue;
      let event: StreamEvent;
      try { event = JSON.parse(data) as StreamEvent; }
      catch { throw new Error("invalid_stream_json"); }
      applyStreamEvent(event, response, state);
    }
    if (done) break;
  }

  if (!state.started || !state.done) throw new Error("incomplete_stream");
}

function addRetry(response: HTMLElement, request: PendingMessage): void {
  if (response.querySelector("button")) return;
  const retry = document.createElement("button");
  retry.className = "chat-retry";
  retry.type = "button";
  retry.textContent = "Reintentar";
  retry.addEventListener("click", () => {
    response.remove();
    void sendMessage(request, false);
  }, { once: true });
  response.append(retry);
}

async function sendMessage(request: PendingMessage, addUser = true): Promise<void> {
  const cleanText = request.text.trim();
  if (!cleanText || sending || !hasCurrentConsent()) return;

  if (addUser) addMessage("user", cleanText);
  composer.value = "";
  setBusy(true);
  const responseMessage = addMessage("agent", "Preparando una respuesta…");
  responseMessage.dataset.empty = "true";
  status.textContent = "Conectando con el asistente.";
  const requestGeneration = ++generation;
  const controller = new AbortController();
  currentController = controller;

  try {
    const response = await fetch("/api/v1/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        client_message_id: request.clientMessageId,
        message: cleanText,
        locale: document.documentElement.lang === "en" ? "en" : "es-AR",
        transcript_consent: true,
        privacy_version: PRIVACY_VERSION,
      }),
    });
    if (!response.ok || !response.body) throw new Error(`http_${response.status}`);
    await consumeSse(response.body, responseMessage, requestGeneration);
  } catch (error) {
    if (requestGeneration !== generation || (error instanceof DOMException && error.name === "AbortError")) return;
    responseMessage.dataset.state = "error";
    responseMessage.querySelector("p")!.textContent =
      "El asistente no está disponible. Podés reintentar o escribirnos.";
    addRetry(responseMessage, request);
    status.textContent = "El asistente no está disponible.";
  } finally {
    if (requestGeneration !== generation) return;
    currentController = undefined;
    setBusy(false);
    composer.focus();
    log.scrollTop = log.scrollHeight;
  }
}

function showConsent(request: PendingLaunch): void {
  gate.hidden = false;
  gateQuestion.hidden = !request.text;
  gateQuestion.textContent = request.text ? `“${request.text}”` : "";
  gateAccept.textContent = request.text ? "Aceptar y enviar" : "Aceptar y continuar";
  interactiveBody.forEach((element) => { element.inert = true; });
  requestAnimationFrame(() => gateAccept.focus());
}

function hideConsent(): void {
  gate.hidden = true;
  interactiveBody.forEach((element) => { element.inert = false; });
}

function acceptPendingLaunch(): void {
  rememberConsent();
  hideConsent();
  const request = pendingLaunch;
  pendingLaunch = undefined;
  if (!request) {
    composer.focus();
    return;
  }
  if (request.input) request.input.value = "";
  if (request.text) void sendMessage(request);
  else composer.focus();
}

function abortCurrentRequest(): void {
  generation += 1;
  currentController?.abort();
  currentController = undefined;
  if (sending) setBusy(false);
}

function createDialog(): HTMLDialogElement {
  applyStyles();
  const element = document.createElement("dialog");
  element.className = "chat-preview";
  element.setAttribute("aria-labelledby", "chat-preview-title");
  element.innerHTML = `<section class="chat-layout"><header class="chat-head"><span class="chat-tech" aria-hidden="true"><svg viewBox="0 0 64 48" focusable="false"><path class="chat-circuit" d="M2 13h10l5 5M62 12H52l-5 5M3 40h9l5-5M61 39h-9l-5-5"/><path class="chat-mountain chat-mountain-left" d="M8 35 27 22l12 9"/><path class="chat-mountain chat-mountain-right" d="m31 30 13-11 14 16"/><circle cx="2" cy="13" r="1.8"/><circle cx="62" cy="12" r="1.8"/><circle cx="3" cy="40" r="1.8"/><circle cx="61" cy="39" r="1.8"/></svg></span><div><strong id="chat-preview-title">Asistente SaltaCode</strong><small>Orientación sobre servicios y proyectos</small></div><button class="chat-close" type="button" aria-label="Cerrar chat">×</button></header><div class="chat-log" role="log" aria-label="Conversación con el asistente"><article class="chat-message" data-role="agent"><p>${INITIAL_MESSAGE}</p></article><div class="chat-suggestions" aria-label="Consultas sugeridas"><button type="button">Necesito software a medida</button><button type="button">Quiero mejorar un proceso</button><button type="button">Busco un equipo IT</button></div></div><form class="chat-compose"><label for="chat-preview-message">Escribí tu consulta</label><div class="chat-row"><textarea id="chat-preview-message" maxlength="4000" rows="1" placeholder="Contanos qué necesitás…"></textarea><button class="chat-send" type="submit">Enviar</button></div><div class="chat-actions"><a href="/contacto/">Contactar a una persona</a></div></form><section class="chat-consent-gate" aria-labelledby="chat-consent-title" hidden><div class="chat-consent-card"><h2 id="chat-consent-title">Antes de iniciar el chat</h2><p>SaltaCode guardará esta conversación para responder y darle continuidad. La consulta puede ser procesada por proveedores de inteligencia artificial. Podés ejercer tus derechos según nuestra <a href="/legal/privacidad/" target="_blank" rel="noopener noreferrer">Política de privacidad</a> y conocer el almacenamiento usado en <a href="/legal/cookies/" target="_blank" rel="noopener noreferrer">Cookies</a>.</p><p class="chat-consent-question"></p><p class="chat-sensitive"><strong>No incluyas contraseñas, credenciales ni datos sensibles.</strong></p><div class="chat-consent-actions"><button class="chat-consent-accept" type="button">Aceptar y enviar</button><button class="chat-consent-cancel" type="button">Cancelar</button></div></div></section><p class="visually-hidden" role="status" aria-live="polite" aria-atomic="true"></p></section>`;
  document.body.append(element);

  composer = element.querySelector("textarea")!;
  sendButton = element.querySelector(".chat-send")!;
  log = element.querySelector(".chat-log")!;
  status = element.querySelector('[role="status"]')!;
  gate = element.querySelector(".chat-consent-gate")!;
  gateAccept = element.querySelector(".chat-consent-accept")!;
  gateQuestion = element.querySelector(".chat-consent-question")!;
  interactiveBody = [log, element.querySelector(".chat-compose")!];

  element.querySelector<HTMLButtonElement>(".chat-close")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLButtonElement>(".chat-consent-cancel")!.addEventListener("click", () => element.close());
  gateAccept.addEventListener("click", acceptPendingLaunch);
  element.querySelector<HTMLAnchorElement>(".chat-actions a")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLFormElement>(".chat-compose")!.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendMessage({ text: composer.value, clientMessageId: createClientMessageId() });
  });
  composer.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void sendMessage({ text: composer.value, clientMessageId: createClientMessageId() });
    }
  });
  element.querySelector(".chat-suggestions")!.addEventListener("click", (event) => {
    const suggestion = (event.target as HTMLElement).closest<HTMLButtonElement>("button");
    if (suggestion) {
      composer.value = suggestion.textContent ?? "";
      composer.focus();
    }
  });
  element.addEventListener("close", () => {
    abortCurrentRequest();
    pendingLaunch = undefined;
    hideConsent();
    returnFocus?.focus();
  });
  return element;
}

export function openChatPreview(launcher: HTMLFormElement): void {
  const question = launcher.elements.namedItem("question");
  const input = question instanceof HTMLInputElement ? question : null;
  const text = input?.value.trim() ?? "";
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : launcher;
  dialog ??= createDialog();
  if (dialog.open) {
    composer.focus();
    return;
  }

  pendingLaunch = { text, clientMessageId: createClientMessageId(), input };
  dialog.showModal();
  if (!hasCurrentConsent()) {
    showConsent(pendingLaunch);
    return;
  }

  hideConsent();
  const request = pendingLaunch;
  pendingLaunch = undefined;
  if (request.input) request.input.value = "";
  if (request.text) void sendMessage(request);
  else composer.focus();
}
