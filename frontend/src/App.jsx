import { useState } from "react";
import CitySelect from "./components/CitySelect.jsx";
import RecordPanel from "./components/RecordPanel.jsx";

export default function App() {
  const [city, setCity] = useState("杭州");

  return (
    <main className="app">
      <h1>语音约碰面地点</h1>
      <p>按住说话，帮你们找到中间附近的碰面地点。</p>

      <CitySelect value={city} onChange={setCity} />

      <RecordPanel />
    </main>
  );
}
