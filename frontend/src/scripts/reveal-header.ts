const compactMenuQuery = matchMedia("(max-width: 1151px)");
const header = document.querySelector<HTMLElement>(".site-header");

if (header) {
  const menu = header.querySelector<HTMLDetailsElement>("[data-header-menu]");

  if (menu) {
    const syncMenuMode = () => (menu.open = !compactMenuQuery.matches);

    syncMenuMode();
    compactMenuQuery.onchange = syncMenuMode;
    menu.onclick = ({ target }) => {
      if (compactMenuQuery.matches && (target as Element).closest("a")) {
        menu.open = false;
      }
    };
    menu.onkeydown = ({ key }) => {
      if (key !== "Escape" || !compactMenuQuery.matches) return;
      menu.open = false;
      menu.querySelector<HTMLElement>("summary")?.focus();
    };
  }

  if (header.hasAttribute("data-scroll-header")) {
    const syncVisibility = () => {
      header.classList.toggle("is-visible", scrollY > 48);
    };

    syncVisibility();
    window.addEventListener("scroll", () => requestAnimationFrame(syncVisibility), {
      passive: true,
    });
    window.addEventListener("pageshow", syncVisibility);
  }
}
