import "./reveal-header";

type Theme = "light" | "dark";
type ThemePreference = Theme | "system";

const storageKey = "saltacode-theme";
const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
const root = document.documentElement;
const choices = [...document.querySelectorAll<HTMLInputElement>("[data-theme-choice]")];

function isPreference(value: string | undefined | null): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system";
}

function resolveTheme(preference: ThemePreference): Theme {
  return preference === "system" ? (systemTheme.matches ? "dark" : "light") : preference;
}

function syncThemeImages(theme: Theme): void {
  document.querySelectorAll<HTMLImageElement>("[data-theme-image]").forEach((image) => {
    const source = theme === "dark" ? image.dataset.themeSrcDark : image.dataset.themeSrcLight;
    if (source && image.getAttribute("src") !== source) image.src = source;
  });
}

function applyPreference(preference: ThemePreference, persist = false): void {
  const theme = resolveTheme(preference);
  root.dataset.theme = theme;
  root.dataset.themePreference = preference;
  root.style.colorScheme = theme;
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute(
    "content",
    theme === "dark" ? "#111016" : "#ffffff",
  );
  choices.forEach((choice) => {
    choice.checked = choice.value === preference;
  });
  syncThemeImages(theme);

  if (!persist) return;
  try {
    if (preference === "system") localStorage.removeItem(storageKey);
    else localStorage.setItem(storageKey, preference);
  } catch {
    // The selected theme still applies when storage is unavailable.
  }
}

const initialPreference = isPreference(root.dataset.themePreference)
  ? root.dataset.themePreference
  : "system";
applyPreference(initialPreference);

choices.forEach((choice) => {
  choice.addEventListener("change", () => {
    if (choice.checked && isPreference(choice.value)) applyPreference(choice.value, true);
  });
});

systemTheme.addEventListener("change", () => {
  if (root.dataset.themePreference === "system") applyPreference("system");
});

window.addEventListener("storage", ({ key, newValue }) => {
  if (key !== storageKey) return;
  applyPreference(isPreference(newValue) ? newValue : "system");
});
