const header = document.querySelector<HTMLElement>("[data-scroll-header]");

if (header) {
  const revealOffset = 48;
  const menu = header.querySelector<HTMLDetailsElement>("[data-header-menu]");
  let framePending = false;

  const syncVisibility = () => {
    header.classList.toggle("is-visible", window.scrollY > revealOffset);
    framePending = false;
  };

  const scheduleSync = () => {
    if (framePending) return;
    framePending = true;
    window.requestAnimationFrame(syncVisibility);
  };

  syncVisibility();
  menu?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => menu.removeAttribute("open"));
  });
  menu?.addEventListener("keydown", ({ key }) => {
    if (key !== "Escape") return;
    menu.removeAttribute("open");
    menu.querySelector<HTMLElement>("summary")?.focus();
  });
  window.addEventListener("scroll", scheduleSync, { passive: true });
  window.addEventListener("pageshow", syncVisibility);
}
