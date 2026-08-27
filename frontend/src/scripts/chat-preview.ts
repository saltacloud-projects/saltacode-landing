const CHAT_STYLES = `.chat-preview{position:fixed;inset:1rem 1rem 1rem auto;width:min(460px,calc(100% - 2rem));height:calc(100dvh - 2rem);margin:0;padding:0;overflow:hidden;border:1px solid var(--line);border-radius:24px;color:var(--ink);background:var(--surface-raised);box-shadow:0 24px 80px rgb(0 0 0/.24)}.chat-preview::backdrop{background:rgb(8 6 14/.46);backdrop-filter:blur(3px)}body:has(.chat-preview[open]){overflow:hidden}.chat-layout{display:grid;height:100%;grid-template-rows:auto minmax(0,1fr) auto;background:var(--surface-raised)}.chat-head{display:flex;align-items:center;gap:.75rem;padding:1rem 1.1rem;border-bottom:1px solid var(--line)}.chat-close{display:grid;width:42px;height:42px;padding:0;border:1px solid var(--line);border-radius:50%;color:var(--ink);background:var(--surface);font-size:1.4rem;cursor:pointer;place-items:center}.chat-log{display:flex;overflow-y:auto;flex-direction:column;gap:.75rem;padding:1.15rem}.chat-message{max-width:86%;padding:.75rem .9rem;border-radius:16px;background:var(--surface-soft);line-height:1.45}.chat-message[data-role=user]{align-self:flex-end;color:var(--on-accent);background:var(--button-accent);border-bottom-right-radius:5px}.chat-message[data-role=agent]{align-self:flex-start;border:1px solid var(--line);border-bottom-left-radius:5px}.chat-message p{margin:0;white-space:pre-wrap}.chat-suggestions{display:flex;flex-wrap:wrap;gap:.45rem}.chat-suggestions button{min-height:38px;padding:.45rem .7rem;border:1px solid var(--line);border-radius:999px;color:var(--ink);background:var(--surface);font-size:.78rem}.chat-compose{padding:.9rem 1rem max(.9rem,env(safe-area-inset-bottom));border-top:1px solid var(--line);background:var(--surface)}.chat-compose>label{display:block;margin-bottom:.45rem;color:var(--muted);font-size:.75rem}.chat-row{display:flex;align-items:flex-end;gap:.55rem}.chat-row textarea{width:100%;min-height:48px;max-height:120px;padding:.7rem .8rem;border:1px solid var(--line);border-radius:14px;color:var(--ink);background:var(--surface-raised);font:inherit;line-height:1.35;resize:vertical}.chat-send{min-height:48px;padding:.6rem 1rem;border:0;border-radius:999px;color:var(--on-accent);background:var(--button-accent);font:inherit;font-weight:800;cursor:pointer}.chat-send:disabled{opacity:.58}.chat-consent{display:flex;align-items:flex-start;gap:.5rem;margin-top:.65rem;color:var(--muted);font-size:.72rem;line-height:1.35}.chat-consent input{margin-top:.15rem;accent-color:var(--purple)}.chat-actions{margin-top:.55rem}.chat-actions a{color:var(--purple-dark);font-size:.78rem}@media(max-width:620px){.chat-preview{inset:0;width:100%;height:100dvh;border:0;border-radius:0}.chat-head{padding-top:max(1rem,env(safe-area-inset-top))}.chat-message{max-width:92%}.chat-row{align-items:stretch}.chat-send{min-width:84px}}`;

const PRIVACY_VERSION = "saltacode-chat-v1";
const INITIAL_MESSAGE = "Hola, soy el asistente de SaltaCode. Contame qué necesitás resolver.";

interface StreamEvent { type: string; delta?: string; code?: string; message?: string; retryable?: boolean; outcome?: string }

let dialog: HTMLDialogElement | undefined;
let composer: HTMLTextAreaElement;
let consent: HTMLInputElement;
let sendButton: HTMLButtonElement;
let log: HTMLElement;
let status: HTMLElement;
let returnFocus: HTMLElement | null;
let stylesApplied = false;
let sending = false;

function applyStyles(): void {
  if (stylesApplied) return;
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(CHAT_STYLES);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  stylesApplied = true;
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
  consent.disabled = value;
  sendButton.disabled = value;
  sendButton.textContent = value ? "Enviando…" : "Enviar";
}

function applyStreamEvent(event: StreamEvent, response: HTMLElement): void {
  const paragraph = response.querySelector("p")!;
  if (event.type === "chat.delta" && event.delta) {
    if (response.dataset.empty === "true") paragraph.textContent = "";
    response.dataset.empty = "false";
    paragraph.textContent += event.delta;
    status.textContent = "El asistente está respondiendo.";
  } else if (event.type === "chat.error") {
    response.dataset.state = "error";
    paragraph.textContent = event.retryable
      ? "No pude responder ahora. Probá nuevamente o contactanos."
      : "No pude procesar la consulta. Revisala e intentá otra vez.";
    status.textContent = "No fue posible completar la respuesta.";
  } else if (event.type === "chat.done" && event.outcome === "completed") {
    status.textContent = "Respuesta recibida.";
  }
  log.scrollTop = log.scrollHeight;
}

async function consumeSse(stream: ReadableStream<Uint8Array>, response: HTMLElement): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const data = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
      if (!data) continue;
      try { applyStreamEvent(JSON.parse(data) as StreamEvent, response); } catch { throw new Error("invalid_stream"); }
    }
    if (done) break;
  }
}

async function sendMessage(text: string): Promise<void> {
  const cleanText = text.trim();
  if (!cleanText || sending) return;
  if (!consent.checked) {
    status.textContent = "Necesitás aceptar el guardado del historial para continuar.";
    consent.focus();
    return;
  }

  addMessage("user", cleanText);
  composer.value = "";
  setBusy(true);
  const responseMessage = addMessage("agent", "Preparando una respuesta…");
  responseMessage.dataset.empty = "true";
  status.textContent = "Conectando con el asistente.";
  try {
    const response = await fetch("/api/v1/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_message_id: crypto.randomUUID(),
        message: cleanText,
        locale: document.documentElement.lang === "en" ? "en" : "es-AR",
        transcript_consent: true,
        privacy_version: PRIVACY_VERSION,
      }),
    });
    if (!response.ok || !response.body) throw new Error(`http_${response.status}`);
    await consumeSse(response.body, responseMessage);
  } catch {
    responseMessage.dataset.state = "error";
    responseMessage.querySelector("p")!.textContent = "El asistente no está disponible. Probá nuevamente o escribinos.";
    status.textContent = "El asistente no está disponible.";
  } finally {
    setBusy(false);
    composer.focus();
    log.scrollTop = log.scrollHeight;
  }
}

function createDialog(): HTMLDialogElement {
  applyStyles();
  const element = document.createElement("dialog");
  element.className = "chat-preview";
  element.setAttribute("aria-labelledby", "chat-preview-title");
  element.innerHTML = `<section class="chat-layout"><header class="chat-head"><span aria-hidden="true">✦</span><div><strong id="chat-preview-title">Asistente SaltaCode</strong><small>Orientación sobre servicios y proyectos</small></div><button class="chat-close" type="button" aria-label="Cerrar chat">×</button></header><div class="chat-log" role="log" aria-label="Conversación con el asistente"><article class="chat-message" data-role="agent"><p>${INITIAL_MESSAGE}</p></article><div class="chat-suggestions" aria-label="Consultas sugeridas"><button type="button">Necesito software a medida</button><button type="button">Quiero mejorar un proceso</button><button type="button">Busco un equipo IT</button></div></div><form class="chat-compose"><label for="chat-preview-message">Escribí tu consulta</label><div class="chat-row"><textarea id="chat-preview-message" maxlength="4000" rows="1" placeholder="Contanos qué necesitás…"></textarea><button class="chat-send" type="submit">Enviar</button></div><label class="chat-consent"><input type="checkbox" name="transcript-consent" /><span>Acepto que SaltaCode guarde este chat para continuar la conversación. No compartas contraseñas ni datos sensibles.</span></label><div class="chat-actions"><a href="#contacto">Contactar a una persona</a></div></form><p class="visually-hidden" role="status" aria-live="polite" aria-atomic="true"></p></section>`;
  document.body.append(element);

  composer = element.querySelector("textarea")!;
  consent = element.querySelector('input[name="transcript-consent"]')!;
  sendButton = element.querySelector(".chat-send")!;
  log = element.querySelector(".chat-log")!;
  status = element.querySelector('[role="status"]')!;
  element.querySelector<HTMLButtonElement>(".chat-close")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLAnchorElement>(".chat-actions a")!.addEventListener("click", () => element.close());
  element.querySelector<HTMLFormElement>(".chat-compose")!.addEventListener("submit", (event) => { event.preventDefault(); void sendMessage(composer.value); });
  composer.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(composer.value); } });
  element.querySelector(".chat-suggestions")!.addEventListener("click", (event) => { const suggestion = (event.target as HTMLElement).closest<HTMLButtonElement>("button"); if (suggestion) { composer.value = suggestion.textContent ?? ""; composer.focus(); } });
  element.addEventListener("close", () => returnFocus?.focus());
  return element;
}

export function openChatPreview(launcher: HTMLFormElement): void {
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : launcher;
  dialog ??= createDialog();
  if (!dialog.open) dialog.showModal();
  const question = launcher.elements.namedItem("question");
  const initialQuestion = question instanceof HTMLInputElement ? question.value : "";
  if (question instanceof HTMLInputElement) question.value = "";
  composer.value = initialQuestion.trim();
  composer.focus();
}
