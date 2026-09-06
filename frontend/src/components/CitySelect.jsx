const CITIES = ["杭州", "上海", "北京", "广州", "深圳", "成都", "南京", "武汉"];

export default function CitySelect({ value, onChange, disabled = false }) {
  return (
    <label className="city-select">
      <span>默认城市</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {CITIES.map((city) => (
          <option key={city} value={city}>
            {city}
          </option>
        ))}
      </select>
    </label>
  );
}
