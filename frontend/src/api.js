import axios from "axios";

const api = axios.create({
  baseURL: "http://localhost:8003",
  timeout: 15000,
});

export async function getHealth() {
  const { data } = await api.get("/health");
  return data;
}

export default api;
