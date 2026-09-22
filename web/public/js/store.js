// Firestore data access for the signed-in user.
//
// Data model:
//   users/{uid}            -> { config: {folder_url, master_url}, status: {...} }
//   users/{uid}/data/games -> { games: [ {title,rating,review,url,year_played,
//                                          release_year,cover,categories[]}, ... ] }
import { db } from './firebase.js';
import {
  doc,
  getDoc,
  setDoc,
  onSnapshot,
} from "https://www.gstatic.com/firebasejs/10.13.2/firebase-firestore.js";

const DEFAULT_FOLDER_URL = 'https://backloggd.com/u/smorrs/lists/folder/games-played-by-year/';
const DEFAULT_MASTER_URL = 'https://backloggd.com/u/smorrs/games/';

const userDoc  = (uid) => doc(db, 'users', uid);
const gamesDoc = (uid) => doc(db, 'users', uid, 'data', 'games');

export async function loadConfig(uid) {
  const snap = await getDoc(userDoc(uid));
  const cfg = (snap.exists() && snap.data().config) || {};
  return {
    folder_url: cfg.folder_url || DEFAULT_FOLDER_URL,
    master_url: cfg.master_url || DEFAULT_MASTER_URL,
    sections:   cfg.sections   || {},
  };
}

export async function saveConfig(uid, folderUrl, masterUrl) {
  await setDoc(
    userDoc(uid),
    { config: { folder_url: folderUrl || '', master_url: masterUrl || '' } },
    { merge: true }
  );
}

export async function saveSections(uid, sections) {
  await setDoc(userDoc(uid), { config: { sections } }, { merge: true });
}

export async function loadGames(uid) {
  const snap = await getDoc(gamesDoc(uid));
  const games = (snap.exists() && snap.data().games) || [];
  return Array.isArray(games) ? games : [];
}

export async function saveGames(uid, games) {
  await setDoc(gamesDoc(uid), { games, updatedAt: Date.now() });
  return true;
}

// Subscribe to the user's scrape status doc; cb receives the status object
// ({running, op, done, error, added, log[], ...}) or null.
export function watchStatus(uid, cb) {
  return onSnapshot(userDoc(uid), (snap) => {
    cb((snap.exists() && snap.data().status) || null);
  });
}
