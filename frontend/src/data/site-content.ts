import type { ImageMetadata } from "astro";

import officeImage from "../assets/about/office.webp";
import consultingImage from "../assets/services/consulting.webp";
import outsourcingImage from "../assets/services/outsourcing.webp";
import saasImage from "../assets/services/saas.webp";
import softwareImage from "../assets/services/software-factory.webp";

export const site = {
  name: "SaltaCode",
  legalName: "Oscar Vargas",
  taxId: "20-38213561-0",
  email: "saltacodear@gmail.com",
  phoneDisplay: "+54 9 387 529-6587",
  phoneHref: "tel:+5493875296587",
  address: "Zuviría 333, Oficina 4C",
  locality: "Salta, Argentina",
  maps: "https://maps.app.goo.gl/RKfbDFHbga3HUNvH7",
  whatsapp:
    "https://wa.me/5493875296587?text=Hola%2C%20quisiera%20informaci%C3%B3n%20sobre%20sus%20servicios",
  social: [
    { name: "LinkedIn", icon: "linkedin", href: "https://www.linkedin.com/company/saltacode/" },
    { name: "Instagram", icon: "instagram", href: "https://www.instagram.com/saltacode.ar/" },
    { name: "Facebook", icon: "facebook", href: "https://www.facebook.com/saltacode.ar" },
  ],
} as const;

export interface Service {
  id: "software-factory" | "consultoria-it" | "outsourcing" | "soluciones-saas";
  slug: "software-a-medida" | "consultoria-it" | "equipos-it" | "productos-saas";
  href: `/servicios/${Service["slug"]}/`;
  legacyAlias: "it-consulting" | "saas-solutions" | null;
  number: string;
  title: string;
  shortDescription: string;
  description: string;
  detailHeading: string;
  detailLead: string;
  seoTitle: string;
  seoDescription: string;
  image: ImageMetadata;
  imageAlt: string;
  features: readonly { title: string; copy: string }[];
  situations: readonly string[];
}

export const services = [
  {
    id: "software-factory",
    slug: "software-a-medida",
    href: "/servicios/software-a-medida/",
    legacyAlias: null,
    number: "01",
    title: "Software a medida e integraciones",
    shortDescription: "Sistemas web y móviles que se adaptan a tus procesos y conectan tus herramientas.",
    description:
      "Diseñamos y desarrollamos sistemas web y móviles adaptados a tus procesos, integraciones y objetivos de negocio.",
    detailHeading: "Software a medida para procesos que no encajan en una herramienta estándar",
    detailLead: "Convertimos una necesidad operativa o comercial en una solución web o móvil que se integra con las herramientas que ya usás.",
    seoTitle: "Software a medida e integraciones | SaltaCode",
    seoDescription: "Desarrollo de software web y móvil a medida, automatización de procesos e integraciones para empresas desde Salta, Argentina.",
    image: softwareImage,
    imageAlt: "Tarjeta de presentación de SaltaCode",
    features: [
      { title: "Procesos", copy: "Digitalizamos tareas y flujos que hoy consumen tiempo." },
      { title: "Integraciones", copy: "Conectamos herramientas y datos para evitar trabajo duplicado." },
      { title: "Web y mobile", copy: "Construimos experiencias para clientes y equipos internos." },
      { title: "Evolución", copy: "Priorizamos entregas según la necesidad concreta del proyecto." },
    ],
    situations: [
      "Tu equipo repite tareas manuales o mueve datos entre varias herramientas.",
      "Un software estándar no refleja el proceso real de tu empresa.",
      "Necesitás conectar sistemas existentes sin reemplazarlos de una sola vez.",
    ],
  },
  {
    id: "consultoria-it",
    slug: "consultoria-it",
    href: "/servicios/consultoria-it/",
    legacyAlias: "it-consulting",
    number: "02",
    title: "Consultoría IT",
    shortDescription: "Decisiones de arquitectura, tecnología y evolución con contexto técnico y de negocio.",
    description:
      "Analizamos tu contexto y te ayudamos a decidir arquitectura, tecnologías y un plan de implementación antes de avanzar.",
    detailHeading: "Consultoría IT para decidir con claridad antes de invertir",
    detailLead: "Revisamos la situación actual, los riesgos y las alternativas para transformar una duda técnica en un plan explicable y ejecutable.",
    seoTitle: "Consultoría IT y arquitectura de software | SaltaCode",
    seoDescription: "Consultoría IT para arquitectura, selección tecnológica, deuda técnica y hojas de ruta de software con contexto de negocio.",
    image: consultingImage,
    imageAlt: "Saludo profesional de un integrante de SaltaCode",
    features: [
      { title: "Arquitectura", copy: "Definimos límites, integraciones y criterios de evolución." },
      { title: "Tecnología", copy: "Comparamos opciones según costo, equipo y mantenimiento." },
      { title: "Revisión", copy: "Detectamos riesgos, cuellos de botella y deuda técnica." },
      { title: "Hoja de ruta", copy: "Ordenamos prioridades y próximos pasos ejecutables." },
    ],
    situations: [
      "Tenés que elegir tecnología o arquitectura y necesitás comparar alternativas.",
      "Un sistema creció y ahora presenta límites, riesgos o deuda técnica.",
      "Querés ordenar una iniciativa antes de comprometer presupuesto y equipo.",
    ],
  },
  {
    id: "outsourcing",
    slug: "equipos-it",
    href: "/servicios/equipos-it/",
    legacyAlias: null,
    number: "03",
    title: "Equipos IT",
    shortDescription: "Perfiles técnicos o equipos para iniciar un proyecto o ampliar tu capacidad.",
    description:
      "Sumamos perfiles técnicos o equipos para iniciar un proyecto, ampliar capacidad o complementar tu equipo interno.",
    detailHeading: "Equipos IT para ampliar capacidad sin perder el contexto",
    detailLead: "Integramos perfiles técnicos o un equipo a una iniciativa concreta, con objetivos y comunicación compartidos con tus responsables.",
    seoTitle: "Equipos IT y talento técnico para proyectos | SaltaCode",
    seoDescription: "Perfiles técnicos y equipos de desarrollo para iniciar proyectos, ampliar capacidad o complementar equipos internos.",
    image: outsourcingImage,
    imageAlt: "Taza de SaltaCode en una oficina",
    features: [
      { title: "Perfiles", copy: "Armamos el equipo según el desafío y la etapa del proyecto." },
      { title: "Integración", copy: "Trabajamos con tus responsables, procesos y herramientas." },
      { title: "Escala", copy: "Ajustamos la composición a medida que cambia el proyecto." },
      { title: "Seguimiento", copy: "Mantenemos objetivos, comunicación y calidad visibles." },
    ],
    situations: [
      "Necesitás iniciar una iniciativa y todavía no contás con el equipo técnico.",
      "Tu equipo requiere capacidad adicional para una etapa o alcance definido.",
      "Buscás perfiles que puedan integrarse a procesos y herramientas existentes.",
    ],
  },
  {
    id: "soluciones-saas",
    slug: "productos-saas",
    href: "/servicios/productos-saas/",
    legacyAlias: "saas-solutions",
    number: "04",
    title: "Desarrollo de productos SaaS",
    shortDescription: "Diseño, construcción y evolución de productos digitales basados en suscripción.",
    description:
      "Diseñamos, construimos y evolucionamos productos SaaS preparados para operar con usuarios reales.",
    detailHeading: "Desarrollo de productos SaaS preparados para evolucionar",
    detailLead: "Acompañamos el paso desde una necesidad y un modelo de servicio hasta un producto digital operable, mantenible y listo para aprender de su uso.",
    seoTitle: "Desarrollo de productos SaaS | SaltaCode",
    seoDescription: "Diseño, desarrollo y evolución de productos SaaS con cuentas, permisos, integraciones y operación para usuarios reales.",
    image: saasImage,
    imageAlt: "Equipo de SaltaCode colaborando frente a una computadora",
    features: [
      { title: "Producto", copy: "Aterrizamos el problema, el alcance y la experiencia de uso." },
      { title: "Cuentas y permisos", copy: "Preparamos usuarios, accesos y operación del servicio." },
      { title: "Integraciones", copy: "Conectamos datos y servicios según cada caso." },
      { title: "Continuidad", copy: "Planificamos mantenimiento y nuevas capacidades." },
    ],
    situations: [
      "Querés convertir un servicio o proceso repetible en un producto digital.",
      "Necesitás validar alcance, experiencia y operación antes de escalar.",
      "Un SaaS existente requiere nuevas capacidades, integraciones o mantenimiento.",
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
  "/servicios/software-a-medida/",
  "/servicios/consultoria-it/",
  "/servicios/equipos-it/",
  "/servicios/productos-saas/",
  "/nosotros/",
  "/contacto/",
  "/legal/privacidad/",
  "/legal/cookies/",
  "/legal/terminos/",
] as const;

export const legalUpdatedAt = "28 de agosto de 2026";
