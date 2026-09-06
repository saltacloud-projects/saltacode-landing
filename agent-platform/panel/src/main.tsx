import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error('Expected an element with id "root" to mount the administration panel.');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
