import type { ImageMetadata } from "astro";

import lockupOnDark from "../assets/optimized/brand/lockup-onDark.webp";
import lockupOnLight from "../assets/optimized/brand/lockup-onLight.webp";
import markOnDark from "../assets/optimized/brand/mark-onDark.webp";
import markOnLight from "../assets/optimized/brand/mark-onLight.webp";
import balanceOnDark from "../assets/optimized/client/balance-onDark.webp";
import balanceOnLight from "../assets/optimized/client/balance-onLight.webp";
import cocelOnDark from "../assets/optimized/client/cocel-onDark.webp";
import cocelOnLight from "../assets/optimized/client/cocel-onLight.webp";
import coseguroTotalOnDark from "../assets/optimized/client/coseguro-total-onDark.webp";
import coseguroTotalOnLight from "../assets/optimized/client/coseguro-total-onLight.webp";
import finanxOnDark from "../assets/optimized/client/finanx-onDark.webp";
import finanxOnLight from "../assets/optimized/client/finanx-onLight.webp";
import grupoKamalOnDark from "../assets/optimized/client/grupo-kamal-onDark.webp";
import grupoKamalOnLight from "../assets/optimized/client/grupo-kamal-onLight.webp";
import ko27OnDark from "../assets/optimized/client/ko27-onDark.webp";
import ko27OnLight from "../assets/optimized/client/ko27-onLight.webp";
import metalnorOnDark from "../assets/optimized/client/metalnor-onDark.webp";
import metalnorOnLight from "../assets/optimized/client/metalnor-onLight.webp";
import marianaProneOnDark from "../assets/optimized/client/mariana-prone-onDark.webp";
import marianaProneOnLight from "../assets/optimized/client/mariana-prone-onLight.webp";
import opticaTotalOnDark from "../assets/optimized/client/optica-total-onDark.webp";
import opticaTotalOnLight from "../assets/optimized/client/optica-total-onLight.webp";
import planetaPunaOnDark from "../assets/optimized/client/planeta-puna-onDark.webp";
import planetaPunaOnLight from "../assets/optimized/client/planeta-puna-onLight.webp";
import v8OnDark from "../assets/optimized/client/v8-onDark.webp";
import v8OnLight from "../assets/optimized/client/v8-onLight.webp";

export interface SurfaceImageVariants {
  onLight: ImageMetadata;
  onDark: ImageMetadata;
}

export interface Client {
  name: string;
  logo: SurfaceImageVariants;
}

export const brandImages = {
  mark: { onLight: markOnLight, onDark: markOnDark },
  lockup: { onLight: lockupOnLight, onDark: lockupOnDark },
} satisfies Record<string, SurfaceImageVariants>;

export const clients = [
  { name: "KO-27", logo: { onLight: ko27OnLight, onDark: ko27OnDark } },
  { name: "Balance", logo: { onLight: balanceOnLight, onDark: balanceOnDark } },
  { name: "V8", logo: { onLight: v8OnLight, onDark: v8OnDark } },
  { name: "Grupo Kamal", logo: { onLight: grupoKamalOnLight, onDark: grupoKamalOnDark } },
  { name: "Planeta Puna", logo: { onLight: planetaPunaOnLight, onDark: planetaPunaOnDark } },
  {
    name: "Óptica Total",
    logo: { onLight: opticaTotalOnLight, onDark: opticaTotalOnDark },
  },
  { name: "Metalnor", logo: { onLight: metalnorOnLight, onDark: metalnorOnDark } },
  { name: "Cocel", logo: { onLight: cocelOnLight, onDark: cocelOnDark } },
  { name: "Finanx", logo: { onLight: finanxOnLight, onDark: finanxOnDark } },
  {
    name: "Coseguro Total",
    logo: { onLight: coseguroTotalOnLight, onDark: coseguroTotalOnDark },
  },
  {
    name: "Mariana Prone",
    logo: { onLight: marianaProneOnLight, onDark: marianaProneOnDark },
  },
] as const satisfies readonly Client[];
