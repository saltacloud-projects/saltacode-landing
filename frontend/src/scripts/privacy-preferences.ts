import privacyStyleUrl from "../styles/privacy-preferences.css?url";

const STORAGE_KEY = "saltacode-privacy-preferences";
const STORAGE_VERSION = "saltacode-storage-2026-08-28";
const CHAT_CONSENT_KEY = "saltacode-chat-consent";

function initializePrivacyCenter(): void {
  const notice = document.querySelector<HTMLElement>("[data-privacy-notice]");
  const center = document.querySelector<HTMLDialogElement>("[data-privacy-center]");
  const status = center?.querySelector<HTMLElement>("[data-privacy-status]");

  function hasAcknowledgedCurrentVersion(): boolean {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")?.version === STORAGE_VERSION;
    } catch {
      return false;
    }
  }

  function saveCurrentConfiguration(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        version: STORAGE_VERSION,
        acknowledgedAt: new Date().toISOString(),
        categories: { necessary: true, analytics: false, marketing: false },
      }));
    } catch {
      if (status) status.textContent = "El navegador no permitió guardar la preferencia; podés seguir usando el sitio.";
    }
    if (notice) notice.hidden = true;
    center?.close();
  }

  function openCenter(): void {
    if (center && !center.open) center.showModal();
  }

  if (notice) notice.hidden = hasAcknowledgedCurrentVersion();

  const globalPrivacyControl = (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl;
  const gpcStatus = center?.querySelector<HTMLElement>("[data-privacy-gpc]");
  if (gpcStatus) {
    gpcStatus.textContent = globalPrivacyControl
      ? "Detectada y respetada: no vendemos ni compartimos datos para publicidad conductual."
      : "No detectada. De todos modos, no vendemos ni compartimos datos para publicidad conductual.";
  }

  document.querySelectorAll<HTMLElement>("[data-privacy-open], [data-privacy-settings]").forEach((control) => {
    control.addEventListener("click", (event) => {
      event.preventDefault();
      openCenter();
    });
  });
  notice?.querySelector<HTMLElement>("[data-privacy-accept]")?.addEventListener("click", saveCurrentConfiguration);
  center?.querySelector<HTMLElement>("[data-privacy-save]")?.addEventListener("click", saveCurrentConfiguration);
  center?.querySelector<HTMLElement>("[data-privacy-reset]")?.addEventListener("click", () => {
    try {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(CHAT_CONSENT_KEY);
      if (status) status.textContent = "Se eliminaron las preferencias locales de privacidad y la aceptación local del chat.";
      if (notice) notice.hidden = false;
    } catch {
      if (status) status.textContent = "El navegador no permitió restablecer las preferencias locales.";
    }
  });
}

const stylesheet = document.createElement("link");
stylesheet.rel = "stylesheet";
stylesheet.href = privacyStyleUrl;
stylesheet.addEventListener("load", initializePrivacyCenter, { once: true });
document.head.append(stylesheet);
