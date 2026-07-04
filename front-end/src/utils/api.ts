import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_FLASK_HOST,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const raw = localStorage.getItem("user");
  if (raw) {
    try {
      const userEmail = JSON.parse(raw);
      if (typeof userEmail === "string" && userEmail.length > 0) {
        config.headers.set("X-Owner-Email", userEmail);
      }
    } catch {
      // Ignore parse errors — user data may not be set yet
    }
  }
  return config;
});
