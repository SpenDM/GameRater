// Firebase app initialization (modular v10 SDK, loaded from gstatic CDN).
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.13.2/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.13.2/firebase-auth.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/10.13.2/firebase-firestore.js";

const config = window.__FIREBASE_CONFIG__;
if (!config || config.apiKey === "REPLACE_ME") {
  console.error(
    "Firebase is not configured. Edit web/public/js/firebase-config.js with your " +
    "project's web config (see README.md)."
  );
}

export const app = initializeApp(config);
export const auth = getAuth(app);
export const db = getFirestore(app);
