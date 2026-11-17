import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/locales/en.json";
import fr from "@/locales/fr.json";

void i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr }, en: { translation: en } },
  lng: navigator.language.startsWith("en") ? "en" : "fr",
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});
i18n.on("languageChanged", (lng) => (document.documentElement.lang = lng));
export default i18n;
