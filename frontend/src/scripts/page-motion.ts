const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const chatLauncher = document.querySelector<HTMLFormElement>("[data-chat-launcher]");
let chatModulePromise: Promise<typeof import("./chat-preview")> | undefined;
let openingChat = false;

if (chatLauncher) chatLauncher.onsubmit = (event) => {
  event.preventDefault();
  const shortcut = event.submitter;
  const question = chatLauncher.elements.namedItem("question");
  if (shortcut instanceof HTMLButtonElement && shortcut.value && question instanceof HTMLInputElement) {
    question.value = `Quiero información sobre ${shortcut.value}.`;
  }
  if (openingChat) return;
  openingChat = true;
  chatModulePromise ??= import("./chat-preview");
  void chatModulePromise
    .then(({ openChatPreview }) => openChatPreview(chatLauncher))
    .finally(() => { openingChat = false; });
};

function initializeClientCarousel(): void {
  void import("./client-carousel").then(({ initializeClientCarousel: startClientCarousel }) => {
    startClientCarousel();
  });
}

function initializeHeroMotion(): void {
  const motionRoot = document.querySelector<HTMLElement>("[data-hero-motion]");
  if (!motionRoot || reducedMotion.matches) return;

  void import("./hero-motion").then(({ startHeroMotion }) => {
    if (!reducedMotion.matches) startHeroMotion(motionRoot);
  });
}

if (!reducedMotion.matches) {
  initializeClientCarousel();

  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(initializeHeroMotion, { timeout: 1_200 });
  } else {
    setTimeout(initializeHeroMotion, 0);
  }
}

if (chatLauncher) try {
  if (localStorage.getItem("saltacode-chat-transcript")) setTimeout(() => {
    chatModulePromise ??= import("./chat-preview");
    void chatModulePromise.then(({ initializeChatResume }) => initializeChatResume(chatLauncher));
  }, 0);
} catch {
  // Storage can be disabled without affecting the first-use chat launcher.
}

reducedMotion.addEventListener("change", ({ matches }) => {
  if (!matches) initializeClientCarousel();
});
