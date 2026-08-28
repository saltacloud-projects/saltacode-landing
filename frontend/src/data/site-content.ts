import type { ImageMetadata } from "astro";

import officeImage from "../assets/about/office.webp";
import consultingImage from "../assets/services/consulting.webp";
import outsourcingImage from "../assets/services/outsourcing.webp";
import saasImage from "../assets/services/saas.webp";
import softwareImage from "../assets/services/software-factory.webp";

export const site = {
  name: "SaltaCode",
  email: "saltacodear@gmail.com",
  phoneDisplay: "+54 9 387 529-6587",
  phoneHref: "tel:+5493875296587",
  address: "Zuviría 333, Oficina 4C",
  locality: "Salta, Argentina",
  maps: "https://maps.app.goo.gl/RKfbDFHbga3HUNvH7",
  whatsapp:
    "https://wa.me/5493875296587?text=Hola%2C%20quisiera%20informaci%C3%B3n%20sobre%20sus%20servicios",
  social: [
    { name: "LinkedIn", href: "https://www.linkedin.com/company/saltacode/" },
    { name: "Instagram", href: "https://www.instagram.com/saltacode.ar/" },
    { name: "Facebook", href: "https://www.facebook.com/saltacode.ar" },
  ],
} as const;

export interface Service {
  id: "software-factory" | "consultoria-it" | "outsourcing" | "soluciones-saas";
  legacyAlias: "it-consulting" | "saas-solutions" | null;
  number: string;
  title: string;
  shortDescription: string;
  description: string;
  image: ImageMetadata;
  imageAlt: string;
  features: readonly { title: string; copy: string }[];
}

export const services = [
  {
    id: "software-factory",
    legacyAlias: null,
    number: "01",
    title: "Software a medida e integraciones",
    shortDescription: "Sistemas web y móviles que se adaptan a tus procesos y conectan tus herramientas.",
    description:
      "Diseñamos y desarrollamos sistemas web y móviles adaptados a tus procesos, integraciones y objetivos de negocio.",
    image: softwareImage,
    imageAlt: "Tarjeta de presentación de SaltaCode",
    features: [
      { title: "Procesos", copy: "Digitalizamos tareas y flujos que hoy consumen tiempo." },
      { title: "Integraciones", copy: "Conectamos herramientas y datos para evitar trabajo duplicado." },
      { title: "Web y mobile", copy: "Construimos experiencias para clientes y equipos internos." },
      { title: "Evolución", copy: "Priorizamos entregas según la necesidad concreta del proyecto." },
    ],
  },
  {
    id: "consultoria-it",
    legacyAlias: "it-consulting",
    number: "02",
    title: "Consultoría IT",
    shortDescription: "Decisiones de arquitectura, tecnología y evolución con contexto técnico y de negocio.",
    description:
      "Analizamos tu contexto y te ayudamos a decidir arquitectura, tecnologías y un plan de implementación antes de avanzar.",
    image: consultingImage,
    imageAlt: "Saludo profesional de un integrante de SaltaCode",
    features: [
      { title: "Arquitectura", copy: "Definimos límites, integraciones y criterios de evolución." },
      { title: "Tecnología", copy: "Comparamos opciones según costo, equipo y mantenimiento." },
      { title: "Revisión", copy: "Detectamos riesgos, cuellos de botella y deuda técnica." },
      { title: "Hoja de ruta", copy: "Ordenamos prioridades y próximos pasos ejecutables." },
    ],
  },
  {
    id: "outsourcing",
    legacyAlias: null,
    number: "03",
    title: "Equipos IT",
    shortDescription: "Perfiles técnicos o equipos para iniciar un proyecto o ampliar tu capacidad.",
    description:
      "Sumamos perfiles técnicos o equipos para iniciar un proyecto, ampliar capacidad o complementar tu equipo interno.",
    image: outsourcingImage,
    imageAlt: "Taza de SaltaCode en una oficina",
    features: [
      { title: "Perfiles", copy: "Armamos el equipo según el desafío y la etapa del proyecto." },
      { title: "Integración", copy: "Trabajamos con tus responsables, procesos y herramientas." },
      { title: "Escala", copy: "Ajustamos la composición a medida que cambia el proyecto." },
      { title: "Seguimiento", copy: "Mantenemos objetivos, comunicación y calidad visibles." },
    ],
  },
  {
    id: "soluciones-saas",
    legacyAlias: "saas-solutions",
    number: "04",
    title: "Desarrollo de productos SaaS",
    shortDescription: "Diseño, construcción y evolución de productos digitales basados en suscripción.",
    description:
      "Diseñamos, construimos y evolucionamos productos SaaS preparados para operar con usuarios reales.",
    image: saasImage,
    imageAlt: "Equipo de SaltaCode colaborando frente a una computadora",
    features: [
      { title: "Producto", copy: "Aterrizamos el problema, el alcance y la experiencia de uso." },
      { title: "Cuentas y permisos", copy: "Preparamos usuarios, accesos y operación del servicio." },
      { title: "Integraciones", copy: "Conectamos datos y servicios según cada caso." },
      { title: "Continuidad", copy: "Planificamos mantenimiento y nuevas capacidades." },
    ],
  },
] as const satisfies readonly Service[];

export const about = {
  image: officeImage,
  imageAlt: "Sala de reuniones de la oficina de SaltaCode en Salta",
  summary:
    "Somos un equipo tecnológico con base en Salta. Combinamos desarrollo, consultoría y equipos IT para entender cada necesidad y construir una solución que pueda evolucionar.",
  principles: [
    {
      title: "Entender antes de construir",
      copy: "Empezamos por el proceso, las personas involucradas y el resultado que se necesita.",
    },
    {
      title: "Decisiones explicadas",
      copy: "Hacemos visibles el alcance, las alternativas técnicas y los próximos pasos.",
    },
    {
      title: "Trabajo cercano",
      copy: "Acompañamos el proyecto desde Salta y trabajamos con equipos de distintos lugares.",
    },
  ],
} as const;

export const publicRoutes = [
  "/",
  "/servicios/",
  "/nosotros/",
  "/contacto/",
  "/legal/privacidad/",
  "/legal/cookies/",
  "/legal/terminos/",
] as const;

export const legalUpdatedAt = "27 de agosto de 2026";
