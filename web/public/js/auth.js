// Authentication helpers (Google + email/password) over Firebase Auth.
import { auth } from './firebase.js';
import {
  GoogleAuthProvider,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut as fbSignOut,
  onAuthStateChanged as fbOnAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/10.13.2/firebase-auth.js";

const googleProvider = new GoogleAuthProvider();

export function onAuthChanged(cb) {
  return fbOnAuthStateChanged(auth, cb);
}

export function loginGoogle() {
  return signInWithPopup(auth, googleProvider);
}

export function loginEmail(email, password) {
  return signInWithEmailAndPassword(auth, email, password);
}

export function registerEmail(email, password) {
  return createUserWithEmailAndPassword(auth, email, password);
}

export function signOut() {
  return fbSignOut(auth);
}

// Firebase ID token for the current user (sent to /api/refresh as a Bearer token).
export async function getIdToken() {
  const user = auth.currentUser;
  if (!user) throw new Error('not signed in');
  return user.getIdToken();
}

// Turn Firebase auth error codes into friendly messages.
export function authErrorMessage(err) {
  const code = (err && err.code) || '';
  switch (code) {
    case 'auth/invalid-email':          return 'That email address looks invalid.';
    case 'auth/user-not-found':
    case 'auth/wrong-password':
    case 'auth/invalid-credential':     return 'Incorrect email or password.';
    case 'auth/email-already-in-use':   return 'That email already has an account — sign in instead.';
    case 'auth/weak-password':          return 'Password should be at least 6 characters.';
    case 'auth/popup-closed-by-user':   return 'Sign-in was cancelled.';
    case 'auth/popup-blocked':          return 'Popup blocked — allow popups and try again.';
    default:                            return (err && err.message) || 'Authentication failed.';
  }
}
