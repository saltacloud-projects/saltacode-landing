const header = document.querySelector<HTMLElement>("[data-scroll-header]");

if (header) {
  const revealOffset = 48;
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
  window.addEventListener("scroll", scheduleSync, { passive: true });
  window.addEventListener("pageshow", syncVisibility);
}
